"""Faithful PyBot execution + clearly labelled replay instrumentation.

The actual candidate set comes directly from upstream bot.runtime.turn().
No rule predictions, module choices, or model-generated explanations are fabricated.
"""
import random
import os
import re
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_RUNTIME_LOCK = threading.RLock()
_SAFE_SESSION = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")


class InputError(ValueError):
    pass


@dataclass
class Session:
    seed: int = 42
    memory: dict = field(default_factory=dict)
    state: object = None
    turns: list = field(default_factory=list)


def _outline(memory):
    """Only a small, readable diagnostic overview; no disk persistence."""
    output = []
    for key, value in list(memory.items())[:30]:
        if key == "turns":
            info = "%d turns" % (len(value) if isinstance(value, list) else 0)
        elif isinstance(value, dict):
            info = "dict: " + ", ".join(str(k) for k in list(value)[:6])
        elif isinstance(value, (tuple, list)):
            info = "%d items" % len(value)
        else:
            info = str(value)[:120]
        output.append({"name": str(key), "summary": info})
    return output


class Engine:
    def __init__(self, source):
        self.source = Path(source).resolve()
        if not (self.source / "bot" / "runtime.py").is_file():
            raise RuntimeError("PyBot本体が見つかりません")
        # Upstream's package is imported without editing or copying its source.
        if str(self.source) not in sys.path:
            sys.path.insert(0, str(self.source))
        from bot import runtime
        self.runtime = runtime
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.started = time.monotonic()

    def session(self, key, seed=42, create=True):
        if not isinstance(key, str) or not _SAFE_SESSION.fullmatch(key):
            raise InputError("セッションIDが不正です")
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 999999:
            raise InputError("seedは0〜999999の整数にしてください")
        with self.session_lock:
            if key not in self.sessions:
                if not create:
                    raise InputError("セッションが見つかりません。まず会話を行ってください")
                if len(self.sessions) >= 40:
                    self.sessions.pop(next(iter(self.sessions)))
                self.sessions[key] = Session(seed=seed)
            return self.sessions[key]

    def reset(self, key):
        current = self.session(key, create=False)
        with _RUNTIME_LOCK:
            current.memory = {}
            current.turns.clear()
            current.state = None
        return {"ok": True}

    def ask(self, key, text, seed=42):
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise InputError("1〜1000文字の質問を入力してください")
        current = self.session(key, seed)
        with _RUNTIME_LOCK:
            global_state = random.getstate()
            try:
                if current.state is None:
                    random.seed(current.seed)
                else:
                    random.setstate(current.state)
                previous = _outline(current.memory)
                start = time.perf_counter()
                # The public upstream interface returns all candidates and the winner.
                result = self.runtime.turn(text, current.memory)
                elapsed = round((time.perf_counter() - start) * 1000)
                current.state = random.getstate()
            finally:
                random.setstate(global_state)
            reply = " ".join(str(result["reply"]).split()) or "Hello!"
            candidates = result.get("candidates") or []
            chosen = result.get("module")
            chosen_index = next((i for i, c in enumerate(candidates)
                                 if c["module"] == chosen and c["reply"] == result["reply"]), -1)
            item = {
                "text": text, "reply": reply, "module": chosen,
                "elapsed_ms": elapsed, "candidate_count": len(candidates),
                "chosen_index": chosen_index,
                "candidates": [
                    {"module": c["module"], "priority": c["priority"], "reply": str(c["reply"])[:1800]}
                    for c in candidates[:200]
                ],
                "memory_before": previous, "memory_after": _outline(current.memory),
                "turn_index": len(current.turns)
            }
            current.turns.append(item)
            return item

    def module_file(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", name):
            raise InputError("不正なモジュール名です")
        path = self.source / "bot" / "modules" / (name + ".py")
        if not path.is_file():
            raise InputError("モジュールが見つかりません: " + name)
        return path

    def trace(self, key, turn_index, module):
        """Replay the dialogue separately; instrument real line events, report any drift."""
        current = self.session(key, create=False)
        if not isinstance(turn_index, int) or not 0 <= turn_index < len(current.turns):
            raise InputError("指定したターンがありません")
        selection = current.turns[turn_index]
        allowed = {c["module"] for c in selection["candidates"]}
        if module not in allowed:
            raise InputError("この回答で候補になっていないモジュールです")
        target = self.module_file(module).resolve()
        arbiter = (self.source / "bot" / "modules" / "arbiter.py").resolve()
        watched = {str(target), str(arbiter)}
        bot_prefix = str(self.source / "bot") + os.sep
        module_prefix = str(self.source / "bot" / "modules") + os.sep
        hits, calls = {}, Counter()
        events, phase_events, call_chain = [], [], []
        phase_counts = Counter()
        PHASE_METHODS = {"observe": "observe", "respond": "respond",
                         "choose": "choose", "after": "after"}

        def inside_selected_responder(frame):
            # A called helper belongs to this candidate only if the selected
            # respond() is still on the stack (not merely because it shares a topic).
            parent = frame.f_back
            depth = 0
            while parent is not None and depth < 48:
                if parent.f_code.co_filename == str(target) and parent.f_code.co_name == "respond":
                    return True
                parent = parent.f_back
                depth += 1
            return False

        def tracer(frame, event, arg):
            filename = frame.f_code.co_filename
            if event == "call":
                # These are OBSERVED hook invocations, not inferred reasoning.
                fn = frame.f_code.co_name
                if filename.startswith(module_prefix) and (
                    fn in ("observe", "respond", "after") or
                    (filename == str(arbiter) and fn == "choose")
                ):
                    phase = PHASE_METHODS[fn]
                    phase_counts[phase] += 1
                    if len(phase_events) < 600:
                        phase_events.append({
                            "phase": phase,
                            "module": Path(filename).stem,
                            "at_ms": round((time.perf_counter() - start) * 1000, 2)
                        })

                is_watched = filename in watched
                is_helper = filename.startswith(bot_prefix) and inside_selected_responder(frame)
                if is_watched or is_helper:
                    relative = str(Path(filename).relative_to(self.source)).replace("\\", "/")
                    key = (relative, fn, frame.f_code.co_firstlineno)
                    if key in calls or len(calls) < 4000:
                        calls[key] += 1
                    # Show a bounded, chronologically ordered CALL MAP. The
                    # runtime is not rewriting one sentence token-by-token.
                    if len(call_chain) < 210:
                        ancestors = 0
                        parent = frame.f_back
                        while parent is not None and ancestors < 32:
                            if parent.f_code.co_filename.startswith(bot_prefix):
                                ancestors += 1
                            parent = parent.f_back
                        call_chain.append({
                            "path": relative, "fn": fn,
                            "line": frame.f_code.co_firstlineno,
                            "depth": ancestors,
                            "at_ms": round((time.perf_counter() - start) * 1000, 2),
                            "kind": "arbiter" if filename == str(arbiter)
                                    else "response" if filename == str(target)
                                    else "helper"
                        })
                # Trace lines only for the chosen candidate and arbiter.
                return tracer if is_watched else None
            if event == "line" and filename in watched:
                rel = str(Path(filename).relative_to(self.source)).replace("\\", "/")
                per_file = hits.setdefault(rel, Counter())
                per_file[frame.f_lineno] += 1
                if len(events) < 110:
                    events.append({"path": rel, "line": frame.f_lineno, "fn": frame.f_code.co_name})
            return tracer

        with _RUNTIME_LOCK:
            global_state = random.getstate()
            old_trace = sys.gettrace()
            start = time.perf_counter()
            try:
                random.seed(current.seed)
                replay_memory = {}
                result = None
                for idx, turn in enumerate(current.turns[:turn_index+1]):
                    if idx == turn_index:
                        sys.settrace(tracer)
                    try:
                        result = self.runtime.turn(turn["text"], replay_memory)
                    finally:
                        sys.settrace(old_trace)
            finally:
                random.setstate(global_state)
                sys.settrace(old_trace)
            replay_reply = " ".join(str(result["reply"]).split()) if result else ""
            return {
                "selected_module": module,
                "replay_equal": replay_reply == selection["reply"] and result.get("module") == selection["module"],
                "replay_module": result.get("module") if result else None,
                "replay_reply": replay_reply,
                "elapsed_ms": round((time.perf_counter() - start) * 1000),
                "hits": {path: [{"line": line, "count": count} for line, count in sorted(counts.items())]
                         for path, counts in hits.items()},
                "calls": [{"path": path, "file": Path(path).name, "fn": fn, "line": line, "count": count}
                          for (path, fn, line), count in calls.most_common(45)],
                "events": events,
                "phase_events": phase_events,
                "phase_counts": dict(phase_counts),
                "call_chain": call_chain,
                "call_chain_truncated": len(call_chain) >= 210,
                "replay_candidate_count": len((result or {}).get("candidates") or []),
                "method": "同じ入力を固定seedで別メモリに再実行し、モジュールの呼出し順・選んだ候補とarbiterの実行行を収集",
                "warning": "再実行が元の回答と一致しません。表示される行は元のターンの確定実行経路ではありません。"
                           if replay_reply != selection["reply"] or result.get("module") != selection["module"] else ""
            }

    def playback(self, key, turn_index):
        """Replay one complete turn for a bounded, seekable execution film.

        The original turn is NEVER rerun in its live conversation memory.
        This is a separate, deterministic, explicitly labelled observation.
        """
        from .playback import replay_film
        current = self.session(key, create=False)
        if not isinstance(turn_index, int) or isinstance(turn_index, bool):
            raise InputError("再生対象のターン番号が不正です")
        with _RUNTIME_LOCK:
            if not 0 <= turn_index < len(current.turns):
                raise InputError("指定された会話のターンがありません")
            selected = current.turns[turn_index]
            inputs = [turn["text"] for turn in current.turns[:turn_index + 1]]
            return replay_film(
                self.runtime, self.source, inputs, selected["module"],
                selected["reply"], current.seed
            )

    def files(self):
        files = list((self.source / "bot").rglob("*.py"))
        buckets = {}
        for folder in ("understanding", "memory", "knowledge", "compose", "modules"):
            group = [p for p in files if p.parent.name == folder]
            buckets[folder] = {"files": len(group), "lines": sum(_count_lines(p) for p in group)}
        buckets["total"] = {"files": len(files), "lines": sum(_count_lines(p) for p in files)}
        return buckets

    def file(self, name):
        if not isinstance(name, str) or not name.startswith("bot/") or not name.endswith(".py"):
            raise InputError("表示できるファイルはPyBotのbot/以下の.pyのみです")
        if not re.fullmatch(r"bot/[a-zA-Z_0-9/]+\.py", name) or ".." in name:
            raise InputError("不正なファイルパスです")
        path = (self.source / name).resolve()
        if self.source not in path.parents:
            raise InputError("参照できないファイルパスです")
        if not path.is_file():
            raise InputError("ソースファイルが見つかりません")
        return path

    def source_lines(self, name, start=1, limit=95, focus=None):
        path = self.file(name)
        rows = path.read_text(encoding="utf-8").splitlines()
        start = max(1, min(int(start), max(1, len(rows))))
        limit = max(1, min(int(limit), 160))
        data = {"path": name, "start": start, "total": len(rows), "lines": [
            {"n": i+1, "code": rows[i]} for i in range(start-1, min(len(rows), start-1+limit))
        ]}
        if focus is not None:
            from .playback import function_docstring
            line = int(focus)
            if not 1 <= line <= len(rows):
                raise InputError("ソースの行番号が不正です")
            data["function_info"] = function_docstring(self.source, name, line)
        return data

    def entry_line(self, module):
        path = self.module_file(module)
        # Fast enough for the large individual modules; does not execute them.
        for number, row in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"^def respond\(", row):
                return number
        return 1

    def search_code(self, needle, scope="all"):
        if not isinstance(needle, str) or not 2 <= len(needle.strip()) <= 80:
            raise InputError("検索語は2〜80文字にしてください")
        if scope not in ("all", "modules"):
            raise InputError("検索対象が不正です")
        root = self.source / "bot" / ("modules" if scope == "modules" else "")
        found = []
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(self.source).as_posix()
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if needle.lower() in line.lower():
                    found.append({"path": rel, "line": number, "snippet": line.strip()[:220]})
                    if len(found) == 36:
                        return {"results": found, "limited": True}
        return {"results": found, "limited": False}


def _count_lines(path):
    with path.open("rb") as handle:
        return sum(1 for _ in handle)
