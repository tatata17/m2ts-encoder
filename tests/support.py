"""テストの共通の土台。本体(m2ts_encoder.pyw)を、画面を出さずに読みこむ。

・tkinter は、にせもの(何もしない部品)に差しかえる。ウインドウは1つも開かない。
・設定の置き場所(%LOCALAPPDATA% / ホーム)と、アプリのフォルダ(ログの置き場所)は、
  テスト専用の一時フォルダに向ける。実際の設定・ログ・録画・出力には、さわらない。
・テストが作るファイルは、すべて一時フォルダの中。終わったら、フォルダごと消す。
"""
import atexit
import importlib.machinery
import importlib.util
import os
import queue
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "m2ts_encoder.pyw"

# ---- 1. 設定などの置き場所を、一時フォルダに向ける(本体を読みこむ前に行う)
SANDBOX = tempfile.mkdtemp(prefix="m2ts_encoder_test_")
atexit.register(shutil.rmtree, SANDBOX, ignore_errors=True)
_HOME = os.path.join(SANDBOX, "home")
_APP_DIR = os.path.join(SANDBOX, "app")          # 「アプリと同じフォルダ」の代わり
for _d in (_HOME, _APP_DIR):
    os.makedirs(_d)
for _name in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA"):
    os.environ[_name] = _HOME
tempfile.tempdir = SANDBOX                      # 本体が作る一時ファイルも、この中に

# ---- 2. tkinter をにせものに差しかえて、本体を読みこむ
for _name in ("tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog",
              "tkinter.simpledialog", "tkinter.scrolledtext", "tkinter.font"):
    sys.modules[_name] = mock.MagicMock()


class _Widget:
    """tk.Tk / tk.Toplevel の代わり(継承できるだけの、空の部品)"""
    def __init__(self, *args, **kwargs):
        pass


sys.modules["tkinter"].Tk = _Widget
sys.modules["tkinter"].Toplevel = _Widget
sys.dont_write_bytecode = True                   # リポジトリに __pycache__ を作らない
_loader = importlib.machinery.SourceFileLoader("m2ts_encoder_under_test", str(APP_PATH))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
m = importlib.util.module_from_spec(_spec)       # ← 本体。テストは support.m.関数名 で呼ぶ
_loader.exec_module(m)

m.get_script_dir = lambda: _APP_DIR              # ログなどが、リポジトリの中に作られないように
m.__file__ = os.path.join(_APP_DIR, "m2ts_encoder.pyw")   # 本体が「自分のファイル」を書きかえる処理(更新)も、一時フォルダの中に向ける

# ---- 3. 安全の確認: 置き場所が一時フォルダの中でなければ、テストを1つも走らせない
_real = os.path.realpath
if not _real(m.get_app_data_dir()).startswith(_real(SANDBOX) + os.sep):
    raise RuntimeError("テストの安全確認に失敗: 設定の置き場所が一時フォルダの外です: " + m.get_app_data_dir())


class Case(unittest.TestCase):
    """一時フォルダ(self.dir)つきのテスト。本体の関数を差しかえたら、終わったときに元へ戻す"""
    maxDiff = None

    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=SANDBOX)

    def patch(self, name, value):
        """本体の関数や定数を、このテストの間だけ差しかえる"""
        patcher = mock.patch.object(m, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, relative, data=b"x"):
        """self.dir の中にファイルを作って、そのパスを返す"""
        path = os.path.join(self.dir, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def tree(self, base=None):
        """フォルダの中身(相対パスの一覧。/ 区切り)"""
        base = base or self.dir
        found = []
        for folder, _dirs, files in os.walk(base):
            for name in files:
                found.append(os.path.relpath(os.path.join(folder, name), base).replace(os.sep, "/"))
        return sorted(found)


def bare_app():
    """画面を作らずに、App の中の処理だけを呼べるようにしたもの(__init__ は通さない)"""
    app = object.__new__(m.App)
    app.encode_queue = queue.Queue()
    app.encode_queue.write_file = lambda line: None   # ログファイルには書かない
    app.stop_requested = False
    app.settings = {}
    app.diagnostic_report = []
    app.results = []
    app.row_data = {}
    app.rplsinfo_path = "rplsinfo"
    return app


def drain(q):
    """キューにたまったものを、全部取り出す"""
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


def logs_of(items):
    return [item[1] for item in items if item and item[0] == "log"]
