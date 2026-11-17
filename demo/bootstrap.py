"""Retrieve an unmodified, pinned upstream PyBot only when first needed.

The downloaded tree is ignored by Git: it is research material, not our app.
No pip packages, Git installation, or LLM credentials are needed.
"""
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import urllib.request
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE = PROJECT_ROOT / ".runtime" / "pybot"
UPSTREAM_REPO = "https://github.com/huggingface/pybot"
UPSTREAM_COMMIT = "7d63c7fbebb44c7e466e5c8b5c1f341ab767929e"
MAX_ARCHIVE = 100 * 1024 * 1024


def _valid(path):
    return (path / "bot" / "runtime.py").is_file() and (path / "bot" / "modules" / "arbiter.py").is_file()


def ensure_upstream(output=print):
    """Return the PyBot source directory; honor an explicitly supplied local checkout."""
    override = os.getenv("PYBOT_DEMO_SOURCE", "").strip()
    if override:
        location = Path(override).expanduser().resolve()
        if not _valid(location):
            raise RuntimeError("PYBOT_DEMO_SOURCE は bot/runtime.py を含むPyBotの親フォルダを指定してください: " + str(location))
        output("ローカルのPyBotを使用: " + str(location))
        return location
    if (_valid(CACHE) and (CACHE / ".demo-source-commit").is_file() and
            (CACHE / ".demo-source-commit").read_text(encoding="utf-8").strip() == UPSTREAM_COMMIT):
        output("取得済みの固定版PyBotを使用します。")
        return CACHE

    output("初回セットアップ: Hugging Face の公開PyBotを固定コミットから取得しています…")
    output("GPU、pipインストール、APIキーは不要です。初回のみネット接続が必要です。")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pybot-fetch-", dir=str(CACHE.parent)) as tmp_name:
        tmp = Path(tmp_name)
        archive = tmp / "source.zip"
        url = "https://codeload.github.com/huggingface/pybot/zip/" + UPSTREAM_COMMIT
        req = urllib.request.Request(url, headers={"User-Agent": "pybot-live-lab/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=90) as response, archive.open("wb") as dest:
                amount = 0
                while True:
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    amount += len(block)
                    if amount > MAX_ARCHIVE:
                        raise RuntimeError("PyBotアーカイブが安全上のサイズ上限を超えました")
                    dest.write(block)
        except Exception as exc:
            raise RuntimeError(
                "PyBotの初回ダウンロードに失敗しました。ネット接続を確認して再度起動するか、"
                "公式PyBotを別途クローンして環境変数 PYBOT_DEMO_SOURCE を指定してください。"
                " 原因: " + str(exc)
            ) from exc
        stage = tmp / "source"
        stage.mkdir()
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                parts = PurePosixPath(item.filename).parts
                if item.is_dir() or len(parts) < 2:
                    continue
                relative = PurePosixPath(*parts[1:])
                if ".." in relative.parts or relative.is_absolute():
                    raise RuntimeError("アーカイブに不正なパスが含まれています")
                # We need the unchanged bot and a few license/metadata files only.
                if relative.parts[0] not in ("bot", "LICENSE", "README.md", "pybot.py"):
                    continue
                target = stage.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
        if not _valid(stage):
            raise RuntimeError("ダウンロードしたPyBotに必要な本体ファイルがありません")
        (stage / ".demo-source-commit").write_text(UPSTREAM_COMMIT, encoding="utf-8")
        if CACHE.exists():
            shutil.rmtree(CACHE)
        shutil.move(str(stage), str(CACHE))
    output("PyBotを取得しました: " + str(CACHE))
    return CACHE
