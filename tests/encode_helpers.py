"""エンコード1本ぶんの処理(_run_bat_process)を、ffmpeg を動かさずに試すための道具"""
import os
from unittest import mock

from support import m, bare_app, drain

# ffmpeg のログの見本(中身は短くしてある)
LOG_OK = [
    "Input #0, mpegts, from 'x':",
    "  Duration: 00:01:00.00, start: 0.1",
    "frame=1800 fps=100 q=30 Lsize=100kB time=00:01:00.00 bitrate=1kbits/s speed=30x",
]
LOG_FAIL = [
    "Error while filtering: Function not implemented",
    "frame=0 Lsize=0kB time=N/A",
    "Conversion failed!",
]
LOG_CUDA_FAIL = [
    "[h264_cuvid] cuvidCreateDecoder(cudec->cudl, &cudec->decoder, &cuinfo) failed -> CUDA_ERROR_INVALID_VALUE",
    "Failed setup for format cuda: hwaccel initialisation returned error.",
    "Conversion failed!",
]
LOG_CUDA_SURFACES = LOG_CUDA_FAIL[:1] + [
    "[h264] Using more than 32 (35) decode surfaces might cause nvdec to fail.",
    "[h264] Try lowering the amount of threads. Using 16 right now.",
] + LOG_CUDA_FAIL[1:]


class FakeProcess:
    """バッチ(cmd.exe)の代わり。作るファイルと、戻り値だけを決めておく"""
    def __init__(self, creates, returncode, record):
        self._creates, self.returncode, self._record = creates, returncode, record
        self.stdout = None

    def __call__(self, cmd_line, **kwargs):          # subprocess.Popen(...) として呼ばれる
        self._record.append((cmd_line, kwargs))
        for path, data in self._creates.items():
            with open(path, "wb") as f:
                f.write(data)
        return self

    def wait(self):
        pass


def run_one(case, source, lines, creates=None, returncode=0, row=None, stop=False, program=("番組X", "20261107")):
    """
    source(録画)を1本エンコードしたことにして、_run_bat_process を通す。
      lines    … ffmpeg が出したことにするログ
      creates  … バッチが作ったことにするファイル {パス: 中身}
      stop     … lines の最後の行が出たところで、「中断」を押したことにする
    戻り値: (戻り値, キューに積まれたもの, Popen に渡されたコマンドライン)
    """
    app = bare_app()
    app.plugin_host = type("Host", (), {"_output_name_fallbacks": []})()
    app.row_data = {"I": dict({"path": source, "program_name": program[0], "channel": "チャンネルX",
                               "broadcast_date": "2026/11/07"}, **(row or {}))}
    app._noise_inspect_and_record = lambda path, iid, out, label, issues: (label, issues)
    record = []
    case.patch("get_program_name_with_date", lambda rpls, path: program)

    def output(stream):
        for number, line in enumerate(lines, 1):
            if stop and number == len(lines):
                app.stop_requested = True
            yield line
    case.patch("iter_process_lines", output)
    case.patch("kill_process_tree", lambda proc: None)
    patcher = mock.patch.object(m.subprocess, "Popen", FakeProcess(creates or {}, returncode, record))
    patcher.start()
    case.addCleanup(patcher.stop)
    case.app = app                                   # 終わったあとの状態を、テストから見られるように
    code = app._run_bat_process(source, os.path.join(case.dir, "x.bat"), case.dir, "x", "I")
    return code, drain(app.encode_queue), (record[0][0] if record else "")
