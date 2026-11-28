"""空白・カンマ・記号を含むファイル名でも、壊れないこと"""
import os
import unittest

from support import m, Case
from encode_helpers import run_one, LOG_OK

# 空白、カンマ、; = & ^ ( ) % ! ' など、cmd.exe や ffmpeg の引数で事故になりやすい文字を入れた名前
AWKWARD_NAMES = [
    "録画 その1.m2ts",
    "a b  c.ts",
    "番組,2026 (再).m2ts",
    "A&B ^ C=D;E.m2ts",
    "100% 'quote' !.m2ts",
    "　全角　空白　.m2ts",
]


class BatchQuoting(Case):
    """バッチの中の %1 の書き方(空白入りの名前で、引数が途中で切れない形になっているか)"""

    def test_harden_rewrites_every_form(self):
        before = 'ffmpeg -i %1 -o "%1.mkv" %1.csv\nset "X=%1"\nrplsinfo %1 > %1.csv %10'
        after = 'ffmpeg -i "%~1" -o "%~1.mkv" "%~1.csv"\nset "X=%~1"\nrplsinfo "%~1" > "%~1.csv" %10'
        self.assertEqual(m.harden_batch_arg_quoting(before), after)

    def test_harden_is_stable_when_applied_twice(self):
        once = m.harden_batch_arg_quoting('ffmpeg -i "%1" %1.mkv')
        self.assertEqual(m.harden_batch_arg_quoting(once), once)

    def test_fragile_forms_are_detected(self):
        self.assertTrue(m.batch_has_fragile_arg_quoting('ffmpeg -i "%1" out.mkv'))
        self.assertTrue(m.batch_has_fragile_arg_quoting("ffmpeg -i x %1.mkv"))
        self.assertFalse(m.batch_has_fragile_arg_quoting('ffmpeg -i "%~1" "%~1.mkv"'))

    def test_builtin_batches_have_no_fragile_form(self):
        for name, body in m.DEFAULT_BAT_SCRIPTS.items():
            with self.subTest(batch=name):
                self.assertFalse(m.batch_has_fragile_arg_quoting(body))
                self.assertNotIn('"%1"', body)

    def test_preset_batches_have_no_fragile_form(self):
        variants = [{}, {"cuda": True}, {"container": "mp4"}, {"subtitle": True}, {"auto": True},
                    {"cuda": True, "cuda_low_threads": True}]
        for options in variants:
            with self.subTest(options=options):
                body = m.build_preset_batch(options)
                self.assertFalse(m.batch_has_fragile_arg_quoting(body))
                self.assertNotIn('"%1"', body)
                self.assertIn('"%~1"', body)


class CommandLine(Case):
    """バッチを呼ぶコマンドライン(対象のファイルが、必ず " " で1つに囲まれて渡ること)"""

    def test_target_path_is_passed_as_one_quoted_argument(self):
        for name in AWKWARD_NAMES:
            with self.subTest(name=name):
                source = self.write(name)
                _code, _items, cmd_line = run_one(self, source, LOG_OK, {source + ".mkv": b"v" * 100})
                bat = os.path.join(self.dir, "x.bat")
                self.assertTrue(cmd_line.endswith(f' /c ""{bat}" "{source}""'), cmd_line)
                os.remove(os.path.join(self.dir, "番組X,20261107.mkv"))


class OutputNames(Case):
    """できあがったファイルの名前(番組名,日付.mkv)"""

    def test_awkward_source_name_still_gets_renamed(self):
        for name in AWKWARD_NAMES:
            with self.subTest(name=name):
                source = self.write(name)
                _code, items, _cmd = run_one(self, source, LOG_OK,
                                             {source + ".mkv": b"v" * 100, source + ".csv": b"c"})
                self.assertIn(("converted", "I", True), items)
                self.assertIn("番組X,20261107.mkv", os.listdir(self.dir))
                self.assertIn("番組X,20261107.csv", os.listdir(self.dir))
                self.assertNotIn(name + ".mkv", os.listdir(self.dir))
                for leftover in ("番組X,20261107.mkv", "番組X,20261107.csv"):
                    os.remove(os.path.join(self.dir, leftover))

    def test_forbidden_characters_in_title_become_fullwidth(self):
        self.assertEqual(m.sanitize_title_for_filename('A:B*C?D<E>F|G\\H/I"J'), "A：B＊C？D＜E＞F｜G＼H／I”J")
        source = self.write("rec.m2ts")
        run_one(self, source, LOG_OK, {source + ".mkv": b"v" * 100}, program=('どっち? A/B: "最終回"', "20261107"))
        self.assertIn("どっち？ A／B： ”最終回”,20261107.mkv", os.listdir(self.dir))

    def test_title_with_spaces_and_commas_is_kept(self):
        source = self.write("rec.m2ts")
        run_one(self, source, LOG_OK, {source + ".mkv": b"v" * 100}, program=("旅, 食べる  歩く", "20261107"))
        self.assertIn("旅, 食べる  歩く,20261107.mkv", os.listdir(self.dir))

    def test_title_without_date(self):
        source = self.write("rec.m2ts")
        run_one(self, source, LOG_OK, {source + ".mkv": b"v" * 100}, program=("番組X", ""))
        self.assertIn("番組X.mkv", os.listdir(self.dir))

    def test_existing_same_name_is_not_overwritten(self):
        source = self.write("rec.m2ts")
        self.write("番組X,20261107.mkv", b"old video")
        self.write("番組X,20261107.csv", b"old csv")
        _code, items, _cmd = run_one(self, source, LOG_OK, {source + ".mkv": b"new video", source + ".csv": b"new"})
        with open(os.path.join(self.dir, "番組X,20261107.mkv"), "rb") as f:
            self.assertEqual(f.read(), b"old video")                 # 前からあったものは、そのまま
        with open(os.path.join(self.dir, "番組X,20261107(2).mkv"), "rb") as f:
            self.assertEqual(f.read(), b"new video")
        self.assertIn("番組X,20261107(2).csv", os.listdir(self.dir))
        self.assertTrue(any("同名あり" in item[1] for item in items if item[0] == "log"))

    def test_numbered_pair_target(self):
        self.assertEqual(m.numbered_pair_target(self.dir, "a b,c", ".mkv"), ("a b,c", False))
        self.write("a b,c.mkv")
        self.assertEqual(m.numbered_pair_target(self.dir, "a b,c", ".mkv"), ("a b,c(2)", True))
        self.write("a b,c(2).csv")                                    # csv だけ先にある番号も、避ける
        self.assertEqual(m.numbered_pair_target(self.dir, "a b,c", ".mkv"), ("a b,c(3)", True))


class Scanning(Case):
    """スキャン(フォルダから録画を集める)と、変換済みの判定"""

    def test_awkward_names_are_collected(self):
        for name in AWKWARD_NAMES:
            self.write(name)
        self.write("sub dir/深い 階層, その2.m2ts")
        self.write("メモ.txt")
        flat = m.collect_target_files(self.dir, recursive=False, extensions=(".m2ts", ".ts"))
        self.assertEqual(sorted(os.path.basename(p) for p in flat), sorted(AWKWARD_NAMES))
        deep = m.collect_target_files(self.dir, recursive=True, extensions=(".m2ts", ".ts"))
        self.assertEqual(len(deep), len(AWKWARD_NAMES) + 1)

    def test_converted_is_found_by_title_with_awkward_characters(self):
        title = "旅, 食べる  歩く (再)"
        self.write("録画 その1.m2ts")
        self.write(m.sanitize_title_for_filename(title) + ",20261107.mkv", b"v" * 100)
        self.patch("get_sort_root", lambda: os.path.join(self.dir, "仕分け"))
        self.assertTrue(m.is_source_converted(self.dir, "録画 その1.m2ts", title, "20261107"))
        self.assertFalse(m.is_source_converted(self.dir, "録画 その1.m2ts", "別の番組", "20261107"))
        self.assertFalse(m.is_source_converted(self.dir, "録画 その1.m2ts", title, "20261114"))   # 別の日の回


if __name__ == "__main__":
    unittest.main()
