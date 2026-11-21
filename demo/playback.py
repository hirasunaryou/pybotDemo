"""Bounded replay-based execution film for PyBot Live Lab.

This does not alter upstream PyBot. Every dynamic frame is an observed Python
call, return or selected line event from a separate replay. Static locations
of literal answers are RESEARCH HINTS, never passed off as executed events.
"""
import ast
from collections import Counter
from pathlib import Path
import os
import random
import re
import sys
import time

MAX_SAMPLES = 1400
MAX_MILESTONES = 650
MAX_DISPLAY = 340
SOURCE_NEEDLE = 38

# These stage labels are derived from the public bot/runtime.py hook contract.
HOOK_NAMES = {"observe": "observe", "respond": "respond", "after": "after"}
DESCRIPTIONS = {
    "observe": "observe: ユーザー発話を観察し、会話情報を記録する段階",
    "respond": "respond: 各モジュールが自分の候補を提出する段階",
    "choose": "choose: 候補の中から採択する段階（arbiter）",
    "after": "after: 採択後のフックと会話履歴の更新",
    "runtime": "runtime: PyBot本体が会話処理を進める制御部分",
}


def source_literal_locations(root, reply):
    """Exact string-constant lookup first; otherwise only weak substring hints.

    Does not execute arbitrary source files or claim a string literal was
    executed. A literal could be data, imported from elsewhere, or unused.
    """
    reply = " ".join(str(reply or "").split())
    if len(reply) < SOURCE_NEEDLE:
        return []
    # Match enough text that unrelated boilerplate is unlikely to qualify.
    fragments = [reply[:min(64, len(reply))], reply[:SOURCE_NEEDLE]]
    hints = []
    for file in sorted((Path(root) / "bot").rglob("*.py")):
        try:
            content = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = content.splitlines()
        matching = [i for i, line in enumerate(lines) if any(frag in line for frag in fragments)]
        if not matching:
            continue
        path = file.relative_to(root).as_posix()
        exact_var, exact_line = None, None
        try:
            parsed = ast.parse(content, filename=str(file))
            for item in ast.walk(parsed):
                if not isinstance(item, (ast.Assign, ast.AnnAssign)):
                    continue
                value = getattr(item, "value", None)
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    continue
                if " ".join(value.value.split()) != reply:
                    continue
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        exact_var, exact_line = t.id, item.lineno
                        break
                if exact_var:
                    break
        except (SyntaxError, MemoryError):
            pass
        if exact_var:
            refs = [
                {"path": path, "line": i + 1, "kind": "static_reference",
                 "label": "静的参照（実行されたとは限りません）"}
                for i, line in enumerate(lines)
                if re.search(r"\breturn\s+" + re.escape(exact_var) + r"\b", line)
            ][:8]
            hints.append({
                "path": path, "line": exact_line, "matched": "exact_literal",
                "label": "元の回答と完全一致する文字列定義", "symbol": exact_var,
                "references": refs, "verified_equal": True,
            })
        else:
            hints.append({
                "path": path, "line": matching[0] + 1, "matched": "fragment",
                "label": "回答の冒頭に一致する文字列断片", "symbol": "",
                "references": [], "verified_equal": False,
            })
        if len(hints) >= 4:
            break
    hints.sort(key=lambda a: (not a["verified_equal"], a["path"], a["line"]))
    return hints


def replay_film(runtime, source, prior_turns, selected_module, expected_reply, seed):
    """Replay a known turn with a deterministic seed and instrument its code.

    prior_turns: the caller's saved raw inputs through the selected turn.
    The recorded real session is never mutated.
    """
    root = Path(source).resolve()
    bot_dir = root / "bot"
    prefix = str(bot_dir) + os.sep
    modules_dir = str(bot_dir / "modules") + os.sep
    runtime_path = str(bot_dir / "runtime.py")
    selected_path = str(bot_dir / "modules" / (selected_module + ".py")) if selected_module else ""
    arbiter_path = str(bot_dir / "modules" / "arbiter.py")
    origins = source_literal_locations(root, expected_reply)
    watched = {runtime_path, selected_path, arbiter_path}
    for hint in origins[:2]:
        watched.add(str(root / hint["path"]))
    literal_lines = {
        (str(root / loc["path"]), loc["line"]) for loc in origins
    }
    return_lines = {
        (str(root / ref["path"]), ref["line"])
        for loc in origins for ref in loc["references"]
    }
    start = 0.0
    phase = "runtime"
    ordinal = 0
    observed_calls = 0
    skipped = 0
    samples, milestones = [], []
    stride = 1
    phases = Counter()
    executed_return_sites = set()
    chosen_candidate_return = False
    source_file_name_cache = {}

    def relative(filename):
        if filename not in source_file_name_cache:
            source_file_name_cache[filename] = str(Path(filename).relative_to(root)).replace("\\", "/")
        return source_file_name_cache[filename]

    def frame_data(frame, kind, note="", **extra):
        return {
            "seq": ordinal, "kind": kind, "phase": phase,
            "path": relative(frame.f_code.co_filename),
            "line": frame.f_lineno if kind in ("line", "return") else frame.f_code.co_firstlineno,
            "fn": frame.f_code.co_name,
            "at_ms": round((time.perf_counter() - start) * 1000, 1),
            "note": note,
            **extra,
        }

    def mark(row):
        if len(milestones) < MAX_MILESTONES:
            milestones.append(row)

    def sample(row):
        nonlocal stride
        if ordinal % stride == 0:
            samples.append(row)
        if len(samples) > MAX_SAMPLES:
            samples[:] = samples[::2]
            stride *= 2

    def monitor(frame, event, arg):
        nonlocal phase, ordinal, observed_calls, skipped, chosen_candidate_return
        path = frame.f_code.co_filename
        if not path.startswith(prefix):
            return None
        fn = frame.f_code.co_name
        if event == "call":
            ordinal += 1
            observed_calls += 1
            is_module_hook = path.startswith(modules_dir) and fn in HOOK_NAMES
            is_arbiter = path == arbiter_path and fn == "choose"
            if is_module_hook:
                phase = HOOK_NAMES[fn]
                phases[phase] += 1
                if phase not in seen_phases:
                    seen_phases.add(phase)
                    mark(frame_data(frame, "phase", "段階の開始（PyBot公式hook）"))
            elif is_arbiter or (path == runtime_path and fn == "_choose"):
                phase = "choose"
                phases["choose"] += 1
                if "choose" not in seen_phases:
                    seen_phases.add("choose")
                    mark(frame_data(frame, "phase", "回答選択の開始"))
            elif path == runtime_path and fn == "turn":
                phase = "runtime"
                mark(frame_data(frame, "start", "PyBot.runtime.turn 開始"))
            if path == selected_path and fn == "respond":
                mark(frame_data(frame, "selected_call", "採択候補となったモジュールの respond()"))
            elif is_arbiter:
                mark(frame_data(frame, "arbiter_call", "arbiter.choose() 呼び出し"))
            elif path in watched and fn in ("_averages", "solve"):
                mark(frame_data(frame, "source_call", "回答に関連する関数の呼び出し"))
            # Not every call becomes a visible frame. The sequence is uniformly
            # sampled and important events are kept separately, even near the end.
            if fn not in ("<module>",):
                sample(frame_data(frame, "call"))
            # Targeted line/return tracing: does not generate 640k line events.
            return monitor if (path in watched or is_module_hook) else None

        if event == "line":
            ordinal += 1
            if (path, frame.f_lineno) in return_lines:
                executed_return_sites.add((relative(path), frame.f_lineno))
                mark(frame_data(frame, "return_site", "候補文を返す分岐を通過（再実行時の観測）"))
            elif (path, frame.f_lineno) in literal_lines:
                # Definition lines are import-time data, not necessarily visited
                # during this turn; if seen, present them as line observations.
                mark(frame_data(frame, "line", "文字列定義付近の実行行"))
            elif path in watched and (
                (path == selected_path and fn == "respond")
                or (path == arbiter_path and fn == "choose")
                or (path == runtime_path and fn in ("_choose", "turn"))
            ):
                sample(frame_data(frame, "line"))
            return monitor

        if event == "return":
            ordinal += 1
            if path == selected_path and fn == "respond" and isinstance(arg, str):
                if " ".join(arg.split()) == " ".join(str(expected_reply).split()):
                    chosen_candidate_return = True
                    mark(frame_data(frame, "candidate_return",
                                    "採択モジュールが元の回答と同じ候補文を返した",
                                    preview=arg[:230]))
            elif path == arbiter_path and fn == "choose":
                mark(frame_data(frame, "arbiter_return", "arbiter.choose() が選択結果を返した",
                                selected_index=arg if isinstance(arg, int) and not isinstance(arg, bool) else None))
            elif path == runtime_path and fn == "turn" and isinstance(arg, dict):
                mark(frame_data(frame, "final", "PyBot.runtime.turn() が最終回答を返した",
                                output_module=arg.get("module"), output=arg.get("reply", "")[:250]))
            return monitor
        return monitor

    # Function keeps early stage markers even when no candidates were generated.
    seen_phases = set()
    state = random.getstate()
    old_trace = sys.gettrace()
    result = None
    try:
        random.seed(seed)
        memory = {}
        for i, prompt in enumerate(prior_turns):
            if i == len(prior_turns)-1:
                start = time.perf_counter()
                sys.settrace(monitor)
            try:
                result = runtime.turn(prompt, memory)
            finally:
                sys.settrace(old_trace)
    finally:
        random.setstate(state)
        sys.settrace(old_trace)

    actual_reply = " ".join(str((result or {}).get("reply", "")).split())
    replay_equal = (
        actual_reply == " ".join(str(expected_reply).split())
        and (result or {}).get("module") == selected_module
    )
    # Chronological replay frames, with end-of-run observations retained.
    all_rows = {r["seq"]: r for r in samples}
    all_rows.update({r["seq"]: r for r in milestones})
    rows = sorted(all_rows.values(), key=lambda item: item["seq"])
    if len(rows) > MAX_DISPLAY:
        priority = [r for r in rows if r["kind"] not in ("call", "line")]
        normal = [r for r in rows if r["kind"] in ("call", "line")]
        keep = max(0, MAX_DISPLAY - len(priority))
        step = max(1, (len(normal) + max(keep,1)-1)//max(keep,1))
        normal = normal[::step][:keep]
        rows = sorted(priority + normal, key=lambda item: item["seq"])
    # The attached source matches are NOT time-line events. They are clickable
    # source-inspection links below the playback sequence, not fictional calls.
    return {
        "replay_equal": replay_equal,
        "replay_reply": actual_reply,
        "replay_module": (result or {}).get("module"),
        "selected_module": selected_module,
        "frames": rows,
        "replay_ms": round((time.perf_counter()-start)*1000),
        "call_count": observed_calls,
        "sampled_frames": len(rows),
        "frame_cap": MAX_DISPLAY,
        "phase_counts": dict(phases),
        "candidate_return_matched": chosen_candidate_return,
        "source_matches": origins,
        "executed_return_sites": [
            {"path": path, "line": line} for path,line in sorted(executed_return_sites)
        ],
        "method": "PyBotの各関数呼び出しを間引いて記録し、重要なhook/回答候補/選択/返答を再実行から保存",
        "warning": "" if replay_equal else (
            "元の実行と再実行の回答・採択モジュールが異なります。"
            "これは元の質問の確定経路ではありません。"
        ),
    }


def function_docstring(source, relative_path, line):
    """Return a REAL Python docstring, never an automatically invented purpose."""
    file = Path(source) / relative_path
    try:
        source_text = file.read_text(encoding="utf-8")
        syntax = ast.parse(source_text, filename=str(file))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return None
    matches = []
    for node in ast.walk(syntax):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
            matches.append(node)
    if not matches:
        return None
    node = max(matches, key=lambda n:n.lineno)
    return {"name": node.name, "line": node.lineno,
            "docstring": (ast.get_docstring(node) or "")[:500]}
