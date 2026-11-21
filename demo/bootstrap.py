"""Retrieve an unmodified, pinned upstream PyBot only when first needed.

The downloaded tree is ignored by Git: it is research material, not our app.
No pip packages, Git installation, or LLM credentials are needed.
"""
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE = PROJECT_ROOT / ".runtime" / "pybot"
UPSTREAM_REPO = "https://github.com/huggingface/pybot"
UPSTREAM_COMMIT = "7d63c7fbebb44c7e466e5c8b5c1f341ab767929e"
MAX_ARCHIVE = 100 * 1024 * 1024


class BootstrapError(RuntimeError):
    """An actionable first-run error, not an unexpected application crash."""


def _download_with_python(request, destination):
    """Fetch using Python's normal verified HTTPS connection."""
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as dest:
        count = 0
        while True:
            block = response.read(256 * 1024)
            if not block:
                break
            count += len(block)
            if count > MAX_ARCHIVE:
                raise BootstrapError("PyBotのダウンロードサイズが安全上の上限を超えました。")
            dest.write(block)


def _is_certificate_failure(error):
    """Only a genuine certificate verification error warrants native-curl fallback."""
    root = error
    for _ in range(5):
        if isinstance(root, ssl.SSLCertVerificationError):
            return True
        if isinstance(root, ssl.SSLError) and (
            "CERTIFICATE_VERIFY_FAILED" in str(root) or "certificate verify failed" in str(root).lower()
        ):
            return True
        root = getattr(root, "reason", None) or getattr(root, "__cause__", None)
        if root is None:
            break
    return False


def _native_curl():
    """macOS system curl uses native platform trust; other platforms use PATH curl."""
    preferred = Path("/usr/bin/curl")
    if sys.platform == "darwin" and preferred.is_file():
        return str(preferred)
    return shutil.which("curl")


def _download_with_native_curl(url, destination):
    """Retry with the OS certificate trust store WITHOUT disabling TLS verification.

    On macOS, python.org's Python may lack its CA bundle even though /usr/bin/curl
    correctly verifies the same HTTPS site against the system's trusted roots.
    """
    curl = _native_curl()
    if not curl:
        raise BootstrapError("システムのcurlコマンドが見つかりませんでした。")
    args = [
        curl, "--fail", "--location", "--silent", "--show-error",
        "--proto", "=https", "--proto-redir", "=https",
        "--tlsv1.2", "--connect-timeout", "20", "--max-time", "150",
        "--max-filesize", str(MAX_ARCHIVE),
        "--output", str(destination), url,
    ]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=165, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BootstrapError("システムcurlでの取得に失敗しました: " + str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:500] or ("終了コード " + str(result.returncode))
        raise BootstrapError("システムcurlでHTTPS取得に失敗しました: " + detail)
    if not destination.is_file() or not 0 < destination.stat().st_size <= MAX_ARCHIVE:
        raise BootstrapError("取得したファイルが空、または安全上のサイズ上限を超えています。")


def _download_securely(url, archive, output):
    request = urllib.request.Request(url, headers={"User-Agent": "pybot-live-lab/1.0"})
    try:
        _download_with_python(request, archive)
        return
    except Exception as original:
        if not _is_certificate_failure(original):
            raise BootstrapError("PyBotのHTTPSダウンロードに失敗しました: " + str(original)) from original
        output("PythonのSSL証明書を検証できません。OSの証明書を使う安全な方法で再試行します…")
        try:
            _download_with_native_curl(url, archive)
        except BootstrapError as second:
            suggestion = (
                "\nMacのPython.org版の場合: Finder → アプリケーション → "
                "Python 3.13 → Install Certificates.command を実行してください。"
                if sys.platform == "darwin" else
                "\nOSの証明書設定とネットワーク接続を確認してください。"
            )
            raise BootstrapError(
                "初回のPyBot取得でSSL証明書を検証できませんでした。"
                + suggestion
                + "\nTLS証明書検証を無効化する処理は実施していません。"
                + "\n再試行の詳細: " + str(second)
            ) from second
        output("OSの証明書検証を利用して、PyBotを安全に取得しました。")


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
        _download_securely(url, archive, output)
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
