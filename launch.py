#!/usr/bin/env python3
"""One action, first-time setup through browser launch (Python standard library)."""
import sys
import traceback
import webbrowser

if sys.version_info < (3, 8):
    raise SystemExit("Python 3.8以上が必要です。python.org からPythonをインストールしてください。")

from demo.bootstrap import ensure_upstream
from demo.server import serve


def main():
    try:
        source = ensure_upstream()
        url, server = serve(source)
        print("\nPyBot Live Labを起動しました: " + url)
        print("このウィンドウを閉じるとサーバーも終了します。 Ctrl+Cで終了できます。")
        webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました。")
    except Exception:
        print("\n起動に失敗しました。以下の内容を確認してください。\n", file=sys.stderr)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
