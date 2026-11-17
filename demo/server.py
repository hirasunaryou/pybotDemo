"""Loopback-only HTTP API and static web UI, with no third-party dependencies."""
import json
import mimetypes
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import threading
import traceback

from .engine import Engine, InputError
from .bootstrap import PROJECT_ROOT, UPSTREAM_COMMIT

STATIC = PROJECT_ROOT / "demo" / "static"
DOCS = PROJECT_ROOT / "docs"
MAX_REQUEST = 20 * 1024


class Application:
    def __init__(self, source):
        self.source = Path(source)
        self.engine = None
        self._lock = threading.Lock()
        self._stats = None

    def get_engine(self):
        if self.engine is None:
            with self._lock:
                if self.engine is None:
                    self.engine = Engine(self.source)
        return self.engine

    def stats(self):
        if self._stats is None:
            # The source tree is unchanged; keep line-count analysis cached.
            bot = self.source / "bot"
            directories = ["understanding", "memory", "knowledge", "compose", "modules"]
            files = list(bot.rglob("*.py"))
            def lines(path):
                with path.open("rb") as stream:
                    return sum(1 for _ in stream)
            self._stats = {"total": {"files": len(files), "lines": sum(lines(p) for p in files)}}
            for name in directories:
                selected = [p for p in files if p.parent.name == name]
                self._stats[name] = {"files": len(selected), "lines": sum(lines(p) for p in selected)}
        return self._stats

    def handle_get(self, path, params):
        if path == "/api/status":
            return {"source_commit": UPSTREAM_COMMIT,
                    "upstream": "https://github.com/huggingface/pybot",
                    "stats": self.stats(), "engine_loaded": self.engine is not None,
                    "mode": "Python rules only / no external AI API"}
        if path == "/api/source":
            engine = self.get_engine()
            name = params.get("path", [""])[0]
            module = params.get("module", [""])[0]
            if module and not name:
                engine.module_file(module)
                name = "bot/modules/" + module + ".py"
                start = max(1, engine.entry_line(module) - 7)
            else:
                start = 1
            if params.get("start"):
                start = int(params["start"][0])
            return engine.source_lines(name, start, 110)
        raise InputError("APIが見つかりません")

    def handle_post(self, path, data):
        engine = self.get_engine()
        key = data.get("session")
        if path == "/api/ask":
            return engine.ask(key, data.get("text"), data.get("seed", 42))
        if path == "/api/reset":
            return engine.reset(key)
        if path == "/api/trace":
            return engine.trace(key, data.get("turn_index"), data.get("module"))
        if path == "/api/search":
            return engine.search_code(data.get("query"), data.get("scope", "all"))
        raise InputError("APIが見つかりません")


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PyBotLiveLab/1.0"

        def log_message(self, fmt, *args):
            # No conversation contents or prompts in default server logs.
            if not self.path.startswith("/api/"):
                return

        def send_body(self, body, status=200, ctype="application/json; charset=utf-8", doc_html=False):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if doc_html:
                # Only our bundled, read-only documents contain inline CSS; this allows
                # single-file HTML to look identical online and when opened from disk.
                # Scripts and network resources remain blocked in docs pages.
                csp = ("default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; "
                       "img-src 'self' data:; object-src 'none'; base-uri 'none'")
            else:
                csp = ("default-src 'self'; script-src 'self'; style-src 'self'; "
                       "img-src 'self' data:; connect-src 'self'; object-src 'none'")
            self.send_header("Content-Security-Policy", csp)
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, obj, status=200):
            self.send_body(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), status)

        def error(self, message, status=400):
            self.json_response({"error": str(message)}, status)

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/"):
                    return self.json_response(app.handle_get(path, parse_qs(parsed.query)))
                if path == "/":
                    filename = STATIC / "index.html"
                elif path.startswith("/static/"):
                    filename = STATIC / path[len("/static/"):]
                elif path.startswith("/docs/"):
                    filename = DOCS / path[len("/docs/"):]
                else:
                    return self.error("ページが見つかりません", 404)
                filename = filename.resolve()
                if filename != (STATIC / "index.html").resolve() and not (
                    STATIC.resolve() in filename.parents or DOCS.resolve() in filename.parents
                ):
                    return self.error("参照できないパスです", 403)
                if not filename.is_file():
                    return self.error("ファイルが見つかりません", 404)
                media = mimetypes.guess_type(str(filename))[0] or "application/octet-stream"
                if media.startswith("text/") or media in ("application/javascript",):
                    media += "; charset=utf-8"
                is_doc_html = filename.suffix.lower() == ".html" and DOCS.resolve() in filename.parents
                self.send_body(filename.read_bytes(), ctype=media, doc_html=is_doc_html)
            except (InputError, ValueError, TypeError) as exc:
                self.error(exc)
            except Exception:
                traceback.print_exc()
                self.error("ファイル読込に失敗しました。ターミナルのエラーを確認してください", 500)

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n <= 0 or n > MAX_REQUEST:
                    raise InputError("送信サイズが上限を超えています")
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    raise InputError("JSON形式で送信してください")
                data = json.loads(self.rfile.read(n).decode("utf-8"))
                if not isinstance(data, dict):
                    raise InputError("JSONオブジェクトが必要です")
                self.json_response(app.handle_post(urlsplit(self.path).path, data))
            except (InputError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.error(exc)
            except Exception:
                traceback.print_exc()
                self.error("PyBot処理に失敗しました。ターミナルのエラーを確認してください", 500)
    return Handler


def serve(source, port=0):
    app = Application(source)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    server.daemon_threads = True
    return "http://127.0.0.1:%d/" % server.server_address[1], server
