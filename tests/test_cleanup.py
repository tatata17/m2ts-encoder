"""失敗・中断のあとの片づけ(作りかけの出力を残さない。前からあるファイルには、さわらない)"""
import os
import unittest

from support import m, Case, bare_app, drain, logs_of
from encode_helpers import run_one, LOG_OK, LOG_FAIL


class AfterFailure(Case):
    def setUp(self):
        super().setUp()
        self.source = self.write("rec.m2ts")
        # 前からある、別の回の変換済みファイル(同じ番組名)
        self.write("番組X,20261031.mkv", b"old video")
        self.write("番組X,20261031.csv", b"old csv")

    def assert_old_files_untouched(self):
        with open(os.path.join(self.dir, "番組X,20261031.mkv"), "rb") as f:
            self.assertEqual(f.read(), b"old video")
        with open(os.path.join(self.dir, "番組X,20261031.csv"), "rb") as f:
            self.assertEqual(f.read(), b"old csv")

    def test_failed_output_is_removed(self):
        code, items, _cmd = run_one(self, self.source, LOG_FAIL,
                                    {self.source + ".mkv": b"broken", self.source + ".csv": b"c"}, returncode=1)
        self.assertEqual(code, 1)
        self.assertEqual(self.tree(), ["rec.m2ts", "番組X,20261031.csv", "番組X,20261031.mkv"])
        self.assert_old_files_untouched()
        self.assertIn(("converted", "I", False), items)
        self.assertEqual([item[2] for item in items if item[0] == "diag"], ["失敗"])
        self.assertTrue(any(line.startswith("[掃除]") for line in logs_of(items)))

    def test_failure_never_removes_an_earlier_output_of_the_same_episode(self):
        """同じ回の変換済みファイルが前からあるときに失敗しても、それを「今回の残骸」として消さない"""
        self.write("番組X,20261107.mkv", b"earlier good video")
        self.write("番組X,20261107.csv", b"earlier csv")
        run_one(self, self.source, LOG_FAIL, {}, returncode=1)
        with open(os.path.join(self.dir, "番組X,20261107.mkv"), "rb") as f:
            self.assertEqual(f.read(), b"earlier good video")
        self.assertIn("番組X,20261107.csv", os.listdir(self.dir))
        self.assert_old_files_untouched()

    def test_success_keeps_the_output_and_the_source(self):
        _code, items, _cmd = run_one(self, self.source, LOG_OK,
                                     {self.source + ".mkv": b"v" * 100, self.source + ".csv": b"c"})
        self.assertEqual(self.tree(), ["rec.m2ts", "番組X,20261031.csv", "番組X,20261031.mkv",
                                       "番組X,20261107.csv", "番組X,20261107.mkv"])
        self.assert_old_files_untouched()
        self.assertIn(("converted", "I", True), items)
        self.assertFalse(any(line.startswith("[掃除]") for line in logs_of(items)))

    def test_nothing_produced_and_no_progress_counts_as_failure(self):
        """ログからは失敗と読めなくても、出力が無く、進み具合も出ていなければ「できた」ことにしない"""
        _code, items, _cmd = run_one(self, self.source, ["元のファイルを開いています..."], {})
        self.assertEqual([item[2] for item in items if item[0] == "diag"], ["失敗"])
        self.assertIn(("converted", "I", False), items)
        self.assert_old_files_untouched()

    def test_source_recording_is_never_touched(self):
        for lines, creates, code in ((LOG_OK, {self.source + ".mkv": b"v" * 100}, 0), (LOG_FAIL, {}, 1)):
            with self.subTest(code=code):
                run_one(self, self.source, lines, creates, returncode=code)
                with open(self.source, "rb") as f:
                    self.assertEqual(f.read(), b"x")


class AfterStop(Case):
    """「中断」を押したとき"""

    def setUp(self):
        super().setUp()
        self.patch("time", type("NoSleep", (), {"sleep": staticmethod(lambda seconds: None),
                                                "time": staticmethod(m.time.time)}))
        self.source = self.write("rec.m2ts")

    def test_partial_output_is_removed(self):
        _code, items, _cmd = run_one(self, self.source, LOG_OK[:2], {self.source + ".mkv": b"half"}, stop=True)
        self.assertEqual(self.tree(), ["rec.m2ts"])
        logs = logs_of(items)
        self.assertTrue(any("[中断]" in line for line in logs))
        self.assertFalse(any(item[0] in ("diag", "converted") for item in items))   # 途中のものを、診断や変換済みにしない

    def test_stop_during_merge_keeps_the_finished_first_pass(self):
        """合体(字幕などを後から足す)の途中で止めたら、できあがっている1回目の出力は残す"""
        lines = LOG_OK + ["[MERGE] 字幕を合体しています"]
        run_one(self, self.source, lines,
                {self.source + ".mkv": b"finished", self.source + ".withsub.mkv": b"half"}, stop=True)
        self.assertEqual(self.tree(), ["rec.m2ts", "rec.m2ts.mkv"])

    def test_stop_during_reencode_puts_the_old_file_back(self):
        """作り直しの途中で止めたら、退避しておいた元の変換済みファイルを戻す"""
        original = self.write("番組X,20261107.mkv", b"old video")
        stash = bare_app()._stash_previous_output(original)
        self.assertEqual(os.path.basename(stash), "番組X,20261107.mkv.old")
        _code, items, _cmd = run_one(self, self.source, LOG_OK[:2], {self.source + ".mkv": b"half"},
                                     stop=True, row={"reencode_old": (original, stash)})
        self.assertEqual(self.tree(), ["rec.m2ts", "番組X,20261107.mkv"])
        with open(original, "rb") as f:
            self.assertEqual(f.read(), b"old video")
        self.assertIn(("converted", "I", True), items)

    def test_failed_reencode_puts_the_old_file_back(self):
        original = self.write("番組X,20261107.mkv", b"old video")
        stash = bare_app()._stash_previous_output(original)
        run_one(self, self.source, LOG_FAIL, {self.source + ".mkv": b"broken"}, returncode=1,
                row={"reencode_old": (original, stash)})
        self.assertEqual(self.tree(), ["rec.m2ts", "番組X,20261107.mkv"])
        with open(original, "rb") as f:
            self.assertEqual(f.read(), b"old video")


class LeftoverFromLastTime(Case):
    """前回、途中で終わって残った出力"""

    def test_stale_outputs_are_removed_before_encoding_again(self):
        app = bare_app()
        source = self.write("rec.m2ts")
        for name in ("rec.m2ts.mkv", "rec.m2ts.mp4", "rec.m2ts.withsub.mkv"):
            self.write(name, b"half")
        self.write("rec.m2ts.csv", b"c")
        self.write("番組X,20261031.mkv", b"finished")
        app._remove_stale_outputs(source, "前回途中で止まった出力が残っていたため")
        self.assertEqual(self.tree(), ["rec.m2ts", "rec.m2ts.csv", "番組X,20261031.mkv"])
        self.assertEqual(len([line for line in logs_of(drain(app.encode_queue)) if line.startswith("[掃除]")]), 3)

    def test_keep_main_keeps_only_the_first_pass(self):
        app = bare_app()
        source = self.write("rec.m2ts")
        self.write("rec.m2ts.mkv", b"finished")
        self.write("rec.m2ts.withsub.mkv", b"half")
        app._remove_stale_outputs(source, "中断したため未完成の出力を", keep_main=True)
        self.assertEqual(self.tree(), ["rec.m2ts", "rec.m2ts.mkv"])

    def test_temporary_batch_is_removed_even_when_the_run_raises(self):
        app = bare_app()
        app.settings = {"encoder": "nvenc", "user_presets": {"テスト設定": {}}}
        source = self.write("rec.m2ts")
        app.row_data = {"R": {"path": source}}
        seen = []

        def explode(m2ts_path, bat, bat_dir, name, iid):
            seen.append(bat)
            self.assertTrue(os.path.isfile(bat))
            raise RuntimeError("途中で落ちた")
        app._run_bat_process = explode
        with self.assertRaises(RuntimeError):
            app._run_bat_inner(source, m.PRESET_PREFIX + "テスト設定", "R")
        self.assertFalse(os.path.exists(seen[0]))


if __name__ == "__main__":
    unittest.main()
