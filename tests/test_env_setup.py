"""環境セットアップ(ffmpeg / ffprobe の導入)と、プラグインフォルダの場所

インターネットには出ない。このパソコンの中だけで動く、にせの配布サーバーを立てて試す。
"""
import hashlib
import http.server
import io
import json
import os
import threading
import time
import unittest
import zipfile

from support import m, Case

FAKE_VERSION_OUTPUT = "ffmpeg version 9.9-full_build\nconfiguration: --enable-libaribb24\n"


def make_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ffmpeg-9.9-full_build/bin/ffmpeg.exe", b"FFMPEG" * 1000)
        z.writestr("ffmpeg-9.9-full_build/bin/ffprobe.exe", b"FFPROBE" * 1000)
        z.writestr("ffmpeg-9.9-full_build/bin/ffplay.exe", b"x")
        z.writestr("ffmpeg-9.9-full_build/doc/ffmpeg.exe", b"WRONG PLACE")
    return buffer.getvalue()


class Install(Case):
    @classmethod
    def setUpClass(cls):
        cls.zip_data = make_zip()
        sha = hashlib.sha256(cls.zip_data).hexdigest()
        asset = "ffmpeg-9.9-full_build.zip"
        cls.pages = {
            "/ver": b"9.9\n", "/badver": b"<html>oops</html>",
            "/f.zip": cls.zip_data, "/cut.zip": cls.zip_data[:len(cls.zip_data) // 2],
            "/api": json.dumps({"assets": [{"name": asset, "digest": "sha256:" + sha}]}).encode(),
            "/badapi": json.dumps({"assets": [{"name": asset, "digest": "sha256:" + "0" * 64}]}).encode(),
        }
        pages = cls.pages

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                data = pages.get(self.path.split("?")[0])
                self.send_response(200 if data is not None else 404)
                self.send_header("Content-Length", str(len(data or b"")))
                self.end_headers()
                self.wfile.write(data or b"")

            def log_message(self, *args):
                pass
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.saved_env = {k: os.environ.pop(k) for k in list(os.environ) if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
        cls.saved_no_proxy = os.environ.get("no_proxy")
        os.environ["no_proxy"] = "127.0.0.1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.update(cls.saved_env)
        if cls.saved_no_proxy is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = cls.saved_no_proxy

    def setUp(self):
        super().setUp()
        self.dest = os.path.join(self.dir, "アプリの フォルダ")
        self.downloads = os.path.join(m.get_app_data_dir(), "downloads")
        self.patch("tool_version_output", lambda path, timeout=20.0: FAKE_VERSION_OUTPUT)
        self.point_to()

    def point_to(self, ver="/ver", api="/api", zip_name="/f.zip"):
        self.patch("FFMPEG_VERSION_URLS", (self.base + "/nothing", self.base + ver))
        self.patch("FFMPEG_LATEST_PAGE", self.base + "/nothing2")
        self.patch("FFMPEG_RELEASE_API", self.base + api + "?{ver}")
        self.patch("FFMPEG_ZIP_URL", self.base + zip_name + "?{ver}")

    def install(self, names=("ffmpeg.exe", "ffprobe.exe"), **kwargs):
        self.logs = []
        return m.install_ffmpeg_tools(list(names), self.dest, log=self.logs.append, **kwargs)

    def placed(self):
        return sorted(os.listdir(self.dest)) if os.path.isdir(self.dest) else []

    def test_installs_only_the_two_tools(self):
        progress = []
        result = self.install(progress=lambda done, total: progress.append((done, total)))
        self.assertEqual([os.path.basename(p) for p in result], ["ffmpeg.exe", "ffprobe.exe"])
        self.assertEqual(self.placed(), ["ffmpeg.exe", "ffprobe.exe"])       # ffplay や、作業用のファイルは置かない
        with open(os.path.join(self.dest, "ffmpeg.exe"), "rb") as f:
            self.assertEqual(f.read(), b"FFMPEG" * 1000)                      # bin の中のものを取り出している
        self.assertEqual(progress[-1], (len(self.zip_data), len(self.zip_data)))
        self.assertEqual(os.listdir(self.downloads), [])                      # ダウンロードした zip は消す
        self.assertTrue(any("一致しました" in line for line in self.logs))

    def test_existing_file_is_not_overwritten(self):
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "ffprobe.exe"), "wb") as f:
            f.write(b"MINE")
        result = self.install()
        self.assertEqual([os.path.basename(p) for p in result], ["ffmpeg.exe"])
        with open(os.path.join(self.dest, "ffprobe.exe"), "rb") as f:
            self.assertEqual(f.read(), b"MINE")

    def expect_failure(self, pattern, **kwargs):
        with self.assertRaisesRegex(m.SetupError, pattern):
            self.install(**kwargs)
        self.assertEqual(self.placed(), [])                                   # 失敗したら、何も置かない
        self.assertEqual(os.listdir(self.downloads), [])

    def test_wrong_sha256_is_rejected(self):
        self.point_to(api="/badapi")
        self.expect_failure("一致しません")

    def test_missing_sha256_record_still_installs(self):
        self.point_to(api="/noapi")
        self.assertEqual(len(self.install()), 2)

    def test_broken_zip_is_rejected(self):
        self.point_to(api="/noapi", zip_name="/cut.zip")
        self.expect_failure("開けませんでした")

    def test_unreadable_version_is_rejected(self):
        self.point_to(ver="/badver")
        self.expect_failure("版数")

    def test_download_error_names_the_source(self):
        self.point_to(zip_name="/none.zip")
        self.expect_failure("ダウンロードできませんでした")

    def test_cancel(self):
        self.expect_failure("中止しました", should_stop=lambda: True)

    def test_tool_that_does_not_run_is_taken_back(self):
        self.patch("tool_version_output", lambda path, timeout=20.0: "")
        self.expect_failure("取り消しました")


class Check(Case):
    """必要なものの一覧(見つかった・見つからない)と、「入れるもの」の決め方"""

    def setUp(self):
        super().setUp()
        self.patch("get_script_dir", lambda: self.dir)
        self.patch("find_rplsinfo", lambda: None)
        self.patch("find_vlc", lambda explicit_path=None: None)
        self.found(None, None)

    def found(self, ffmpeg, ffprobe, output=FAKE_VERSION_OUTPUT):
        self.patch("find_ffmpeg", lambda: ffmpeg)
        self.patch("find_ffprobe", lambda: ffprobe)
        self.patch("tool_version_output", lambda path, timeout=20.0: output)
        rows = m.check_environment("8.6")
        return {row["key"]: row["state"] for row in rows}, m.ffmpeg_tools_to_install(rows)

    def test_nothing_installed(self):
        states, names = self.found(None, None)
        self.assertEqual(states, {"python": "ok", "rplsinfo": "missing", "ffmpeg": "missing",
                                  "ffprobe": "missing", "vlc": "optional"})
        self.assertEqual(names, ["ffmpeg.exe", "ffprobe.exe"])                # rplsinfo と VLC は、自動では入れない

    def test_full_build_needs_nothing(self):
        states, names = self.found("/elsewhere/ffmpeg.exe", "/elsewhere/ffprobe.exe")
        self.assertEqual((states["ffmpeg"], names), ("ok", []))

    def test_essentials_build_elsewhere_can_be_replaced_by_a_copy_in_the_app_folder(self):
        states, names = self.found("/elsewhere/ffmpeg.exe", "/elsewhere/ffprobe.exe",
                                   "ffmpeg version 9.9-essentials_build\nconfiguration: --enable-gpl\n")
        self.assertEqual((states["ffmpeg"], names), ("warn", ["ffmpeg.exe", "ffprobe.exe"]))

    def test_essentials_build_in_the_app_folder_is_not_overwritten(self):
        mine = self.write("ffmpeg.exe")
        states, names = self.found(mine, self.write("ffprobe.exe"),
                                   "ffmpeg version 9.9-essentials_build\nconfiguration: --enable-gpl\n")
        self.assertEqual((states["ffmpeg"], names), ("warn", []))

    def test_unreadable_version_is_not_called_a_problem(self):
        states, names = self.found("/elsewhere/ffmpeg.exe", "/elsewhere/ffprobe.exe", "")
        self.assertEqual((states["ffmpeg"], names), ("ok", []))


class PluginFolder(Case):
    """Microsoft Store 版の Python で置いたプラグインを、通常版の Python でも見つける"""

    def setUp(self):
        super().setUp()
        self.own = os.path.join(self.dir, "m2ts_encoder", "plugins")
        self.patch("get_app_data_dir", lambda: os.path.join(self.dir, "m2ts_encoder"))
        find = m.find_store_python_plugin_dirs
        self.patch("find_store_python_plugin_dirs", lambda local_app_data=None: find(self.dir))

    def store(self, version, files):
        folder = os.path.join(self.dir, "Packages", f"PythonSoftwareFoundation.Python.{version}_abc123",
                              "LocalCache", "Local", "m2ts_encoder", "plugins")
        os.makedirs(folder)
        for name in files:
            with open(os.path.join(folder, name), "w") as f:
                f.write("x")
        return folder

    def test_own_folder_when_nothing_else_exists(self):
        self.assertEqual(m.get_plugins_dir(), self.own)
        self.assertTrue(os.path.isdir(self.own))

    def test_store_folder_is_used_only_while_own_folder_has_no_plugin(self):
        self.store("3.12", ["readme.txt"])                                    # .py が無いフォルダは数えない
        os.makedirs(os.path.join(self.dir, "Packages", "Other.App", "LocalCache", "Local", "m2ts_encoder", "plugins"))
        older = self.store("3.11", ["a.py"])
        self.assertEqual(m.get_plugins_dir(), older)
        time.sleep(0.05)
        newer = self.store("3.10", ["b.py"])
        self.assertEqual(m.find_store_python_plugin_dirs(), [newer, older])   # 新しく使われたほうが先
        with open(os.path.join(self.own, "note.txt"), "w") as f:
            f.write("x")
        self.assertEqual(m.get_plugins_dir(), newer)
        with open(os.path.join(self.own, "mine.py"), "w") as f:
            f.write("x")
        self.assertEqual(m.get_plugins_dir(), self.own)                       # 自分のフォルダに .py があれば、そちら


if __name__ == "__main__":
    unittest.main()
