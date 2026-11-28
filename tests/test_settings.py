"""設定ファイル(JSON)の保存と、壊れたときの復旧。すべて一時フォルダの中の設定で試す"""
import json
import os
import unittest

from support import m, Case, SANDBOX


class SafeJson(Case):
    """write_json_safely / read_json_with_backup"""

    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.dir, "settings.json")

    def test_round_trip_keeps_japanese_and_nested_values(self):
        data = {"folder": "D:\\録画 フォルダ", "user_presets": {"自作": {"qp": 28, "cuda": True}}, "list": [1, "二"]}
        self.assertTrue(m.write_json_safely(self.path, data))
        self.assertEqual(m.read_json_with_backup(self.path, dict), data)
        self.assertFalse(os.path.exists(self.path + ".tmp"))            # 書きかけのファイルは残さない

    def test_previous_content_is_kept_as_backup(self):
        m.write_json_safely(self.path, {"v": 1})
        m.write_json_safely(self.path, {"v": 2})
        with open(self.path + ".bak", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1})

    def test_broken_file_is_recovered_from_backup(self):
        m.write_json_safely(self.path, {"v": 1})
        m.write_json_safely(self.path, {"v": 2})
        for broken in (b"", b'{"v": 2', b"\x00\x00\x00\x00", "ただの文字".encode("utf-8"), b"\xff\xfe\x00"):
            with self.subTest(broken=broken):
                with open(self.path, "wb") as f:
                    f.write(broken)
                self.assertEqual(m.read_json_with_backup(self.path, dict), {"v": 1})

    def test_missing_file_is_recovered_from_backup(self):
        m.write_json_safely(self.path, {"v": 1})
        m.write_json_safely(self.path, {"v": 2})
        os.remove(self.path)
        self.assertEqual(m.read_json_with_backup(self.path, dict), {"v": 1})

    def test_wrong_type_counts_as_broken(self):
        m.write_json_safely(self.path, {"v": 1})
        m.write_json_safely(self.path, {"v": 2})
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")                                          # 読めるが、設定の形(辞書)ではない
        self.assertEqual(m.read_json_with_backup(self.path, dict), {"v": 1})

    def test_nothing_readable_returns_none(self):
        self.assertIsNone(m.read_json_with_backup(self.path, dict))
        for name in (self.path, self.path + ".bak"):
            with open(name, "w", encoding="utf-8") as f:
                f.write("{broken")
        self.assertIsNone(m.read_json_with_backup(self.path, dict))

    def test_broken_file_does_not_replace_a_good_backup(self):
        """壊れた本体の上に保存しなおしても、読める .bak を、壊れた中身で上書きしない"""
        m.write_json_safely(self.path, {"v": 1})
        m.write_json_safely(self.path, {"v": 2})
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertTrue(m.write_json_safely(self.path, {"v": 3}))
        self.assertEqual(m.read_json_with_backup(self.path, dict), {"v": 3})
        with open(self.path + ".bak", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1})

    def test_unwritable_data_leaves_the_file_untouched(self):
        m.write_json_safely(self.path, {"v": 1})
        self.assertFalse(m.write_json_safely(self.path, {"v": object()}))   # JSON にできない値
        self.assertEqual(m.read_json_with_backup(self.path, dict), {"v": 1})
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_unwritable_folder_returns_false(self):
        self.assertFalse(m.write_json_safely(os.path.join(self.dir, "無いフォルダ", "s.json"), {"v": 1}))


class AppSettings(Case):
    """アプリの設定・バッチの登録(置き場所は、テスト専用の一時フォルダ)"""

    def setUp(self):
        super().setUp()
        self.settings_path = m.get_settings_path()
        self.config_path = m.get_config_path()
        self.assertTrue(os.path.realpath(self.settings_path).startswith(os.path.realpath(SANDBOX)))
        self.addCleanup(self.remove_all)
        self.remove_all()

    def remove_all(self):
        for base in (self.settings_path, self.config_path):
            for name in (base, base + ".bak", base + ".tmp"):
                if os.path.exists(name):
                    os.remove(name)

    def test_no_settings_file_means_empty_settings(self):
        self.assertEqual(m.load_settings(), {})
        self.assertEqual(m.load_bat_scripts(), [])

    def test_settings_survive_a_broken_file(self):
        m.save_settings({"target_folder": "D:\\録画", "encoder": "auto"})
        m.save_settings({"target_folder": "E:\\べつの場所", "encoder": "auto"})
        with open(self.settings_path, "wb") as f:
            f.write(b'{"target_folder": "E:\\\\')                         # 書いている途中で切れた形
        self.assertEqual(m.load_settings(), {"target_folder": "D:\\録画", "encoder": "auto"})

    def test_settings_broken_with_no_backup_start_empty(self):
        with open(self.settings_path, "wb") as f:
            f.write(b"\x00" * 64)
        self.assertEqual(m.load_settings(), {})                           # 起動できなくなるより、初期値で始める

    def test_batch_list_skips_malformed_entries(self):
        m.save_bat_scripts([{"name": "自作", "path": "C:\\bat\\自作.bat"}, {"name": "pathが無い"}, "文字列", 3])
        self.assertEqual(m.load_bat_scripts(), [{"name": "自作", "path": "C:\\bat\\自作.bat"}])

    def test_batch_list_recovers_from_backup(self):
        m.save_bat_scripts([{"name": "自作", "path": "a.bat"}])
        m.save_bat_scripts([{"name": "自作", "path": "a.bat"}, {"name": "もう1つ", "path": "b.bat"}])
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write('{"これは": "一覧ではない"}')
        self.assertEqual(m.load_bat_scripts(), [{"name": "自作", "path": "a.bat"}])

    def test_embedded_defaults_are_added_without_touching_user_entries(self):
        mine = {"name": "自作", "path": "C:\\bat\\自作.bat"}
        gone = {"name": "昔の埋め込み", "path": m.EMBEDDED_BAT_PREFIX + "もう無い.bat"}
        result = m.register_embedded_defaults([mine, gone])
        self.assertIn(mine, result)
        self.assertNotIn(gone, result)                                    # 無くなった埋め込みバッチの登録は外す
        names = [entry["name"] for entry in result]
        for filename in m.DEFAULT_BAT_SCRIPTS:
            self.assertIn(os.path.splitext(filename)[0], names)
        self.assertEqual(m.register_embedded_defaults(result), result)    # 2回やっても増えない


class OldNameMigration(Case):
    """旧名(m2ts_info_viewer)の設定フォルダからの引きつぎ"""

    def test_old_files_are_copied_but_never_overwrite(self):
        old_dir = os.path.join(self.dir, "m2ts_info_viewer")
        new_dir = os.path.join(self.dir, "m2ts_encoder")
        os.makedirs(old_dir)
        os.makedirs(new_dir)
        for name, text in (("m2ts_info_viewer_settings.json", "old settings"), ("m2ts_info_viewer_bats.json", "old bats")):
            with open(os.path.join(old_dir, name), "w", encoding="utf-8") as f:
                f.write(text)
        with open(os.path.join(new_dir, "m2ts_encoder_bats.json"), "w", encoding="utf-8") as f:
            f.write("new bats")
        self.patch("_migration_done", False)
        m._migrate_old_app_data(self.dir, new_dir)
        with open(os.path.join(new_dir, "m2ts_encoder_settings.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "old settings")                    # 無かったものは、名前を直してコピー
        with open(os.path.join(new_dir, "m2ts_encoder_bats.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "new bats")                        # 新しい側にあるものは、上書きしない
        self.assertEqual(sorted(os.listdir(old_dir)), ["m2ts_info_viewer_bats.json", "m2ts_info_viewer_settings.json"])


if __name__ == "__main__":
    unittest.main()
