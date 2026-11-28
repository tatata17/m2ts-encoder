"""仕分け(チャンネル別 → 作品ごと)。番組名・放送局名は、すべて架空のもの"""
import os
import queue
import unittest

from support import m, Case, bare_app, drain


def item(path, program, channel="チャンネルX", cur_series=""):
    return {"path": path, "channel": channel, "cur_series": cur_series, "program": program}


class ChannelSort(Case):
    """チャンネル別の仕分け"""

    def test_channel_folder_name(self):
        self.assertEqual(m.channel_folder_name("チャンネルX"), "チャンネルX")
        self.assertEqual(m.channel_folder_name(" A:B. "), "A：B")          # 禁止文字は全角に、末尾の . と空白は取る
        self.assertIsNone(m.channel_folder_name("(不明)"))
        self.assertIsNone(m.channel_folder_name(""))
        self.assertIsNone(m.channel_folder_name(None))

    def test_channel_from_tab_csv_utf16(self):
        path = self.write("a.csv", "00001.m2ts\t番組A #1\t2026/10/01\t19:00:00\tチャンネルX\t内容\r\n".encode("utf-16"))
        self.assertEqual(m.read_channel_from_sidecar_csv(path, []), "チャンネルX")
        self.assertEqual(m.read_program_info_from_sidecar_csv(path), ("番組A #1", "2026/10/01"))
        self.assertEqual(m.read_start_time_from_sidecar_csv(path), "19:00")

    def test_channel_from_comma_csv(self):
        path = self.write("a.csv", "00001.m2ts,番組A,チャンネルY,20261001\n")
        self.assertEqual(m.read_channel_from_sidecar_csv(path, []), "チャンネルY")
        self.assertEqual(m.read_program_info_from_sidecar_csv(path), ("番組A", "2026/10/01"))

    def test_channel_from_unknown_layout_uses_known_names(self):
        path = self.write("a.csv", "なにか,ﾁｬﾝﾈﾙX,べつの項目\n")              # 半角カナでも、同じ局とみなす
        self.assertEqual(m.read_channel_from_sidecar_csv(path, ["チャンネルX"]), "チャンネルX")
        self.assertIsNone(m.read_channel_from_sidecar_csv(path, ["チャンネルZ"]))

    def test_channel_missing_or_broken_csv(self):
        self.assertIsNone(m.read_channel_from_sidecar_csv(os.path.join(self.dir, "無い.csv"), ["チャンネルX"]))
        self.assertIsNone(m.read_channel_from_sidecar_csv(self.write("空.csv", b""), ["チャンネルX"]))

    def test_move_keeps_video_and_csv_together(self):
        """動画とcsvを一緒に動かす。移動先に同じ名前があれば、上書きせずに (2) を付ける"""
        app = bare_app()
        app._sort_queue = queue.Queue()
        dest = os.path.join(self.dir, "仕分け", "チャンネルX")
        first = self.write("in/番組A,20261001.mkv", b"one")
        self.write("in/番組A,20261001.csv", b"one csv")
        self.write("仕分け/チャンネルX/番組B,20261002.mkv", b"already")     # 移動先に、前からあるもの
        second = self.write("in/番組B,20261002.mkv", b"two")
        self.write("in/番組B,20261002.csv", b"two csv")
        app._sort_worker([("I1", first, dest, "チャンネルX"), ("I2", second, dest, "チャンネルX")])
        events = drain(app._sort_queue)
        self.assertEqual(events[-1], ("done", 2, 1, []))
        self.assertEqual(self.tree(), [
            "仕分け/チャンネルX/番組A,20261001.csv", "仕分け/チャンネルX/番組A,20261001.mkv",
            "仕分け/チャンネルX/番組B,20261002(2).csv", "仕分け/チャンネルX/番組B,20261002(2).mkv",
            "仕分け/チャンネルX/番組B,20261002.mkv",
        ])
        with open(os.path.join(dest, "番組B,20261002.mkv"), "rb") as f:
            self.assertEqual(f.read(), b"already")

    def test_move_error_is_reported_and_others_continue(self):
        app = bare_app()
        app._sort_queue = queue.Queue()
        dest = os.path.join(self.dir, "out")
        ok = self.write("in/番組A,20261001.mkv")
        app._sort_worker([("I0", os.path.join(self.dir, "in", "無い.mkv"), dest, "c"), ("I1", ok, dest, "c")])
        done = drain(app._sort_queue)[-1]
        self.assertEqual(done[:3], ("done", 1, 0))
        self.assertEqual(len(done[3]), 1)
        self.assertIn("無い.mkv", done[3][0])


class SeriesNames(Case):
    """作品名の決め方"""

    def test_episode_numbers_and_tags_are_removed(self):
        self.assertEqual(m.clean_program_title("うさぎの旅 #24[字]"), "うさぎの旅")
        self.assertEqual(m.clean_program_title("[新]うさぎの旅 第3話"), "うさぎの旅")

    def test_genre_word_is_skipped(self):
        self.assertEqual(m.suggest_series_name("アニメ うさぎの旅「はじまりの段」"), "うさぎの旅")
        self.assertEqual(m.suggest_series_name("アニメ　うさぎの旅 #3"), "うさぎの旅")
        self.assertEqual(m.suggest_series_name("アニメ"), "アニメ")           # それしか無ければ、残す

    def test_subtitle_in_brackets_is_separated_without_space(self):
        self.assertEqual(m._title_words("うさぎの旅「はじまりの段」"), ["うさぎの旅", "はじまりの段"])
        self.assertEqual(m._title_words("うさぎの旅『おわりの段』 #2"), ["うさぎの旅", "おわりの段"])

    def test_triangle_marks_separate_title_and_content(self):
        self.assertEqual(m.suggest_series_name("ねこ日和▼春のひなたぼっこ"), "ねこ日和")
        self.assertEqual(m.suggest_series_name("ねこ日和▽夏の夕すずみ"), "ねこ日和")

    def test_bulk_uses_the_longest_shared_words(self):
        programs = {f"p{i}": f"うさぎの旅 ふしぎ島 #{i}[二]" for i in range(1, 6)}
        self.assertEqual(set(m.suggest_series_names_bulk(programs).values()), {"うさぎの旅 ふしぎ島"})

    def test_bulk_does_not_split_on_subtitles(self):
        programs = {"a": "ねこ日和 春のひなた", "b": "ねこ日和 夏の夕すずみ", "c": "ねこ日和 秋の縁側"}
        self.assertEqual(set(m.suggest_series_names_bulk(programs).values()), {"ねこ日和"})

    def test_series_key_ignores_width_case_kana_and_spaces(self):
        self.assertEqual(m.series_key("ＡＢＣ　ウサギ ２"), m.series_key("abcうさぎ2"))
        self.assertNotEqual(m.series_key("うさぎの旅"), m.series_key("うさぎの旅人"))

    def test_folder_name_is_safe_for_windows(self):
        self.assertEqual(m.series_folder_name(" どっち? A/B. "), "どっち？ A／B")


class SeriesRules(Case):
    """手で決めた作品名の覚え"""

    def test_rule_key_when_name_is_at_the_start(self):
        self.assertEqual(m.series_rule_key("うさぎの旅 ふしぎ島 #3", "うさぎの旅"), m.series_key("うさぎの旅"))

    def test_rule_key_when_name_is_in_the_middle(self):
        key = m.series_rule_key("アニメ うさぎの旅「はじまりの段」", "うさぎの旅")
        self.assertEqual(key, m.series_key("アニメうさぎの旅"))
        # 次の回(サブタイトルが違う)にも、同じ規則が効く
        self.assertEqual(m.apply_series_rules("アニメ うさぎの旅「つづきの段」", {key: "うさぎの旅"}), "うさぎの旅")
        self.assertIsNone(m.apply_series_rules("アニメ ねこ日和「春」", {key: "うさぎの旅"}))

    def test_longest_rule_wins(self):
        rules = {m.series_key("うさぎ"): "短い", m.series_key("うさぎの旅"): "長い"}
        self.assertEqual(m.apply_series_rules("うさぎの旅 #1", rules), "長い")

    def test_words_selection(self):
        words = ["アニメ", "うさぎの旅", "はじまりの段"]
        self.assertEqual(m.series_words_selection(words, "うさぎの旅"), [False, True, False])
        self.assertEqual(m.series_words_selection(words, "どこにも無い"), [False, False, False])


class SeriesSuggestions(Case):
    """自動の提案(どのファイルを、どの作品フォルダへ動かすか)。None=動かさない"""

    def test_two_or_more_episodes_get_a_folder_single_one_stays(self):
        items = [item("a", "うさぎの旅 #1"), item("b", "うさぎの旅 #2"), item("c", "ねこ日和 #1")]
        self.assertEqual(m.suggest_series_destinations(items, {}), {"a": "うさぎの旅", "b": "うさぎの旅", "c": None})

    def test_same_title_on_another_channel_is_counted_separately(self):
        items = [item("a", "うさぎの旅 #1"), item("b", "うさぎの旅 #2", channel="チャンネルY")]
        self.assertEqual(m.suggest_series_destinations(items, {}), {"a": None, "b": None})

    def test_rule_applies_even_to_a_single_episode(self):
        rules = {m.series_key("ねこ日和"): "ねこ"}
        self.assertEqual(m.suggest_series_destinations([item("c", "ねこ日和 #1")], rules), {"c": "ねこ"})

    def test_already_sorted_files_are_never_moved(self):
        """仕分け済みのファイルは、提案の決め方が変わっても、別の名前のフォルダへ動かし直さない"""
        items = [
            item("a", "うさぎの旅２ 未来の昔ばなし #1", cur_series="うさぎの旅２"),
            item("b", "うさぎの旅２ 未来の昔ばなし #2", cur_series="うさぎの旅２"),
            item("c", "アニメ ねこ日和「春」", cur_series="アニメ ねこ日和"),
            item("d", "ＴＶシリーズ「くま物語」 #1", cur_series="ＴＶシリーズ「くま物語」"),
        ]
        result = m.suggest_series_destinations(items, {})
        self.assertEqual(result, {it["path"]: it["cur_series"] for it in items})

    def test_new_episode_joins_the_existing_folder(self):
        items = [
            item("old", "うさぎの旅２ 未来の昔ばなし #1", cur_series="うさぎの旅２"),
            item("new", "うさぎの旅２ 未来の昔ばなし #2"),
        ]
        self.assertEqual(m.suggest_series_destinations(items, {})["new"], "うさぎの旅２")

    def test_new_episode_joins_a_folder_named_with_the_genre_word(self):
        items = [item("old", "アニメ ねこ日和「春」", cur_series="アニメ ねこ日和"), item("new", "アニメ ねこ日和「夏」")]
        self.assertEqual(m.suggest_series_destinations(items, {})["new"], "アニメ ねこ日和")

    def test_new_episode_joins_a_folder_that_differs_only_in_brackets(self):
        items = [item("old", "ＴＶシリーズ「くま物語」 #1", cur_series="ＴＶシリーズ「くま物語」"),
                 item("new", "ＴＶシリーズ「くま物語」 #2")]
        self.assertEqual(m.suggest_series_destinations(items, {})["new"], "ＴＶシリーズ「くま物語」")

    def test_similar_prefix_is_not_the_same_series(self):
        """名前の先頭が似ているだけの別の作品を、すでにあるフォルダへ入れない"""
        items = [
            item("old", "うさぎの旅 #1", cur_series="うさぎの旅"),
            item("x1", "うさぎの旅人たち #1"), item("x2", "うさぎの旅人たち #2"),
        ]
        result = m.suggest_series_destinations(items, {})
        self.assertEqual((result["x1"], result["x2"]), ("うさぎの旅人たち", "うさぎの旅人たち"))

    def test_genre_only_folder_is_not_used(self):
        items = [item("old", "アニメ くま物語 #1", cur_series="アニメ"),
                 item("n1", "アニメ ねこ日和 #1"), item("n2", "アニメ ねこ日和 #2")]
        result = m.suggest_series_destinations(items, {})
        self.assertEqual((result["n1"], result["n2"]), ("ねこ日和", "ねこ日和"))


class SeriesMoves(Case):
    """作品フォルダへの移動と、元に戻す"""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.dir, "仕分け")

    def test_scan_lists_videos_under_channel_folders(self):
        self.write("仕分け/チャンネルX/うさぎの旅 #1,20261001.mkv")
        self.write("仕分け/チャンネルX/うさぎの旅 #1,20261001.csv",
                   "00001.m2ts\tうさぎの旅 ふしぎ島 #1\t2026/10/01\t19:00:00\tチャンネルX\t\r\n".encode("utf-16"))
        self.write("仕分け/チャンネルX/ねこ日和/ねこ日和 #2,20261002.mp4")
        self.write("仕分け/外にあるもの,20261003.mkv")                       # 放送局フォルダの外は、対象外
        found = {i["file"]: i for i in m.scan_series_items(self.root)}
        self.assertEqual(sorted(found), ["うさぎの旅 #1,20261001.mkv", "ねこ日和 #2,20261002.mp4"])
        first = found["うさぎの旅 #1,20261001.mkv"]
        self.assertEqual((first["channel"], first["cur_series"], first["program"]),
                         ("チャンネルX", "", "うさぎの旅 ふしぎ島 #1"))     # csv があれば、番組名は csv から
        second = found["ねこ日和 #2,20261002.mp4"]
        self.assertEqual((second["cur_series"], second["program"]), ("ねこ日和", "ねこ日和 #2"))

    def test_target_dir_reuses_folder_that_differs_only_in_width(self):
        os.makedirs(os.path.join(self.root, "チャンネルX", "うさぎの旅２"))
        self.assertEqual(m.resolve_series_target_dir(self.root, "チャンネルX", "うさぎの旅2"),
                         os.path.join(self.root, "チャンネルX", "うさぎの旅２"))
        self.assertEqual(m.resolve_series_target_dir(self.root, "チャンネルX", ""),
                         os.path.join(self.root, "チャンネルX"))

    def test_move_then_undo_restores_everything(self):
        video = self.write("仕分け/チャンネルX/うさぎの旅 #1,20261001.mkv", b"v")
        self.write("仕分け/チャンネルX/うさぎの旅 #1,20261001.csv", b"c")
        before = self.tree()
        dest = os.path.join(self.root, "チャンネルX", "うさぎの旅")
        moved, errors = m.execute_series_moves([(video, dest)])
        self.assertEqual(errors, [])
        self.assertEqual(self.tree(), ["仕分け/チャンネルX/うさぎの旅/うさぎの旅 #1,20261001.csv",
                                       "仕分け/チャンネルX/うさぎの旅/うさぎの旅 #1,20261001.mkv"])
        m.save_series_undo(moved)
        restored, errors = m.undo_series_moves(m.load_series_undo(), self.root)
        self.assertEqual((restored, errors), (1, []))
        self.assertEqual(self.tree(), before)
        self.assertFalse(os.path.exists(dest))                               # 空になった作品フォルダは消す
        self.assertTrue(os.path.isdir(os.path.join(self.root, "チャンネルX")))  # 放送局フォルダは消さない
        m.clear_series_undo()
        self.assertEqual(m.load_series_undo(), [])

    def test_move_never_overwrites(self):
        video = self.write("仕分け/チャンネルX/うさぎの旅 #1,20261001.mkv", b"new")
        self.write("仕分け/チャンネルX/うさぎの旅/うさぎの旅 #1,20261001.mkv", b"old")
        moved, errors = m.execute_series_moves([(video, os.path.join(self.root, "チャンネルX", "うさぎの旅"))])
        self.assertEqual(moved, [])
        self.assertEqual(len(errors), 1)
        self.assertTrue(os.path.isfile(video))
        with open(os.path.join(self.root, "チャンネルX", "うさぎの旅", "うさぎの旅 #1,20261001.mkv"), "rb") as f:
            self.assertEqual(f.read(), b"old")

    def test_undo_does_not_overwrite_a_file_that_came_back(self):
        video = self.write("仕分け/チャンネルX/うさぎの旅 #1,20261001.mkv", b"moved")
        moved, _ = m.execute_series_moves([(video, os.path.join(self.root, "チャンネルX", "うさぎの旅"))])
        self.write("仕分け/チャンネルX/うさぎの旅 #1,20261001.mkv", b"someone put this back")
        restored, errors = m.undo_series_moves(moved, self.root)
        self.assertEqual(restored, 0)
        self.assertEqual(len(errors), 1)
        with open(video, "rb") as f:
            self.assertEqual(f.read(), b"someone put this back")


if __name__ == "__main__":
    unittest.main()
