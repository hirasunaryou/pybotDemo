#!/usr/bin/env python3
"""One action, first-time setup through browser launch (Python standard library)."""
import sys
import traceback
import webbrowser
import os

if sys.version_info < (3, 8):
    raise SystemExit("Python 3.8以上が必要です。python.org からPythonをインストールしてください。")

from demo.bootstrap import BootstrapError, ensure_upstream
from demo.server import serve


def main():
    try:
        source = ensure_upstream()
        url, server = serve(source)
        if "--self-check" in sys.argv[1:] or os.getenv("PYBOT_LIVE_LAB_SELF_CHECK") == "1":
            # Real-platform smoke path: no browser popup, no user input.
            import json
            import threading
            import urllib.request
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with urllib.request.urlopen(url + "api/status", timeout=40) as response:
                    info = json.load(response)
                assert info["stats"]["total"]["files"] > 100
                with urllib.request.urlopen(url + "api/source?module=chat", timeout=90) as response:
                    code = json.load(response)
                assert code["path"] == "bot/modules/chat.py"
                with urllib.request.urlopen(url + "docs/MANUAL.html", timeout=30) as response:
                    html = response.read().decode("utf-8")
                assert "<style>" in html and "data:image/png;base64," in html
                print("PyBot Live Lab self-check passed (OS, original runtime, web UI and bundled manual).")
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
            return 0
        print("\nPyBot Live Labを起動しました: " + url)
        print("このウィンドウを閉じるとサーバーも終了します。 Ctrl+Cで終了できます。")
        webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました。")
    except BootstrapError as exc:
        print("\n初回セットアップを完了できませんでした。\n" + str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("\n起動に失敗しました。以下の内容を確認してください。\n", file=sys.stderr)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
