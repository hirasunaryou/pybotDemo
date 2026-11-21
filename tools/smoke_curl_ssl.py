"""macOS integration check: a simulated python.org CA failure followed by REAL system curl.

This check deliberately does not disable TLS verification. It must fail when
macOS /usr/bin/curl cannot validate GitHub's HTTPS certificate.
"""
import ssl
import tempfile
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

from demo import bootstrap


def main():
    url = "https://codeload.github.com/huggingface/pybot/zip/" + bootstrap.UPSTREAM_COMMIT
    error = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "pybot.zip"
        with mock.patch.object(bootstrap, "_download_with_python", side_effect=error):
            bootstrap._download_securely(url, target, print)
        if not zipfile.is_zipfile(target):
            raise RuntimeError("Fallback produced a non-ZIP archive")
        with zipfile.ZipFile(target) as z:
            names = set(z.namelist())
        if not any(n.endswith("/bot/runtime.py") for n in names):
            raise RuntimeError("Fallback did not retrieve the upstream PyBot source")
    print("PASS: Python SSL failure -> system curl with verified HTTPS -> pinned PyBot ZIP")


if __name__ == "__main__":
    main()
