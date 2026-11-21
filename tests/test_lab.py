"""Fully offline tests for the demonstration app.

The miniature PyBot fixture is used ONLY for tests, never as the app's runtime.
The production app always imports the original, unmodified bot.runtime.
"""
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import threading
import unittest
from unittest import mock
from urllib.request import Request, urlopen

from demo.bootstrap import ensure_upstream
from demo.engine import Engine, InputError
from demo.server import serve


FIXTURE_RUNTIME = '''
from .modules import arbiter, greeting, backup

def turn(text, memory):
    memory.setdefault("seen", []).append(text)
    choices = [
        {"module":"greeting","priority":10,"reply":greeting.respond(text, memory)},
        {"module":"backup","priority":-10,"reply":backup.respond(text, memory)},
    ]
    index = arbiter.choose(text, memory, choices)
    choice = choices[index]
    memory.setdefault("turns", []).append({"user":text,"bot":choice["reply"],"module":choice["module"]})
    return {"reply":choice["reply"],"module":choice["module"],"candidates":choices}
'''
FIXTURE_GREETING = '''
PRIORITY=10
def respond(text, memory):
    if "hello" in text.lower():
        return "Hello from the fixture"
    if memory.get("seen"):
        return "I remember " + memory["seen"][0]
    return "Unknown"
'''
FIXTURE_BACKUP = '''
PRIORITY=-10
def respond(text, memory):
    return "Another candidate"
'''
FIXTURE_ARBITER = '''
def choose(text, memory, candidates):
    if "special" in text.lower():
        return 1
    return 0
'''


class FakeSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        files = {
            "bot/__init__.py": "",
            "bot/modules/__init__.py": "",
            "bot/runtime.py": FIXTURE_RUNTIME,
            "bot/modules/greeting.py": FIXTURE_GREETING,
            "bot/modules/backup.py": FIXTURE_BACKUP,
            "bot/modules/arbiter.py": FIXTURE_ARBITER,
        }
        for path, content in files.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        # Prevent tests from depending on any cached external 'bot' import.
        import sys
        for name in list(sys.modules):
            if name == "bot" or name.startswith("bot."):
                del sys.modules[name]
        self.engine = Engine(self.root)

    def test_actual_candidates_and_choice(self):
        item = self.engine.ask("test_session_1", "Hello!")
        self.assertEqual(item["module"], "greeting")
        self.assertEqual(item["candidate_count"], 2)
        self.assertEqual(item["chosen_index"], 0)
        self.assertEqual(item["candidates"][0]["priority"], 10)
        self.assertEqual(item["reply"], "Hello from the fixture")
        follow = self.engine.ask("test_session_1", "special request")
        self.assertEqual(follow["module"], "backup")
        self.assertEqual(follow["chosen_index"], 1)
        self.assertEqual(follow["turn_index"], 1)
        self.assertIn("seen", {x["name"] for x in follow["memory_after"]})

    def test_replay_trace_is_separate_and_exact(self):
        item = self.engine.ask("test_session_2", "Hello! special")
        trace = self.engine.trace("test_session_2", item["turn_index"], "backup")
        self.assertTrue(trace["replay_equal"])
        self.assertEqual(trace["selected_module"], "backup")
        self.assertIn("phase_counts", trace)
        self.assertGreaterEqual(trace["phase_counts"].get("respond", 0), 2)
        self.assertGreaterEqual(trace["phase_counts"].get("choose", 0), 1)
        self.assertTrue(any(c["phase"] == "choose" for c in trace["phase_events"]))
        self.assertTrue(any(c["path"] == "bot/modules/backup.py" for c in trace["call_chain"]))
        self.assertGreaterEqual(trace["replay_candidate_count"], 2)
        self.assertIn("bot/modules/backup.py", trace["hits"])
        self.assertIn("bot/modules/arbiter.py", trace["hits"])
        # Replaying for instrumentation must NOT add another turn to the real chat.
        self.assertEqual(len(self.engine.session("test_session_2").memory["turns"]), 1)

    def test_seekable_playback_preserves_live_memory(self):
        first = self.engine.ask("playback_session_1", "Hello!")
        earlier_state = dict(self.engine.session("playback_session_1").memory)
        film = self.engine.playback("playback_session_1", 0)
        self.assertTrue(film["replay_equal"])
        self.assertGreater(len(film["frames"]), 1)
        self.assertEqual(film["frames"][0]["kind"], "start")
        self.assertEqual(film["frames"][-1]["kind"], "final")
        self.assertTrue(film["candidate_return_matched"])
        self.assertTrue(any(f["kind"] == "candidate_return" for f in film["frames"]))
        self.assertTrue(any(f["kind"] == "arbiter_call" for f in film["frames"]))
        self.assertGreaterEqual(film["phase_counts"].get("respond", 0), 2)
        self.assertLessEqual(film["sampled_frames"], film["frame_cap"])
        self.assertEqual(self.engine.session("playback_session_1").memory, earlier_state)
        self.assertEqual(len(self.engine.session("playback_session_1").turns), 1)

    def test_playback_unknown_turn_rejected(self):
        self.engine.ask("playback_session_2", "hello")
        with self.assertRaises(InputError):
            self.engine.playback("playback_session_2", 999)

    def test_static_source_literal_and_return_sites(self):
        from demo.playback import source_literal_locations
        phrase = ("The mean, which is what most people mean by an average, "
                  "is the total shared out evenly with this example.")
        source = self.root / "bot" / "knowledge" / "maths.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "_AVERAGE_EXPLAIN = (\n"
            "  \"The mean, which is what most people mean by an average, \"\n"
            "  \"is the total shared out evenly with this example.\")\n"
            "def solve():\n"
            "  return _AVERAGE_EXPLAIN\n", encoding="utf-8")
        locations = source_literal_locations(self.root, phrase)
        self.assertEqual(locations[0]["path"], "bot/knowledge/maths.py")
        self.assertTrue(locations[0]["verified_equal"])
        self.assertEqual(locations[0]["symbol"], "_AVERAGE_EXPLAIN")
        self.assertEqual(locations[0]["line"], 1)
        self.assertEqual(locations[0]["references"][0]["line"], 5)

    def test_source_and_search(self):
        line = self.engine.entry_line("greeting")
        self.assertGreater(line, 1)
        result = self.engine.source_lines("bot/modules/greeting.py", 1, 50)
        self.assertTrue(any("PRIORITY" in row["code"] for row in result["lines"]))
        found = self.engine.search_code("remember", "modules")
        self.assertTrue(any(r["path"].endswith("greeting.py") for r in found["results"]))
        with self.assertRaises(InputError):
            self.engine.file("bot/modules/../../etc/passwd.py")
        with self.assertRaises(InputError):
            self.engine.module_file("../../../secrets")
        with self.assertRaises(InputError):
            self.engine.ask("short", "test")
        with self.assertRaises(InputError):
            self.engine.trace("test_session_2", 44, "backup")

    def test_original_pybot_receives_unmodified_raw_text(self):
        # Translation is a separate, opt-in browser layer, not part of PyBot.
        japanese = "日本語だけの質問です"
        result = self.engine.ask("japanese_only_session", japanese)
        self.assertEqual(result["text"], japanese)
        self.assertEqual(self.engine.session("japanese_only_session").memory["turns"][0]["user"],
                         japanese)
        self.assertNotIn("lab", result)

    def test_reset_and_rng_isolation(self):
        random.seed(1234)
        before = random.getstate()
        self.engine.ask("test_session_3", "Hello")
        self.assertEqual(random.getstate(), before)
        self.engine.reset("test_session_3")
        self.assertEqual(self.engine.session("test_session_3").memory, {})
        self.assertEqual(self.engine.session("test_session_3").turns, [])

    def test_local_http_endpoints(self):
        url, server = serve(self.root)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with urlopen(url + "api/status", timeout=10) as response:
            info = json.load(response)
            self.assertEqual(info["stats"]["total"]["files"], 6)
        with urlopen(url, timeout=10) as response:
            html = response.read().decode("utf-8")
            self.assertIn("PYBOT", html)
            self.assertIn("2026年11月", html)
            self.assertIn("Apache-2.0", html)
            self.assertIn("独立した勉強会用ツール", html)
            self.assertIn("id=\"voiceBtn\"", html)
            self.assertIn('id="themeToggle"', html)
            self.assertIn('id="jaBridgeBtn"', html)
            self.assertIn('id="fontPlus"', html)
            self.assertIn('id="traceMap"', html)
            self.assertIn('id="filmPlayer"', html)
            self.assertIn('id="filmSeek"', html)
            self.assertIn('id="filmGenerateBtn"', html)
            self.assertIn('data-tab="architecture"', html)
            self.assertIn('href="/docs/RESEARCH.html"', html)
        with urlopen(url + "static/voice.js", timeout=10) as response:
            js = response.read().decode("utf-8")
            self.assertIn("SpeechRecognition", js)
            self.assertIn("never", js.lower())
        with urlopen(url + "static/theme.js", timeout=10) as response:
            theme_script = response.read().decode("utf-8")
            self.assertIn("prefers-color-scheme", theme_script)
            self.assertIn("localStorage", theme_script)
            self.assertIn('data-theme', theme_script)
        for name, needle in (("translation.js", "Translator.create"),
                             ("presentation.js", "--lab-font-scale"),
                             ("trace-map.js", "phase_counts"),
                             ("code-player.js", "source_matches"),
                             ("code-player.css", ".film-player"),
                             ("enhancements.css", ".map-step")):
            with urlopen(url + "static/" + name, timeout=10) as response:
                self.assertIn(needle, response.read().decode("utf-8"))
        with urlopen(url + "docs/RESEARCH.html", timeout=10) as response:
            research = response.read().decode("utf-8")
            self.assertIn("ELIZA", research)
            self.assertIn("<style>", research)
            self.assertIn("'unsafe-inline'", response.headers.get("Content-Security-Policy", ""))
        def post(endpoint, payload):
            req = Request(url+"api/"+endpoint, data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type":"application/json"})
            with urlopen(req, timeout=10) as response:
                return json.load(response)
        item = post("ask", {"session":"http_session_01","text":"hello"})
        self.assertEqual(item["module"], "greeting")
        trace = post("trace", {"session":"http_session_01","turn_index":0,"module":"greeting"})
        self.assertTrue(trace["replay_equal"])
        movie = post("playback", {"session":"http_session_01","turn_index":0})
        self.assertTrue(movie["replay_equal"])
        self.assertGreater(len(movie["frames"]), 1)
        self.assertTrue(any(x["kind"] == "final" for x in movie["frames"]))
        src = urlopen(url+"api/source?module=greeting", timeout=10)
        self.assertEqual(json.load(src)["path"], "bot/modules/greeting.py")
        self.assertTrue(post("reset", {"session":"http_session_01"})["ok"])

    def test_japanese_ui_sources_are_valid_utf8(self):
        project = Path(__file__).resolve().parents[1]
        files = (
            "README.md",
            "demo/static/index.html",
            "demo/static/app.js",
            "demo/static/styles.css",
            "demo/static/theme.js",
            "docs/MANUAL.source.html",
            "docs/RESEARCH.html",
            "docs/MANUAL.html",
        )
        for name in files:
            with self.subTest(name=name):
                content = (project / name).read_text(encoding="utf-8", errors="strict")
                self.assertNotIn("\ufffd", content, "Replacement glyph detected")
                self.assertNotIn("\x00", content, "Unexpected NUL byte")
                self.assertIn("PyBot", content) if name != "demo/static/styles.css" and name != "demo/static/theme.js" else None
        for name in ("demo/static/index.html", "docs/MANUAL.source.html", "docs/RESEARCH.html"):
            source = (project / name).read_text(encoding="utf-8")
            self.assertTrue('charset="utf-8"' in source.lower() or 'charset=utf-8' in source.lower())

    def test_unicode_and_spaces_in_source_path(self):
        # Both Windows and macOS users may unzip projects under Japanese paths.
        japanese = self.root / "日本語 とスペース"
        shutil.copytree(self.root / "bot", japanese / "bot")
        with mock.patch.dict(os.environ, {"PYBOT_DEMO_SOURCE": str(japanese)}):
            source = ensure_upstream(output=lambda *_: None)
            self.assertEqual(source, japanese.resolve())
            url, server = serve(source)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with urlopen(url + "api/status", timeout=10) as response:
                    status = json.load(response)
                self.assertEqual(status["stats"]["total"]["files"], 6)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)

    def test_user_override_does_not_download(self):
        with mock.patch.dict(os.environ, {"PYBOT_DEMO_SOURCE":str(self.root)}):
            self.assertEqual(ensure_upstream(output=lambda *_: None), self.root.resolve())


if __name__ == "__main__":
    unittest.main()
