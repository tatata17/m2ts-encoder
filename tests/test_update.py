"""アップデートの照合(公開側 tools/release.py と、アプリ側の計算が食い違っていないこと)

ネットワークには出ない。ダウンロードの部分は、手元のデータを返すにせものに差しかえる。
"""
import hashlib
import json
import os
import subprocess
import sys
import unittest

from support import m, Case, ROOT, APP_PATH


def body(version="2099.01.01.1", newline=b"\n", extra=b""):
    """本体の代わりになる、10万バイト以上の正しい Python のソース"""
    lines = [b"# test body", b'APP_VERSION = "' + version.encode() + b'"'] + [b"# " + b"x" * 70] * 1500
    return newline.join(lines) + newline + extra


class Download(Case):
    def fetch(self, raw, **info):
        self.patch("_http_get", lambda url, timeout=15.0: raw)
        return m.download_update_source(dict({"version": "2099.01.01.1", "file": "m2ts_encoder.pyw"}, **info))

    def test_matching_sha256_passes(self):
        raw = body()
        self.assertEqual(self.fetch(raw, sha256=hashlib.sha256(raw).hexdigest()), raw)

    def test_crlf_download_matches_the_lf_hash_and_is_saved_as_lf(self):
        """改行コードが CRLF で届いても、LF にそろえてから照合する(公開側と同じ計算)"""
        lf, crlf = body(), body(newline=b"\r\n")
        self.assertEqual(self.fetch(crlf, sha256=hashlib.sha256(lf).hexdigest()), lf)

    def test_wrong_sha256_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.fetch(body(extra=b"# tampered\n"), sha256=hashlib.sha256(body()).hexdigest())

    def test_old_version_json_without_sha256_still_works(self):
        raw = body()
        self.assertEqual(self.fetch(raw), raw)

    def test_too_small_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "小さすぎます"):
            self.fetch(b'APP_VERSION = "2099.01.01.1"\n')

    def test_version_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "版番号"):
            self.fetch(body(version="2099.01.01.2"))

    def test_syntax_error_is_rejected(self):
        with self.assertRaises(SyntaxError):
            self.fetch(body(extra=b"def broken(:\n"))

    def test_version_comparison(self):
        self.assertTrue(m.is_newer_version("2026.11.24.2", "2026.11.24.1"))
        self.assertTrue(m.is_newer_version("2026.11.24.10", "2026.11.24.9"))     # 文字ではなく、数として比べる
        self.assertFalse(m.is_newer_version("2026.11.24.1", "2026.11.24.1"))
        self.assertFalse(m.is_newer_version("2026.11.23.9", "2026.11.24.1"))
        self.assertFalse(m.is_newer_version("こわれた値", "2026.11.24.1"))


class ReleaseScript(Case):
    """tools/release.py が書く version.json を、アプリ側の確認にそのまま通す(一時フォルダに写した tools で試す)"""

    def run_release(self, source, *args, tests_pass=True):
        work = os.path.join(self.dir, "repo")
        os.makedirs(os.path.join(work, "tools"), exist_ok=True)
        os.makedirs(os.path.join(work, "tests"), exist_ok=True)
        with open(os.path.join(work, "tests", "run_tests.py"), "w", encoding="utf-8") as f:
            f.write("import sys\nprint('stub tests')\nsys.exit(%d)\n" % (0 if tests_pass else 1))   # テストの代わり
        with open(ROOT / "tools" / "release.py", "rb") as f:
            script = f.read()
        with open(os.path.join(work, "tools", "release.py"), "wb") as f:
            f.write(script)
        with open(os.path.join(work, "m2ts_encoder.pyw"), "wb") as f:
            f.write(source)
        done = subprocess.run([sys.executable, os.path.join(work, "tools", "release.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=work)
        info_path = os.path.join(work, "version.json")
        info = None
        if os.path.exists(info_path):
            with open(info_path, encoding="utf-8") as f:
                info = json.load(f)
        return done, info

    def test_written_hash_is_accepted_by_the_app(self):
        crlf = body(newline=b"\r\n")                                    # 手元のファイルが CRLF でも
        done, info = self.run_release(crlf, "テストの更新")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual((info["version"], info["file"], info["notes"]), ("2099.01.01.1", "m2ts_encoder.pyw", "テストの更新"))
        self.patch("_http_get", lambda url, timeout=15.0: body())       # 配布されるのは LF
        self.assertEqual(m.download_update_source(info), body())

    def test_same_version_with_a_different_body_is_stopped(self):
        self.run_release(body(), "1回目")
        done, info = self.run_release(body(extra=b"# changed\n"), "2回目")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(info["notes"], "1回目")                         # version.json は、書きかえられていない

    def test_failing_tests_stop_the_release(self):
        done, info = self.run_release(body(), "出してはいけない", tests_pass=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIsNone(info)                                         # version.json は書かれない
        self.assertIn("テスト", done.stdout + done.stderr)

    def test_missing_tests_stop_the_release(self):
        self.run_release(body(), "1回目")
        os.remove(os.path.join(self.dir, "repo", "tests", "run_tests.py"))
        os.remove(os.path.join(self.dir, "repo", "version.json"))
        done = subprocess.run([sys.executable, os.path.join(self.dir, "repo", "tools", "release.py")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "repo", "version.json")))

    def test_syntax_error_is_stopped(self):
        done, info = self.run_release(body(extra=b"def broken(:\n"))
        self.assertNotEqual(done.returncode, 0)
        self.assertIsNone(info)

    def test_real_version_json_matches_the_real_body(self):
        """リポジトリの version.json が、いまの本体と合っているか(本体を変えたのに release.py を忘れた、を見つける)。
        本体のほうが新しい版(これから公開する途中)なら、まだ書かれていなくてよい。"""
        with open(ROOT / "version.json", encoding="utf-8") as f:
            info = json.load(f)
        raw = APP_PATH.read_bytes().replace(b"\r\n", b"\n")
        if m.parse_version(m.APP_VERSION) > m.parse_version(info["version"]):
            self.skipTest("本体の版番号が version.json より新しい(公開の作業中)")
        self.assertEqual(info["version"], m.APP_VERSION)
        self.assertEqual(info["sha256"], hashlib.sha256(raw).hexdigest(),
                         "本体が、version.json を書いたあとに変わっています。APP_VERSION を上げて release.py を実行してください")


if __name__ == "__main__":
    unittest.main()
