"""GPU(CUDA)でのデコードに失敗したときの、やりなおしの順番

  ふつうに CUDA → (作業用の領域が足りない失敗なら)スレッドを1にして CUDA → 分割(TsSplitter) → CPU でデコード
実機の GPU は使わない。ffmpeg が出すログの文面と、やりなおしの判断だけを確かめる。
"""
import os
import unittest

from support import m, Case, bare_app, drain, logs_of
from encode_helpers import run_one, LOG_OK, LOG_FAIL, LOG_CUDA_FAIL, LOG_CUDA_SURFACES

PRESET = m.PRESET_PREFIX + "テスト設定"


class Worker(Case):
    """キューの処理(_encode_worker)。1本の結果を順番に決めておき、何回・どの状態で呼ばれたかを見る"""

    def make(self, outcomes, bat_path=PRESET, split="0", name="rec.m2ts"):
        """outcomes: 呼ばれるたびの結果 [(診断, CUDAの失敗か, 領域が足りない失敗か), ...]"""
        app = bare_app()
        app.settings = {"tssplitter_split": split}
        path = self.write(name)
        app.row_data = {"R": {"path": path, "bat_path": bat_path, "bat_name": "x"}}
        self.calls = []
        pending = list(outcomes)

        def fake_run(m2ts_path, bat, iid):
            row = app.row_data[iid]
            self.calls.append((os.path.basename(m2ts_path), bool(row.get("cuda_low_threads")), bool(row.get("cpu_decode"))))
            label, cuda, surfaces = pending.pop(0)
            app._last_diag_label, app._last_cuda_failure, app._last_cuda_surfaces = label, cuda, surfaces
            return 0
        app._run_bat = fake_run
        return app

    def finish(self, app, iids=("R",)):
        app._encode_worker(list(iids))
        items = drain(app.encode_queue)
        self.assertEqual(items[-1], ("all_done",))
        final = [item[2] for item in items if item[0] == "status"][-1]
        return items, logs_of(items), final

    def test_success_runs_once(self):
        app = self.make([("OK", False, False)])
        _items, logs, final = self.finish(app)
        self.assertEqual(self.calls, [("rec.m2ts", False, False)])
        self.assertEqual(final, "完了")
        self.assertFalse(any("やりなおし" in line for line in logs))

    def test_surfaces_failure_retries_with_one_thread(self):
        app = self.make([("失敗", True, True), ("OK", False, False)])
        _items, logs, final = self.finish(app)
        self.assertEqual(self.calls, [("rec.m2ts", False, False), ("rec.m2ts", True, False)])
        self.assertEqual(final, "完了")
        self.assertTrue(any("スレッド数を減らしてやりなおします" in line for line in logs))

    def test_one_thread_also_fails_then_cpu(self):
        app = self.make([("失敗", True, True), ("失敗", True, True), ("OK", False, False)])
        _items, logs, final = self.finish(app)
        self.assertEqual(self.calls, [("rec.m2ts", False, False), ("rec.m2ts", True, False), ("rec.m2ts", True, True)])
        self.assertEqual(final, "完了")
        self.assertTrue(any("CPUでデコードしてやりなおします" in line for line in logs))

    def test_other_cuda_failure_goes_straight_to_cpu(self):
        app = self.make([("失敗", True, False), ("OK", False, False)])
        self.finish(app)
        self.assertEqual(self.calls, [("rec.m2ts", False, False), ("rec.m2ts", False, True)])

    def test_everything_fails_stops_after_three_tries(self):
        app = self.make([("失敗", True, True)] * 5)
        _items, logs, _final = self.finish(app)
        self.assertEqual(len(self.calls), 3)                          # 同じファイルを、いつまでもやりなおさない
        self.assertTrue(any("CPUでのデコードでも変換できませんでした" in line for line in logs))

    def test_failure_without_cuda_error_is_not_retried(self):
        app = self.make([("失敗", False, False)] * 3)
        _items, logs, _final = self.finish(app)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(any("やりなおし" in line for line in logs))

    def test_custom_batch_is_never_rewritten_or_retried(self):
        app = self.make([("失敗", True, True)] * 3, bat_path=os.path.join(self.dir, "自作.bat"))
        _items, logs, _final = self.finish(app)
        self.assertEqual(self.calls, [("rec.m2ts", False, False)])
        self.assertTrue(any("常にCUDAデコードで変換" in line for line in logs))   # 設定で止められることを知らせる

    def test_stop_request_prevents_retry(self):
        app = self.make([("失敗", True, True)] * 3)
        run = app._run_bat

        def run_then_stop(path, bat, iid):
            code = run(path, bat, iid)
            app.stop_requested = True
            return code
        app._run_bat = run_then_stop
        app._encode_worker(["R"])
        self.assertEqual(len(self.calls), 1)

    def test_split_is_tried_before_cpu(self):
        """失敗したら、先に分割(TsSplitter)を試す。分割でできた2本を、順にエンコードする"""
        app = self.make([("失敗", True, False), ("OK", False, False), ("OK", False, False)], split="1")
        self.patch("detect_ts_service_change", lambda path: (False, ""))
        self.patch("detect_head_timestamp_reset", lambda path: (False, ""))
        app._ensure_tssplitter = lambda: "TsSplitter"

        def fake_split(iid, tool):
            new = []
            for suffix in ("_HD", "_SD1"):
                piece = self.write("rec" + suffix + ".m2ts")
                app.row_data["P" + suffix] = {"path": piece, "bat_path": PRESET, "bat_name": "x", "split_from": "R"}
                new.append("P" + suffix)
            return new
        app._split_row = fake_split
        self.finish(app)
        self.assertEqual([c[0] for c in self.calls], ["rec.m2ts", "rec_HD.m2ts", "rec_SD1.m2ts"])
        self.assertTrue(all(not c[2] for c in self.calls))            # 分割で通ったので、CPU には切りかえない

    def test_split_piece_that_fails_on_cuda_falls_back_to_cpu(self):
        """分割でできたファイルは、もう分割しない。CUDA が受け付けなければ、CPU でやりなおす"""
        app = self.make([("失敗", True, False), ("OK", False, False)], split="1", name="rec_HD.m2ts")
        app.row_data["R"]["split_from"] = "X"
        app._ensure_tssplitter = lambda: self.fail("分割でできたファイルを、もう一度分割しようとしました")
        self.finish(app)
        self.assertEqual(self.calls, [("rec_HD.m2ts", False, False), ("rec_HD.m2ts", False, True)])


class LogDetection(Case):
    """ffmpeg のログから、CUDA の失敗の種類を読み分ける"""

    def flags(self, lines):
        source = self.write("rec.m2ts")
        run_one(self, source, lines, returncode=1)
        return self.app._last_diag_label, self.app._last_cuda_failure, self.app._last_cuda_surfaces

    def test_success(self):
        source = self.write("rec.m2ts")
        run_one(self, source, LOG_OK, {source + ".mkv": b"v" * 100})
        self.assertEqual((self.app._last_diag_label, self.app._last_cuda_failure, self.app._last_cuda_surfaces),
                         ("OK", False, False))

    def test_plain_failure_is_not_a_cuda_failure(self):
        self.assertEqual(self.flags(LOG_FAIL), ("失敗", False, False))

    def test_cuda_failure(self):
        self.assertEqual(self.flags(LOG_CUDA_FAIL), ("失敗", True, False))

    def test_cuda_surfaces_failure(self):
        self.assertEqual(self.flags(LOG_CUDA_SURFACES), ("失敗", True, True))

    def test_thread_hint_without_cuda_error_is_ignored(self):
        lines = ["[h264] Try lowering the amount of threads. Using 16 right now."] + LOG_FAIL
        self.assertEqual(self.flags(lines), ("失敗", False, False))


class Commands(Case):
    """やりなおしのときに、ffmpeg のコマンドがどう変わるか"""

    def test_threads_one_is_added_only_for_the_retry(self):
        normal, _ = m.build_ffmpeg_command({"cuda": True})
        retry, _ = m.build_ffmpeg_command({"cuda": True, "cuda_low_threads": True})
        self.assertIn("-hwaccel cuda", normal)
        self.assertNotIn("-threads 1", normal)                         # いつも付けると、HD の変換が遅くなる
        self.assertIn("-hwaccel cuda -hwaccel_output_format cuda -threads 1 -i ", retry)

    def test_threads_one_is_not_added_without_cuda(self):
        command, _ = m.build_ffmpeg_command({"cuda": False, "cuda_low_threads": True})
        self.assertNotIn("-threads 1", command)
        self.assertNotIn("-hwaccel", command)

    def batch_for(self, row_flags, settings=None):
        """設定(プリセット)で1本実行したときに、実際に書き出されるバッチの中身"""
        app = bare_app()
        app.settings = dict({"encoder": "nvenc", "user_presets": {"テスト設定": {"cuda": True}}}, **(settings or {}))
        path = self.write("rec.m2ts")
        app.row_data = {"R": dict({"path": path}, **row_flags)}
        seen = {}

        def capture(m2ts_path, bat, bat_dir, name, iid):
            with open(bat, encoding="utf-8") as f:
                seen["body"] = f.read()
            seen["bat"] = bat
            return 0
        app._run_bat_process = capture
        self.assertEqual(app._run_bat_inner(path, PRESET, "R"), 0)
        self.assertFalse(os.path.exists(seen["bat"]))                  # 一時のバッチは、終わったら消す
        return seen["body"], logs_of(drain(app.encode_queue))

    def test_first_try_uses_cuda_as_set(self):
        body, _logs = self.batch_for({})
        self.assertIn("-hwaccel cuda", body)
        self.assertNotIn("-threads 1", body)

    def test_low_threads_retry(self):
        body, logs = self.batch_for({"cuda_low_threads": True})
        self.assertIn("-hwaccel cuda", body)
        self.assertIn("-threads 1", body)
        self.assertTrue(any("スレッド数を1にします" in line for line in logs))

    def test_cpu_retry_drops_cuda_even_when_forced(self):
        body, logs = self.batch_for({"cuda_low_threads": True, "cpu_decode": True}, {"force_cuda": "1"})
        self.assertNotIn("-hwaccel", body)
        self.assertNotIn("-threads 1", body)
        self.assertTrue(any("CPUでデコードします" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
