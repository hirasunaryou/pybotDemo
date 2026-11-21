"""Regression tests for macOS Python.org certificate bootstrap failures.

No network is used and no TLS verification is disabled. These tests simulate
Python's SSL failure, an OS-trusted curl retry and a correctly pinned ZIP.
"""
import io
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error
import zipfile

from demo import bootstrap


SSL_FAILED = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))


class SecureBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.url = "https://codeload.github.com/huggingface/pybot/zip/" + bootstrap.UPSTREAM_COMMIT

    def test_cert_error_is_recognized_without_accepting_other_errors(self):
        self.assertTrue(bootstrap._is_certificate_failure(SSL_FAILED))
        self.assertTrue(bootstrap._is_certificate_failure(ssl.SSLCertVerificationError(1, "bad CA")))
        self.assertFalse(bootstrap._is_certificate_failure(urllib.error.URLError("DNS unreachable")))
        self.assertFalse(bootstrap._is_certificate_failure(RuntimeError("network down")))

    def test_certificate_failure_retries_with_verified_system_curl(self):
        archive = self.root / "source.zip"
        notes = []
        with (
            mock.patch.object(bootstrap, "_download_with_python", side_effect=SSL_FAILED) as first,
            mock.patch.object(bootstrap, "_download_with_native_curl") as second,
        ):
            bootstrap._download_securely(self.url, archive, notes.append)
        self.assertEqual(first.call_count, 1)
        second.assert_called_once_with(self.url, archive)
        self.assertTrue(any("SSL" in note for note in notes))
        self.assertTrue(any("安全" in note for note in notes))

    def test_no_retry_for_unrelated_network_error(self):
        archive = self.root / "source.zip"
        with (
            mock.patch.object(bootstrap, "_download_with_python",
                              side_effect=urllib.error.URLError("DNS unreachable")),
            mock.patch.object(bootstrap, "_download_with_native_curl") as fallback,
        ):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "HTTPSダウンロード"):
                bootstrap._download_securely(self.url, archive, lambda _: None)
        fallback.assert_not_called()

    def test_second_certificate_failure_is_actionable_not_insecure(self):
        archive = self.root / "source.zip"
        with (
            mock.patch.object(bootstrap, "_download_with_python", side_effect=SSL_FAILED),
            mock.patch.object(bootstrap, "_download_with_native_curl",
                              side_effect=bootstrap.BootstrapError("curl: (60) SSL certificate problem")),
        ):
            with self.assertRaises(bootstrap.BootstrapError) as context:
                bootstrap._download_securely(self.url, archive, lambda _: None)
        message = str(context.exception)
        self.assertIn("SSL証明書", message)
        self.assertIn("無効化する処理は実施していません", message)
        self.assertIn("curl: (60)", message)

    def test_curl_restricts_protocol_and_keeps_tls_verification(self):
        archive = self.root / "source.zip"
        seen = []
        def fake_run(args, **kwargs):
            seen.extend(args)
            Path(args[args.index("--output") + 1]).write_bytes(b"zip data")
            return subprocess.CompletedProcess(args, 0, "", "")
        with (
            mock.patch.object(bootstrap, "_native_curl", return_value="/usr/bin/curl"),
            mock.patch.object(bootstrap.subprocess, "run", side_effect=fake_run),
        ):
            bootstrap._download_with_native_curl(self.url, archive)
        self.assertEqual(seen[0], "/usr/bin/curl")
        self.assertEqual(seen[seen.index("--proto") + 1], "=https")
        self.assertEqual(seen[seen.index("--proto-redir") + 1], "=https")
        self.assertIn("--tlsv1.2", seen)
        self.assertIn("--max-filesize", seen)
        self.assertIn("--fail", seen)
        self.assertNotIn("-k", seen)
        self.assertNotIn("--insecure", seen)
        self.assertNotIn("--cacert", seen)
        self.assertEqual(archive.read_bytes(), b"zip data")

    def test_failed_curl_does_not_appear_to_succeed(self):
        archive = self.root / "source.zip"
        with (
            mock.patch.object(bootstrap, "_native_curl", return_value="/usr/bin/curl"),
            mock.patch.object(bootstrap.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["/usr/bin/curl"], 60, "", "curl: (60) SSL certificate problem"
            )),
        ):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "certificate problem"):
                bootstrap._download_with_native_curl(self.url, archive)

    def test_cert_failure_then_valid_pinned_source_is_cached(self):
        cache = self.root / "cache" / "pybot"
        notes = []
        def make_zip(url, archive):
            self.assertEqual(url, self.url)
            with zipfile.ZipFile(archive, "w") as dest:
                prefix = "pybot-" + bootstrap.UPSTREAM_COMMIT
                dest.writestr(prefix + "/bot/runtime.py", "def turn(text, memory): pass\n")
                dest.writestr(prefix + "/bot/modules/arbiter.py", "def choose(*args): return 0\n")
                dest.writestr(prefix + "/LICENSE", "Apache License Version 2.0\n")
        with (
            mock.patch.object(bootstrap, "CACHE", cache),
            mock.patch.object(bootstrap, "_download_with_python", side_effect=SSL_FAILED),
            mock.patch.object(bootstrap, "_download_with_native_curl", side_effect=make_zip) as fallback,
            mock.patch.dict("os.environ", {"PYBOT_DEMO_SOURCE": ""}),
        ):
            self.assertEqual(bootstrap.ensure_upstream(output=notes.append), cache)
            self.assertTrue((cache / "bot" / "runtime.py").exists())
            self.assertEqual((cache / ".demo-source-commit").read_text().strip(),
                             bootstrap.UPSTREAM_COMMIT)
            self.assertEqual(bootstrap.ensure_upstream(output=notes.append), cache)
            self.assertEqual(fallback.call_count, 1, "A valid cache should skip all network access")

    def test_curl_is_optional_and_never_called_if_python_tls_succeeds(self):
        archive = self.root / "source.zip"
        with (
            mock.patch.object(bootstrap, "_download_with_python", side_effect=lambda _, p: p.write_bytes(b"ok")),
            mock.patch.object(bootstrap, "_download_with_native_curl") as fallback,
        ):
            bootstrap._download_securely(self.url, archive, lambda _: None)
        self.assertEqual(archive.read_bytes(), b"ok")
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
