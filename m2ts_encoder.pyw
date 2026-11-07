# -*- coding: utf-8 -*-
"""
m2ts_encoder.pyw

このファイルを置いたフォルダ内の .m2ts / .rpls ファイルを自動認識し、
rplsinfo.exe で「元ファイル名」「録画番組名」を取得して一覧表示するGUIツール。
さらに、登録した .bat エンコードスクリプトを各ファイルに割り当てて、
リストの上から順に自動でエンコードを実行する機能も備えています。

■ 使い方
    1. rplsinfo.exe をこのファイルと同じフォルダに置く
       (または PATH が通ったフォルダに置く)
    2. 対象の .m2ts / .rpls ファイルが入ったフォルダにこのファイルをコピーする
    3. このファイルをダブルクリックする
       -> コマンドプロンプトを開かず、ウィンドウが直接開いて自動スキャンが始まります
       -> このファイルに埋め込まれた既定のエンコード用バッチ(6種類)が自動的に
          使える状態になります。実行時にだけ一時ファイルとして展開してすぐ削除する
          方式のため、作業フォルダにもAppDataにもバッチファイル自体は生成されません
          (配布・コピーが必要なファイルはこの .pyw 1つだけです)
    4. ① 対象を選ぶ: 行をCtrl/Shift+クリックで選ぶ(チャンネルでまとめて選ぶことも可能)
    5. ② 設定を決める: 「適用する設定」を選んで「選択した行に適用」
       - 「おまかせ」はファイルごとに字幕・音声・インターレース等を自動判定します
       - 「設定の編集...」(またはメニューの「設定」)で、チェックボックスで設定を作ったり、
         独自の .bat を追加/削除/編集できます
    6. ③ 実行: 「エンコード開始」でリストの上から順に1ファイルずつ自動処理されます
    たまに使う機能(CSV保存・チャンネル別仕分け・ファイル名の記号修正・変換済みm2tsの削除・
    ログ関連)は、上部のメニューバーにあります。

■ 拡張子について
    ファイル名を「m2ts_encoder.pyw」のまま保存してください。
    .pyw 拡張子は Windows 上で pythonw.exe に関連付けられるため、
    ダブルクリックしてもコンソール画面が表示されません。

■ 設定の保存場所について
    登録バッチの一覧(m2ts_encoder_bats.json)や再生ソフトのパスなどの設定は
    %LOCALAPPDATA%\\m2ts_encoder\\ に小さなテキスト(json)として保存されます。
    同梱の既定バッチ自体はここにも作業フォルダにもファイルとして保存されません
    (実行時にだけ一時的に展開されます)。
    「設定の編集...」→「バッチファイル」タブで既定バッチを編集したい場合は、保存先を選んで
    エクスポートしてから編集する形になります(その時点で初めて実ファイルが
    作られ、以後そのファイルが使われます)。

■ バッチファイルの実行について
    - 独自に追加した .bat は「そのバッチファイルが置かれているフォルダ」を
      作業フォルダとして、対象ファイルのフルパスを引数(%1)に実行します。
      (エクスプローラーでドラッグ&ドロップした場合と同じ挙動です)
      同梱の既定バッチは、このpywと同じフォルダを作業フォルダとして実行されます。
    - .bat 内の `pause` は自動的にスキップされ、次のファイルの処理へ進みます。
      すべてのファイルの処理が終わった時点でウィンドウ側が完了通知を表示します。
    - 出力先に同名ファイルが既に存在する場合、ffmpeg が対話的な上書き確認を
      要求すると自動化できずそのまま失敗することがあります。自動運用したい場合は
      .bat 側の ffmpeg コマンドに `-y` (常に上書き) を追加することをおすすめします。

■ 右クリックメニューについて
    一覧の各行を右クリックすると、以下の操作ができます。
    - 元のファイルの場所を開く: エクスプローラーでそのファイルを選択した状態で開く
    - エンコード後のファイルを再生 / 場所を開く: 変換済みのmkv/mp4(仕分け済みのものも含む)
    - 元のファイルを再生: 再生ソフトで開く(メニュー「設定」→「再生ソフトを選ぶ」で選べます。未指定ならVLC、
      それも無ければWindowsの既定のアプリで開きます)
    - rplsから番組情報を再取得(BDAV用): BDAV形式(.../<番号>/STREAM/xxxxx.m2ts と
      .../<番号>/PLAYLIST/xxxxx.rpls という構成)で、m2ts単体からはタイトルが
      取得できない場合に、対応するrplsファイルから番組情報を読み直します。
      Ctrl+クリックやShift+クリックで複数選択してから右クリックすれば、
      選択した全行にまとめて適用できます。
      この操作をした行は、エンコード時のCSV取得・ファイルリネームも
      (同梱の既定バッチであれば)rplsファイルの方を情報源として使うようになります。
"""

import sys
import os

# ---- コンソール非表示処理 (.py のまま python.exe で起動された場合の保険) ----
if sys.platform == "win32":
    try:
        import ctypes
        _console_wnd = ctypes.windll.kernel32.GetConsoleWindow()
        if _console_wnd:
            ctypes.windll.user32.ShowWindow(_console_wnd, 0)  # SW_HIDE
    except Exception:
        pass

import csv
import datetime
import io
import json
import queue
import re
import shutil
import base64
import hashlib
import subprocess
import tempfile
import zlib
import time
import unicodedata
import urllib.request
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, scrolledtext
from typing import Dict, Iterator, List, Optional, Tuple


def get_script_dir() -> str:
    """このスクリプト自身が置かれているフォルダを返す"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_rplsinfo() -> Optional[str]:
    """rplsinfo.exe のパスを探す(スクリプトと同じフォルダ優先、次に PATH)"""
    same_dir = os.path.join(get_script_dir(), "rplsinfo.exe")
    if os.path.isfile(same_dir):
        return same_dir

    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path_dir, "rplsinfo.exe")
        if os.path.isfile(candidate):
            return candidate

    return None


def reveal_in_explorer(path: str) -> None:
    """
    エクスプローラーで、ファイルを選択した状態でフォルダを開く(Windows)。
    「explorer /select, パス」は、パスにカンマ(番組名,日付.mkv のような名前)があると途中で切れて、
    PCやドキュメントの画面が開いてしまう。そのため、シェルのAPIで、パスをそのまま渡して開く。
    APIが使えないときは、パス全体を引用符で囲んで explorer に渡す。
    """
    path = os.path.normpath(path)
    try:
        import ctypes
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        ole32.CoInitialize(None)
        shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
        shell32.ILCreateFromPathW.restype = ctypes.c_void_p
        shell32.ILFree.argtypes = [ctypes.c_void_p]
        shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_ulong]
        pidl = shell32.ILCreateFromPathW(path)
        if pidl:
            try:
                if shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0) == 0:
                    return
            finally:
                shell32.ILFree(pidl)
    except Exception:
        pass
    subprocess.Popen('explorer /select,"%s"' % path)


def find_tssplitter() -> Optional[str]:
    """TsSplitter.exe のパスを探す(スクリプトと同じフォルダ優先、次に PATH)。なければ None"""
    same_dir = os.path.join(get_script_dir(), "TsSplitter.exe")
    if os.path.isfile(same_dir):
        return same_dir
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path_dir, "TsSplitter.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def extract_embedded_tssplitter() -> Tuple[Optional[str], str]:
    """
    このファイルに埋め込んである TsSplitter.exe(Ver 1.26。再配布自由)を、スクリプトと同じフォルダに取り出す。
    戻り値: (取り出したパス, エラーの説明。成功なら空文字)
    """
    dest = os.path.join(get_script_dir(), "TsSplitter.exe")
    try:
        data = zlib.decompress(base64.b64decode("".join(_TSSPLITTER_B64)))
        if hashlib.sha256(data).hexdigest() != _TSSPLITTER_SHA256:
            return None, "埋め込みデータが壊れています"
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        return dest, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


TARGET_EXTENSIONS = (".m2ts", ".rpls")
CONVERTED_EXTENSIONS = (".mkv", ".mp4")
CONFIG_FILENAME = "m2ts_encoder_bats.json"


def collect_target_files(
    folder: str, recursive: bool = False, extensions: Tuple[str, ...] = TARGET_EXTENSIONS
) -> List[str]:
    """
    対象フォルダの .m2ts / .rpls ファイル一覧を取得する。
    recursive=True の場合、folder 以下のサブフォルダ(フォルダ内フォルダも含む)を
    再帰的に検索する。os.walk は指定した folder のツリー内しか辿らないため、
    兄弟フォルダ(例: folder の隣にある別フォルダ)が検索されることはない。
    extensions で検索対象の拡張子を絞り込める(例: (".m2ts",) にすればm2tsのみ)。
    """
    targets = []
    if not extensions:
        return targets
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(extensions):
                    targets.append(os.path.join(root, name))
    else:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and name.lower().endswith(extensions):
                targets.append(path)
    return sorted(targets)


# チャンネル別の仕分け先(スクリプトと同じフォルダの「仕分け」の中に、チャンネル名のフォルダを作る)
SORT_ROOT_NAME = "仕分け"


_TARGET_FOLDER: Optional[str] = None   # 対象フォルダ(指定がなければ、このスクリプトのフォルダ)


def get_target_folder() -> str:
    return _TARGET_FOLDER or get_script_dir()


def set_target_folder(path: Optional[str]) -> None:
    global _TARGET_FOLDER
    _TARGET_FOLDER = os.path.abspath(path) if path else None


def get_sort_root() -> str:
    """仕分けフォルダ。対象フォルダの下の「仕分け」"""
    return os.path.join(get_target_folder(), SORT_ROOT_NAME)


def list_sorted_dirs() -> List[str]:
    """仕分けフォルダ本体と、その下にあるすべてのフォルダ(チャンネル別・作品別)の一覧(存在するものだけ)"""
    root = get_sort_root()
    if not os.path.isdir(root):
        return []
    dirs = [root]
    try:
        for current, subdirs, _files in os.walk(root):
            subdirs.sort()
            for name in subdirs:
                dirs.append(os.path.join(current, name))
    except OSError:
        pass
    return dirs


def list_channel_dirs() -> List[str]:
    """仕分けフォルダの直下にあるチャンネル別フォルダの一覧"""
    root = get_sort_root()
    result: List[str] = []
    try:
        for name in sorted(os.listdir(root)):
            sub = os.path.join(root, name)
            if os.path.isdir(sub):
                result.append(sub)
    except OSError:
        pass
    return result


def list_converted_names(folder: str, include_sorted: bool = True) -> List[str]:
    """
    フォルダ直下の .mkv / .mp4 ファイル名(拡張子付き)の一覧を返す。
    include_sorted=True なら、仕分け済みのファイル(仕分けフォルダ内)も含める
    (仕分けで移動したあとも「変換済み」と判定できるようにするため)。
    """
    names = []
    folders = [folder] + (list_sorted_dirs() if include_sorted else [])
    for current in folders:
        try:
            entries = os.listdir(current)
        except Exception:
            continue
        for name in entries:
            if name.lower().endswith(CONVERTED_EXTENSIONS) and os.path.isfile(os.path.join(current, name)):
                names.append(name)
    return names


def is_other_date_file(base: str, date_digits: str, source_base_name: Optional[str] = None) -> bool:
    """
    変換済みファイル(拡張子抜きのbase)の末尾に付いている日付が、対象ファイルの
    録画日付(date_digits)と異なる場合にTrueを返す。
    同名番組(例: 同じタイトルの別日放送)を、別の回の変換済みファイルと
    取り違えないために使う。日付が不明な場合や、元ファイル名そのものと一致する
    場合はFalse(=除外しない)。
    """
    if not date_digits:
        return False
    m = _DATE_SUFFIX_PATTERN.search(base)
    if not m or m.group(1) == date_digits:
        return False
    if source_base_name and normalize_name(base) == normalize_name(os.path.splitext(source_base_name)[0]):
        return False
    return True


def collect_converted_basenames(
    folder: str,
    date_digits: str = "",
    source_base_name: Optional[str] = None,
    names: Optional[List[str]] = None,
) -> List[str]:
    """
    フォルダ直下にある .mkv / .mp4 ファイルの「拡張子抜きファイル名」一覧を
    正規化して返す。エンコード後のファイルは
        「番組名.mkv」
        「番組名,20250804.mkv」(末尾に録画日付が付くパターン)
        「[HV]番組名 #1 [二].mkv」(手動でタグや記号を付け足したパターン)
    のように表記ゆれが色々あるため、各ファイルについて
        - ファイル名そのもの
        - 末尾の日付部分を取り除いたもの
    の両方を正規化してリストに登録しておく。実際の一致判定は
    names_match() で完全一致・部分一致の両方を見る。
    """
    keys = []
    for name in (names if names is not None else list_converted_names(folder)):
        base, _ext = os.path.splitext(name)
        if is_other_date_file(base, date_digits, source_base_name):
            continue
        keys.append(normalize_name(base))
        stripped = normalize_name(strip_trailing_date(base))
        if stripped not in keys:
            keys.append(stripped)
    return keys


# 末尾の「区切り文字(全角/半角カンマ・アンダーバー・ハイフン・空白) + 8桁日付」を取り除く
# 末尾に「(…ノイズ…)」のタグ(ノイズ箇所の記載)が付いていても、日付として扱えるようにしておく
# (同名ファイルに自動で付ける連番「(2)」も同様に許容する)
_DATE_SUFFIX_PATTERN = re.compile(r"[,\uFF0C_\-\s]*(\d{8})(?:\([^()]*ノイズ[^()]*\)|\(\d+\))*$")


def strip_trailing_date(name: str) -> str:
    """末尾に付いている ',20250804' のような日付部分を取り除いた文字列を返す"""
    return _DATE_SUFFIX_PATTERN.sub("", name)


# 番組情報が取れなかった行に入れる仮の番組名(照合には使わない。「(吹)」などで始まる本物の番組名とは区別する)
NO_PROGRAM_INFO = "(番組情報を取得できませんでした)"


def normalize_name(name: str) -> str:
    """
    ファイル名比較用の正規化を行う。
    - Windowsで使用できない記号(と、その代替として使われる全角文字・
      バッチ内の一時的なASCII置換文字)を除去
    - 空白の有無による差異を無視(バッチがスペースの代わりに使う
      アンダースコアも同様に無視する)
    - 大文字小文字を無視
    """
    # (禁止文字の代わりに使う全角文字 ＼／：＊？”＜＞｜ も、半角と同様に除去して照合する)
    name = re.sub(r'[\\`/:：;*＊?？$<＜>＞|｜"＼／”“＂]', "", name)
    name = re.sub(r"[\s_]+", "", name)
    return name.strip().lower()


# 部分一致を許容する最低文字数(これより短い文字列同士は完全一致のみ判定する。
# 短い文字列で部分一致を許すと無関係なファイル名同士が偶然一致してしまうため)
_MIN_SUBSTRING_MATCH_LENGTH = 6


def _is_safe_boundary(char: Optional[str]) -> bool:
    """
    部分一致した箇所のすぐ外側の文字が「安全」かどうかを判定する。
    数字だった場合は危険とみなす(例: "アニメ#1" が "アニメ#10" に部分一致
    してしまうと、話数違いの別エピソードを同一と誤判定してしまうため。
    直後/直前が数字でなければ、話数の区切りが変わったとは考えにくい)。
    文字が無い(文字列の端まで一致している)場合は安全とみなす。
    """
    if char is None:
        return True
    return not char.isdigit()


def _contains_at_safe_boundary(shorter: str, longer: str) -> bool:
    """shorter が longer の中に、数字の途中を切らない形で含まれているか"""
    idx = longer.find(shorter)
    if idx == -1:
        return False
    before = longer[idx - 1] if idx > 0 else None
    after_idx = idx + len(shorter)
    after = longer[after_idx] if after_idx < len(longer) else None
    return _is_safe_boundary(before) and _is_safe_boundary(after)


def names_match(candidate: str, converted_name: str) -> bool:
    """
    候補文字列(candidate)と変換済みファイル名(converted_name)が
    一致するとみなせるかを判定する。完全一致に加えて、
    「[HV]」等の手動タグ付与や記号違いを吸収するため部分一致も許容する。
    ただし、一致した箇所の直後/直前が数字の場合は「話数違いの別エピソードを
    誤って同一視している」可能性が高いため不一致として扱う
    (例: "アニメ#1" が "アニメ#10" に部分一致してしまうのを防ぐ)。
    """
    if not candidate or not converted_name:
        return False
    if candidate == converted_name:
        return True
    if len(candidate) >= _MIN_SUBSTRING_MATCH_LENGTH and _contains_at_safe_boundary(candidate, converted_name):
        return True
    if len(converted_name) >= _MIN_SUBSTRING_MATCH_LENGTH and _contains_at_safe_boundary(converted_name, candidate):
        return True
    return False


def build_match_candidates(
    source_base_name: str, program_name: Optional[str], include_source_name: bool = True
) -> List[str]:
    """
    照合に使う正規化済み候補文字列のリストを作る。
    「元ファイル名で一致」「録画番組名で一致(日付有無どちらでも)」の
    どちらのパターンにも対応する。
    """
    candidates = set()

    if include_source_name:
        name_no_ext, _ext = os.path.splitext(source_base_name)
        candidates.add(normalize_name(name_no_ext))

    if program_name and program_name != NO_PROGRAM_INFO:
        base_title = strip_trailing_date(program_name)
        candidates.add(normalize_name(program_name))
        candidates.add(normalize_name(base_title))
        # rplsinfo.exe を -C 無し(バッチ内部の呼び出し)で使うと、番組名中の
        # カンマがそのまま保持されずファイル名から消えることがあるため、
        # カンマを除去したバージョンも候補に加えておく
        no_comma_title = base_title.replace(",", "").replace("\uFF0C", "")
        candidates.add(normalize_name(no_comma_title))

    return [c for c in candidates if c]


def is_converted_match(candidates: List[str], converted_names: List[str]) -> bool:
    """candidatesのいずれかがconverted_namesのいずれかとnames_match()するか"""
    for candidate in candidates:
        for converted_name in converted_names:
            if names_match(candidate, converted_name):
                return True
    return False


def is_source_converted(
    file_dir: str, source_base_name: str, program_name: Optional[str], date_digits: str = "",
    cache: Optional[dict] = None,
) -> bool:
    """
    元ファイル(m2ts)が変換済みかを判定する。
      - 同じフォルダの mkv/mp4: 元ファイル名(00001など)でも、番組名でも照合する
      - 仕分けフォルダ内の mkv/mp4: 番組名でだけ照合する
        (「00001」のような番号だけの一致は、別の番組の00001.mkvを拾ってしまうため使わない)
    """
    if cache is None:
        cache = {}
    if file_dir not in cache:
        cache[file_dir] = list_converted_names(file_dir, include_sorted=False)
    if "__sorted__" not in cache:
        cache["__sorted__"] = [
            n for d in list_sorted_dirs()
            for n in list_converted_names(d, include_sorted=False)
        ]
    local_keys = collect_converted_basenames(
        file_dir, date_digits=date_digits, source_base_name=source_base_name, names=cache[file_dir]
    )
    if is_converted_match(build_match_candidates(source_base_name, program_name), local_keys):
        return True
    sorted_keys = collect_converted_basenames(
        file_dir, date_digits=date_digits, source_base_name=source_base_name, names=cache["__sorted__"]
    )
    return is_converted_match(
        build_match_candidates(source_base_name, program_name, include_source_name=False), sorted_keys
    )


def find_converted_file(
    folder: str, source_base_name: str, program_name: Optional[str], date_digits: str = ""
) -> Optional[str]:
    """
    collect_converted_basenames / build_match_candidates と同じ照合ロジックで、
    実際にマッチした変換済みファイルの「ファイル名(拡張子付き)」を返す。
    見つからなければ None。
    """
    candidates = build_match_candidates(source_base_name, program_name)
    if not candidates:
        return None
    try:
        entries = os.listdir(folder)
    except Exception:
        return None
    for name in entries:
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or not name.lower().endswith(CONVERTED_EXTENSIONS):
            continue
        base, _ext = os.path.splitext(name)
        if is_other_date_file(base, date_digits, source_base_name):
            continue
        converted_names = [normalize_name(base), normalize_name(strip_trailing_date(base))]
        if is_converted_match(candidates, converted_names):
            return name
    return None


def find_converted_path(
    folder: str, source_base_name: str, program_name: Optional[str], date_digits: str = ""
) -> Optional[str]:
    """
    find_converted_file と同じ照合で、変換済みファイルの「フルパス」を返す。
    folder に加えて、仕分けフォルダ内(チャンネル別に仕分け済み)も探す。見つからなければ None。
    """
    candidates = build_match_candidates(source_base_name, program_name)
    if not candidates:
        return None
    name_only = build_match_candidates(source_base_name, program_name, include_source_name=False)
    for current in [folder] + list_sorted_dirs():
        # 仕分けフォルダ内は、番号だけ(00001など)の一致では判定しない
        use = candidates if os.path.normcase(current) == os.path.normcase(folder) else name_only
        try:
            entries = os.listdir(current)
        except Exception:
            continue
        for name in entries:
            path = os.path.join(current, name)
            if not name.lower().endswith(CONVERTED_EXTENSIONS) or not os.path.isfile(path):
                continue
            base, _ext = os.path.splitext(name)
            if is_other_date_file(base, date_digits, source_base_name):
                continue
            converted_names = [normalize_name(base), normalize_name(strip_trailing_date(base))]
            if is_converted_match(use, converted_names):
                return path
    return None


def channel_folder_name(channel: str) -> Optional[str]:
    """チャンネル名からフォルダ名を作る。不明な場合は None"""
    name = sanitize_title_for_filename((channel or "").strip()).strip().rstrip(". ")
    if not name or name.startswith("("):
        return None
    return name


def _norm_channel_key(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip().casefold()


def read_channel_from_sidecar_csv(csv_path: str, known_channels) -> Optional[str]:
    """
    mkv/mp4と対のcsv(rplsinfoの出力)から、チャンネル名を読む。m2tsが残っていないファイルの仕分け用。
    バッチが作るcsvは UTF-16・タブ区切りで、1行目が
      ファイル名 / 番組名 / 放送日 / 開始時刻 / チャンネル名 / 番組内容
    の並び(チャンネル名は5列目)。カンマ区切り(ファイル名,番組名,チャンネル名,日付)の形にも対応する。
    どちらの並びでもなければ、先頭の数行の項目のうち、既に分かっているチャンネル名
    (一覧の行・仕分けフォルダ名)と一致するものを使う。見つからなければ None。
    ノイズ検査で書き足したブロック以降は見ない。
    """
    try:
        text, _enc = read_text_auto(csv_path)
    except OSError:
        return None
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    delimiter = "\t" if "\t" in first_line else ","
    rows: List[List[str]] = []
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            if row and row[0].lstrip().startswith(NOISE_CSV_MARKER):
                break
            if any(cell.strip() for cell in row):
                rows.append(row)
            if len(rows) >= 3:
                break
    except csv.Error:
        return None
    if not rows:
        return None
    first = [cell.strip() for cell in rows[0]]
    looks_like_file = bool(first) and re.search(r"\.(m2ts|rpls|mts)$", first[0], re.IGNORECASE)
    if looks_like_file:
        if delimiter == "\t" and len(first) >= 5 and first[4] and not first[4].isdigit():
            return first[4]
        if delimiter == "," and len(first) >= 3 and first[2] and not first[2].isdigit():
            return first[2]
    known = {_norm_channel_key(c): c for c in known_channels if c}
    for row in rows:
        for cell in row:
            hit = known.get(_norm_channel_key(cell))
            if hit:
                return hit
    return None


def read_program_info_from_sidecar_csv(csv_path: str) -> Tuple[str, str]:
    """対になっているcsvから、(番組名, 放送日 "YYYY/MM/DD") を読む。読めない項目は空文字"""
    try:
        text, _enc = read_text_auto(csv_path)
    except OSError:
        return "", ""
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    delimiter = "\t" if "\t" in first_line else ","
    try:
        row = next(csv.reader(io.StringIO(first_line), delimiter=delimiter), [])
    except csv.Error:
        return "", ""
    row = [c.strip() for c in row]
    if not row or not re.search(r"\.(m2ts|rpls|mts)$", row[0], re.IGNORECASE):
        return "", ""
    program = row[1] if len(row) > 1 else ""
    date_cell = row[2] if delimiter == "\t" else (row[3] if len(row) > 3 else "")
    return program, format_date_digits(normalize_date_digits(date_cell)) if date_cell else ""


def read_start_time_from_sidecar_csv(csv_path: str) -> str:
    """対になっているcsv(タブ区切り)から、放送の開始時刻 "HH:MM" を読む。読めなければ空文字"""
    try:
        text, _enc = read_text_auto(csv_path)
    except OSError:
        return ""
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    if "\t" not in first_line:
        return ""
    cells = [c.strip() for c in first_line.split("\t")]
    if len(cells) > 3:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", cells[3])
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


def list_sorted_videos(sort_root: str) -> List[str]:
    """仕分けフォルダ(の下)にある mkv/mp4 の一覧"""
    result: List[str] = []
    for current, _dirs, files in os.walk(sort_root):
        for name in sorted(files):
            if name.lower().endswith(CONVERTED_EXTENSIONS):
                result.append(os.path.join(current, name))
    return result


def find_orphan_videos(folder: str, recursive: bool, exclude_paths) -> List[str]:
    """
    folder内の mkv/mp4 のうち、仕分けフォルダの外にあり、exclude_paths(一覧の行に対応する
    出力ファイル)に含まれないものを返す。m2tsを削除した後の変換済みファイルが対象。
    """
    sort_root = os.path.normcase(os.path.abspath(get_sort_root()))
    excluded = {os.path.normcase(os.path.abspath(p)) for p in exclude_paths if p}
    result: List[str] = []
    walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
    for current, dirs, files in walker:
        cur_norm = os.path.normcase(os.path.abspath(current))
        if cur_norm == sort_root or cur_norm.startswith(sort_root + os.sep):
            dirs[:] = []
            continue
        for name in sorted(files):
            if not name.lower().endswith(CONVERTED_EXTENSIONS):
                continue
            path = os.path.join(current, name)
            if os.path.normcase(os.path.abspath(path)) in excluded or not os.path.isfile(path):
                continue
            result.append(path)
    return result


def numbered_pair_target(directory: str, stem: str, video_ext: str) -> Tuple[str, bool]:
    """
    directory内で、動画(stem+video_ext)とcsv(stem+.csv)の両方が空いている名前(stem)を返す。
    空いていなければ「stem(2)」「stem(3)」…と番号を付ける。戻り値は (使うstem, 番号を付けたか)。
    """
    def free(candidate: str) -> bool:
        return not os.path.exists(os.path.join(directory, candidate + video_ext)) and not os.path.exists(
            os.path.join(directory, candidate + ".csv")
        )

    if free(stem):
        return stem, False
    for number in range(2, 10000):
        candidate = f"{stem}({number})"
        if free(candidate):
            return candidate, True
    raise OSError("空いている連番が見つかりません")


# 埋め込みバッチ側では、cmd.exeのコードページ依存の文字化けを避けるため、
# Windowsのファイル名に使えない記号(: * ? < > | \)を、全角文字ではなく
# 安全なASCII文字に一時的に置き換えてリネームしている。
# { 左側(プレースホルダ) : 右側(本来の全角文字) }
PLACEHOLDER_TO_FULLWIDTH: Dict[str, str] = {
    ";": "：",
    "$": "？",
    "`": "＼",
}
# 「*」「<」「>」「|」はcmd.exeの%VAR:old=new%構文やリダイレクト/パイプの特殊文字と
# 衝突する(構文エラーや誤動作の恐れがある)ため、バッチ側では置換せず元の文字のまま
# 残している。これらを含む番組タイトルは、現状リネームに失敗する可能性がある。


def restore_colon_in_output_filename(path: Optional[str]) -> Optional[str]:
    """
    バッチが一時的に使ったASCIIプレースホルダ文字を、本来の全角記号へ戻す。
    Pythonのファイル操作はコードページに依存しない(Unicodeのままファイル
    システム操作できる)ため、エンコード完了直後にここで安全に変換できる。
    """
    if not path or not os.path.isfile(path):
        return path
    directory, filename = os.path.split(path)
    new_filename = filename
    for placeholder, fullwidth in PLACEHOLDER_TO_FULLWIDTH.items():
        new_filename = new_filename.replace(placeholder, fullwidth)
    if new_filename == filename:
        return path
    new_path = os.path.join(directory, new_filename)
    if os.path.exists(new_path):
        # 既に同名のファイルがある場合は、事故を避けるためリネームしない
        return path
    try:
        os.rename(path, new_path)
        return new_path
    except OSError:
        return path


def snapshot_output_files(folder: str) -> Dict[str, int]:
    """フォルダ直下の mkv/mp4/csv について {ファイル名: 更新時刻(ns)} を返す"""
    result: Dict[str, int] = {}
    try:
        entries = os.listdir(folder)
    except Exception:
        return result
    for name in entries:
        if not name.lower().endswith(CONVERTED_EXTENSIONS + (".csv",)):
            continue
        try:
            result[name] = os.stat(os.path.join(folder, name)).st_mtime_ns
        except OSError:
            continue
    return result


def diff_output_files(before: Dict[str, int], after: Dict[str, int]) -> List[str]:
    """before→afterで新規作成された、または更新時刻が変わったファイル名の一覧"""
    return [name for name, mtime in after.items() if before.get(name) != mtime]


def normalize_date_digits(raw: str) -> str:
    """
    rplsinfo.exeが出力する日付文字列(例: "26/10/05")から数字のみを取り出し、
    8桁(YYYYMMDD)に正規化する。取得・正規化できなければ空文字を返す。
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 6:
        # 2桁年(YYMMDD)形式の場合、20XX年と仮定して4桁化する
        digits = "20" + digits
    elif len(digits) != 8:
        digits = ""
    return digits


def format_date_digits(date_digits: str) -> str:
    """8桁(YYYYMMDD)の数字列を "YYYY/MM/DD" 表示用の文字列に変換する"""
    if len(date_digits) != 8:
        return ""
    return f"{date_digits[0:4]}/{date_digits[4:6]}/{date_digits[6:8]}"


def find_paired_rpls(m2ts_path: str) -> Optional[str]:
    """
    BDAV構成(.../<番号>/STREAM/xxxxx.m2ts)で、対応する .../<番号>/PLAYLIST/xxxxx.rpls が
    存在すればそのパスを返す。なければ None。
    """
    if not m2ts_path.lower().endswith(".m2ts"):
        return None
    stream_dir = os.path.dirname(m2ts_path)
    parent_dir = os.path.dirname(stream_dir)
    base_no_ext = os.path.splitext(os.path.basename(m2ts_path))[0]
    rpls_path = os.path.join(parent_dir, "PLAYLIST", base_no_ext + ".rpls")
    return rpls_path if os.path.isfile(rpls_path) else None


def get_program_info(rplsinfo_path: str, target_file: str) -> Optional[Tuple[str, str, str, str]]:
    """
    rplsinfo.exe を実行し、(ファイル名, 番組名, チャンネル名, 放送日("YYYY/MM/DD"。
    取得できなければ空文字)) のタプルを返す。取得できなかった場合は None を返す。
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        cmd = [rplsinfo_path, target_file, tmp_path, "-C", "-f", "-b", "-c", "-d"]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
            creationflags=creationflags,
        )

        if not os.path.exists(tmp_path):
            return None

        with io.open(tmp_path, "r", encoding="utf-16") as f:
            content = f.read()

        if not content.strip():
            return None

        reader = csv.reader(io.StringIO(content))
        row = next(reader, None)
        if not row or len(row) < 3:
            return None

        broadcast_date = ""
        if len(row) >= 4:
            broadcast_date = format_date_digits(normalize_date_digits(row[3]))

        return row[0], row[1], row[2], broadcast_date

    except subprocess.TimeoutExpired:
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# Windowsのファイル名に使えない記号 -> 見た目の近い全角文字 への変換表。
# cmd.exe のバッチ内で置換しようとするとコードページや構文上の問題が色々あったため、
# エンコード完了後にPython側(Unicodeのままファイル操作でき、コードページに依存しない)で
# 番組名から直接ファイル名を組み立てる際に使う。
ILLEGAL_CHAR_TO_FULLWIDTH: Dict[str, str] = {
    "\\": "＼",
    "/": "／",
    ":": "：",
    "*": "＊",
    "?": "？",
    '"': "”",
    "<": "＜",
    ">": "＞",
    "|": "｜",
}


def sanitize_title_for_filename(title: str) -> str:
    """番組名中のWindows禁止文字を、見た目の近い全角文字に置き換える"""
    return "".join(ILLEGAL_CHAR_TO_FULLWIDTH.get(ch, ch) for ch in title)


def get_program_name_with_date(rplsinfo_path: str, target_file: str) -> Optional[Tuple[str, str]]:
    """
    rplsinfo.exe をCSVモード(ファイル出力、UTF-16)で実行し、
    (番組名, 録画日付(YYYYMMDD の数字のみ。取得できなければ空文字)) を返す。
    バッチ内部のようにコンソール出力を直接キャプチャするのではなく、
    get_program_info() と同じくファイル出力を使うため、コードページに依存せず安全。
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        cmd = [rplsinfo_path, target_file, tmp_path, "-C", "-f", "-b", "-d"]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
            creationflags=creationflags,
        )

        if not os.path.exists(tmp_path):
            return None

        with io.open(tmp_path, "r", encoding="utf-16") as f:
            content = f.read()

        if not content.strip():
            return None

        reader = csv.reader(io.StringIO(content))
        row = next(reader, None)
        if not row or len(row) < 2:
            return None

        program_name = row[1]
        date_digits = normalize_date_digits(row[2]) if len(row) >= 3 else ""

        return program_name, date_digits

    except subprocess.TimeoutExpired:
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# ffmpegログの解析(エンコード失敗・映像/音声ノイズの可能性を検出する)
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_TIME_RE = re.compile(r"\btime=(\d+):(\d+):(\d+(?:\.\d+)?)")
_DUP_RE = re.compile(r"\bdup=(\d+)")
_AUDIO_BSF_ERROR_RE = re.compile(r"error applying bitstream filters to a packet", re.IGNORECASE)
_AUDIO_GAP_CATEGORY = "音声の一部が欠けた疑い(壊れた音声パケットを飛ばした)"
_DROP_RE = re.compile(r"\bdrop=(\d+)")

# 内容に関わらず「失敗」扱いにするパターン
_CRITICAL_PATTERNS = [
    (re.compile(r"conversion failed", re.IGNORECASE), "変換に失敗しました(Conversion failed)"),
    (re.compile(r"error while opening encoder", re.IGNORECASE), "エンコーダーを開けませんでした"),
    (re.compile(r"cannot allocate memory", re.IGNORECASE), "メモリを確保できませんでした"),
    (re.compile(r"not supported by the bitstream filter", re.IGNORECASE), "音声の形式に合わない設定でした(bitstream filter)"),
    (re.compile(r"error initializing bitstream filter", re.IGNORECASE), "音声の変換フィルタを初期化できませんでした"),
]

# 発生位置に関わらず「要確認」扱いにするパターン(映像/音声ノイズの疑い)
_WARNING_PATTERNS = [
    (re.compile(r"corrupt decoded frame", re.IGNORECASE), "映像ブロックノイズの疑い(corrupt decoded frame)"),
    (re.compile(r"error while decoding mb", re.IGNORECASE), "映像ブロックノイズの疑い(decode MB error)"),
    (
        re.compile(
            r"missing reference picture|reference picture missing during reorder|illegal short term buffer state",
            re.IGNORECASE,
        ),
        "映像破損の疑い(参照フレーム欠落)",
    ),
    (re.compile(r"error submitting packet to decoder", re.IGNORECASE), "音声破損の疑い(音声デコード失敗)"),
    (re.compile(r"invalid data found when processing input", re.IGNORECASE), "データ破損の疑い"),
]

# 録画の先頭・末尾に出るぶんには無視してよいが、本編途中に出ると要確認扱いにするパターン
_BOUNDARY_OK_PATTERNS = [
    re.compile(r"sps_id \d+ out of range", re.IGNORECASE),
    re.compile(r"non-existing pps", re.IGNORECASE),
    re.compile(r"decode_slice_header error", re.IGNORECASE),
    re.compile(r"no frame!", re.IGNORECASE),
    re.compile(r"pes packet size mismatch", re.IGNORECASE),
    re.compile(r"packet corrupt", re.IGNORECASE),
    re.compile(r"invalid dts:.*replacing by guess", re.IGNORECASE),
]

_HEAD_SECONDS = 4.0            # 録画の先頭とみなす秒数(この範囲の映像/音声エラーは無視)
_TAIL_SECONDS = 20.0           # 録画の末尾とみなす秒数(終端の切れ目で出るエラーは無視)
_TRUNCATED_SECONDS = 60.0      # 出力の長さが元よりこの秒数以上短ければ「途中で終わった」と判断
_DUP_IGNORE_HEAD_SECONDS = 2.0  # 録画の先頭この秒数以内のdupの増加は、開始直後の正常な現象なので無視する
_DUP_JUMP_THRESHOLD = 30       # 直近の進捗更新間でこれ以上dupが増えたら記録する(参考情報)
_DROP_JUMP_THRESHOLD = 30      # 同上(drop)。dupと違い、これは単独でも要確認にする
_DUP_TOTAL_THRESHOLD = 1000    # 累計dupがこれを超えたら記録する(参考情報)
_ISSUE_DEDUP_SECONDS = 3.0     # 同じ種類の警告は、この秒数以内なら1件にまとめる
_MAX_ENTRIES_PER_CATEGORY = 15 # 1種類あたりに記録する発生時刻の上限(種類ごとに独立)

# 一定間隔で規則的に出続けるエラー(GOP周期の「corrupt decoded frame」等)は、実際の
# ノイズではなく変換の仕様上の副作用だったため、ノイズ扱いにしない。
# デコード系エラーが短時間に大量に出続ける場合(受信状態が悪い区間など)は、周期的であっても
# 「継続的な映像破損」として必ず要確認にする。ログ1行ごと(まとめる前)の件数で判定する。
_BURST_WINDOW_SECONDS = 60.0   # この秒数の窓の中で数える
_BURST_MIN_EVENTS = 60         # 窓内にこの件数以上あれば継続的な破損とみなす(通常の周期的なものは1分に15件程度)
_BURST_MERGE_SECONDS = 30.0    # 破損が途切れてもこの秒数以内なら同じ区間とみなす
_PERIODIC_MIN_EVENTS = 5       # この件数以上でないと周期性の判定をしない
_PERIODIC_MAX_MULTIPLE = 6     # 基本間隔の何倍までの欠けを同じ周期の並びとみなすか
_PERIODIC_TOLERANCE = 0.2      # 基本間隔に対する許容ずれ(割合)
_PERIODIC_COVERAGE = 0.7       # 全体のうち、この割合以上が周期の並びなら「周期的」と判定

# ソフトウェアデコーダ(特にSD放送の720x480)は、画が正常でも多数のフレームに
# 「corrupt decoded frame」の印を付けることがある。検証(00024.m2ts)で、CUDAデコードでは
# 0件、ソフトウェアデコードでは約2,840フレーム(全体の約6%)に印が付いたが、
# 全フレームのハッシュを比べると、末尾の1フレームを除いて完全に一致した(=画は壊れていない)。
# このため、印の付いたフレームが多数(=本物の破損ではなく、デコーダの判定の癖)で、かつ
# MBエラー・参照フレーム欠落・パケット破損など他の兆候が本編中に一切ない場合は、
# corrupt decoded frame を無視する。
_CORRUPT_FRAME_CATEGORY = "映像ブロックノイズの疑い(corrupt decoded frame)"
_CORRUPT_FRAME_MIN_FRAMES = 300   # ログの「Last message repeated」分を含めたフレーム数がこれ以上
_CORRUPT_FRAME_MIN_EVENTS = 10    # ログ上の出現回数(まとめ表示の回数)がこれ以上
_REPEATED_RE = re.compile(r"Last message repeated (\d+) times", re.IGNORECASE)

# デコード由来のエラー(先頭・末尾・周期的なものを除外して判定する種類)
_FATAL_ALWAYS_CATEGORIES = {
    "エンコーダーを開けませんでした",
    "メモリを確保できませんでした",
}
_CONVERSION_FAILED_CATEGORY = "変換に失敗しました(Conversion failed)"
_DUP_CATEGORIES = ("重複フレーム(dup)が急増", "重複フレーム(dup)の累計が多い")


def _seconds_to_hms(total_seconds: float) -> str:
    total_seconds = max(0.0, total_seconds)
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def format_minutes_seconds(total_seconds: float) -> str:
    """秒数を「27分22秒」のような表記に変換する(ファイル名への追記用)"""
    total_seconds = max(0, int(round(total_seconds)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}分{seconds}秒"


def _find_bursts(times: List[float]) -> List[Tuple[float, float, int]]:
    """
    ログ1行ごとの発生時刻から、短時間に大量に出ている区間を (開始秒, 終了秒, 件数) で返す。
    _BURST_WINDOW_SECONDS の窓に _BURST_MIN_EVENTS 件以上あれば、その窓の範囲を破損区間とし、
    _BURST_MERGE_SECONDS 以内に続くものは1つの区間にまとめる。
    """
    ts = sorted(times)
    if len(ts) < _BURST_MIN_EVENTS:
        return []
    marked = [False] * len(ts)
    j = 0
    for i, t in enumerate(ts):
        while ts[j] < t - _BURST_WINDOW_SECONDS:
            j += 1
        if i - j + 1 >= _BURST_MIN_EVENTS:
            for k in range(j, i + 1):
                marked[k] = True
    bursts: List[Tuple[float, float, int]] = []
    start = end = None
    count = 0
    for t, m in zip(ts, marked):
        if not m:
            continue
        if start is not None and (t - end) <= _BURST_MERGE_SECONDS:
            end = t
            count += 1
        else:
            if start is not None:
                bursts.append((start, end, count))
            start, end, count = t, t, 1
    if start is not None:
        bursts.append((start, end, count))
    return bursts


def _periodic_times(times: List[float]) -> List[float]:
    """
    発生時刻の並びのうち、一定間隔(の整数倍)で規則的に出ているものを返す。
    全体の _PERIODIC_COVERAGE 以上がそうでなければ「周期的ではない」として空リストを返す。
    """
    ts = sorted(times)
    if len(ts) < _PERIODIC_MIN_EVENTS:
        return []
    gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
    base = gaps[len(gaps) // 2]
    if base < 1.0:
        return []

    def fits(gap: float) -> bool:
        k = round(gap / base)
        return 1 <= k <= _PERIODIC_MAX_MULTIPLE and abs(gap - k * base) <= _PERIODIC_TOLERANCE * base

    in_series = []
    for i, t in enumerate(ts):
        near_prev = i > 0 and fits(t - ts[i - 1])
        near_next = i + 1 < len(ts) and fits(ts[i + 1] - t)
        if near_prev or near_next:
            in_series.append(t)
    if len(in_series) >= _PERIODIC_COVERAGE * len(ts):
        return in_series
    return []


def analyze_ffmpeg_log(
    lines: List[str], returncode: int
) -> Tuple[str, List[Tuple[str, int, List[Tuple[float, str]]]]]:
    """
    ffmpegの出力ログ(1行ずつのリスト)を解析し、
    (診断ラベル, [(種類, 発生回数, [(秒数, 表示用テキスト), ...]), ...]) を返す。
    診断ラベルは "OK" / "要確認" / "失敗" のいずれか。
    種類(カテゴリ)ごとに個別の上限で発生時刻を記録するため、
    1種類のエラーが多発しても他の種類のエラーが埋もれない。
    秒数を保持しておくことで、あとからプレーヤーでその時刻から再生する、といった用途に使える。

    誤検知を減らすため、次のものはノイズ/失敗として扱わない:
      - 録画の先頭(_HEAD_SECONDS)・末尾(_TAIL_SECONDS)に出るデコード系エラー
        (録画の切れ目で必ず出る副作用のため)
      - 一定間隔で規則的に出続けるデコード系エラー(GOP周期の副作用)
      - 録画の末尾で出る「Conversion failed」(最後まで変換できていれば内容は無事)
      - 重複フレーム(dup)の増加(ほぼ全ファイルで出るため、他に問題がある時の参考情報としてのみ記録)
    """
    duration_seconds: Optional[float] = None
    current_time_seconds = 0.0
    max_time_seconds = 0.0  # 2回目(合体)で進捗が巻き戻っても、1回目の到達位置で「最後まで行けたか」を判断する
    saw_time = False
    prev_dup = 0
    prev_drop = 0

    # (カテゴリ, 発生時刻, 付随情報) を種類ごとに溜めておき、最後にまとめて判定する
    events: Dict[str, List[Tuple[float, Optional[str]]]] = {}

    def add_event(time_seconds: float, category: str, detail: Optional[str] = None):
        events.setdefault(category, []).append((time_seconds, detail))

    corrupt_frame_events = 0
    corrupt_frame_total = 0
    last_was_corrupt_frame = False

    for line in lines:
        rep_match = _REPEATED_RE.search(line)
        if rep_match and last_was_corrupt_frame:
            corrupt_frame_total += int(rep_match.group(1))
            last_was_corrupt_frame = False

        dur_match = _DURATION_RE.search(line)
        if dur_match and duration_seconds is None:
            h, m, s = dur_match.groups()
            duration_seconds = int(h) * 3600 + int(m) * 60 + float(s)

        time_match = _TIME_RE.search(line)
        if time_match:
            h, m, s = time_match.groups()
            current_time_seconds = int(h) * 3600 + int(m) * 60 + float(s)
            max_time_seconds = max(max_time_seconds, current_time_seconds)
            saw_time = True

        dup_match = _DUP_RE.search(line)
        if dup_match:
            dup_val = int(dup_match.group(1))
            delta = dup_val - prev_dup
            if delta >= _DUP_JUMP_THRESHOLD and current_time_seconds >= _DUP_IGNORE_HEAD_SECONDS:
                add_event(current_time_seconds, "重複フレーム(dup)が急増", f"+{delta}、累計{dup_val}")
            prev_dup = dup_val

        drop_match = _DROP_RE.search(line)
        if drop_match:
            drop_val = int(drop_match.group(1))
            delta = drop_val - prev_drop
            if delta >= _DROP_JUMP_THRESHOLD:
                add_event(current_time_seconds, "コマ落ち(drop)が急増", f"+{delta}、累計{drop_val}")
            prev_drop = drop_val

        for pattern, category in _CRITICAL_PATTERNS:
            if pattern.search(line):
                add_event(current_time_seconds, category)

        if _AUDIO_BSF_ERROR_RE.search(line):
            # コピーしている音声の、壊れたパケットを飛ばした(その部分の音が欠ける)。先頭はAACの形式情報が
            # 不完全なために必ず出るので、他のデコード系エラーと同じ扱い(先頭・末尾は無視)にする
            add_event(current_time_seconds, _AUDIO_GAP_CATEGORY)

        for pattern, category in _WARNING_PATTERNS:
            if pattern.search(line):
                add_event(current_time_seconds, category)
                if category == _CORRUPT_FRAME_CATEGORY:
                    corrupt_frame_events += 1
                    corrupt_frame_total += 1
                    last_was_corrupt_frame = True
                else:
                    last_was_corrupt_frame = False

        for pattern in _BOUNDARY_OK_PATTERNS:
            if pattern.search(line):
                add_event(current_time_seconds, "デコードエラー(本編中に発生)")
                break

    if prev_dup >= _DUP_TOTAL_THRESHOLD and "重複フレーム(dup)が急増" not in events:
        add_event(current_time_seconds, "重複フレーム(dup)の累計が多い", f"合計{prev_dup}")

    def in_tail(t: float) -> bool:
        return duration_seconds is not None and (duration_seconds - t) <= _TAIL_SECONDS

    # 最後まで変換できていたか(Conversion failedが録画末尾の切れ目によるものか判断するため)
    reached_end = (
        duration_seconds is not None and saw_time and (duration_seconds - max_time_seconds) <= _TAIL_SECONDS
    )

    # corrupt decoded frame が多数あるのに、他の破損の兆候が本編中に無い場合は、
    # デコーダの判定の癖とみなして無視する(定数の説明を参照)
    if (
        corrupt_frame_total >= _CORRUPT_FRAME_MIN_FRAMES
        and corrupt_frame_events >= _CORRUPT_FRAME_MIN_EVENTS
        and _CORRUPT_FRAME_CATEGORY in events
    ):
        other_mid_decode = False
        for category, occurrences in events.items():
            if category == _CORRUPT_FRAME_CATEGORY:
                continue
            if category in _DUP_CATEGORIES or category in _FATAL_ALWAYS_CATEGORIES:
                continue
            if category in (_CONVERSION_FAILED_CATEGORY, "コマ落ち(drop)が急増"):
                continue
            if any(t > _HEAD_SECONDS and not in_tail(t) for t, _ in occurrences):
                other_mid_decode = True
                break
        if not other_mid_decode:
            del events[_CORRUPT_FRAME_CATEGORY]

    # ---- 種類ごとに「本当に問題のある発生時刻」だけを残す ----
    significant: Dict[str, List[Tuple[float, Optional[str]]]] = {}
    burst_runs: List[Tuple[float, float, int]] = []
    supporting: Dict[str, List[Tuple[float, Optional[str]]]] = {}
    fatal = False

    for category, occurrences in events.items():
        # 近接した発生は1件にまとめる(従来と同じ)
        deduped: List[Tuple[float, Optional[str]]] = []
        for t, detail in sorted(occurrences, key=lambda x: x[0]):
            if not deduped or (t - deduped[-1][0]) >= _ISSUE_DEDUP_SECONDS:
                deduped.append((t, detail))

        if category in _DUP_CATEGORIES:
            supporting[category] = deduped
            continue

        if category in _FATAL_ALWAYS_CATEGORIES:
            fatal = True
            significant[category] = deduped
            continue

        if category == _CONVERSION_FAILED_CATEGORY:
            real = [(t, d) for t, d in deduped if not (reached_end and in_tail(t))]
            if real:
                fatal = True
                significant[category] = real
            continue

        if category == "コマ落ち(drop)が急増":
            significant[category] = deduped
            continue

        # デコード系エラー: まず、大量に出続けている区間(継続的な破損)を探す。
        # これは先頭・末尾・周期性の除外の対象にしない。
        raw_mid = [t for t, _ in occurrences if t > _HEAD_SECONDS and not in_tail(t)]
        burst_runs.extend(_find_bursts(raw_mid))

        # 先頭・末尾・周期的なものを除外する
        mid = [(t, d) for t, d in deduped if t > _HEAD_SECONDS and not in_tail(t)]
        periodic = set(_periodic_times([t for t, _ in mid]))
        isolated = [(t, d) for t, d in mid if t not in periodic]
        if isolated:
            significant[category] = isolated

    # 種類を問わず、継続的な破損の区間は1つにまとめて(重なり・近接するものを結合して)記録する
    if burst_runs:
        merged: List[List[float]] = []
        for b_start, b_end, b_count in sorted(burst_runs):
            if merged and b_start - merged[-1][1] <= _BURST_MERGE_SECONDS:
                merged[-1][1] = max(merged[-1][1], b_end)
                merged[-1][2] += b_count
            else:
                merged.append([b_start, b_end, b_count])
        significant["継続的な映像/音声破損(受信状態が悪い区間など)"] = [
            (st, f"〜{_seconds_to_hms(en)} 約{(en - st) / 60:.1f}分間、エラー計{int(cnt)}行")
            for st, en, cnt in merged
        ]

    # 出力が元の長さより大幅に短い(=途中で終わっている)場合は、メッセージが無くても検出する
    if (
        not fatal
        and duration_seconds is not None
        and saw_time
        and (duration_seconds - max_time_seconds) > _TRUNCATED_SECONDS
    ):
        short_by = duration_seconds - max_time_seconds
        significant["出力が元の長さより短く終了"] = [
            (max_time_seconds, f"元{_seconds_to_hms(duration_seconds)}→出力{_seconds_to_hms(max_time_seconds)}、{short_by:.0f}秒不足")
        ]

    # dupは、他に問題がある時だけ参考情報として併記する
    issue_data = dict(significant)
    if significant:
        issue_data.update(supporting)

    result_issues: List[Tuple[str, int, List[Tuple[float, str]]]] = []
    for category, occurrences in issue_data.items():
        entries = []
        for t, detail in occurrences[:_MAX_ENTRIES_PER_CATEGORY]:
            display_text = f"{_seconds_to_hms(t)} 付近" + (f" ({detail})" if detail else "")
            entries.append((t, display_text))
        result_issues.append((category, len(occurrences), entries))

    if fatal:
        label = "失敗"
    elif returncode != 0 and not (reached_end and events.get(_CONVERSION_FAILED_CATEGORY)):
        # 終了コードが0でない原因が、末尾の切れ目による「Conversion failed」だと
        # 説明できない場合は、安全側で失敗扱いにする
        label = "失敗"
    elif result_issues:
        label = "要確認"
    else:
        label = "OK"

    return label, result_issues


# ---------------------------------------------------------------------------
# ノイズ検査(ソフトウェアデコードとCUDAデコードのフレームハッシュを比較する)
# ---------------------------------------------------------------------------
# H.264のデコード結果は、正常なストリームなら、どのデコーダでも1ビットの狂いなく一致する。
# 一方、ストリームが壊れている箇所は、デコーダごとに補完(隠蔽)のしかたが違うため、
# 出力が食い違う。この食い違うフレームの位置が、画が実際に壊れている箇所になる。
# (ffmpegの「corrupt decoded frame」の警告と違い、画が正常なフレームを誤検出しない)

_FRAMEMD5_TB_RE = re.compile(r"#tb 0:\s*(\d+)/(\d+)")
_NOISE_GROUP_GAP_SECONDS = 1.0        # 食い違うフレームがこの秒数以内に続けば同じ区間にまとめる
_NOISE_TAIL_SECONDS = 20.0            # 録画の末尾とみなす秒数
_NOISE_TAIL_MAX_FRAMES = 60           # 末尾でこのフレーム数以下の食い違いは、録画の切れ目として無視
_NOISE_UNRELIABLE_RATIO = 0.5         # 食い違いが全体のこの割合を超えたら、比較自体が成り立っていないと判断
_NOISE_NAME_MERGE_SECONDS = 5.0       # ファイル名に載せる時の、近接区間のまとめ幅
_NOISE_NAME_MAX_LENGTH = 200          # ファイル名(拡張子抜き)がこれを超えるなら、秒数の記載をやめてCSV参照にする
NOISE_CSV_MARKER = "[ノイズ検査]"
NOISE_TAG_CSV_REF = "(ノイズ有_csv参照)"
_NOISE_DIFF_CATEGORY = "映像フレーム不一致(ソフト/CUDAデコード比較)"
_DIAG_NON_NOISE_CATEGORIES = ("重複フレーム(dup)が急増", "重複フレーム(dup)の累計が多い")


def find_ffmpeg() -> Optional[str]:
    """ffmpeg.exe のパスを探す(スクリプトと同じフォルダ優先、次に PATH)"""
    same_dir = os.path.join(get_script_dir(), "ffmpeg.exe")
    if os.path.isfile(same_dir):
        return same_dir
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def find_ffprobe() -> Optional[str]:
    """ffprobe.exe のパスを探す(スクリプトと同じフォルダ優先、次に PATH、最後にffmpegの隣)"""
    same_dir = os.path.join(get_script_dir(), "ffprobe.exe")
    if os.path.isfile(same_dir):
        return same_dir
    found = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if found:
        return found
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        for name in ("ffprobe.exe", "ffprobe"):
            neighbor = os.path.join(os.path.dirname(ffmpeg), name)
            if os.path.isfile(neighbor):
                return neighbor
    return None


# 字幕ストリームを「中身あり」とみなす最小パケット数。
# 空のARIB字幕(ffmpegは認識するがパケットが1つも来ない)では N/A(=0)になる。
# 実際に字幕が出る録画では数百個以上になる。
SUBTITLE_MIN_PACKETS = 10


def _parse_frame_rate(text: object) -> float:
    try:
        num, den = str(text).split("/")
        return float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_probe_json(text: str) -> List[dict]:
    """
    ffprobe -of json の出力から、ストリームの一覧を作る。
    "programs" の中に出てくるストリームが番組情報(PMT)に宣言されているもの、
    トップレベルの "streams" がffmpegの認識した全ストリーム。
    nb_read_packets が無い(N/A)ものは、パケットを1つも読めなかった=0個として扱う。
    """
    try:
        data = json.loads(text)
    except ValueError:
        return []
    declared = set()
    for program in data.get("programs", []) or []:
        for st in program.get("streams", []) or []:
            if isinstance(st.get("index"), int):
                declared.add(st["index"])
    result: List[dict] = []
    for st in data.get("streams", []) or []:
        index = st.get("index")
        if not isinstance(index, int):
            continue
        try:
            packets = int(st.get("nb_read_packets", 0))
        except (TypeError, ValueError):
            packets = 0
        result.append({
            "index": index,
            "codec": str(st.get("codec_name", "")),
            "type": str(st.get("codec_type", "")),
            "packets": packets,
            "in_program": index in declared,
            "width": st.get("width"),
            "height": st.get("height"),
            "field_order": str(st.get("field_order", "")),
            "fps": _parse_frame_rate(st.get("avg_frame_rate", "")),
            "channels": st.get("channels"),
            "sample_rate": st.get("sample_rate"),
        })
    return sorted(result, key=lambda x: x["index"])


# TSのPTSは33bitで約95443.7秒ごとに一周する
_TS_WRAP_SECONDS = 2 ** 33 / 90000.0

# 音声・字幕の最後のパケットが、映像の最後よりこれ以上早く終わっていたら「途中で途切れる」とみなす。
# 2つの番組が地続きで録画され、後半の番組には解説放送・字幕が無い、という録画で起こる。
# このようなストリームをエンコードと同時にコピーすると、mkv/mp4の書き込みが
# そのストリームの続きを待ち続けて映像が溜まり、最後にメモリ不足で失敗する。
STREAM_EARLY_END_SECONDS = 60.0
# 録画の途中(本編の開始など)から現れるストリーム(二か国語の2本目の音声など)を見つけるため、
# ffmpeg/ffprobeに先頭のこれだけ(データ量・時間)を調べさせる。標準の設定だと、先頭の数秒でストリームを
# 確定してしまうため、本編に入ってから始まる音声が「無い」ものとして扱われる。
WIDE_PROBE_ARGS = ["-probesize", "500M", "-analyzeduration", "500M"]
# 字幕のパケットの間がこれ以上空く(まばらな字幕)と、同時に入れた時にエンコードが止まる
SUBTITLE_SPARSE_GAP_SECONDS = 300.0


def parse_packet_times(lines) -> Dict[int, Tuple[float, float]]:
    return {i: (v[0], v[1]) for i, v in parse_packet_times_ex(lines).items()}


def parse_packet_times_ex(lines) -> Dict[int, Tuple[float, float, float]]:
    """
    ffprobe -show_entries packet=stream_index,pts_time,dts_time -of compact=p=0 の出力(行の並び)から、
    {stream_index: (最初の時刻, 最後の時刻, パケット間の最大の空き秒数)} を作る。
    項目の並びは固定ではないため、必ず key=value で読む。33bit PTSの一周は補正する。
    """
    state: Dict[int, List[float]] = {}  # index -> [first, last(補正後), offset, max, 直前の時刻, 最大の空き]
    for line in lines:
        fields = {}
        for part in line.strip().split("|"):
            if "=" in part:
                key, _, value = part.partition("=")
                fields[key] = value
        try:
            index = int(fields["stream_index"])
        except (KeyError, ValueError):
            continue
        raw = fields.get("pts_time", "N/A")
        if raw in ("N/A", ""):
            raw = fields.get("dts_time", "N/A")
        try:
            t = float(raw)
        except ValueError:
            continue
        st = state.get(index)
        if st is None:
            state[index] = [t, t, 0.0, t, t, 0.0]
            continue
        if t + st[2] < st[3] - _TS_WRAP_SECONDS / 2:
            st[2] += _TS_WRAP_SECONDS
        t += st[2]
        st[1] = t
        if t - st[4] > st[5]:
            st[5] = t - st[4]
        st[4] = t
        if t > st[3]:
            st[3] = t
    return {i: (v[0], v[3], v[5]) for i, v in state.items()}


def probe_stream_times(path: str, timeout: float = 1800.0) -> Dict[int, Tuple[float, float, float]]:
    """各ストリームの(最初, 最後)のパケット時刻をffprobeで調べる。失敗したら空の辞書。"""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return {}
    cmd = [ffprobe, "-v", "error"] + WIDE_PROBE_ARGS + [
           "-show_entries", "packet=stream_index,pts_time,dts_time", "-of", "compact=p=0", path]
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, creationflags=creationflags,
        )
    except Exception:
        return {}
    return parse_packet_times_ex(completed.stdout.decode("utf-8", errors="replace").splitlines())


def probe_streams(path: str, timeout: float = 1800.0) -> Tuple[Optional[List[dict]], str]:
    """ffprobeでストリーム構成とパケット数を調べる。(結果 or None, エラー文)"""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None, "ffprobe が見つかりません"
    cmd = [ffprobe, "-v", "error"] + WIDE_PROBE_ARGS + ["-count_packets", "-show_entries",
           "stream=index,codec_type,codec_name,nb_read_packets,field_order,avg_frame_rate,"
           "width,height,channels,sample_rate:format=start_time", "-of", "json", path]
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, creationflags=creationflags,
        )
    except Exception as e:
        return None, f"ffprobeの実行に失敗: {e}"
    streams = parse_probe_json(completed.stdout.decode("utf-8", errors="replace"))
    if not streams:
        return None, "ストリーム情報を取得できませんでした"
    times = probe_stream_times(path, timeout)
    container_start: Optional[float] = None
    try:
        container_start = float(json.loads(completed.stdout.decode("utf-8", errors="replace")).get("format", {}).get("start_time"))
    except (TypeError, ValueError):
        container_start = None
    for st in streams:
        if st["index"] in times:
            st["first_time"], st["last_time"], st["max_gap"] = times[st["index"]]
        st["container_start"] = container_start
    return streams, ""


# 2本目の音声のパケット数が1本目のこの割合を下回ったら「解説放送」とみなす
AUDIO_DESC_RATIO = 0.9

# 放送局名にこれが含まれ、かつ音声が1本のとき「モノラル二か国語」とみなす
MONO_BILINGUAL_CHANNEL_KEYWORDS = ("カートゥーン", "cartoon")


def is_mono_bilingual_channel(channel_name: str) -> bool:
    """放送局名がカートゥーンネットワーク系か(半角カナ・全角英数・大文字小文字の違いは吸収する)"""
    normalized = unicodedata.normalize("NFKC", channel_name or "").casefold()
    return any(k in normalized for k in MONO_BILINGUAL_CHANNEL_KEYWORDS)


def _fmt_hms(seconds: float) -> str:
    total = int(max(0.0, seconds))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def resolve_auto_options(
    options: Dict[str, object], streams: List[dict], channel_name: str = ""
) -> Tuple[Dict[str, object], List[str]]:
    """
    ffprobeの結果をもとに、字幕・音声の設定を実際の中身に合わせる。
    - 字幕: パケットが十分あるものだけ入れる(空のARIB字幕は入れない)
    - 音声: パケットが無い(存在しない)トラックは使わない
    戻り値: (設定, 判定結果のメモ)
    """
    o = normalize_encode_options(options)
    o["wide_probe"] = True  # 途中から現れるストリームも見つけるため、広めに調べる
    notes: List[str] = []
    audio = [st for st in streams if st["type"] == "audio"]
    subs = [st for st in streams if st["type"] == "subtitle"]

    def _audio_usable(st: dict) -> bool:
        # パケットが無い、またはffmpegがチャンネル数/サンプルレートを判定できなかった(0ch)音声は、
        # 実体のない空トラック。コピーしようとすると "sample rate not set" で書き出しに失敗する
        if st["packets"] <= 0:
            return False
        return st.get("channels") not in (0, None) and str(st.get("sample_rate") or "0") not in ("0", "")

    live_audio = [k for k, st in enumerate(audio) if _audio_usable(st)]
    if audio and not live_audio:
        # 判定が全滅したときは、ffprobeの出力形式の違いなどが疑わしいので、パケットの有無だけで判断する
        live_audio = [k for k, st in enumerate(audio) if st["packets"] > 0]
    if audio:
        detail = ", ".join(
            f"a:{k}={st['packets']}" + ("" if k in live_audio else "(空)") for k, st in enumerate(audio)
        )
        notes.append(f"音声 {len(audio)}本 ({detail})")
        if live_audio and (len(live_audio) != len(audio) or o["audio_tracks"] == "first"):
            if o["audio_tracks"] == "first":
                live_audio = live_audio[:1]
            o["audio_ordinals"] = live_audio
            if o["audio_tracks"] == "first":
                notes.append("→ 音声は1本目だけを使います")
            elif len(live_audio) != len(audio):
                notes.append("→ 実体のない(パケットが無い・0chの)音声トラックは使いません")

    non_aac = [k for k, st in enumerate(audio) if k in live_audio and st.get("codec") not in ("aac", "aac_latm")]
    if non_aac:
        o["audio_non_aac"] = non_aac
        if "audio_ordinals" not in o:
            o["audio_ordinals"] = list(live_audio)
        names = ", ".join(f"a:{k}={audio[k].get('codec') or '不明'}" for k in non_aac)
        notes.append(f"音声がAAC以外です({names})→ AAC用のフィルタは付けずにコピーします")

    auto_select = bool(o["auto_select"])
    if auto_select:
        o["subs"] = True  # まず字幕を入れる前提にして、下の判定で中身が無ければ外す
    # 2本目の音声のパケットが1本目より明らかに少ない(約9割未満)なら、二か国語ではなく
    # CMなどで無音になる「解説放送」とみなす(二か国語放送は2本の数がほぼ揃う)
    if len(audio) >= 2 and 0 in live_audio and 1 in live_audio:
        both_used = "audio_ordinals" not in o or {0, 1} <= set(o["audio_ordinals"])
        def _rate(st: dict) -> float:
            """1秒あたりのパケット数。途中から始まる音声は、始まってからの長さで割る"""
            first, last = st.get("first_time"), st.get("last_time")
            if first is not None and last is not None and last - first > 1.0:
                return st["packets"] / (last - first)
            return float(st["packets"])

        late_second = (
            audio[1].get("first_time") is not None and audio[0].get("first_time") is not None
            and audio[1]["first_time"] - audio[0]["first_time"] > STREAM_EARLY_END_SECONDS
        )
        if late_second and _rate(audio[0]) > 0:
            ratio_value = _rate(audio[1]) / _rate(audio[0])
        else:
            ratio_value = audio[1]["packets"] / audio[0]["packets"] if audio[0]["packets"] else 1.0
        if both_used and ratio_value < AUDIO_DESC_RATIO:
            o["audio_desc"] = True
            ratio = int(ratio_value * 100)
            notes.append(f"→ 2本目の音声は1本目の{ratio}%のため、解説放送とみなします(language=jpn, title=解説放送)")

    # 映像より早く途切れる音声(2番組が地続きの録画で、後半に解説放送が無い等)は、
    # エンコードと同時に入れると失敗するので、最後に元のm2tsから合体する
    video_st = next((st for st in streams if st["type"] == "video"), None)
    video_end = video_st.get("last_time") if video_st else None

    def _ends_early(st: dict) -> Optional[float]:
        end = st.get("last_time")
        if video_end is None or end is None:
            return None
        gap = video_end - end
        return gap if gap > STREAM_EARLY_END_SECONDS else None


    video_first = video_st.get("first_time") if video_st else None
    if video_first is not None:
        for k in live_audio:
            first = audio[k].get("first_time")
            if first is not None and first - video_first > STREAM_EARLY_END_SECONDS:
                notes.append(f"音声 a:{k} は {_fmt_hms(first - video_first)} から始まります(本編に入ってから現れる二か国語の音声など)")

    if video_end is not None and live_audio:
        selected = list(o.get("audio_ordinals", live_audio))
        post: List[int] = []
        for k in selected[1:]:  # 1本目は本編の音声なので、そのままエンコードに入れる
            gap = _ends_early(audio[k])
            if gap is not None:
                post.append(k)
                notes.append(
                    f"音声 a:{k} は {_fmt_hms(audio[k]['last_time'])} で途切れます(映像は {_fmt_hms(video_end)} まで)"
                )
            elif video_first is not None and audio[k].get("first_time") is not None \
                    and audio[k]["first_time"] - video_first > STREAM_EARLY_END_SECONDS:
                # 途中から始まる音声も、途切れる音声と同じく、同時に入れると待ち続けて映像が溜まることがある
                post.append(k)

        if post:
            o["audio_ordinals"] = [k for k in selected if k not in post]
            o["audio_post_ordinals"] = post
            notes.append("→ 途切れる・途中から始まる音声は、エンコード後に元のm2tsから合体します(同時に入れると長い番組で失敗するため)")

    sub_early_note = ""
    if o["subs"]:
        live_subs = [k for k, st in enumerate(subs) if st["packets"] >= SUBTITLE_MIN_PACKETS]
        if subs:
            detail = ", ".join(
                f"s:{k}={st['codec']} パケット{st['packets']}個"
                + ("" if st["in_program"] else "・番組情報に宣言なし")
                for k, st in enumerate(subs)
            )
            notes.append(f"字幕 {len(subs)}本 ({detail})")
        else:
            notes.append("字幕: なし")
        if live_subs:
            o["sub_ordinals"] = live_subs
            early = [k for k in live_subs if _ends_early(subs[k]) is not None]
            video_start = video_st.get("first_time") if video_st else None

            def _sparse_gap(st: dict) -> float:
                gaps = [st.get("max_gap") or 0.0]
                if video_start is not None and st.get("first_time") is not None:
                    gaps.append(st["first_time"] - video_start)
                if video_end is not None and st.get("last_time") is not None:
                    gaps.append(video_end - st["last_time"])
                return max(gaps)

            sparse = [k for k in live_subs if _sparse_gap(subs[k]) > SUBTITLE_SPARSE_GAP_SECONDS]
            if (early or sparse) and not o.get("sub_postmux"):
                o["sub_postmux"] = True
                if early:
                    sub_early_note = (
                        f"字幕 s:{early[0]} は {_fmt_hms(subs[early[0]]['last_time'])} で途切れます"
                        f"(映像は {_fmt_hms(video_end)} まで)"
                    )
                else:
                    sub_early_note = (
                        f"字幕 s:{sparse[0]} は {_sparse_gap(subs[sparse[0]]) / 60:.0f}分以上パケットが空きます"
                        "(まばらな字幕は同時に入れるとエンコードが止まるため)"
                    )
        else:
            o["subs"] = False
            notes.append("→ 中身のある字幕が無いため、字幕は入れません(空トラック対策)")

    if auto_select:
        video = next((st for st in streams if st["type"] == "video"), None)
        fps = float(video["fps"]) if video else 0.0
        field_order = str(video["field_order"]) if video else ""
        interlaced = field_order in ("tt", "bb", "tb", "bt")
        height = video.get("height") if video else None
        # CATVの録画は、インターレースの1フィールドを1フレームとして出した「高さ半分の60p」
        # (例: 1920x540, 59.94fps, SAR 1:1)。本物の720p60などを取り違えないよう、高さも見る
        half_height = not isinstance(height, int) or height <= 576
        progressive_60 = fps >= 50.0 and not interlaced and half_height
        is_mono = len(audio) == 1 and is_mono_bilingual_channel(channel_name)
        notes.append(f"放送局: 「{channel_name or '(取得できていません)'}」")

        o["audio"] = "mono" if is_mono else "copy"
        o["catv"] = bool(progressive_60 and not is_mono)
        o["deint"] = "none" if progressive_60 else "bwdif"
        # 16:9を強制するのは、CATVの高さ半分の60p(SAR 1:1)や、HD放送のとき。
        # 720x480などのSD(4:3の放送が多い)に強制すると、横に伸びてしまうので、元の縦横比のままにする
        o["aspect"] = bool(progressive_60 or not half_height)
        if is_mono:
            o["container"] = "mp4"  # モノラル二か国語の分離は、字幕を扱わないmp4で行う
            o["subs"] = False
        else:
            # AAC以外(mp2など)の音声はmp4だと互換性が低いので、mkvにする
            o["container"] = "mkv" if (o["subs"] or non_aac) else "mp4"
        o["hvc1"] = o["container"] == "mp4"
        size = f"{video['width']}x{video['height']}" if video and video.get("width") else "?"
        notes.append(
            ("" if o["aspect"] else "SD映像のため縦横比は元のまま(16:9を強制しません) / ") + f"映像 {size} {fps:.2f}fps field_order={field_order or '不明'} → "
            + ("プログレッシブ60p(CATV扱い・インターレース解除なし)" if progressive_60
               else "インターレース扱い(bwdif)")
        )
        if is_mono:
            notes.append(f"音声1本・放送局「{channel_name}」→ モノラル二か国語として主/副に分離")
        notes.append(f"→ 出力は {str(o['container']).upper()}")
    # 後から合体するときに、元のm2tsでの位置(途中から始まる音声・字幕など)を保つための基準時刻
    start_candidates = [st.get("container_start") for st in streams if st.get("container_start") is not None]
    if not start_candidates:
        start_candidates = [st["first_time"] for st in streams if st.get("first_time") is not None]
    if start_candidates:
        o["post_ts_offset"] = float(min(start_candidates))
    if o["subs"] and o["container"] == "mkv" and o.get("sub_postmux"):
        if sub_early_note:
            notes.append(sub_early_note)
        notes.append("→ 字幕はエンコード後に元のm2tsから合体します(同時に入れると長い番組で落ちることがあるため)")
    return o, notes


def parse_framemd5(path: str) -> Tuple[Dict[int, str], float]:
    """framemd5の出力を読み、({pts: md5}, 1tickあたりの秒数) を返す"""
    frames: Dict[int, str] = {}
    tick = 0.0
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                m = _FRAMEMD5_TB_RE.match(line)
                if m and int(m.group(2)) > 0:
                    tick = int(m.group(1)) / int(m.group(2))
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue
            try:
                frames[int(parts[2])] = parts[5]
            except ValueError:
                continue
    return frames, tick


def group_times(times: List[float], gap: float) -> List[Tuple[float, float, int]]:
    """時刻の並びを、gap秒以内に続くものごとにまとめて (開始, 終了, 個数) で返す"""
    ts = sorted(times)
    groups: List[Tuple[float, float, int]] = []
    if not ts:
        return groups
    start = end = ts[0]
    count = 1
    for t in ts[1:]:
        if t - end <= gap:
            end = t
            count += 1
        else:
            groups.append((start, end, count))
            start = end = t
            count = 1
    groups.append((start, end, count))
    return groups


def compare_framemd5(sw_path: str, hw_path: str) -> dict:
    """
    ソフトウェアデコードとCUDAデコードのframemd5を比べる。
    戻り値: {"status": "ok"|"unreliable", "total": 全フレーム数, "ranges": [(開始秒, 終了秒, フレーム数)],
             "ignored_tail": 末尾で無視したフレーム数, "bad_frames": 食い違ったフレーム数}
    """
    sw, tick = parse_framemd5(sw_path)
    hw, tick_hw = parse_framemd5(hw_path)
    if tick <= 0:
        tick = tick_hw
    all_pts = sorted(set(sw) | set(hw))
    total = len(all_pts)
    if total == 0 or tick <= 0:
        return {"status": "unreliable", "total": total, "ranges": [], "ignored_tail": 0, "bad_frames": 0}
    bad = [p for p in all_pts if sw.get(p) != hw.get(p)]
    if len(bad) > _NOISE_UNRELIABLE_RATIO * total:
        return {"status": "unreliable", "total": total, "ranges": [], "ignored_tail": 0, "bad_frames": len(bad)}

    last_time = all_pts[-1] * tick
    ranges: List[Tuple[float, float, int]] = []
    ignored_tail = 0
    for start, end, count in group_times([p * tick for p in bad], _NOISE_GROUP_GAP_SECONDS):
        if start >= last_time - _NOISE_TAIL_SECONDS and count <= _NOISE_TAIL_MAX_FRAMES:
            ignored_tail += count
            continue
        ranges.append((start, end, count))
    return {
        "status": "ok",
        "total": total,
        "ranges": ranges,
        "ignored_tail": ignored_tail,
        "bad_frames": len(bad),
    }


def merge_noise_ranges(ranges: List[Tuple[float, float]], gap: float = _NOISE_NAME_MERGE_SECONDS) -> List[Tuple[float, float]]:
    """(開始秒, 終了秒) の並びを、gap秒以内に近接するものをまとめて返す"""
    merged: List[List[float]] = []
    for start, end in sorted(ranges):
        if merged and start - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


_ISSUE_END_RE = re.compile(r"〜(\d+):(\d+):(\d+(?:\.\d+)?)")


def noise_ranges_from_issues(
    issues: List[Tuple[str, int, List[Tuple[float, str]]]]
) -> List[Tuple[float, float]]:
    """診断結果(ログ解析+フレーム比較)の各項目から、怪しい (開始秒, 終了秒) を取り出す(dupは除く)"""
    ranges: List[Tuple[float, float]] = []
    for category, _count, entries in issues:
        if category in _DIAG_NON_NOISE_CATEGORIES:
            continue
        for seconds, text in entries:
            end = seconds
            m = _ISSUE_END_RE.search(text)
            if m:
                end = max(seconds, int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))
            ranges.append((seconds, end))
    return ranges


def format_noise_range(start: float, end: float) -> str:
    """(開始秒, 終了秒) を「8分51秒～27分13秒」(短ければ「8分51秒」)に整形する"""
    s = int(start)
    e = int(end + 0.999)
    if e - s < 2:
        return format_minutes_seconds(s)
    return f"{format_minutes_seconds(s)}～{format_minutes_seconds(e)}"


def build_noise_name_tag(ranges: List[Tuple[float, float]]) -> str:
    """ノイズ区間をファイル名に載せるタグ(例: 「(8分51秒～27分13秒,29分3秒ノイズ)」)にする"""
    merged = merge_noise_ranges(ranges)
    return "(" + ",".join(format_noise_range(s, e) for s, e in merged) + "ノイズ)"


def read_text_auto(path: str) -> Tuple[str, str]:
    """CSV等を読み、(本文, エンコーディング) を返す。rplsinfoのCSVはUTF-16のため、BOMで判別する"""
    with io.open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp932", errors="replace"), "cp932"


def write_noise_block_to_csv(csv_path: str, rows: List[List[str]]) -> None:
    """
    csvの末尾にノイズ検査の結果ブロックを書き足す。既に同じブロックがあれば置き換える
    (再検査・再エンコードのたびに重複しないようにするため)。元の文字コード・改行を保つ。
    """
    text = ""
    encoding = "utf-8-sig"
    if os.path.isfile(csv_path):
        text, encoding = read_text_auto(csv_path)

    newline = "\r\n" if ("\r\n" in text or not text) else "\n"
    lines = text.splitlines()
    cut = None
    for i, line in enumerate(lines):
        if line.startswith(NOISE_CSV_MARKER) or line.startswith('"' + NOISE_CSV_MARKER):
            cut = i
            break
    if cut is not None:
        lines = lines[:cut]
    while lines and not lines[-1].strip():
        lines.pop()

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator=newline)
    for row in rows:
        writer.writerow(row)

    new_text = newline.join(lines)
    if lines:
        new_text += newline + newline
    new_text += buf.getvalue()

    with io.open(csv_path, "w", encoding=encoding, newline="") as f:
        f.write(new_text)


def build_noise_csv_rows(
    result: Optional[dict],
    unavailable_reason: str,
    issues: List[Tuple[str, int, List[Tuple[float, str]]]],
    timestamp: str,
) -> List[List[str]]:
    """csvに書き足すブロックの行を組み立てる"""
    rows: List[List[str]] = []
    if result is not None and result.get("status") == "ok":
        method = (
            f"ソフトウェアデコードとCUDAデコードの全{result['total']}フレームを比較"
            f"(食い違い{result['bad_frames']}フレーム、うち末尾の切れ目{result['ignored_tail']}フレームは除外)"
        )
    elif result is not None:
        method = "フレーム比較は成り立ちませんでした(両デコーダの出力が大きく異なる)"
    else:
        method = f"フレーム比較は未実施({unavailable_reason})"
    rows.append([NOISE_CSV_MARKER, "実行日時", timestamp])
    rows.append(["方式", method])
    rows.append(["種別", "開始(秒)", "終了(秒)", "開始(時:分:秒)", "終了(時:分:秒)", "フレーム数", "内容"])

    count = 0
    if result is not None and result.get("status") == "ok":
        for start, end, frames in result["ranges"]:
            rows.append([
                "フレーム不一致(確定)", f"{start:.2f}", f"{end:.2f}",
                _seconds_to_hms(start), _seconds_to_hms(end), str(frames),
                "ソフトとCUDAでデコード結果が食い違う=この区間の画は壊れている",
            ])
            count += 1
    for category, _n, entries in issues:
        if category == _NOISE_DIFF_CATEGORY:
            continue
        for seconds, text in entries:
            end = seconds
            m = _ISSUE_END_RE.search(text)
            if m:
                end = max(seconds, int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)))
            rows.append([
                "ログ診断(参考)", f"{seconds:.2f}", f"{end:.2f}",
                _seconds_to_hms(seconds), _seconds_to_hms(end), "", f"{category} {text}",
            ])
            count += 1
    if count == 0:
        rows.append(["検査結果", "ノイズ・異常は検出されませんでした"])
    rows.append(["注", "ログ診断の時刻はffmpegの進捗表示に基づくため、実際の位置より数秒〜十数秒ずれることがあります"])
    return rows


# ---------------------------------------------------------------------------
# バッチスクリプト登録情報の読み書き
# ---------------------------------------------------------------------------

def get_app_data_dir() -> str:
    """
    設定ファイル(登録済みバッチの一覧)や、埋め込みバッチの書き出し先として使う
    専用フォルダを返す。m2tsファイルが入っている作業フォルダを汚さないよう、
    Windowsのアプリ設定用フォルダ(%LOCALAPPDATA%)配下に置く。
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    app_dir = os.path.join(base, "m2ts_encoder")
    try:
        os.makedirs(app_dir, exist_ok=True)
    except Exception:
        pass
    _migrate_old_app_data(base, app_dir)
    return app_dir


_OLD_APP_NAME = "m2ts_info_viewer"
_NEW_APP_NAME = "m2ts_encoder"
_migration_done = False


def _migrate_old_app_data(base: str, new_dir: str) -> None:
    """旧名(m2ts_info_viewer)の設定フォルダがあれば、中身を新しいフォルダへコピーする(旧フォルダは残す)。
    新しい側にすでにあるファイルは上書きしない。"""
    global _migration_done
    if _migration_done:
        return
    _migration_done = True
    old_dir = os.path.join(base, _OLD_APP_NAME)
    try:
        if not os.path.isdir(old_dir):
            return
        for name in os.listdir(old_dir):
            src = os.path.join(old_dir, name)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(new_dir, name.replace(_OLD_APP_NAME, _NEW_APP_NAME))
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
    except Exception:
        pass


def get_config_path() -> str:
    return os.path.join(get_app_data_dir(), CONFIG_FILENAME)


SETTINGS_FILENAME = "m2ts_encoder_settings.json"


def get_settings_path() -> str:
    return os.path.join(get_app_data_dir(), SETTINGS_FILENAME)


def load_settings() -> Dict[str, str]:
    path = get_settings_path()
    if not os.path.isfile(path):
        return {}
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_settings(settings: Dict[str, str]) -> None:
    path = get_settings_path()
    try:
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def find_vlc(explicit_path: Optional[str] = None) -> Optional[str]:
    """VLCの実行ファイル(vlc.exe)を探す"""
    if explicit_path and os.path.isfile(explicit_path):
        return explicit_path

    which_result = shutil.which("vlc") or shutil.which("vlc.exe")
    if which_result:
        return which_result

    candidates = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def player_seek_args(player_path: str, seconds: float) -> Optional[List[str]]:
    """再生ソフトに「この時刻から再生」と伝える引数。時刻指定に対応していないソフトはNone"""
    name = os.path.basename(player_path).lower()
    if name.startswith("vlc"):
        return [f"--start-time={seconds:.2f}"]
    if name.startswith("mpv"):
        return [f"--start={seconds:.2f}"]
    if name.startswith("mpc-hc") or name.startswith("mpc-be"):
        return ["/start", str(int(seconds * 1000))]
    if name.startswith("potplayer"):
        total = int(seconds)
        return [f"/seek={total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"]
    return None


def load_bat_scripts() -> List[Dict[str, str]]:
    path = get_config_path()
    if not os.path.isfile(path):
        return []
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if "name" in item and "path" in item]
    except Exception:
        pass
    return []


def save_bat_scripts(scripts: List[Dict[str, str]]) -> None:
    path = get_config_path()
    try:
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(scripts, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# デフォルトで同梱するエンコード用バッチ(内容をこのファイル自身に埋め込んでおき、
# 初回起動時にサブフォルダへ書き出す。これにより配布物は .pyw 1つだけで済む)
# ---------------------------------------------------------------------------


DEFAULT_BAT_SCRIPTS: Dict[str, str] = {
    "m2ts→mkv(ステレオ二か国語) CATV Dch用.bat": """echo on
:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.csv "%NAME%".csv

set "error_log_prefix=ffmpeg_error_"


ffmpeg -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" -fflags +discardcorrupt -map 0 -c copy -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc -qp 32 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -c:s copy -aspect 16:9 -buffer_size 512k %1.mkv

REM -bsf:a aac_adtstoasc 2> %error_log_prefix%%~n1.log

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.mkv "%NAME%.mkv"

REM del %1

if "%~2"=="" GOTO EXIT
shift
GOTO REPEAT
:EXIT
copy *.log matome.log
pause
""",
    "m2ts→mp4(モノラル二か国語)_CATV.bat": """echo on

:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.csv "%NAME%".csv

chcp 65001

ffmpeg -i "%1" -fflags +discardcorrupt -dn -ignore_unknown -filter_complex channelsplit[FL][FR] -ss 0 -map 0:v -map [FL] -map [FR] -map 0:a -c:v hevc_nvenc -c:a:0 aac -c:a:1 aac -c:a:2 copy -bsf:a aac_adtstoasc -ac 1 -qp 32 -tag:v hvc1 -metadata:s:a:0 title=主音声 -metadata:s:a:1 title=副音声 -metadata:s:a:2 title=主/副 -aspect 16:9 %1.mp4
REM 2> %error_log_prefix%%~n1.log 

chcp 932


for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.mp4 "%NAME%.mp4"

if "%~2"=="" GOTO EXIT
shift
GOTO REPEAT
:EXIT
copy *.log matome.log
pause
""",
    "m2ts→mp4_CATV用.bat": """echo on
:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.csv "%NAME%".csv

set "error_log_prefix=ffmpeg_error_"


ffmpeg -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" -fflags +discardcorrupt -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc -qp 32 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -aspect 16:9 -buffer_size 512k %1.mp4

REM -bsf:a aac_adtstoasc 2> %error_log_prefix%%~n1.log

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.mp4 "%NAME%.mp4"

REM del %1

if "%~2"=="" GOTO EXIT
shift
GOTO REPEAT
:EXIT
copy *.log matome.log
pause
""",
    "m2ts→mkv(ステレオ二か国語)オールマイティ.bat": """echo on
:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.csv "%NAME%".csv

set "error_log_prefix=ffmpeg_error_"


ffmpeg -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" -fflags +discardcorrupt -map 0 -c copy -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc -vf bwdif=1 -qp 32 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -c:s copy -aspect 16:9 -buffer_size 512k %1.mkv 

REM -bsf:a aac_adtstoasc 2> %error_log_prefix%%~n1.log

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.mkv "%NAME%.mkv"

REM del %1

if "%~2"=="" GOTO EXIT
shift
GOTO REPEAT
:EXIT
copy *.log matome.log
pause
""",
    "m2ts→mp4(ステレオ二か国語).bat": """echo on

:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
ffmpeg -i "%1" -fflags +discardcorrupt -map 0:v -map 0:a -ss 0 -vf bwdif=1 -c:v hevc_nvenc -qp 32 -tag:v hvc1 -c:a copy -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng %1.mp4

REM 2> %error_log_prefix%%~n1.log

REM ここでx265のmp4に変換

REM ffmpeg -i "%1" -fflags +discardcorrupt -ss 0 -map 0:0 -map 0:1 -map 0:2 -vf bwdif=1 -c:v hevc_nvenc -qp 32 -tag:v hvc1 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -aspect 16:9 %1.mkv

rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.mp4 "%NAME%.mp4"
rename %1.csv "%NAME%.csv"

REM 名前を番組名に変更

REM del %1

if "%~2"=="" GOTO EXIT
shift
GOTO REPEAT
:EXIT
copy *.log matome.log
pause
""",
    "m2ts→mp4(モノラル二か国語)_忘れずアスペクト比変える.bat": """echo on

:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.csv "%NAME%".csv

chcp 65001

ffmpeg -i "%1" -fflags +discardcorrupt -dn -ignore_unknown -filter_complex channelsplit[FL][FR] -ss 0 -map 0:v -map [FL] -map [FR] -map 0:a -vf yadif=1 -c:v hevc_nvenc -c:a:0 aac -c:a:1 aac -c:a:2 copy -bsf:a aac_adtstoasc -ac 1 -qp 32 -tag:v hvc1 -metadata:s:a:0 title=主音声 -metadata:s:a:1 title=副音声 -metadata:s:a:2 title=主/副 -aspect 16:9 %1.mp4 
REM 2> %error_log_prefix%%~n1.log 

chcp 932


for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set "NAME=%%A"
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo "%NAME%"
rename %1.mp4 "%NAME%.mp4"

if "%~2"=="" GOTO EXIT
shift
GOTO REPEAT
:EXIT
copy *.log matome.log
pause
""",
}


def _derive_embedded_batch(base_key: str, ffmpeg_line: str) -> str:
    """既存の埋め込みバッチのffmpeg行だけを差し替えた派生バッチを作る"""
    return re.sub(r"(?m)^ffmpeg .*$", lambda _m: ffmpeg_line, DEFAULT_BAT_SCRIPTS[base_key], count=1)


_VLC_VF = '-vf "hwdownload,format=nv12,bwdif=1,format=yuv420p" -color_primaries bt709 -color_trc bt709 -colorspace bt709 -color_range tv'
DEFAULT_BAT_SCRIPTS["m2ts→mkv(CUDAデコード)_ノイズ出ない時用.bat"] = _derive_embedded_batch(
    "m2ts→mkv(ステレオ二か国語) CATV Dch用.bat",
    'ffmpeg -hwaccel cuda -hwaccel_output_format cuda -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" '
    '-fflags +discardcorrupt -map 0 -c copy -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc '
    + _VLC_VF + ' -qp 32 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng '
    '-c:s copy -aspect 16:9 -buffer_size 512k %1.mkv',
)
DEFAULT_BAT_SCRIPTS["m2ts→mp4(CUDAデコード)_ノイズ出ない時用.bat"] = _derive_embedded_batch(
    "m2ts→mp4_CATV用.bat",
    'ffmpeg -hwaccel cuda -hwaccel_output_format cuda -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" '
    '-fflags +discardcorrupt -map 0:0 -map 0:1 -map 0:2 -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc '
    + _VLC_VF + ' -qp 32 -c:a copy -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng '
    '-aspect 16:9 -buffer_size 512k %1.mp4',
)

DEFAULT_BAT_SCRIPTS["m2ts→mkv(NHK_音声1本のみ).bat"] = _derive_embedded_batch(
    "m2ts→mkv(ステレオ二か国語) CATV Dch用.bat",
    'ffmpeg -i "%1" -fflags +discardcorrupt -map 0:a:0 -map 0:v -map 0:s -ss 0 -c copy -dn -ignore_unknown '
    '-max_interleave_delta 0 -c:v hevc_nvenc -vf bwdif=1 -qp 32 -c:a:1 copy -bsf:a aac_adtstoasc '
    '-metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -c:s copy -aspect 16:9 %1.mkv',
)


# 登録データの path にこのプレフィックスが付いている場合、実ファイルではなく
# 埋め込みバッチ(DEFAULT_BAT_SCRIPTS)を指す。実行時にのみ一時ファイルとして
# 書き出し、終わったら削除する(永続的なファイル生成を避けるため)。
EMBEDDED_BAT_PREFIX = "embedded:"


def register_embedded_defaults(existing: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    埋め込んである既定バッチのうち、まだ登録されていないものを
    「埋め込み実行」として登録リストに追加する。実ファイルは一切作成しない。
    既に(旧バージョンなどで)実ファイルとして登録済みのものには触れない。
    """
    # 名前を変えて無くなった埋め込みバッチの登録は外す(実行しても「見つかりません」になるため)
    updated = [
        item for item in existing
        if not (str(item.get("path", "")).startswith(EMBEDDED_BAT_PREFIX)
                and str(item["path"])[len(EMBEDDED_BAT_PREFIX):] not in DEFAULT_BAT_SCRIPTS)
    ]
    existing_names = {item["name"] for item in updated}
    for filename in DEFAULT_BAT_SCRIPTS:
        name = os.path.splitext(filename)[0]
        if name not in existing_names:
            updated.append({"name": name, "path": f"{EMBEDDED_BAT_PREFIX}{filename}"})
            existing_names.add(name)
    return updated


# ---------------------------------------------------------------------------
# チェックボックスで組み立てるエンコード設定(プリセット)
# バッチファイルを増やさず、「mkv/mp4」「CATVか否か」「モノラル二か国語/ステレオ」
# 「ARIB字幕」などを組み合わせて、ffmpegコマンドを自動生成する。
# ---------------------------------------------------------------------------
PRESET_PREFIX = "preset:"
PRESET_LABEL = "設定｜"  # 一覧で、バッチと区別するための名前の頭
BAT_LABEL = "バッチ｜"

DEFAULT_ENCODE_OPTIONS: Dict[str, object] = {
    "container": "mkv",      # "mkv" or "mp4"
    "catv": False,           # CATV向けの読み込み設定(scan_all_pmts等・interleave・buffer)
    "subs": False,           # ARIB字幕を入れる(mkvのみ)
    "audio": "copy",         # "copy"=ステレオ/二か国語をそのまま, "mono"=モノラル二か国語を主/副/主副に分離
    "deint": "none",         # "none" / "yadif" / "bwdif"
    "cuda": False,           # CUDA(GPU)でデコード(ソフトウェアデコードのノイズ回避用)
    "hvc1": False,           # mp4に hvc1 タグを付ける(Apple系で再生する場合)
    "aspect": True,          # -aspect 16:9
    "qp": 32,
    "auto_select": False,    # おまかせ: mkv/mp4・CATV・インターレース・モノラル二か国語まで、ファイルごとに全部自動で決める
    "auto": False,           # ffprobeで字幕・音声の中身を調べ、空/存在しないトラックを自動で外す
    "audio_tracks": "all",   # "all"=全音声 / "first"=1本目だけ(存在しない音声トラックでの失敗対策。NHK等)
    "sub_postmux": False,    # 字幕は、字幕なしでエンコードした後に元のm2tsから合体する(試験的。ffmpegが失敗しても終了コード0を返す場合があり、その時も合体まで進んでしまう)
}

BUILTIN_PRESETS: List[Tuple[str, Dict[str, object]]] = [
    ("おまかせ(ファイルごとに自動判定)", {"container": "mp4", "auto": True, "auto_select": True}),
    ("mkv・CATV・字幕入り(Dch)", {"container": "mkv", "catv": True, "subs": True, "auto": True}),
    ("mkv・CATV・字幕入り・bwdif(オールマイティ)",
     {"container": "mkv", "catv": True, "subs": True, "deint": "bwdif", "auto": True}),
    ("mp4・CATV", {"container": "mp4", "catv": True}),
    ("mp4・CATV・モノラル二か国語", {"container": "mp4", "audio": "mono", "hvc1": True}),
    ("mp4・モノラル二か国語・yadif",
     {"container": "mp4", "audio": "mono", "hvc1": True, "deint": "yadif"}),
    ("mp4・ステレオ二か国語・bwdif", {"container": "mp4", "hvc1": True, "deint": "bwdif", "aspect": False}),
    ("mkv・字幕入り・bwdif(NHK・存在しない音声は自動で外す)",
     {"container": "mkv", "subs": True, "deint": "bwdif", "auto": True}),
    ("mp4・CATV・CUDAデコード・bwdif(ノイズ出ない時用)",
     {"container": "mp4", "catv": True, "cuda": True, "deint": "bwdif"}),
    ("mkv・CATV・字幕入り・CUDAデコード・bwdif(ノイズ出ない時用)",
     {"container": "mkv", "catv": True, "subs": True, "cuda": True, "deint": "bwdif", "auto": True}),
]


def normalize_encode_options(options: Optional[Dict[str, object]]) -> Dict[str, object]:
    merged = dict(DEFAULT_ENCODE_OPTIONS)
    if options:
        merged.update({k: v for k, v in options.items() if k in DEFAULT_ENCODE_OPTIONS})
    # 実行時にだけ使う(ffprobe判定の結果。保存はしない)
    for key in ("audio_ordinals", "sub_ordinals", "audio_post_ordinals", "audio_non_aac"):
        if options and isinstance(options.get(key), list):
            merged[key] = list(options[key])
    if options and isinstance(options.get("post_ts_offset"), (int, float)):
        merged["post_ts_offset"] = float(options["post_ts_offset"])
    if options and options.get("wide_probe"):
        merged["wide_probe"] = True
    if options and options.get("audio_desc"):
        merged["audio_desc"] = True  # 2本目が解説放送とみなされた(ffprobe判定の結果)
    if merged["container"] not in ("mkv", "mp4"):
        merged["container"] = "mkv"
    if merged["container"] != "mkv":
        merged["subs"] = False  # mp4にはARIB字幕を入れられない
    if merged["audio"] not in ("copy", "mono"):
        merged["audio"] = "copy"
    merged["auto_select"] = bool(merged["auto_select"])
    merged["auto"] = bool(merged["auto"]) or merged["auto_select"]
    if merged["audio_tracks"] not in ("all", "first"):
        merged["audio_tracks"] = "all"
    if merged["deint"] not in ("none", "yadif", "bwdif"):
        merged["deint"] = "none"
    try:
        merged["qp"] = max(0, min(51, int(merged["qp"])))
    except (TypeError, ValueError):
        merged["qp"] = 32
    for key in ("catv", "subs", "cuda", "hvc1", "aspect", "sub_postmux"):
        merged[key] = bool(merged[key])
    return merged


# 設定から作るバッチには日本語を直接書かない。
# cmd.exeはchcp 65001の区間でUTF-8のバッチを読むと、日本語を含む行の前後で数バイトずれて
# コマンドの先頭が欠ける("ffmpeg -y" が "y" になる)ことがあるため。
# ffmpegに渡す日本語のタイトルは、環境変数(Python側からUTF-16で渡す)経由にする。
PRESET_BAT_ENV = {
    "M2TS_TITLE_DESC": "解説放送",
    "M2TS_TITLE_MAIN": "主音声",
    "M2TS_TITLE_SUB": "副音声",
    "M2TS_TITLE_BOTH": "主/副",
}


# ---------------------------------------------------------------------------
# エンコーダー(映像の圧縮に使うもの)。既定はNVIDIAのGPU(hevc_nvenc)。
# GPUが無い環境向けに、Intel(QSV)・AMD(AMF)・CPU(libx265)にも切り替えられる。
# ---------------------------------------------------------------------------
ENCODER_CHOICES: List[Tuple[str, str]] = [
    ("auto", "自動(使えるものを自動で選ぶ)"),
    ("nvenc", "NVIDIA(hevc_nvenc)"),
    ("qsv", "Intel(hevc_qsv)"),
    ("amf", "AMD(hevc_amf)"),
    ("x265", "CPU(libx265・遅い)"),
]
ENCODER_AUTO_ORDER = ("nvenc", "qsv", "amf", "x265")
_ENCODER_CODEC = {"nvenc": "hevc_nvenc", "qsv": "hevc_qsv", "amf": "hevc_amf", "x265": "libx265"}
_ENCODER_LABEL = {k: v for k, v in ENCODER_CHOICES}
_ACTIVE_ENCODER = "nvenc"  # 実際にバッチを作る時に使うエンコーダー(アプリが、設定と使える物から決めて入れる)


def set_active_encoder(name: str) -> None:
    global _ACTIVE_ENCODER
    _ACTIVE_ENCODER = name if name in _ENCODER_CODEC else "nvenc"


def get_active_encoder() -> str:
    return _ACTIVE_ENCODER


def encoder_video_args(encoder: str, qp: int) -> List[str]:
    """映像エンコーダーの指定と画質の引数。画質は、設定のQP値から各エンコーダーの目安に換算する"""
    codec = _ENCODER_CODEC.get(encoder, "hevc_nvenc")
    if encoder == "x265":
        return ["-c:v", codec, "-preset", "fast", "-crf", str(max(0, qp - 4))]
    if encoder == "qsv":
        return ["-c:v", codec, "-global_quality", str(max(1, qp - 4))]
    if encoder == "amf":
        return ["-c:v", codec, "-rc", "cqp", "-qp_i", str(qp), "-qp_p", str(qp), "-qp_b", str(qp)]
    return ["-c:v", codec, "-qp", str(qp)]


def detect_available_encoders(ffmpeg_path: str, timeout: float = 25.0) -> Dict[str, bool]:
    """各エンコーダーで、ごく短い映像を実際にエンコードしてみて、使えるかを調べる"""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result: Dict[str, bool] = {}
    for name in ENCODER_AUTO_ORDER:
        cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=0.5",
               "-frames:v", "5", "-pix_fmt", "yuv420p"] + encoder_video_args(name, 32) + ["-f", "null", "-"]
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, creationflags=flags, timeout=timeout)
            result[name] = proc.returncode == 0
        except Exception:
            result[name] = False
    return result


def resolve_encoder(choice: str, available: Optional[Dict[str, bool]]) -> str:
    """設定(自動/個別)と、使えるエンコーダーから、実際に使うものを決める"""
    if choice in _ENCODER_CODEC:
        return choice
    if available:
        for name in ENCODER_AUTO_ORDER:
            if available.get(name):
                return name
    return "nvenc"


def build_ffmpeg_command(options: Optional[Dict[str, object]], input_expr: str = '"%1"') -> Tuple[str, str]:
    """
    設定からffmpegコマンド行(cmd.exe用の文字列)と出力拡張子(".mkv"/".mp4")を作る。
    入力は input_expr(バッチ内の "%1")、出力は %1.<拡張子>。
    """
    o = normalize_encode_options(options)
    ext = "." + str(o["container"])
    # 字幕を後から合体する設定の時は、エンコードの段階では字幕を入れない
    inline_subs = bool(o["subs"]) and not o["sub_postmux"]
    encoder = get_active_encoder()
    use_cuda = bool(o["cuda"]) and encoder == "nvenc"  # CUDAデコードはNVIDIAのGPUだけ
    parts: List[str] = ["ffmpeg"]
    if use_cuda:
        parts += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    if o["catv"]:
        parts += ["-scan_all_pmts", "1", "-probesize", "500M", "-analyzeduration", "500M"]
    elif o.get("wide_probe"):
        parts += WIDE_PROBE_ARGS
    parts += ["-i", input_expr, "-fflags", "+discardcorrupt"]

    if o["audio"] == "mono":
        parts += ["-filter_complex", "channelsplit[FL][FR]",
                  "-map", "0:v", "-map", "[FL]", "-map", "[FR]", "-map", "0:a"]
    elif "audio_ordinals" in o or "sub_ordinals" in o:
        # ffprobeの判定結果にもとづき、中身のあるトラックだけを明示的に選ぶ
        parts += ["-map", "0:v"]
        if "audio_ordinals" in o:
            for k in o["audio_ordinals"]:
                parts += ["-map", f"0:a:{k}"]
        else:
            parts += ["-map", "0:a"]
        if inline_subs and o.get("sub_ordinals"):
            for k in o["sub_ordinals"]:
                parts += ["-map", f"0:s:{k}"]
            parts += ["-c", "copy"]
    elif o["audio_tracks"] == "first":
        parts += ["-map", "0:a:0", "-map", "0:v"]
        if inline_subs:
            parts += ["-map", "0:s", "-c", "copy"]
    elif inline_subs:
        parts += ["-map", "0", "-c", "copy"]
    else:
        parts += ["-map", "0:v", "-map", "0:a"]

    parts += ["-ss", "0", "-dn", "-ignore_unknown"]
    if o["catv"]:
        parts += ["-max_interleave_delta", "0"]
    else:
        # 既定は10秒。番組の途中(CM明けのミニ番組など)で映像の処理が遅れ、コピーする音声だけが先に
        # 書き込まれると、ファイルの中で音声が映像より遠く手前に置かれ、シークした後その部分が無音になる。
        # 300秒(単位はマイクロ秒)まで待って並べ替える(0=無制限だと、パケットが来ない音声があると全部をためてしまう)
        parts += ["-max_interleave_delta", "300000000"]
    parts += ["-c:v", _ENCODER_CODEC.get(encoder, "hevc_nvenc")]

    filters: List[str] = []
    if use_cuda:
        filters += ["hwdownload", "format=nv12"]
    if o["deint"] == "yadif":
        filters.append("yadif=1")
    elif o["deint"] == "bwdif":
        filters.append("bwdif=1")
    if use_cuda:
        filters.append("format=yuv420p")
    if filters:
        vf = ",".join(filters)
        parts += ["-vf", f'"{vf}"' if ("," in vf) else vf]
    if use_cuda:
        parts += ["-color_primaries", "bt709", "-color_trc", "bt709",
                  "-colorspace", "bt709", "-color_range", "tv"]

    # 画質の引数。ここでは、上で入れた "-c:v <codec>" の直後ではなく、従来どおりこの位置に置く
    quality = encoder_video_args(encoder, int(o["qp"]))[2:]
    parts += quality
    if o["container"] == "mp4" and o["hvc1"]:
        parts += ["-tag:v", "hvc1"]

    if o["audio"] == "mono":
        parts += ["-c:a:0", "aac", "-c:a:1", "aac", "-c:a:2", "copy", "-bsf:a", "aac_adtstoasc", "-ac", "1",
                  "-metadata:s:a:0", "title=%M2TS_TITLE_MAIN%", "-metadata:s:a:1", "title=%M2TS_TITLE_SUB%",
                  "-metadata:s:a:2", "title=%M2TS_TITLE_BOTH%"]
    else:
        parts += ["-c:a", "copy"]
        # aac_adtstoascはAAC専用。mp2などに付けるとffmpegが出力を作れず失敗するため、AACの音声だけに付ける
        non_aac = set(o.get("audio_non_aac", []))
        if not non_aac:
            parts += ["-bsf:a", "aac_adtstoasc"]
        else:
            selected = list(o.get("audio_ordinals", []))
            for n, k in enumerate(selected):
                if k not in non_aac:
                    parts += [f"-bsf:a:{n}", "aac_adtstoasc"]
        parts += ["-metadata:s:a:0", "language=jpn"]
        if "audio_ordinals" in o:
            single_audio = len(o["audio_ordinals"]) == 1
        else:
            single_audio = o["audio_tracks"] == "first"
        if not single_audio:
            if o.get("audio_desc"):
                # 解説放送(CM等で無音のためパケットが少ない)。英語ではなく日本語の解説音声として記録する
                parts += ["-metadata:s:a:1", "language=jpn", "-metadata:s:a:1", "title=%M2TS_TITLE_DESC%"]
            else:
                parts += ["-metadata:s:a:1", "language=eng"]
    if inline_subs and o.get("sub_ordinals", [0]):
        parts += ["-c:s", "copy"]
    if o["aspect"]:
        parts += ["-aspect", "16:9"]
    if o["catv"]:
        parts += ["-buffer_size", "512k"]
    parts.append("%1" + ext)
    return " ".join(parts), ext


def _postmux_plan(o: Dict[str, object]) -> Tuple[List[int], List[int]]:
    """最後に元のm2tsから合体する (音声の番号, 字幕の番号)。無ければ両方空。"""
    audio = [int(k) for k in o.get("audio_post_ordinals", [])] if o.get("audio_ordinals") else []
    subs: List[int] = []
    if o["subs"] and o["sub_postmux"] and o["container"] == "mkv":
        subs = list(o.get("sub_ordinals", [0]))
    return audio, subs


def build_postmux_command(options: Optional[Dict[str, object]]) -> Optional[str]:
    """
    音声・字幕を後から合体する場合の2回目のffmpegコマンド(コピーだけなので短時間で終わる)。
    エンコード済みの "%1.<拡張子>" に、元のm2ts("%1")の音声・字幕だけを足して "%1.withsub.<拡張子>" を作る。
    後付けするものが無い時はNone。
    """
    o = normalize_encode_options(options)
    audio, subs = _postmux_plan(o)
    if not audio and not subs:
        return None
    ext = "." + str(o["container"])
    parts: List[str] = ["ffmpeg", "-y", "-i", f'"%1{ext}"']
    if o["catv"]:
        # 読み込み設定は、直後の入力(元のm2ts)にだけ効く
        parts += ["-scan_all_pmts", "1", "-probesize", "500M", "-analyzeduration", "500M"]
    elif o.get("wide_probe"):
        parts += WIDE_PROBE_ARGS
    if o.get("post_ts_offset") is not None:
        # 追加する側の時刻を、元のm2tsの先頭(container start)を0として揃える。何も指定しないと、
        # 途中から始まる音声・字幕が、追加した側の先頭(0秒)に詰められてしまう
        parts += ["-copyts", "-itsoffset", f"{-float(o['post_ts_offset']):.6f}"]
    parts += ["-i", '"%1"', "-map", "0"]
    for k in audio:
        parts += ["-map", f"1:a:{k}"]
    for k in subs:
        parts += ["-map", f"1:s:{k}"]
    parts += ["-c", "copy"]
    # 1回目の出力に入っている音声の本数の次から、足した音声が並ぶ
    first_pass_audio = len(o["audio_ordinals"]) if o.get("audio_ordinals") else 1
    for i in range(len(audio)):
        n = first_pass_audio + i
        if audio[i] not in set(o.get("audio_non_aac", [])):
            parts += [f"-bsf:a:{n}", "aac_adtstoasc"]
        if o.get("audio_desc"):
            parts += [f"-metadata:s:a:{n}", "language=jpn", f"-metadata:s:a:{n}", "title=%M2TS_TITLE_DESC%"]
        else:
            parts += [f"-metadata:s:a:{n}", "language=eng"]
    parts += ["-dn", "-ignore_unknown", f'"%1.withsub{ext}"']
    return " ".join(parts)


def build_preset_batch(options: Optional[Dict[str, object]]) -> str:
    """設定から、1ファイル分を処理する一時バッチの内容を作る(後処理・リネームはPython側が行う)"""
    command, ext = build_ffmpeg_command(options)
    postmux = build_postmux_command(options)
    lines = [
        "echo on",
        'if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")',
        'rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e',
        "chcp 65001",
        command,
    ]
    if postmux:
        # ファイル名に ) 等が含まれても壊れないよう、括弧のブロックは使わずgotoで分岐する。
        # 1回目が失敗した時は2回目を行わない。2回目が失敗しても、合体前のファイルはそのまま残る。
        lines += [
            "if errorlevel 1 goto :m2ts_done",
            f'if not exist "%1{ext}" goto :m2ts_done',
            "echo [MERGE] adding audio/subtitle streams from the original m2ts",
            postmux,
            "if errorlevel 1 goto :m2ts_submux_failed",
            f'move /y "%1.withsub{ext}" "%1{ext}"',
            "goto :m2ts_done",
            ":m2ts_submux_failed",
            "echo [MERGE-FAILED] keeping the file without the merged streams",
            f'if exist "%1.withsub{ext}" del "%1.withsub{ext}"',
            ":m2ts_done",
        ]
    lines += ["chcp 932", ""]
    return "\r\n".join(lines)


def describe_encode_options(options: Optional[Dict[str, object]]) -> str:
    o = normalize_encode_options(options)
    bits = [str(o["container"]).upper()]
    bits.append("CATV" if o["catv"] else "通常")
    bits.append("モノラル二か国語を分離" if o["audio"] == "mono" else "音声そのまま")
    if o["audio_tracks"] == "first":
        bits.append("音声1本のみ")
    if o.get("audio_desc"):
        bits.append("2本目=解説放送")
    if o.get("audio_post_ordinals") and o.get("audio_ordinals"):
        bits.append("途切れる音声は最後に合体")
    if o["subs"]:
        bits.append("ARIB字幕(最後に合体)" if o["sub_postmux"] and o["container"] == "mkv" else "ARIB字幕")
    if o["auto_select"]:
        bits.append("おまかせ(全自動)")
    elif o["auto"]:
        bits.append("字幕・音声を自動判定")
    if o["deint"] != "none":
        bits.append(str(o["deint"]))
    if o["cuda"]:
        bits.append("CUDAデコード")
    return " / ".join(bits)



RUN_LOG_DIR_NAME = "ログ"
MERGED_LOG_PREFIX = "まとめ_"
RUN_LOG_KEEP_DAYS = 60                      # これより古いログは削除する
RUN_LOG_MAX_BYTES = 5 * 1024 * 1024 * 1024  # 合計がこれを超えたら古いものから削除する
_APP_START_TIME = datetime.datetime.now().timestamp()  # この起動中に作ったログは消さない


TOOLTIP_DELAY_MS = 1500  # マウスを置いてから説明が出るまでの時間(ミリ秒)

TOOLTIP_TEXTS = {
    "作品フォルダ名を入力...": "選んだ行を入れる作品フォルダの名前を手で決めます(空欄なら放送局フォルダの直下)。行をダブルクリックでも開きます。",
    "作品名の長さを指定...": "番組名の先頭から何文字を作品名にするかを数で決めます。話数や[二]は除いた名前から数えます。",
    "動かさない": "選んだ行は、今の場所のままにします。",
    "放送局の直下へ": "選んだ行を、作品フォルダではなく放送局フォルダの直下に置きます。",
    "フォルダを変更...": "m2ts / rplsを読み取るフォルダを選びます。選んだフォルダは次回の起動でも使われます。「仕分け」フォルダも、そのフォルダの下になります。",
    "このアプリのフォルダに戻す": "対象フォルダを、このアプリ(.pyw)があるフォルダに戻します。",
    "削除にする(この行)": "選んだ行を「削除」にします(実行するまでは何も削除されません)。ダブルクリックでも切り替えられます。",
    "残す(この行)": "選んだ行を「残す」にします。",
    "この組を最初の提案に戻す": "選んだ行の組を、最初の提案(1本だけ残す。長さが違う組は全部残す)に戻します。",
    "ファイルの場所を開く": "選んだ行のファイルを、エクスプローラーで開きます。",
    "実行(削除の行を削除する)": "「削除」の行の動画と、対のcsvを削除します。ごみ箱には入らず、元に戻せません。",
    "読み直す": "変換済みの一覧を読み直して、二重のものを探し直します(手で決めた内容は消えます)。",
    "1つのtxtに書き出す...": "選んだログを、1つのtxtにまとめて書き出します(見出し付き。AIや他の人に見せる時に便利です)。",
    "1件ずつ書き出す...": "選んだログを、1件ずつ別のtxtにして、選んだフォルダに書き出します。",
    "ログを読み直す": "ログの一覧を読み直します。",
    "従来の1件ずつのtxtを、まとめに取り込む": "「ログ」フォルダにある、従来の1件ずつのtxtを、まとめ_実行ログ.txt に追記して、元のtxtを削除します。",
    "自動提案に戻す": "選んだ行の移動先を、自動の提案に戻します(手で決めた内容は消えます)。",
    "手で決めた名前を、次回の自動提案に使う": "ONにすると、手で決めた作品名を覚えて、次回から同じ作品を自動でその名前に振り分けます。",
    "実行(移動する)": "緑の行を、確認のあとで作品フォルダへ移動します。mkv/mp4と対のcsvを一緒に動かします。",
    "直前の仕分けを元に戻す": "直前の1回の仕分けで動かしたファイルを、元の場所へ戻します。",
    "一覧を読み直す": "仕分けフォルダを読み直して、自動提案もやり直します(手で決めた内容は消えます)。",
    "変換済み一覧から選ぶ...": "「エンコード済み」タブと同じ一覧から、縦横比を直したいファイルを選んで追加します(複数選択OK)。",
    "ファイルを追加...": "縦横比を直したいmkv/mp4を、ファイル選択画面から追加します。",
    "元のファイルを .bak で残す": "ONにすると、直す前のファイルを「名前.mkv.bak」として残します(容量が倍になります)。OFFなら上書きします。",
    "再スキャン": "対象フォルダを調べ直して一覧を作り直します。ファイルを追加・削除したあとに押してください。",
    ".m2ts": "ONにすると .m2ts ファイルを一覧に出します。切り替えると自動で再スキャンします。",
    ".rpls": "ONにすると .rpls ファイル(レコーダーの番組情報ファイル)も一覧に出します。",
    "サブフォルダも検索する": "ONにすると、対象フォルダの中のフォルダ(「仕分け」フォルダなど)の中も探します。",
    "クリア": "絞り込み欄を空にして、全件表示に戻します。",
    "全選択": "いま表示されている行をすべて選択します。絞り込みで隠れている行は含みません。",
    "選択解除": "選択をすべて外します。",
    "このチャンネルを選択": "左で選んだチャンネルの行をまとめて選択します。(未変換のものだけ。変換済みも選ぶ場合は右のチェックをON)",
    "変換済みも含める": "「このチャンネルを選択」の対象に、変換済み(エンコード済み)のファイルも入れます。\n普段はOFFでOK。再エンコード防止のため、通常は未変換だけを選びます。",
    "選択した行に適用": "選んでいる行に、左で選んだ設定(おまかせ・プリセット)を割り当てます。\nこの時点ではエンコードは始まりません。",
    "選択行の設定を解除": "選んでいる行に割り当てた設定を取り消します。(エンコードされません)",
    "すべて解除": "割り当てた設定を、全行ぶんまとめて取り消します。",
    "設定の編集...": "エンコード設定(プリセット)の作成・編集をします。おまかせの設定もここです。",
    "エンコード開始": "設定を割り当てた行を、上から順にエンコードします。\n終わった行の設定は自動で解除されます。",
    "中断": "エンコードを止めます。実行中のファイルは途中で終了します。",
    "エンコード後にノイズ検査する": "エンコード後、元のm2tsをソフト/CUDAでデコードして比べ、ノイズの有無をCSVに記録します。\n検査が終わるまで、元のm2tsは削除できません。",
    "▼ 実行ログ": "実行ログ欄を折りたたみます。",
    "▶ 実行ログ": "実行ログ欄を開きます。",
    "一覧を更新": "エンコード済みの一覧を読み直します。",
    "選択した行をチャンネル別に仕分け": "選んでいる行を、チャンネル名のフォルダ(「仕分け」フォルダの中)へ移動します。",
    "未仕分けをすべて仕分け": "まだ仕分けされていないものを全部、チャンネル別のフォルダへ移動します。(表示中の行が対象)",
    "ARIB字幕を入れる": "ARIB字幕を字幕トラックとして入れます。mkv形式のときだけ使えます。",
    "字幕は最後に合体": "字幕だけ別の工程で後から合体します。字幕を入れると失敗する番組向けの試験的な機能です。",
    "おまかせ": "ファイルごとにffprobeで中身を調べ、音声・字幕・CATVなどを全部自動で決めます。",
    "CATVの録画": "CATV録画で必要になる読み込み設定(scan_all_pmts等)を付けます。",
    "音声は1本目だけ使う": "1本目の音声だけをエンコードします。存在しない音声で失敗する番組用です。",
    "ffprobeで調べて": "ffprobeで中身を調べて、空の字幕や存在しない音声を自動で外します。(1本あたり数十秒かかります)",
    "CUDA(GPU)でデコードする": "デコードにGPUを使います。ソフトウェアデコードで出るブロックノイズの対策になります。",
    "-aspect 16:9 を指定": "映像の縦横比を16:9に指定します。",
    "mp4に hvc1 タグを付ける": "iPhone/Macなどで再生できるよう、mp4にhvc1タグを付けます。",
    "この名前で保存": "いまの設定を、上の「名前」で保存します。",
    "保存して選択行に適用": "設定を保存して、そのまま選択中の行に割り当てます。",
    "mkv(ARIB字幕": "出力をmkvにします。ARIB字幕を字幕トラックとして入れられます。",
    "mp4": "出力をmp4にします。ARIB字幕は入れられません。iPhone/Mac等で再生する場合に向きます。",
    "ステレオ/二か国語": "音声を再エンコードせず、そのままコピーします。(ステレオ・二か国語向け)",
    "モノラル二か国語": "モノラル二か国語を、主音声/副音声/主副の3本に分けてAACで入れます。",
    "なし": "インターレース解除をしません。",
    "yadif=1": "yadifでインターレースを解除します(速いが、bwdifよりやや粗め)。",
    "bwdif=1": "bwdifでインターレースを解除します(きれい。おすすめ)。",
    "削除": "選んでいるものを削除します。",
    "閉じる": "この画面を閉じます。",
    "追加...": "新しいエンコード用バッチを追加します。",
    "編集...": "選んでいるバッチの中身を編集します。",
    "名前変更": "選んでいるバッチの名前を変えます。",
    "既定バッチを組み込み方式に戻す": "既定のバッチを、アプリ内蔵の方式(最新の自動判定付き)に戻します。",
    "既定バッチを任意のフォルダに出力": "既定のバッチを、好きなフォルダにファイルとして書き出します。",
    "テキストで保存": "この結果をテキストファイルに保存します。",
}


class Tooltip:
    """マウスを置いてしばらくすると説明を出す(ほかのソフトによくあるアレ)"""

    def __init__(self, widget, text: str, delay: int = TOOLTIP_DELAY_MS):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._job = None
        self._tip = None
        widget._tooltip = self
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._job = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._job = None

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _show(self):
        self._job = None
        if self._tip is not None:
            return
        try:
            x = self.widget.winfo_pointerx() + 14
            y = self.widget.winfo_pointery() + 18
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            try:
                tip.wm_attributes("-topmost", True)
            except tk.TclError:
                pass
            tk.Label(
                tip, text=self.text, justify=tk.LEFT, wraplength=380, background="#ffffe1",
                foreground="#000000", relief=tk.SOLID, borderwidth=1, padx=6, pady=4,
            ).pack()
            tip.update_idletasks()
            w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
            x = max(0, min(x, tip.winfo_screenwidth() - w - 4))
            if y + h > tip.winfo_screenheight() - 4:
                y = self.widget.winfo_pointery() - h - 10
            tip.wm_geometry(f"+{x}+{max(0, y)}")
            self._tip = tip
        except tk.TclError:
            self._tip = None

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


MENU_TIPS = {
    "ファイル": "再スキャンや、一覧のCSV保存、終了。",
    "ツール": "仕分け(チャンネル別・作品ごと)・ファイル名や縦横比の修正・二重エンコードや変換済みm2tsの削除など、たまに使う機能。",
    "設定": "エンコード設定とバッチファイルの管理、CUDAデコードの常時ON/OFF。",
    "ログ": "実行ログの保存・管理と、エンコード診断結果の表示。",
    "ヘルプ": "アップデートの確認、旧版のバックアップ管理、バージョン情報。",
    "再スキャン": "対象フォルダをもう一度読み直して、一覧を作り直します。",
    "一覧をCSVに保存...": "いま表示している一覧(ファイル名・番組名・放送局など)を、CSVファイルに保存します。",
    "終了": "アプリを終了します。エンコード中は、先に止めてください。",
    "仕分け": "仕分けに関する機能をまとめたメニューです(まとめて仕分け・チャンネル別・作品ごと)。",
    "まとめて仕分け(チャンネル別→作品ごと)...": "チャンネル別の仕分けを行い、終わったら続けて「作品ごとに仕分け」の画面を開きます。いつもの2段階をひと続きでできます。",
    "チャンネル別に仕分け": "変換済みのmkv/mp4と対のcsvを、「仕分け/放送局名/」のフォルダに移動します。m2tsは動かしません。",
    "ファイル名の記号を全角に修正": "古い版で ; @ $ { } ~ ` に置き換わっていた記号を、本来の全角の記号に戻します。",
    "変換済みm2tsを削除...": "変換済み(mkv/mp4がある)のm2tsだけを削除します。ごみ箱には入りません。mkv/mp4は削除しません。",
    "作品ごとに仕分け": "仕分け済みの放送局フォルダの中を、作品名のフォルダに分けます。実行前に一覧で確認でき、直前の1回は元に戻せます。",
    "縦横比を直す": "変換済みのmkv/mp4の表示の縦横比(4:3 / 16:9)だけを、再エンコードなしで書き換えます。",
    "二重にエンコードしたファイルを探して削除": "番組名・放送日・開始時刻が同じ変換済みファイルを組にして並べ、残す/削除を1本ずつ決めてまとめて削除します。",
    "エンコード設定...": "エンコードの設定(プリセット)を作る・編集する画面を開きます。",
    "バッチファイル管理...": "エンコードに使うバッチファイルを登録・編集する画面を開きます。",
    "画面下の実行ログをtxtに保存...": "画面の下に表示されている「実行ログ」(スキャン・仕分け・エンコードの途中経過など)を、そのままtxtファイルに保存します。過去のエンコードのログは「ログを管理」で扱います。",
    "ログフォルダを開く": "エンコードごとのログが保存される「ログ」フォルダを、エクスプローラーで開きます。",
    "ログを管理": "ログを一覧にして、選んだものを1つのtxtや1件ずつに書き出す・内容を見る・削除する画面を開きます。",
    "ログの保存方法": "エンコードのログの保存のしかたを選びます(1つのtxtにまとめる / 1件ずつ別のtxt)。",
    "1つのtxtにまとめて保存": "エンコードのログを、まとめ_実行ログ.txt に1件ずつ追記して保存します(ファイルが増えません)。",
    "1件ずつ別のtxtで保存": "エンコードのログを、1件ごとに別のtxtファイルにして保存します(従来の方法)。",
    "ログフォルダのtxtを1つにまとめる": "「ログ」フォルダにある個別のtxtを、見出し付きの1つのtxtにまとめて保存します。元のログは消しません。",
    "ログ(txt)を全削除": "「ログ」フォルダのtxt(まとめファイルも含む)を、すべて削除します。元に戻せません。",
    "エンコード診断結果を表示(全件)": "これまでのエンコードの診断結果(OK / 要確認)を、全件まとめて表示します。",
    "アップデートを確認": "新しい版があるか確認して、あれば更新します(今の版は自動でバックアップします)。",
    "エンコーダー(映像の圧縮に使うもの)": "映像の圧縮に使うものを選びます。「自動」は、使えるものを上から順(NVIDIA→Intel→AMD→CPU)に選びます。GPUが無い環境では、CPU(libx265)になります(遅いです)。エンコード設定(プリセット)にだけ効きます。",
    "使えるエンコーダーを調べる": "ffmpegで短い映像を実際にエンコードして、NVIDIA・Intel・AMD・CPUのどれが使えるかを調べて表示します。",
    "NVIDIA(hevc_nvenc)": "NVIDIAのGPUのハードウェアエンコード(既定)。速いです。",
    "Intel(hevc_qsv)": "Intelの内蔵GPU(Quick Sync)のハードウェアエンコード。Windowsで動作する環境のみ。",
    "AMD(hevc_amf)": "AMDのGPUのハードウェアエンコード。",
    "CPU(libx265・遅い)": "GPUを使わず、CPUだけでエンコードします。どの環境でも動きますが、遅いです。",
    "自動(使えるものを自動で選ぶ)": "使えるものを、NVIDIA→Intel→AMD→CPUの順に選びます。",
    "再生ソフトを選ぶ": "右クリックの「再生」や、診断の時刻からの再生に使うソフトを選びます。VLC・mpv・MPC-HC・PotPlayerは、時刻を指定して再生できます。他のソフトは、ファイルを開くだけになります。",
    "再生ソフトの指定を解除": "選んだ再生ソフトを解除します。VLCが入っていればVLCで、無ければWindowsの既定のアプリで開きます。",
    "常にCUDAデコードで変換": "ONにすると、おまかせ・モノラル二か国語の分離など、どのエンコード設定でもCUDA(GPU)でデコードします。VLCなどのプレーヤーでは出ないノイズが、エンコード後に出る時用です。NVIDIA製GPUが必要です。バッチファイルを直接選んだ場合は対象外です。",
    "切替のある録画は、TsSplitterで分割してから変換": "ONにすると、録画の途中で本チャンネル⇔サブチャンネルが切り替わっているファイルを見つけて、TsSplitter(番組情報とPMTの切替ごとに分割)で分けてから、エンコードします。分けたファイルは一覧の元の行の下に追加され、元のファイルは残ります。エンコードに失敗したときにも、分割して試しなおします。TsSplitter.exe は、このアプリに埋め込んであり、必要になったときに同じフォルダへ取り出します(自分で置いたものがあれば、そちらを使います)。",
    "起動時に更新を確認する": "ONにすると、起動の数秒後に新しい版を確認して、あれば更新の案内を出します。",
    "旧版のバックアップを管理": "アップデートのたびに自動で作られる旧版のバックアップを、一覧・削除・その版に戻す、ができます。",
    "メニューの説明": "メニューの全項目と、その説明を、1つの画面で読めます(絞り込みもできます)。",
    "バージョン情報": "いまのバージョンと、配布元を表示します。",
}


class MenuGuideWindow(tk.Toplevel):
    """「メニューの説明」: メニューの全項目と説明を、1つの画面で読めるようにする(絞り込みつき)"""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("メニューの説明")
        self.geometry("820x600")
        self.minsize(520, 320)
        self.filter_var = tk.StringVar()
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill=tk.X)
        ttk.Label(top, text="絞り込み:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.filter_var, width=34).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="クリア", command=lambda: self.filter_var.set("")).pack(side=tk.LEFT, padx=(4, 0))
        self.box = scrolledtext.ScrolledText(self, wrap=tk.WORD, font=("Meiryo UI", 10))
        self.box.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.box.tag_configure("head", font=("Meiryo UI", 11, "bold"), spacing1=10, spacing3=2)
        self.box.tag_configure("label", font=("Meiryo UI", 10, "bold"))
        self.box.tag_configure("tip", lmargin1=24, lmargin2=24, spacing3=4)
        self.filter_var.trace_add("write", lambda *_: self._fill())
        self._fill()

    def _items(self):
        """メニューの実際の並び順で、(メニュー名, [(項目名, 説明)…]) を作る"""
        result = []
        for name, menu in self.app._menu_groups:
            rows = []
            try:
                last = menu.index("end")
            except tk.TclError:
                last = None
            if last is not None:
                for i in range(last + 1):
                    try:
                        if menu.type(i) in ("separator", "tearoff"):
                            continue
                        label = menu.entrycget(i, "label")
                        if menu.type(i) == "cascade":
                            rows.append((label + " ▶", MENU_TIPS.get(label, "")))
                            sub = self.app.nametowidget(menu.entrycget(i, "menu"))
                            for k in range(sub.index("end") + 1):
                                if sub.type(k) in ("separator", "tearoff"):
                                    continue
                                sl = sub.entrycget(k, "label")
                                stip = MENU_TIPS.get(sl)
                                if stip is None:
                                    for key, t in MENU_TIPS.items():
                                        if len(key) >= 4 and sl.startswith(key):
                                            stip = t
                                            break
                                rows.append(("    " + sl, stip or ""))
                            continue
                    except tk.TclError:
                        continue
                    tip = MENU_TIPS.get(label)
                    if tip is None:
                        for key, t in MENU_TIPS.items():
                            if len(key) >= 4 and label.startswith(key):
                                tip = t
                                break
                    rows.append((label, tip or ""))
            result.append((name, MENU_TIPS.get(name, ""), rows))
        return result

    def _fill(self):
        terms = self.app._norm_search(self.filter_var.get()).split()
        self.box.configure(state=tk.NORMAL)
        self.box.delete("1.0", tk.END)
        for name, name_tip, rows in self._items():
            shown = [(l, t) for l, t in rows if not terms or all(x in self.app._norm_search(l + " " + t) for x in terms)]
            if not shown:
                continue
            self.box.insert(tk.END, f"【{name}】 {name_tip}\n", "head")
            for label, tip in shown:
                self.box.insert(tk.END, f"・{label}\n", "label")
                if tip:
                    self.box.insert(tk.END, f"{tip}\n", "tip")
        self.box.configure(state=tk.DISABLED)


def _tooltip_text_for(label: str) -> Optional[str]:
    label = (label or "").strip()
    if not label:
        return None
    if label in TOOLTIP_TEXTS:
        return TOOLTIP_TEXTS[label]
    for key, text in TOOLTIP_TEXTS.items():
        if len(key) >= 4 and label.startswith(key):
            return text
    return None


def attach_tooltips(root, extra: Optional[dict] = None):
    """root以下のボタン/チェック/ラジオに、TOOLTIP_TEXTSの説明を付ける(何度呼んでもOK)"""
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            stack.extend(w.winfo_children())
        except tk.TclError:
            continue
        if getattr(w, "_tip_attached", False):
            continue
        if w.winfo_class() in ("TButton", "TCheckbutton", "TRadiobutton", "Button", "Checkbutton"):
            try:
                text = _tooltip_text_for(str(w.cget("text")))
            except tk.TclError:
                text = None
            if text:
                Tooltip(w, text)
                w._tip_attached = True


class RangeSelect:
    """
    Treeviewの複数選択を、エクスプローラーと同じ動きにする。
    標準のTreeviewは、Shift+クリックの範囲の起点を「フォーカス中の行」にし、Ctrl+クリックではフォーカスを
    動かさない。そのため、キーボード(Shift+↑↓)で選択を広げたあとや、Ctrl+クリックのあとに
    Shift+クリックすると、思った起点にならなかった。ここでは起点(アンカー)を1つだけ持ち、
    マウスもキーボードも同じ起点から範囲を作る。
      ・通常クリック / Ctrl+クリック … その行が新しい起点になる
      ・Shift+クリック … 起点からクリックした行までを選択(Ctrl併用なら今の選択に追加)
      ・Shift+↑↓ … 起点からフォーカス行を1つ動かした所までを選択
    """

    PAGE = 10  # Shift+PageUp/Down で動く行数

    def __init__(self, tree):
        self.tree = tree
        self.anchor: Optional[str] = None
        tree.bind("<Button-1>", self._on_click, add="+")
        tree.bind("<Control-Button-1>", self._on_ctrl_click, add="+")
        tree.bind("<Shift-Button-1>", self._on_shift_click)
        tree.bind("<Shift-Down>", lambda e: self._extend(1))
        tree.bind("<Shift-Up>", lambda e: self._extend(-1))
        tree.bind("<Shift-Next>", lambda e: self._extend(self.PAGE))
        tree.bind("<Shift-Prior>", lambda e: self._extend(-self.PAGE))
        tree.bind("<Shift-End>", lambda e: self._extend(len(self.tree.get_children(""))))
        tree.bind("<Shift-Home>", lambda e: self._extend(-len(self.tree.get_children(""))))
        # Shiftを押さない移動キー(↑↓・Home/End・PageUp/Down)は、移動先の行が新しい起点になる
        for key in ("Up", "Down", "Home", "End", "Prior", "Next"):
            tree.bind(f"<{key}>", self._on_plain_key, add="+")

    def _valid_anchor(self, children) -> Optional[str]:
        if self.anchor in children:
            return self.anchor
        return None

    def _on_click(self, event):
        if not (event.state & 0x0001) and not (event.state & 0x0004):  # Shift=0x1, Control=0x4
            row = self.tree.identify_row(event.y)
            if row:
                self.anchor = row
        # 選択とフォーカスの移動は標準の処理に任せる

    def _on_plain_key(self, event):
        if event.state & 0x0001 or event.state & 0x0004:  # Shift / Ctrl が押されているときは対象外
            return
        # 標準の処理で選択・フォーカスが動いたあとの行を、新しい起点にする
        self.tree.after_idle(self._sync_anchor)

    def _sync_anchor(self):
        focus = self.tree.focus()
        if focus:
            self.anchor = focus

    def _on_ctrl_click(self, event):
        row = self.tree.identify_row(event.y)
        if row and not (event.state & 0x0001):
            self.anchor = row
            self.tree.focus(row)  # 標準ではCtrl+クリックでフォーカスが動かない

    def _on_shift_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return "break"
        children = self.tree.get_children("")
        anchor = self._valid_anchor(children)
        if anchor is None:
            focus = self.tree.focus()
            selection = self.tree.selection()
            anchor = focus if focus in children else (selection[0] if selection else row)
            self.anchor = anchor
        start, end = sorted((children.index(anchor), children.index(row)))
        rng = children[start:end + 1]
        if event.state & 0x0004:  # Ctrl+Shift: 今の選択に範囲を追加
            self.tree.selection_add(rng)
        else:
            self.tree.selection_set(rng)
        self.tree.focus(row)
        return "break"

    def _extend(self, direction: int):
        children = self.tree.get_children("")
        if not children:
            return "break"
        current = self.tree.focus()
        if current not in children:
            selection = self.tree.selection()
            current = selection[-1] if selection else children[0]
        anchor = self._valid_anchor(children)
        if anchor is None:
            anchor = current
            self.anchor = anchor
        idx_next = max(0, min(len(children) - 1, children.index(current) + direction))
        next_iid = children[idx_next]
        start, end = sorted((children.index(anchor), idx_next))
        self.tree.selection_set(children[start:end + 1])
        self.tree.focus(next_iid)
        self.tree.see(next_iid)
        return "break"


class MenuEntryProxy:
    """メニュー項目を、ボタンのように .state(["disabled"]) / .state(["!disabled"]) で操作するための薄いラッパー"""

    def __init__(self, menu, index: int):
        self.menu = menu
        self.index = index

    def state(self, flags):
        disabled = "disabled" in flags
        try:
            self.menu.entryconfigure(self.index, state="disabled" if disabled else "normal")
        except Exception:
            pass

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state(["disabled"] if kwargs["state"] == "disabled" else ["!disabled"])


class LogTeeQueue(queue.Queue):
    """("log", 文字列) を画面用に流しつつ、開いているログファイルにも全行そのまま書き込むキュー"""

    def __init__(self):
        super().__init__()
        self.sink = None

    def put(self, item, block=True, timeout=None):
        sink = self.sink
        if sink is not None and isinstance(item, tuple) and item and item[0] == "log":
            self.write_file(str(item[1]))
        super().put(item, block, timeout)

    def write_file(self, text: str) -> None:
        sink = self.sink
        if sink is None:
            return
        try:
            sink.write(text + "\n")
            sink.flush()
        except Exception:
            pass


APP_VERSION = "2026.11.07.10"
UPDATE_BASE_URL = "https://raw.githubusercontent.com/tatata17/m2ts-encoder/main/"
UPDATE_INFO_FILE = "version.json"
UPDATE_BACKUP_KEEP = 5


def parse_version(text: str) -> Tuple[int, ...]:
    """「2026.10.23.1」のような版番号を比較用のタプルにする。読めなければ空タプル"""
    try:
        return tuple(int(x) for x in str(text).strip().split("."))
    except ValueError:
        return ()


def _http_get(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "m2ts-encoder-updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


UPDATE_COMMIT_API = "https://api.github.com/repos/tatata17/m2ts-encoder/commits/main"


def resolve_update_base() -> str:
    """
    取得元のURLの先頭を決める。mainの最新コミットのIDを調べて、そのコミットに固定したURLにする。
    mainのままだと、公開した直後はGitHubの配信側のキャッシュで version.json と本体の版が食い違うことがある
    (同じコミットなら、2つのファイルは必ず同じ版になる)。調べられなければ、これまでどおりmainを使う。
    """
    try:
        sha = str(json.loads(_http_get(UPDATE_COMMIT_API, timeout=8.0).decode("utf-8")).get("sha", ""))
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return UPDATE_BASE_URL.replace("/main/", f"/{sha}/")
    except Exception:
        pass
    return UPDATE_BASE_URL


def fetch_update_info() -> Dict[str, object]:
    """GitHub上の version.json を取得する。失敗したら例外"""
    base = resolve_update_base()
    raw = _http_get(base + UPDATE_INFO_FILE + f"?t={int(datetime.datetime.now().timestamp())}")
    info = json.loads(raw.decode("utf-8"))
    if not isinstance(info, dict) or not parse_version(info.get("version", "")) or not info.get("file"):
        raise ValueError("version.json の形式が正しくありません")
    info["_base"] = base  # 本体も同じコミットから取る
    return info


def is_newer_version(remote: str, local: Optional[str] = None) -> bool:
    r, l = parse_version(remote), parse_version(local if local is not None else APP_VERSION)
    return bool(r) and r > l


def download_update_source(info: Dict[str, object]) -> bytes:
    """新しい版のファイルを取得し、壊れていないか確認してから返す(確認に通らなければ例外)"""
    base = str(info.get("_base") or UPDATE_BASE_URL)
    raw = _http_get(base + str(info["file"]) + f"?t={int(datetime.datetime.now().timestamp())}", timeout=60.0)
    text = raw.decode("utf-8")
    if len(raw) < 100_000:
        raise ValueError("ダウンロードしたファイルが小さすぎます(壊れている可能性があります)")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m or m.group(1) != str(info["version"]):
        raise ValueError("ダウンロードしたファイルの版番号が version.json と一致しません(少し待ってからやり直してください)")
    compile(text, "m2ts_encoder_update", "exec")  # 構文エラーがないか確認
    return raw


def update_backup_dir() -> str:
    return os.path.join(get_app_data_dir(), "backup")


def update_backup_keep() -> int:
    """アップデート時に自動で残すバックアップの本数(設定。1〜30、既定はUPDATE_BACKUP_KEEP)"""
    try:
        n = int(load_settings().get("update_backup_keep", UPDATE_BACKUP_KEEP))
    except (TypeError, ValueError):
        n = UPDATE_BACKUP_KEEP
    return max(1, min(30, n))


_BACKUP_NAME_RE = re.compile(r"m2ts_encoder_(.+)_(\d{8}-\d{6})\.pyw$")


def list_update_backups() -> List[dict]:
    """旧版のバックアップを、新しい順に返す: [{path, name, version, stamp, size}]"""
    d = update_backup_dir()
    result: List[dict] = []
    try:
        names = os.listdir(d)
    except OSError:
        return result
    for n in names:
        m = _BACKUP_NAME_RE.match(n)
        if not m:
            continue
        path = os.path.join(d, n)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        result.append({"path": path, "name": n, "version": m.group(1), "stamp": m.group(2), "size": size})
    result.sort(key=lambda b: b["stamp"], reverse=True)
    return result


def prune_update_backups(keep: Optional[int] = None) -> int:
    """バックアップを新しい順に keep 本だけ残して、あとを削除する。削除した本数を返す"""
    keep = update_backup_keep() if keep is None else keep
    removed = 0
    for b in list_update_backups()[keep:]:
        try:
            os.remove(b["path"])
            removed += 1
        except OSError:
            pass
    return removed


def install_update(raw: bytes) -> str:
    """今のスクリプトをバックアップしてから、新しい版に置き換える。バックアップのパスを返す"""
    script = os.path.abspath(__file__)
    backup_dir = os.path.join(get_app_data_dir(), "backup")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(backup_dir, f"m2ts_encoder_{APP_VERSION}_{stamp}.pyw")
    shutil.copy2(script, backup_path)
    tmp = script + ".new"
    with io.open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, script)
    prune_update_backups()
    return backup_path


def kill_process_tree(proc) -> None:
    """プロセスと、その子プロセス(バッチから起動したffmpeg等)をまとめて止める。
    Windowsでは proc.terminate() だと cmd.exe しか止まらず、ffmpegが動き続けてしまう。"""
    if proc is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
            )
        else:
            proc.terminate()
    except Exception:
        pass
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass


def get_run_log_dir() -> str:
    return os.path.join(get_script_dir(), RUN_LOG_DIR_NAME)


def prune_run_logs(log_dir: str, now: Optional[float] = None) -> None:
    """古いログを整理する。件数では消さない(何百本まとめて回しても同じ回のログは残す)"""
    now = now if now is not None else datetime.datetime.now().timestamp()
    entries = []
    try:
        for name in os.listdir(log_dir):
            if not name.lower().endswith(".txt") or name.startswith(MERGED_LOG_PREFIX):
                continue  # まとめファイルは自動削除しない
            path = os.path.join(log_dir, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, path))
    except OSError:
        return
    entries.sort()  # 古い順
    total = sum(size for _m, size, _p in entries)
    for mtime, size, path in entries:
        if mtime >= _APP_START_TIME:
            continue  # この起動中のログは消さない
        too_old = now - mtime > RUN_LOG_KEEP_DAYS * 86400
        if too_old or total > RUN_LOG_MAX_BYTES:
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass


# ----------------------------------------------------------------------
# 実行ログを「1つのtxt」にまとめて保存する仕組み
#   ログ/まとめ_実行ログ.txt に、1件分ずつ見出し付きで追記していく。あとから「ログを管理」で
#   選んで書き出す(1つにまとめて / 1件ずつ)・削除できる。従来の「1件ずつ別のtxt」にも切り替えられる。
# ----------------------------------------------------------------------
LOG_STORE_NAME = MERGED_LOG_PREFIX + "実行ログ.txt"
LOG_WORK_DIR_NAME = "_作業中"          # エンコード中のログを一時的に書く場所(終わったらまとめに追記して消す)
LOG_SECTION_MARK = "### [実行ログ] "
_LOG_SECTION_RULE = "=" * 70
_LOG_STORE_LOCK = threading.Lock()
_LOG_NAME_STAMP_RE = re.compile(r"^(\d{8})-(\d{6})_")


def get_log_mode() -> str:
    """"single"(1つのtxtにまとめる。既定) / "each"(1件ずつ別のtxt)"""
    return "each" if str(load_settings().get("log_mode", "single")) == "each" else "single"


def get_log_store_path() -> str:
    return os.path.join(get_run_log_dir(), LOG_STORE_NAME)


def log_name_to_time(name: str) -> Optional[datetime.datetime]:
    m = _LOG_NAME_STAMP_RE.match(name)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _section_header(name: str) -> bytes:
    return (f"{_LOG_SECTION_RULE}\n{LOG_SECTION_MARK}{name}\n{_LOG_SECTION_RULE}\n").encode("utf-8")


def fold_run_log_file(temp_path: str) -> bool:
    """1件分のログ(作業中のtxt)を、まとめファイルの末尾に追記して、作業中のtxtを消す。成功したらTrue"""
    try:
        with io.open(temp_path, "rb") as f:
            body = f.read()
    except OSError:
        return False
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    body = body.replace(b"\r\n", b"\n").rstrip(b"\n") + b"\n\n"
    name = os.path.basename(temp_path)
    try:
        with _LOG_STORE_LOCK:
            with io.open(get_log_store_path(), "ab") as out:
                out.write(_section_header(name) + body)
                out.flush()
        os.remove(temp_path)
        return True
    except OSError:
        return False        # 追記できなければ、作業中のtxtを残す(次の起動で、もう一度まとめる)


def fold_leftover_run_logs() -> int:
    """作業中のまま残っているログ(アプリが途中で終了した等)を、まとめに追記する。追記した件数を返す"""
    work = os.path.join(get_run_log_dir(), LOG_WORK_DIR_NAME)
    try:
        names = sorted(n for n in os.listdir(work) if n.lower().endswith(".txt"))
    except OSError:
        return 0
    return sum(1 for n in names if fold_run_log_file(os.path.join(work, n)))


def scan_log_store(path: str) -> List[dict]:
    """まとめファイルを頭から読んで、1件ごとの{name, offset, length, ...}の一覧にする(本文は読み込まない)"""
    entries: List[dict] = []
    cur: Optional[dict] = None
    try:
        with io.open(path, "rb") as f:
            offset = 0
            mark = LOG_SECTION_MARK.encode("utf-8")
            rule = _LOG_SECTION_RULE.encode("utf-8")
            prev_line_start = -1
            prev_was_rule = False
            for line in f:
                size = len(line)
                if line.startswith(mark) and prev_was_rule:
                    if cur is not None:
                        cur["length"] = prev_line_start - cur["offset"]
                    cur = {"name": line[len(mark):].decode("utf-8", "replace").strip(), "offset": prev_line_start,
                           "length": 0, "src": "", "program": "", "channel": "", "diag": "", "lines": 0, "kind": "store"}
                    entries.append(cur)
                elif cur is not None:
                    cur["lines"] += 1
                    if cur["lines"] <= 12 or line.startswith(b"# ====="):
                        _read_log_meta_line(cur, line)
                prev_was_rule = line.rstrip(b"\r\n") == rule
                prev_line_start = offset
                offset += size
            if cur is not None:
                cur["length"] = offset - cur["offset"]
    except OSError:
        pass
    return entries


def _read_log_meta_line(entry: dict, raw: bytes) -> None:
    text = raw.decode("utf-8", "replace").rstrip("\r\n")
    if text.startswith("# 番組:") and not entry["program"]:
        m = re.match(r"# 番組:\s*(.*?)\s*/\s*チャンネル:\s*(.*)$", text)
        if m:
            entry["program"], entry["channel"] = m.group(1), m.group(2)
        else:
            entry["program"] = text[len("# 番組:"):].strip()
    elif re.match(r"# \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\s+", text) and not entry["src"]:
        entry["src"] = re.sub(r"^# \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\s+", "", text)
    elif text.startswith("# ===== 診断結果:"):
        m = re.match(r"# ===== 診断結果:\s*(\S+)", text)
        if m:
            entry["diag"] = m.group(1)


def scan_legacy_logs(folder: str) -> List[dict]:
    """従来の「1件ずつ別のtxt」を、まとめファイルの一覧と同じ形にする"""
    entries: List[dict] = []
    try:
        names = os.listdir(folder)
    except OSError:
        return entries
    for n in names:
        if not n.lower().endswith(".txt") or n.startswith(MERGED_LOG_PREFIX):
            continue
        path = os.path.join(folder, n)
        try:
            size = os.path.getsize(path)
            e = {"name": n, "path": path, "offset": 0, "length": size, "src": "", "program": "", "channel": "",
                 "diag": "", "lines": 0, "kind": "legacy"}
            with io.open(path, "rb") as f:
                for i, line in enumerate(f):
                    e["lines"] = i + 1
                    if i < 12 or line.startswith(b"# ====="):
                        _read_log_meta_line(e, line)
            entries.append(e)
        except OSError:
            continue
    return entries


def read_log_entry(entry: dict, store_path: str) -> str:
    """1件分のログ本文を読む(まとめの見出し3行は含まない)"""
    try:
        if entry["kind"] == "legacy":
            with io.open(entry["path"], "rb") as f:
                data = f.read()
        else:
            with io.open(store_path, "rb") as f:
                f.seek(entry["offset"])
                data = f.read(entry["length"])
            lines = data.split(b"\n")
            data = b"\n".join(lines[3:])      # 見出し(区切り線・名前・区切り線)を除く
        return data.decode("utf-8-sig", "replace").replace("\r\n", "\n").rstrip("\n") + "\n"
    except OSError as e:
        return f"(読み込めませんでした: {e})\n"


def delete_log_entries(entries: List[dict], store_path: str) -> int:
    """選んだログを削除する(まとめの中の分は、まとめファイルを書き直す)。削除した件数を返す"""
    removed = 0
    store_cut = sorted((e["offset"], e["offset"] + e["length"]) for e in entries if e["kind"] == "store")
    for e in entries:
        if e["kind"] == "legacy":
            try:
                os.remove(e["path"])
                removed += 1
            except OSError:
                pass
    if store_cut:
        tmp = store_path + ".tmp"
        with _LOG_STORE_LOCK:
            with io.open(store_path, "rb") as src, io.open(tmp, "wb") as dst:
                pos = 0
                for a, b in store_cut:
                    if a > pos:
                        src.seek(pos)
                        _copy_range(src, dst, a - pos)
                    pos = max(pos, b)
                src.seek(pos)
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
            os.replace(tmp, store_path)
        removed += len(store_cut)
    return removed


def _copy_range(src, dst, n: int) -> None:
    while n > 0:
        chunk = src.read(min(1 << 20, n))
        if not chunk:
            break
        dst.write(chunk)
        n -= len(chunk)


def prune_log_store() -> int:
    """まとめファイルの中の、保存期間(RUN_LOG_KEEP_DAYS日)を過ぎた分と、容量を超えた分(古い順)を削除する"""
    store = get_log_store_path()
    if not os.path.isfile(store):
        return 0
    entries = scan_log_store(store)
    cutoff = datetime.datetime.now() - datetime.timedelta(days=RUN_LOG_KEEP_DAYS)
    doomed = []
    total = sum(e["length"] for e in entries)
    for e in entries:      # 古い順に並んでいる(追記しているため)
        t = log_name_to_time(e["name"])
        if (t is not None and t < cutoff) or total > RUN_LOG_MAX_BYTES:
            doomed.append(e)
            total -= e["length"]
    return delete_log_entries(doomed, store) if doomed else 0


def export_logs_merged(entries: List[dict], store_path: str, dest: str) -> int:
    """選んだログを、1つのtxtに書き出す(従来の「1つにまとめる」と同じ見出しの形)"""
    with io.open(dest, "w", encoding="utf-8", newline="\n") as out:
        for i, e in enumerate(entries, 1):
            t = log_name_to_time(e["name"])
            stamp = t.strftime("%Y-%m-%d %H:%M:%S") if t else ""
            out.write(f"{_LOG_SECTION_RULE}\n### [{i}/{len(entries)}] {e['name']}  (更新: {stamp})\n{_LOG_SECTION_RULE}\n")
            out.write(read_log_entry(e, store_path).rstrip("\n") + "\n\n")
    return len(entries)


def export_logs_each(entries: List[dict], store_path: str, folder: str) -> Tuple[int, List[str]]:
    """選んだログを、1件ずつ別のtxtで書き出す。同じ名前があれば番号を付ける"""
    done = 0
    errors: List[str] = []
    for e in entries:
        base = re.sub(r'[\\/:*?"<>|\r\n]', "_", os.path.splitext(e["name"])[0]) or "log"
        path = os.path.join(folder, base + ".txt")
        n = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"{base}({n}).txt")
            n += 1
        try:
            with io.open(path, "w", encoding="utf-8", newline="\n") as out:
                out.write(read_log_entry(e, store_path))
            done += 1
        except OSError as ex:
            errors.append(f"{e['name']}: {ex}")
    return done, errors


def import_legacy_logs(entries: List[dict]) -> int:
    """従来の1件ずつのtxtを、まとめファイルに追記して、元のtxtを消す。取り込んだ件数を返す"""
    count = 0
    for e in sorted((x for x in entries if x["kind"] == "legacy"), key=lambda x: x["name"]):
        if fold_run_log_file(e["path"]):
            count += 1
    return count


def open_run_log(m2ts_path: str):
    """エンコード1件分のログファイルを開く(失敗したらNone)。古いログは一定数を超えたら消す"""
    try:
        log_dir = get_run_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        stem = re.sub(r'[\\/:*?"<>|\r\n]', "_", os.path.splitext(os.path.basename(m2ts_path))[0])[:80]
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        if get_log_mode() == "single":
            # エンコード中は作業用のtxtに書き、終わったら「まとめ_実行ログ.txt」に追記して消す
            work = os.path.join(log_dir, LOG_WORK_DIR_NAME)
            os.makedirs(work, exist_ok=True)
            handle = io.open(os.path.join(work, f"{stamp}_{stem}.txt"), "w", encoding="utf-8", newline="\n")
            prune_run_logs(log_dir)      # 従来の1件ずつのtxtが残っていれば、期限切れを整理する
            return handle
        path = os.path.join(log_dir, f"{stamp}_{stem}.txt")
        handle = io.open(path, "w", encoding="utf-8", newline="\n")
        prune_run_logs(log_dir)
        return handle
    except Exception:
        return None


def decode_console_bytes(data: bytes) -> str:
    """
    バッチの出力1行を文字列にする。chcp 65001 の後(ffmpegやcmdのパス表示)はUTF-8、
    それ以前(rplsinfo等)はcp932なので、UTF-8として正しく読めるかで判断する。
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp932", errors="replace")


def iter_process_lines(stream):
    """子プロセスの出力を、\\r(ffmpegの進捗行)・\\n・\\r\\n のいずれでも区切って1行ずつ返す"""
    buf = b""
    while True:
        chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(1)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"\r\n|\r|\n", buf)
        buf = parts.pop()
        for part in parts:
            yield decode_console_bytes(part)
    if buf:
        yield decode_console_bytes(buf)


# ----------------------------------------------------------------------
# 本チャンネル⇔サブチャンネルの切替がある録画の検出と、TsSplitterによる分割
# (録画の途中でサービスやPMTが変わると、ffmpegが正しく扱えずに失敗することがある)
# ----------------------------------------------------------------------
_TS_VIDEO_STREAM_TYPES = (0x01, 0x02, 0x1B, 0x24)
SPLIT_JUNK_SECONDS = 5.0         # TsSplitterで分けたファイルが、これ以下の長さならゴミとして削除する
_TS_SAMPLE_COUNT = 24            # ファイルのこの数の地点を調べる
_TS_SAMPLE_PACKETS = 8000        # 1地点あたりに読むパケット数(約1.5MB)


def _ts_sync_offset(buf: bytes) -> Optional[int]:
    """188バイト間隔で 0x47 が並ぶ先頭位置を返す(なければ None)"""
    for i in range(min(188, max(0, len(buf) - 376))):
        if buf[i] == 0x47 and buf[i + 188] == 0x47 and buf[i + 376] == 0x47:
            return i
    return None


def _ts_iter_sections(buf: bytes, offset: int, want) -> "Iterator[Tuple[int, bytes]]":
    """TSパケット列から、want(pid) が真のPIDのセクション(PAT/PMT等)を取り出す"""
    pending: Dict[int, bytearray] = {}
    for i in range(offset, len(buf) - 187, 188):
        if buf[i] != 0x47:
            continue
        b1 = buf[i + 1]
        pid = ((b1 & 0x1F) << 8) | buf[i + 2]
        if not want(pid):
            continue
        afc = (buf[i + 3] >> 4) & 3
        if not afc & 1:
            continue
        p = i + 4
        if afc & 2:
            p += 1 + buf[i + 4]
        if p >= i + 188:
            continue
        if b1 & 0x40:  # セクションの先頭
            start = p + 1 + buf[p]
            if start >= i + 188:
                pending.pop(pid, None)
                continue
            pending[pid] = bytearray(buf[start:i + 188])
        else:
            data = pending.get(pid)
            if data is None:
                continue
            data += buf[p:i + 188]
        data = pending.get(pid)
        if data is not None and len(data) >= 3:
            need = 3 + (((data[1] & 0x0F) << 8) | data[2])
            if len(data) >= need:
                yield pid, bytes(data[:need])
                pending.pop(pid, None)


def parse_ts_programs(buf: bytes) -> Dict[int, Tuple[int, ...]]:
    """TSの断片から {番組番号(サービス): 映像PIDの組} を読み取る(PAT→PMTの順に解釈)"""
    off = _ts_sync_offset(buf)
    if off is None:
        return {}
    pmt_pids: Dict[int, int] = {}
    for _pid, sec in _ts_iter_sections(buf, off, lambda pid: pid == 0):
        if sec[0] != 0x00 or len(sec) < 12:
            continue
        for k in range(8, len(sec) - 4 - 3, 4):
            number = (sec[k] << 8) | sec[k + 1]
            pid = ((sec[k + 2] & 0x1F) << 8) | sec[k + 3]
            if number != 0:
                pmt_pids[pid] = number
    programs: Dict[int, Tuple[int, ...]] = {}
    for pid, sec in _ts_iter_sections(buf, off, lambda pid: pid in pmt_pids):
        if sec[0] != 0x02 or len(sec) < 16:
            continue
        number = (sec[3] << 8) | sec[4]
        pos = 12 + (((sec[10] & 0x0F) << 8) | sec[11])
        videos = []
        while pos + 5 <= len(sec) - 4:
            stype = sec[pos]
            epid = ((sec[pos + 1] & 0x1F) << 8) | sec[pos + 2]
            if stype in _TS_VIDEO_STREAM_TYPES:
                videos.append(epid)
            pos += 5 + (((sec[pos + 3] & 0x0F) << 8) | sec[pos + 4])
        if videos:
            programs[number] = tuple(sorted(videos))
    return programs


def detect_ts_service_change(path: str) -> Tuple[bool, str]:
    """
    ファイルの複数の地点でPAT/PMTを調べ、録画の途中で「サービス(本チャンネル/サブチャンネル)」や
    映像PIDが切り替わっていないかを判定する。(切り替わっていれば True と、その説明)
    ファイル全体は読まず、離れた地点だけを調べる(短い切替は見逃すことがある)。
    """
    try:
        size = os.path.getsize(path)
        chunk = 188 * _TS_SAMPLE_PACKETS
        if size <= chunk * 2:
            offsets = [0]
        else:
            offsets = [(size - chunk) * k // (_TS_SAMPLE_COUNT - 1) for k in range(_TS_SAMPLE_COUNT)]
        samples: List[Tuple[float, Dict[int, Tuple[int, ...]]]] = []
        with open(path, "rb") as f:
            for off in offsets:
                f.seek(off)
                progs = parse_ts_programs(f.read(chunk))
                if progs:
                    samples.append((off * 100.0 / max(size, 1), progs))
    except OSError:
        return False, ""
    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            (pa, a), (pb, b) = samples[i], samples[j]
            common = set(a) & set(b)
            if not common:
                return True, (f"ファイルの{pa:.0f}%付近と{pb:.0f}%付近で、サービスが違います"
                              f"(番組番号 {sorted(a)} → {sorted(b)})")
            for number in sorted(common):
                if a[number] != b[number]:
                    return True, (f"ファイルの{pa:.0f}%付近と{pb:.0f}%付近で、映像のPIDが変わっています"
                                  f"(番組番号 {number}: {list(a[number])} → {list(b[number])})")
    return False, ""


def _split_piece_sort_key(path: str) -> Tuple[str, int, str]:
    """分けたファイルの並び順。「元の名前_HD」「_HD-1」「_HD-2」…の順(「-10」が「-2」より前にならないように数値で比べる)"""
    name = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"_([A-Za-z0-9()]+?)(?:-(\d+))?$", name)
    if not m:
        return (name, 0, name)
    return (m.group(1), int(m.group(2) or 0), name)


_HEAD_SCAN_BYTES = 16 * 1024 * 1024   # 先頭のこの量だけ調べる
_HEAD_RESET_MIN_SECONDS = 0.5         # 映像の時刻がこれ以上巻き戻ったら、先頭に別の映像が混ざっているとみなす


def _pes_timestamp(pkt_payload: bytes) -> Optional[int]:
    """PESパケットの先頭から、DTS(なければPTS)を90kHz単位で返す"""
    if len(pkt_payload) < 19 or pkt_payload[0:3] != b"\x00\x00\x01":
        return None
    flags = pkt_payload[7] >> 6
    def read33(b: bytes) -> int:
        return (((b[0] >> 1) & 0x07) << 30) | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)
    if flags == 3:
        return read33(pkt_payload[14:19])
    if flags == 2:
        return read33(pkt_payload[9:14])
    return None


def _ts_video_pids(buf: bytes, off: int) -> Dict[int, Tuple[int, ...]]:
    return parse_ts_programs(buf)


def detect_head_timestamp_reset(path: str) -> Tuple[bool, str]:
    """
    ファイルの先頭で、映像の時刻(DTS)が大きく巻き戻っていないかを調べる。
    録画の頭に、前の番組や別のサービスの短い映像(ゴミ)が混ざっていると、
    その終わりで時刻が巻き戻る。サービスもPIDも同じままのことがあり、PMTを見るだけでは分からない。
    """
    try:
        with open(path, "rb") as f:
            buf = f.read(_HEAD_SCAN_BYTES)
    except OSError:
        return False, ""
    off = _ts_sync_offset(buf)
    if off is None:
        return False, ""
    video_pids = {pid for vids in _ts_video_pids(buf, off).values() for pid in vids}
    if not video_pids:
        return False, ""
    prev: Optional[int] = None
    frames = 0
    for i in range(off, len(buf) - 187, 188):
        if buf[i] != 0x47 or not (buf[i + 1] & 0x40):
            continue
        pid = ((buf[i + 1] & 0x1F) << 8) | buf[i + 2]
        if pid not in video_pids:
            continue
        afc = (buf[i + 3] >> 4) & 3
        if not afc & 1:
            continue
        p = i + 4 + (1 + buf[i + 4] if afc & 2 else 0)
        ts = _pes_timestamp(buf[p:i + 188])
        if ts is None:
            continue
        frames += 1
        if prev is not None:
            back = prev - ts
            if _HEAD_RESET_MIN_SECONDS * 90000 <= back < 3600 * 90000:
                return True, (f"ファイルの先頭から約{frames}フレーム目で、映像の時刻が{back / 90000:.1f}秒巻き戻っています"
                              f"(先頭に別の映像が混ざっている可能性があります)")
        prev = ts
    return False, ""


def probe_video_signature(path: str) -> Optional[Tuple[int, int, str]]:
    """映像の(幅, 高さ, フレームレート)をffprobeで読む。読めなければ None"""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,r_frame_rate", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30, creationflags=flags,
        ).stdout.strip().splitlines()
        if not out:
            return None
        width, height, rate = out[0].split(",")[:3]
        return int(width), int(height), rate
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def merge_split_pieces(pieces: List[str], log=None) -> List[str]:
    """
    TsSplitterで分けたファイルのうち、「同じ種類(_HD同士など)で番号が続いていて、映像の解像度が同じ」ものを、
    1本につなぎ直す(番組情報の切替で、本編と次回予告が別のファイルに分かれてしまうため)。
    TSは、ファイルを順に連結するだけでつなげられる。つないだ先のファイルのパス一覧を返す。
    """
    groups: List[dict] = []
    for piece in pieces:
        tag = _split_piece_sort_key(piece)[0]
        sig = probe_video_signature(piece)
        if groups and sig is not None and groups[-1]["sig"] == sig and groups[-1]["tag"] == tag:
            groups[-1]["files"].append(piece)
        else:
            groups.append({"tag": tag, "sig": sig, "files": [piece]})
    result: List[str] = []
    for g in groups:
        files = g["files"]
        first = files[0]
        if len(files) > 1:
            try:
                original_size = os.path.getsize(first)
                with open(first, "ab") as out:
                    try:
                        for extra in files[1:]:
                            with open(extra, "rb") as src:
                                shutil.copyfileobj(src, out, 1 << 20)
                    except OSError:
                        out.truncate(original_size)  # 失敗したら、つなぐ前の状態に戻す
                        raise
            except OSError as e:
                if log:
                    log(f"[分割] ファイルをつなげませんでした({e})。つなげずに、別々にエンコードします")
                result.extend(files)
                continue
            for extra in files[1:]:
                try:
                    os.remove(extra)
                except OSError:
                    pass
            if log:
                names = "・".join(os.path.basename(f) for f in files)
                w, h, _ = g["sig"]
                log(f"[分割] {names} は、映像の大きさが同じ({w}x{h})ため、1本につなぎ直しました: {os.path.basename(first)}")
        result.append(first)
    return result


def _tssplitter_once(exe: str, path: str, out_dir: Optional[str], on_line, should_stop) -> Tuple[List[str], str]:
    """TsSplitterを1回実行する。out_dir が None なら元と同じフォルダに出力する。戻り値: (できたファイル, エラーの行)"""
    folder = os.path.dirname(path) or "."
    stem = os.path.splitext(os.path.basename(path))[0]
    src_ext = os.path.splitext(path)[1]
    dest_dir = out_dir or folder
    started = time.time() - 2
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    # TsSplitterGUI で実際に分割できた設定(番組情報及びPMTで分割・ワンセグは出力しない)と同じ呼び方にする。
    # 番組情報(-EIT)は残さない: 分けたファイルの名前などは元のファイルの情報を使うため、不要
    cmd = [exe, "-1SEG", "-SEP2"] + (["-OUT", out_dir] if out_dir else []) + [path]
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except OSError as e:
        return [], f"TsSplitterを起動できませんでした({e})"
    error_line = ""
    try:
        for line in iter_process_lines(proc.stdout):
            if line.strip():
                if line.lstrip().lower().startswith("error"):
                    error_line = line.strip()
                if on_line:
                    on_line(line)
            if should_stop and should_stop():
                kill_process_tree(proc)
                break
    finally:
        proc.wait()
    if should_stop and should_stop():
        return [], "中断しました"
    pieces: List[str] = []
    try:
        names = sorted(os.listdir(dest_dir))
    except OSError as e:
        return [], f"フォルダを読めませんでした({e})"
    for name in names:
        low = name.lower()
        # 出力は「元の名前_HD」「元の名前_SD1」など(拡張子は入力と同じ。念のため .ts も拾う)
        if not (low.endswith(src_ext.lower()) or low.endswith(".ts")) or not name.startswith(stem + "_"):
            continue
        full = os.path.join(dest_dir, name)
        if os.path.abspath(full) == os.path.abspath(path) or not os.path.isfile(full):
            continue
        try:
            if os.path.getmtime(full) < started:
                continue
        except OSError:
            continue
        pieces.append(full)
    pieces.sort(key=_split_piece_sort_key)
    if error_line and not pieces:
        return [], error_line
    if proc.returncode not in (0, None) and not pieces:
        return [], f"TsSplitterが失敗しました(code {proc.returncode})"
    return pieces, ""


def run_tssplitter(exe: str, path: str, on_line=None, should_stop=None) -> Tuple[List[str], str]:
    """
    TsSplitter で、番組情報とPMTの切替ごとに分割する(1segは出力しない)。
    分割後のファイルは、元と同じフォルダに「元の名前_HD.m2ts」などの名前でできる。
    出力ファイルを作れなかったとき(日本語のフォルダ名などが原因のことがある)は、半角英数字の
    一時フォルダに出力してから、元のフォルダへ移す方法でやりなおす。
    戻り値: (分割後のファイルのパス一覧, エラーの説明。正常なら空文字)
    """
    pieces, error = _tssplitter_once(exe, path, None, on_line, should_stop)
    if not error or "failed on open" not in error:
        return pieces, error
    if on_line:
        on_line("(出力ファイルを作れなかったため、一時フォルダに出力する方法でやりなおします)")
    tmp_root = tempfile.gettempdir()
    try:
        tmp_root.encode("ascii")
    except UnicodeEncodeError:
        tmp_root = os.environ.get("SystemDrive", "C:") + os.sep
    tmp_dir = tempfile.mkdtemp(prefix="m2ts_split_", dir=tmp_root)
    moved: List[str] = []
    try:
        pieces, error = _tssplitter_once(exe, path, tmp_dir, on_line, should_stop)
        if error:
            return [], error
        folder = os.path.dirname(path) or "."
        for piece in pieces:
            dest = os.path.join(folder, os.path.basename(piece))
            try:
                shutil.move(piece, dest)
                moved.append(dest)
            except OSError as e:
                return [], f"分割したファイルを元のフォルダへ移せませんでした({e})"
        return moved, ""
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ----------------------------------------------------------------------
# 作品ごとの仕分け(「仕分け/放送局名/」の中に、作品名のフォルダを作る)
# ----------------------------------------------------------------------
_SERIES_TAG = r"(?:\[[^\[\]]{1,4}\]|【[^【】]{1,4}】|＜[^＜＞]{1,4}＞|\([^()]{1,3}\)|（[^（）]{1,3}）)"
_SERIES_TRAIL_TAGS_RE = re.compile(r"(?:\s*" + _SERIES_TAG + r")+\s*$")
_SERIES_LEAD_TAG_RE = re.compile(r"^\s*(?:\[[^\[\]]+\]|【[^【】]+】)\s*")
_SERIES_EPISODE_RES = [
    re.compile(r"\s*[#＃♯]\s*[0-9０-９]+.*$"),
    re.compile(r"\s*第\s*[0-9０-９一二三四五六七八九十百]+\s*[話回夜章幕].*$"),
    re.compile(r"\s*[0-9０-９]+\s*[話回]\b.*$"),
]
_SERIES_STRIP_CHARS = " 　-－―~〜・:：,、。.…"


def clean_program_title(program: str) -> str:
    """番組名から、先頭の[特集名]、末尾の[二][字]などの記号、話数(#24 / 第3話)を外す"""
    text = (program or "").strip()
    for _ in range(4):  # [HV]【先行放送】のように、先頭に記号が続く場合は全部外す
        lead = _SERIES_LEAD_TAG_RE.match(text)
        if not (lead and text[lead.end():].strip()):
            break
        text = text[lead.end():]
    for _ in range(4):
        before = text
        text = _SERIES_TRAIL_TAGS_RE.sub("", text)
        for pattern in _SERIES_EPISODE_RES:
            cut = pattern.sub("", text)
            if cut.strip():
                text = cut
        text = text.strip(_SERIES_STRIP_CHARS)
        if text == before:
            break
    return text.strip(_SERIES_STRIP_CHARS) or (program or "").strip()


def suggest_series_name(program: str) -> str:
    """作品名の提案。話数などを外した名前の、最初の空白までを作品名とみなす(空白が無ければ全体)"""
    base = clean_program_title(program)
    parts = re.split(r"[ 　]+", base, maxsplit=1)
    first = parts[0].strip(_SERIES_STRIP_CHARS)
    return first if len(first) >= 2 else base


def _title_words(program: str) -> List[str]:
    return [w for w in re.split(r"[ 　]+", clean_program_title(program)) if w]


def suggest_series_names_bulk(programs_by_key: Dict[str, str], min_ratio: float = 0.5) -> Dict[str, str]:
    """
    同じ放送局の番組名どうしを見比べて、作品名を決める(キー→作品名)。
    番組名を空白で区切った「先頭からの単語の並び」を候補にし、最初の単語を共有する仲間のうち
    min_ratio 以上(かつ2本以上)が共通して持っている、いちばん長い並びを作品名にする。
    例: 「うさぎの旅 ふしぎ島 ＃25[二]」×10本 → 「うさぎの旅 ふしぎ島」。
    サブタイトル付きの回(「○○ 特別編」だけ2本など)は、細かく割れずに共通の短い名前へ寄る。
    """
    words = {k: _title_words(v) for k, v in programs_by_key.items()}
    prefix_count: Dict[Tuple[str, ...], int] = {}
    for w in words.values():
        for n in range(1, len(w) + 1):
            pk = tuple(series_key(x) for x in w[:n])
            prefix_count[pk] = prefix_count.get(pk, 0) + 1
    out: Dict[str, str] = {}
    for k, w in words.items():
        if not w:
            out[k] = programs_by_key[k]
            continue
        # 先頭が1文字だけの場合(「あ」など)は、次の単語まで含めて最小の候補にする
        start = 1
        while start < len(w) and len(w[start - 1]) < 2:
            start += 1
        head = prefix_count[tuple(series_key(x) for x in w[:start])]
        need = max(2, int(head * min_ratio + 0.999))
        best = start
        for n in range(start, len(w) + 1):
            if prefix_count[tuple(series_key(x) for x in w[:n])] >= need:
                best = n
        out[k] = " ".join(w[:best]).strip(_SERIES_STRIP_CHARS) or programs_by_key[k]
    return out


def series_key(name: str) -> str:
    """作品名の比較用キー(全角/半角・大文字小文字・ひらがな/カタカナ・空白の違いを無視)"""
    folded = unicodedata.normalize("NFKC", name or "").casefold()
    folded = "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in folded)
    return re.sub(r"\s+", "", folded)


def series_folder_name(name: str) -> str:
    """作品名をフォルダ名にする(禁止文字は全角に。末尾の空白・ドットは取る)"""
    return sanitize_title_for_filename((name or "").strip()).strip().rstrip(". ")


def apply_series_rules(program: str, rules: Dict[str, str]) -> Optional[str]:
    """覚えさせた規則(作品名の先頭が一致 → フォルダ名)に合うものがあれば、そのフォルダ名を返す(長い規則を優先)"""
    base_key = series_key(clean_program_title(program))
    best = ""
    for key in rules:
        if key and base_key.startswith(key) and len(key) > len(best):
            best = key
    return rules[best] if best else None


def title_from_video_name(path: str) -> str:
    """csvが無いときの番組名: ファイル名から ",20131123" の日付と拡張子を外したもの"""
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r",\d{8}(?:\(\d+\))?$", "", stem)


def scan_series_items(root: str) -> List[dict]:
    """
    仕分けフォルダ(root)の「放送局フォルダ」の中にある mkv/mp4 を一覧にする。
    戻り値の各要素: path / channel(放送局フォルダ名) / cur_series(今いる作品フォルダ名。放送局直下なら空) /
    where(rootからの相対位置) / program(番組名) / file
    仕分けフォルダ直下(放送局フォルダの外)にあるものは対象外。
    """
    items: List[dict] = []
    if not os.path.isdir(root):
        return items
    for path in list_sorted_videos(root):
        parts = os.path.relpath(path, root).split(os.sep)
        if len(parts) < 2:
            continue
        csv_path = os.path.splitext(path)[0] + ".csv"
        program = ""
        if os.path.isfile(csv_path):
            program = read_program_info_from_sidecar_csv(csv_path)[0]
        items.append({
            "path": path, "channel": parts[0],
            "cur_series": parts[1] if len(parts) >= 3 else "",
            "deep": len(parts) > 3,
            "where": os.sep.join(parts[:-1]),
            "program": program or title_from_video_name(path),
            "file": parts[-1],
        })
    return items


def suggest_series_destinations(items: List[dict], rules: Dict[str, str]) -> Dict[str, Optional[str]]:
    """
    各ファイル(path)の作品フォルダの自動提案。None=動かさない、""=放送局直下、文字列=その作品フォルダへ。
    同じ放送局で同じ作品名が2本以上あるものだけ作品フォルダを提案する(1本だけは動かさない)。
    覚えさせた規則に合うものは、本数に関わらずその名前にする。
    """
    cands: Dict[str, str] = {}
    counts: Dict[Tuple[str, str], int] = {}
    ruled: set = set()
    by_channel: Dict[str, Dict[str, str]] = {}
    for it in items:
        by_channel.setdefault(it["channel"], {})[it["path"]] = it["program"]
    bulk: Dict[str, str] = {}
    for progs in by_channel.values():
        bulk.update(suggest_series_names_bulk(progs))
    for it in items:
        rule = apply_series_rules(it["program"], rules)
        name = rule if rule else bulk.get(it["path"]) or suggest_series_name(it["program"])
        cands[it["path"]] = name
        if rule:
            ruled.add(it["path"])
        key = (it["channel"], series_key(name))
        counts[key] = counts.get(key, 0) + 1
    result: Dict[str, Optional[str]] = {}
    for it in items:
        name = cands[it["path"]]
        if it["path"] in ruled or counts[(it["channel"], series_key(name))] >= 2:
            result[it["path"]] = series_folder_name(name) or None
        else:
            result[it["path"]] = None
    return result


def resolve_series_target_dir(root: str, channel: str, series: str) -> str:
    """作品フォルダの実際のパス。放送局フォルダの中に、全角/半角などの違いだけの同じ作品フォルダがあれば、それを使う"""
    channel_dir = os.path.join(root, channel)
    if not series:
        return channel_dir
    try:
        for name in os.listdir(channel_dir):
            if os.path.isdir(os.path.join(channel_dir, name)) and series_key(name) == series_key(series):
                return os.path.join(channel_dir, name)
    except OSError:
        pass
    return os.path.join(channel_dir, series)


SERIES_UNDO_FILENAME = "series_sort_undo.json"


def get_series_undo_path() -> str:
    return os.path.join(get_app_data_dir(), SERIES_UNDO_FILENAME)


def execute_series_moves(plan: List[Tuple[str, str]], progress=None) -> Tuple[List[dict], List[str]]:
    """
    plan: [(動画のパス, 移動先フォルダ)]。動画と同名のcsvを一緒に動かす。
    移動先に同名のファイルがあるときは、上書きせずにその1本を止める。
    戻り値: (動かした記録[{video_from, video_to, csv_from, csv_to}], エラー文のリスト)
    """
    moved: List[dict] = []
    errors: List[str] = []
    for index, (video, dest_dir) in enumerate(plan, 1):
        try:
            stem, ext = os.path.splitext(os.path.basename(video))
            csv_from = os.path.join(os.path.dirname(video), stem + ".csv")
            video_to = os.path.join(dest_dir, stem + ext)
            csv_to = os.path.join(dest_dir, stem + ".csv")
            if os.path.exists(video_to) or (os.path.isfile(csv_from) and os.path.exists(csv_to)):
                errors.append(f"{os.path.basename(video)}: 移動先に同名のファイルがあるため動かしませんでした")
                continue
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(video, video_to)
            record = {"video_from": video, "video_to": video_to, "csv_from": "", "csv_to": ""}
            if os.path.isfile(csv_from):
                try:
                    shutil.move(csv_from, csv_to)
                    record["csv_from"], record["csv_to"] = csv_from, csv_to
                except OSError as e:
                    errors.append(f"{stem}.csv: {e}")
            moved.append(record)
        except Exception as e:
            errors.append(f"{os.path.basename(video)}: {e}")
        if progress:
            progress(index, len(plan))
    return moved, errors


def save_series_undo(moved: List[dict]) -> None:
    try:
        with io.open(get_series_undo_path(), "w", encoding="utf-8") as f:
            json.dump({"moves": moved}, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def load_series_undo() -> List[dict]:
    try:
        with io.open(get_series_undo_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return [m for m in data.get("moves", []) if isinstance(m, dict)]
    except Exception:
        return []


def clear_series_undo() -> None:
    try:
        os.remove(get_series_undo_path())
    except OSError:
        pass


def undo_series_moves(moved: List[dict], root: str) -> Tuple[int, List[str]]:
    """記録を逆順にたどって、動画とcsvを元の場所へ戻す。戻せなかった1本は飛ばして、エラー文を返す。
    動かした先の作品フォルダが空になったら削除する(放送局フォルダ・仕分けフォルダ本体は消さない)。"""
    restored = 0
    errors: List[str] = []
    emptied: set = set()
    for rec in reversed(moved):
        try:
            vt, vf = rec["video_to"], rec["video_from"]
            if not os.path.isfile(vt):
                errors.append(f"{os.path.basename(vt)}: 動かした先に見つかりません")
                continue
            if os.path.exists(vf):
                errors.append(f"{os.path.basename(vf)}: 元の場所に同名のファイルがあるため戻せません")
                continue
            os.makedirs(os.path.dirname(vf), exist_ok=True)
            shutil.move(vt, vf)
            emptied.add(os.path.dirname(vt))
            if rec.get("csv_to") and os.path.isfile(rec["csv_to"]) and not os.path.exists(rec["csv_from"]):
                shutil.move(rec["csv_to"], rec["csv_from"])
            restored += 1
        except Exception as e:
            errors.append(f"{os.path.basename(rec.get('video_to', '?'))}: {e}")
    root_norm = os.path.normcase(os.path.abspath(root))
    for d in emptied:
        d_norm = os.path.normcase(os.path.abspath(d))
        depth = len(os.path.relpath(d_norm, root_norm).split(os.sep)) if d_norm.startswith(root_norm + os.sep) else 0
        if depth >= 2:  # 放送局フォルダより深い(=作品フォルダ)だけ
            try:
                if not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass
    return restored, errors


def probe_video_aspect(path: str) -> Tuple[str, str]:
    """mkv/mp4の映像の (サイズ文字列, 表示アスペクト比) をffprobeで調べる。分からなければ空文字"""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return "", ""
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=width,height,sample_aspect_ratio,display_aspect_ratio", "-of", "json", path]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        out = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=60, creationflags=flags).stdout.decode("utf-8", errors="replace")
        st = (json.loads(out).get("streams") or [{}])[0]
    except Exception:
        return "", ""
    size = f"{st.get('width', '?')}x{st.get('height', '?')}"
    dar = str(st.get("display_aspect_ratio") or "")
    if not dar or dar in ("0:1", "N/A"):
        try:
            w, h = int(st["width"]), int(st["height"])
            sn, sd = [int(x) for x in str(st.get("sample_aspect_ratio") or "1:1").split(":")]
            from math import gcd
            a, b = w * sn, h * sd
            g = gcd(a, b) or 1
            dar = f"{a // g}:{b // g}"
        except Exception:
            dar = ""
    return size, dar


class AspectFixWindow(tk.Toplevel):
    """
    変換済みのmkv/mp4の縦横比(表示アスペクト比)だけを、再エンコードせずに書き換える。
    ffmpegの -c copy で作り直す(映像・音声はそのまま。短時間で終わる)。
    追加方法: 変換済み一覧から選ぶ / ファイルを選ぶ / ドラッグ&ドロップ(tkinterdnd2があれば)
    """

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("縦横比を直す(再エンコードなし)")
        self.geometry("900x520")
        self.minsize(640, 360)
        self.items: Dict[str, str] = {}  # iid -> path
        self._queue: "queue.Queue" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._proc = None
        self._stop = False
        self.target_var = tk.StringVar(value="4:3")
        self.keep_var = tk.BooleanVar(value=False)

        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Button(top, text="変換済み一覧から選ぶ...", command=self._pick_from_done).pack(side=tk.LEFT)
        ttk.Button(top, text="ファイルを追加...", command=self._add_files).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="選択を外す", command=self._remove_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="全部クリア", command=self._clear).pack(side=tk.LEFT, padx=(6, 0))

        mid = ttk.Frame(self, padding=(8, 0))
        mid.pack(fill=tk.BOTH, expand=True)
        cols = ("file", "size", "now", "result")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        for c, label, w, anc in (("file", "ファイル", 460, "w"), ("size", "サイズ", 90, "center"),
                                 ("now", "今の比率", 80, "center"), ("result", "結果", 200, "w")):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor=anc)
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.tag_configure("ok", background="#c6efce", foreground="#006100")
        self.tree.tag_configure("ng", background="#ffc7ce", foreground="#9c0006")

        self.hint_var = tk.StringVar()
        ttk.Label(self, textvariable=self.hint_var, foreground="#555").pack(fill=tk.X, padx=10, pady=(4, 0))

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill=tk.X)
        ttk.Label(bottom, text="直したい比率:").pack(side=tk.LEFT)
        ttk.Radiobutton(bottom, text="4:3", variable=self.target_var, value="4:3").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(bottom, text="16:9", variable=self.target_var, value="16:9").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Checkbutton(bottom, text="元のファイルを .bak で残す", variable=self.keep_var).pack(side=tk.LEFT, padx=(16, 0))
        self.run_button = ttk.Button(bottom, text="実行", command=self._run)
        self.run_button.pack(side=tk.RIGHT)
        self.stop_button = ttk.Button(bottom, text="中止", command=self._request_stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT, padx=(0, 6))
        self.status_var = tk.StringVar(value="ファイルを追加してください")
        ttk.Label(self, textvariable=self.status_var).pack(fill=tk.X, padx=10, pady=(0, 8))

        self._setup_dnd()
        attach_tooltips(self)
        self.after(150, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ---- ファイルの追加 ----
    def _setup_dnd(self):
        self.dnd_ok = False
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES  # type: ignore
            TkinterDnD._require(self)
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_ok = True
            self.hint_var.set("ここにmkv/mp4をドラッグ&ドロップしても追加できます")
        except Exception:
            self.hint_var.set("ドラッグ&ドロップを使うには、コマンドプロンプトで  pip install tkinterdnd2  を実行して再起動してください"
                              "(使わなくても、上のボタンから追加できます)")

    def _on_drop(self, event):
        try:
            paths = list(self.tk.splitlist(event.data))
        except tk.TclError:
            paths = [event.data]
        self.add_paths(paths)

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="縦横比を直すファイル", filetypes=[("mkv/mp4", "*.mkv *.mp4"), ("すべて", "*.*")])
        self.add_paths(list(paths))

    def _pick_from_done(self):
        if self.app.encoding_running or self.app.scanning:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は一覧を読み込めません。", parent=self)
            return
        if not getattr(self.app, "_done_loaded", False):
            self.app.refresh_done_list()
        entries = list(getattr(self.app, "_done_all", []))
        if not entries:
            messagebox.showinfo("情報", "変換済みのファイルが見つかりません。", parent=self)
            return
        dlg = tk.Toplevel(self)
        dlg.title("変換済み一覧から選ぶ(複数選択できます)")
        dlg.geometry("820x480")
        dlg.transient(self)
        fvar = tk.StringVar()
        fr = ttk.Frame(dlg, padding=8)
        fr.pack(fill=tk.X)
        ttk.Label(fr, text="絞り込み:").pack(side=tk.LEFT)
        ent = ttk.Entry(fr, textvariable=fvar)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        tv = ttk.Treeview(dlg, columns=("file", "program", "channel"), show="headings", selectmode="extended")
        for c, label, w in (("file", "ファイル", 360), ("program", "番組名", 280), ("channel", "放送局", 140)):
            tv.heading(c, text=label)
            tv.column(c, width=w, anchor="w")
        tv.pack(fill=tk.BOTH, expand=True, padx=8)
        shown: Dict[str, str] = {}

        def refill(*_a):
            for i in tv.get_children():
                tv.delete(i)
            shown.clear()
            terms = self.app._norm_search(fvar.get()).split()
            for e in entries:
                hay = self.app._norm_search(e["program"] + " " + e["file"] + " " + e["channel_text"])
                if all(t in hay for t in terms):
                    iid = tv.insert("", "end", values=(e["file"], e["program"], e["channel_text"]))
                    shown[iid] = e["path"]

        fvar.trace_add("write", refill)
        refill()

        def ok():
            self.add_paths([shown[i] for i in tv.selection() if i in shown])
            dlg.destroy()

        bar = ttk.Frame(dlg, padding=8)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="全選択", command=lambda: tv.selection_set(tv.get_children())).pack(side=tk.LEFT)
        ttk.Button(bar, text="追加", command=ok).pack(side=tk.RIGHT)
        ttk.Button(bar, text="キャンセル", command=dlg.destroy).pack(side=tk.RIGHT, padx=(0, 6))
        ent.focus_set()

    def add_paths(self, paths: List[str]):
        existing = {os.path.normcase(os.path.abspath(p)) for p in self.items.values()}
        added = 0
        for p in paths:
            p = os.path.abspath(p)
            if os.path.isdir(p):
                continue
            if not p.lower().endswith(CONVERTED_EXTENSIONS) or not os.path.isfile(p):
                continue
            key = os.path.normcase(p)
            if key in existing:
                continue
            existing.add(key)
            iid = self.tree.insert("", "end", values=(os.path.basename(p), "…", "…", ""))
            self.items[iid] = p
            added += 1
        if added:
            self.status_var.set(f"{len(self.items)}件を追加しました(比率を調べています)")
            threading.Thread(target=self._probe_all, daemon=True).start()

    def _probe_all(self):
        for iid, path in list(self.items.items()):
            size, dar = probe_video_aspect(path)
            self._queue.put(("probe", iid, size, dar))

    def _remove_selected(self):
        if self._worker and self._worker.is_alive():
            return
        for iid in self.tree.selection():
            self.items.pop(iid, None)
            self.tree.delete(iid)

    def _clear(self):
        if self._worker and self._worker.is_alive():
            return
        for iid in list(self.items):
            self.tree.delete(iid)
        self.items.clear()
        self.status_var.set("ファイルを追加してください")

    # ---- 実行 ----
    def _run(self):
        if self._worker and self._worker.is_alive():
            return
        if not self.items:
            messagebox.showinfo("情報", "ファイルを追加してください。", parent=self)
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            messagebox.showerror("エラー", "ffmpeg が見つかりません。", parent=self)
            return
        target = self.target_var.get()
        if not messagebox.askokcancel(
                "確認", f"{len(self.items)}件の縦横比を {target} に書き換えます。\n"
                        "映像・音声は再エンコードせず、そのままコピーして作り直します。", parent=self):
            return
        self._stop = False
        self.run_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        keep = bool(self.keep_var.get())
        jobs = list(self.items.items())
        self._worker = threading.Thread(target=self._work, args=(ffmpeg, target, keep, jobs), daemon=True)
        self._worker.start()

    def _request_stop(self):
        self._stop = True
        kill_process_tree(self._proc)

    def _work(self, ffmpeg: str, target: str, keep: bool, jobs: List[Tuple[str, str]]):
        done = failed = 0
        for n, (iid, path) in enumerate(jobs, 1):
            if self._stop:
                break
            self._queue.put(("status", f"{n}/{len(jobs)} 処理中: {os.path.basename(path)}"))
            ok, msg = change_aspect_copy(ffmpeg, path, target, keep, self)
            if ok:
                done += 1
                size, dar = probe_video_aspect(path)
                self._queue.put(("probe", iid, size, dar))
            else:
                failed += 1
            self._queue.put(("result", iid, ok, msg))
        text = f"完了: 成功 {done}件 / 失敗 {failed}件" + ("(中止しました)" if self._stop else "")
        self._queue.put(("finish", text))

    def _poll(self):
        try:
            while True:
                kind, *rest = self._queue.get_nowait()
                if kind == "probe":
                    iid, size, dar = rest
                    if self.tree.exists(iid):
                        self.tree.set(iid, "size", size or "?")
                        self.tree.set(iid, "now", dar or "?")
                elif kind == "result":
                    iid, ok, msg = rest
                    if self.tree.exists(iid):
                        self.tree.set(iid, "result", msg)
                        self.tree.item(iid, tags=("ok" if ok else "ng",))
                elif kind == "status":
                    self.status_var.set(rest[0])
                elif kind == "finish":
                    self.status_var.set(rest[0])
                    self.run_button.config(state=tk.NORMAL)
                    self.stop_button.config(state=tk.DISABLED)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._poll)

    def _close(self):
        if self._worker and self._worker.is_alive():
            if not messagebox.askyesno("確認", "処理中です。中止して閉じますか?", parent=self):
                return
            self._request_stop()
        self.destroy()


def change_aspect_copy(ffmpeg: str, path: str, target: str, keep_original: bool, win=None) -> Tuple[bool, str]:
    """
    mkv/mp4の表示アスペクト比を target("4:3"/"16:9") に書き換える(-c copy。再エンコードしない)。
    いったん別名に書き出し、比率と長さを確かめてから元のファイルと入れ替える。
    """
    base, ext = os.path.splitext(path)
    tmp = base + ".aspect_tmp" + ext
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        cmd = [ffmpeg, "-y", "-v", "error", "-i", path, "-map", "0", "-c", "copy",
               "-ignore_unknown", "-aspect", target, tmp]
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, creationflags=flags)
        if win is not None:
            win._proc = proc
        err = proc.communicate()[1].decode("utf-8", errors="replace").strip()
        if win is not None:
            win._proc = None
        if proc.returncode != 0 or not os.path.isfile(tmp):
            raise RuntimeError("ffmpegが失敗しました: " + (err.splitlines()[-1] if err else f"code={proc.returncode}"))
        _size, dar = probe_video_aspect(tmp)
        if dar != target:
            raise RuntimeError(f"書き換え後の比率が {dar or '不明'} でした")
        if os.path.getsize(tmp) < os.path.getsize(path) * 0.9:
            raise RuntimeError("出力が小さすぎるため中止しました(元は変更していません)")
        if keep_original:
            bak = path + ".bak"
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(path, bak)
            os.replace(tmp, path)
        else:
            os.replace(tmp, path)
        return True, f"{target} に変更しました"
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False, str(e)


def probe_duration_seconds(path: str) -> Optional[float]:
    """ffprobeで再生時間(秒)を読む。読めなければ None"""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30, creationflags=flags,
        ).stdout.strip()
        return float(out.splitlines()[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def format_duration_text(sec: Optional[float]) -> str:
    if sec is None:
        return "…"
    s = int(round(sec))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


DUP_LENGTH_TOLERANCE_SEC = 3.0   # 長さの差がこれ以内なら「同じ番組を2回エンコードした」とみなす


def duplicate_group_key(entry: dict, norm) -> Tuple[str, str, str]:
    """
    二重エンコードの候補をまとめるキー。対のcsvから読めた(番組名, 放送日, 開始時刻)が同じなら同じグループ。
    同じ番組名・同じ日でも、開始時刻が違えば(再放送など)別の放送として扱う。
    csvが無いものは、ファイル名から末尾の連番「(2)」を除いたものを使う。
    """
    if entry.get("program"):
        return ("p", norm(entry["program"]), entry.get("date", "") + " " + entry.get("time", ""))
    stem = os.path.splitext(entry["file"])[0]
    return ("f", norm(re.sub(r"\(\d+\)$", "", stem)), "")


class DuplicateEncodeWindow(tk.Toplevel):
    """
    「二重にエンコードしたファイルを探す」: 変換済みのmkv/mp4のうち、同じ放送(番組名・放送日・開始時刻が同じ)が
    2本以上あるものをグループにして並べ、1本ずつ「残す / 削除」を決めて、まとめて削除する。
    最初は各グループで1本だけ残し、あとは削除の予定にしておく(長さが違うものは別の放送かもしれないので全部残す)。
    削除は、動画と対のcsvを完全に削除する(ごみ箱には入らない)。
    """

    COLS = (("group", "組", 44), ("file", "ファイル", 280), ("program", "番組名", 220), ("channel", "放送局", 110),
            ("date", "放送日時", 120), ("where", "場所", 150), ("size", "サイズ", 80), ("length", "長さ", 70),
            ("mtime", "作成日時", 120), ("action", "処理", 64))

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("二重にエンコードしたファイルを探す")
        self.geometry("1280x640")
        self.minsize(820, 420)
        self.entries: List[dict] = []          # グループに入った変換済みファイル
        self.action: Dict[str, str] = {}       # path -> "keep" / "delete"
        self.manual: set = set()               # 手で変えた行(長さがわかっても、勝手に戻さない)
        self.lengths: Dict[str, Optional[float]] = {}
        self.group_of: Dict[str, int] = {}
        self.rows: Dict[str, str] = {}         # iid -> path
        self.sort_state: Tuple[str, bool] = ("group", True)
        self.filter_var = tk.StringVar()
        self.info_var = tk.StringVar()
        self.q: "queue.Queue" = queue.Queue()
        self._gen = 0

        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill=tk.X)
        ttk.Label(top, text="絞り込み:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.filter_var, width=34).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="クリア", command=lambda: self.filter_var.set("")).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="読み直す", command=self.reload).pack(side=tk.RIGHT)
        self.filter_var.trace_add("write", lambda *_: self._render())

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=8)
        self.tree = ttk.Treeview(mid, columns=[c for c, _l, _w in self.COLS], show="headings", selectmode="extended")
        self._labels = {}
        for c, label, w in self.COLS:
            self._labels[c] = label
            self.tree.heading(c, text=label, command=lambda col=c: self._sort_by(col))
            self.tree.column(c, width=w, anchor="e" if c in ("size", "length", "group") else "w")
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.tag_configure("delete", background="#ffc7ce", foreground="#9c0006")
        self.tree.tag_configure("keep", background="#c6efce", foreground="#006100")
        self.tree.tag_configure("warn", background="#fff2cc", foreground="#7f6000")
        self.range_select = RangeSelect(self.tree)
        self.tree.bind("<Double-1>", lambda e: self._toggle_clicked())

        ops = ttk.Frame(self, padding=(8, 6, 8, 0))
        ops.pack(fill=tk.X)
        ttk.Label(ops, text="選んだ行を:").pack(side=tk.LEFT)
        ttk.Button(ops, text="削除にする(この行)", command=lambda: self._set_selected("delete")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="残す(この行)", command=lambda: self._set_selected("keep")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="この組を最初の提案に戻す", command=self._reset_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="ファイルの場所を開く", command=self._open_location).pack(side=tk.LEFT, padx=(14, 0))

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill=tk.X)
        self.run_button = ttk.Button(bottom, text="実行(削除の行を削除する)", command=self._run)
        self.run_button.pack(side=tk.RIGHT)
        ttk.Label(self, textvariable=self.info_var).pack(fill=tk.X, padx=10, pady=(0, 8))

        attach_tooltips(self)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(150, self._poll)
        self.reload()

    def _close(self):
        self._gen += 1
        self.destroy()

    # ---- 読み込み ----
    def reload(self):
        if self.app.encoding_running or self.app.scanning:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は読み込めません。", parent=self)
            return
        self.app.refresh_done_list()
        norm = self.app._norm_search
        groups: Dict[Tuple[str, str, str], List[dict]] = {}
        for e in list(getattr(self.app, "_done_all", [])):
            groups.setdefault(duplicate_group_key(e, norm), []).append(e)
        self.entries = []
        self.group_of = {}
        self.action = {}
        self.manual = set()
        self.lengths = {}
        multi = sorted((g for g in groups.values() if len(g) >= 2),
                       key=lambda g: (norm(g[0]["program"] or g[0]["file"]), g[0].get("date", ""), g[0].get("time", "")))
        for gi, members in enumerate(multi, 1):
            for e in members:
                try:
                    st = os.stat(e["path"])
                    e["size"], e["mtime"] = st.st_size, st.st_mtime
                except OSError:
                    e["size"], e["mtime"] = 0, 0.0
            # 残す1本: 仕分け済み > 連番「(2)」の付かない名前 > 作成日時が古い
            members.sort(key=lambda e: (e["state"] != "sorted",
                                        bool(re.search(r"\(\d+\)$", os.path.splitext(e["file"])[0])),
                                        e["mtime"], e["file"]))
            for k, e in enumerate(members):
                self.group_of[e["path"]] = gi
                self.action[e["path"]] = "keep" if k == 0 else "delete"
                self.entries.append(e)
        self._render()
        self._gen += 1
        gen = self._gen
        paths = [e["path"] for e in self.entries]
        threading.Thread(target=self._probe_lengths, args=(gen, paths), daemon=True).start()

    def _probe_lengths(self, gen: int, paths: List[str]):
        for p in paths:
            if gen != self._gen:
                return
            self.q.put((gen, p, probe_duration_seconds(p)))

    def _poll(self):
        got = False
        try:
            while True:
                gen, path, sec = self.q.get_nowait()
                if gen == self._gen:
                    self.lengths[path] = sec
                    got = True
        except queue.Empty:
            pass
        if got:
            self._apply_lengths()
        try:
            self.after(400, self._poll)
        except tk.TclError:
            pass

    def _apply_lengths(self):
        """長さが読めたグループで、長さが違うもの(別の放送かもしれない)は、全部「残す」にして黄色で示す"""
        changed = False
        by_group: Dict[int, List[dict]] = {}
        for e in self.entries:
            by_group.setdefault(self.group_of[e["path"]], []).append(e)
        self.diff_groups = getattr(self, "diff_groups", set())
        for gi, members in by_group.items():
            if any(e["path"] not in self.lengths for e in members):
                continue
            vals = [self.lengths[e["path"]] for e in members if self.lengths[e["path"]] is not None]
            if len(vals) < 2:
                continue
            differ = (max(vals) - min(vals)) > DUP_LENGTH_TOLERANCE_SEC
            if differ and gi not in self.diff_groups:
                self.diff_groups.add(gi)
                for e in members:
                    if e["path"] not in self.manual:
                        self.action[e["path"]] = "keep"
                changed = True
        self._render()

    # ---- 表示 ----
    def _matches(self, e: dict) -> bool:
        terms = self.app._norm_search(self.filter_var.get()).split()
        if not terms:
            return True
        hay = self.app._norm_search(e["program"] + " " + e["file"] + " " + e["channel_text"])
        return all(t in hay for t in terms)

    def _sort_by(self, col: str):
        asc = not (self.sort_state[0] == col and self.sort_state[1])
        self.sort_state = (col, asc)
        self._render()

    def _row_values(self, e: dict):
        sz = e.get("size", 0)
        size_text = f"{sz / 1024 / 1024:,.0f} MB"
        mt = time.strftime("%Y/%m/%d %H:%M", time.localtime(e["mtime"])) if e.get("mtime") else ""
        act = "削除" if self.action.get(e["path"]) == "delete" else "残す"
        return (self.group_of[e["path"]], e["file"], e["program"], e["channel_text"],
                (e["date"] + " " + e.get("time", "")).strip(), e["where"],
                size_text, format_duration_text(self.lengths.get(e["path"], None)) if e["path"] in self.lengths else "…",
                mt, act)

    def _render(self):
        selected = {self.rows[i] for i in self.tree.selection() if i in self.rows}
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.rows = {}
        shown = [e for e in self.entries if self._matches(e)]
        col, asc = self.sort_state
        norm = self.app._norm_search
        keyfn = {
            "group": None,
            "file": lambda e: norm(e["file"]), "program": lambda e: norm(e["program"]),
            "channel": lambda e: norm(e["channel_text"]), "date": lambda e: e["date"] + " " + e.get("time", ""),
            "where": lambda e: norm(e["where"]), "size": lambda e: e.get("size", 0),
            "length": lambda e: self.lengths.get(e["path"]) or 0, "mtime": lambda e: e.get("mtime", 0),
            "action": lambda e: self.action.get(e["path"], ""),
        }.get(col)
        if keyfn is None:
            if not asc:
                shown = list(reversed(shown))
        else:
            shown.sort(key=keyfn, reverse=not asc)
        reselect = []
        diff = getattr(self, "diff_groups", set())
        for e in shown:
            gi = self.group_of[e["path"]]
            tag = "delete" if self.action.get(e["path"]) == "delete" else ("warn" if gi in diff else "keep")
            iid = self.tree.insert("", "end", tags=(tag,), values=self._row_values(e))
            self.rows[iid] = e["path"]
            if e["path"] in selected:
                reselect.append(iid)
        if reselect:
            self.tree.selection_set(reselect)
        for c, label in self._labels.items():
            self.tree.heading(c, text=label + ((" ▲" if asc else " ▼") if c == col else ""))
        dels = [e for e in self.entries if self.action.get(e["path"]) == "delete"]
        total = sum(e.get("size", 0) for e in dels)
        n_groups = len(set(self.group_of.values()))
        if not self.entries:
            self.info_var.set("同じ放送(番組名・放送日・開始時刻が同じ)が2本以上あるファイルは見つかりませんでした。")
        else:
            self.info_var.set(
                f"{len(shown)} / {len(self.entries)}件を表示  /  重なっている番組: {n_groups}組  /  "
                f"削除の予定: {len(dels)}件({total / 1024 / 1024 / 1024:.2f} GB)  "
                "※ 黄色は長さが違うので別の放送かもしれません(初期値は全部残す)。同じ組の中でダブルクリックすると残す/削除が切り替わります")

    # ---- 編集 ----
    def _selected_paths(self) -> List[str]:
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def _set_selected(self, act: str):
        paths = self._selected_paths()
        if not paths:
            messagebox.showinfo("情報", "行を選んでください。", parent=self)
            return
        for p in paths:
            self.action[p] = act
            self.manual.add(p)
        self._render()

    def _reset_selected(self):
        """選んだ行の組を、最初の提案(1本だけ残す。長さが違う組は全部残す)に戻す"""
        paths = self._selected_paths()
        if not paths:
            messagebox.showinfo("情報", "行を選んでください。", parent=self)
            return
        groups = {self.group_of[p] for p in paths}
        diff = getattr(self, "diff_groups", set())
        seen = set()
        for e in self.entries:      # entriesは、組ごとに「残す1本」が先頭に並んでいる
            gi = self.group_of[e["path"]]
            if gi not in groups:
                continue
            self.manual.discard(e["path"])
            if gi in diff:
                self.action[e["path"]] = "keep"
            else:
                self.action[e["path"]] = "delete" if gi in seen else "keep"
                seen.add(gi)
        self._render()

    def _toggle_clicked(self):
        sel = self._selected_paths()
        if len(sel) != 1:
            return
        p = sel[0]
        self.action[p] = "keep" if self.action.get(p) == "delete" else "delete"
        self.manual.add(p)
        self._render()

    def _open_location(self):
        paths = self._selected_paths()
        if not paths:
            messagebox.showinfo("情報", "行を選んでください。", parent=self)
            return
        p = paths[0]
        try:
            if sys.platform == "win32":
                reveal_in_explorer(p)
            else:
                messagebox.showinfo("場所", p, parent=self)
        except OSError as e:
            messagebox.showerror("エラー", str(e), parent=self)

    # ---- 実行 ----
    def _run(self):
        if self.app.encoding_running or self.app.scanning:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は削除できません。", parent=self)
            return
        dels = [e for e in self.entries if self.action.get(e["path"]) == "delete" and os.path.isfile(e["path"])]
        if not dels:
            messagebox.showinfo("情報", "削除の予定のファイルがありません。", parent=self)
            return
        # 同じ組の全部を削除にしている場合は、念のため別に確認する
        all_gone = []
        for gi in set(self.group_of.values()):
            members = [e for e in self.entries if self.group_of[e["path"]] == gi]
            if members and all(self.action.get(e["path"]) == "delete" for e in members):
                all_gone.append(members[0]["program"] or members[0]["file"])
        if all_gone:
            if not messagebox.askyesno(
                    "全部削除になっている組があります",
                    "次の番組は、重なっているファイルを全部削除する設定です。\n" + "\n".join(all_gone[:8]) +
                    ("\n…" if len(all_gone) > 8 else "") + "\n\nこの番組は1本も残りません。このまま進みますか？",
                    icon="warning", parent=self):
                return
        total = sum(e.get("size", 0) for e in dels)
        preview = "\n".join(e["file"] for e in dels[:10]) + (f"\n…ほか{len(dels) - 10}件" if len(dels) > 10 else "")
        if not messagebox.askyesno(
                "削除の確認",
                f"{len(dels)}件(合計 {total / 1024 / 1024 / 1024:.2f} GB)を削除します。対のcsvも一緒に削除します。\n"
                "ごみ箱には入らず、元には戻せません。\n\n" + preview + "\n\n削除しますか？",
                icon="warning", parent=self):
            return
        ok, errors = 0, []
        for e in dels:
            path = e["path"]
            try:
                os.remove(path)
                ok += 1
            except OSError as ex:
                errors.append(f"{e['file']}: {ex}")
                continue
            csv_path = os.path.splitext(path)[0] + ".csv"
            if os.path.isfile(csv_path):
                try:
                    os.remove(csv_path)
                except OSError as ex:
                    errors.append(f"{os.path.basename(csv_path)}: {ex}")
        self.app.status_var.set(f"二重にエンコードしたファイル {ok}件を削除しました。")
        msg = f"{ok}件を削除しました。"
        if errors:
            msg += "\n\n削除できなかったもの:\n" + "\n".join(errors[:10])
        messagebox.showinfo("完了", msg, parent=self)
        self.reload()


class BackupManagerWindow(tk.Toplevel):
    """旧版のバックアップ(アップデートのたびに自動で作られる)を一覧して、削除したり、その版に戻したりする"""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("旧版のバックアップを管理")
        self.geometry("760x420")
        self.minsize(560, 300)
        self.rows: Dict[str, dict] = {}
        self.info_var = tk.StringVar()
        self.keep_var = tk.IntVar(value=update_backup_keep())

        self.tree = ttk.Treeview(self, columns=("version", "stamp", "size"), show="headings", selectmode="extended")
        for c, label, w, anc in (("version", "バージョン(置き換えられた版)", 260, "w"),
                                 ("stamp", "バックアップした日時", 200, "w"), ("size", "サイズ", 90, "e")):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor=anc)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))
        self.range_select = RangeSelect(self.tree)

        ops = ttk.Frame(self, padding=(8, 6, 8, 0))
        ops.pack(fill=tk.X)
        ttk.Button(ops, text="選んだバックアップを削除", command=self._delete_selected).pack(side=tk.LEFT)
        ttk.Button(ops, text="最新の1本を残して全部削除", command=self._delete_all_but_latest).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="選んだ版に戻す", command=self._rollback).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Button(ops, text="フォルダを開く", command=self._open_folder).pack(side=tk.RIGHT)

        keep = ttk.Frame(self, padding=(8, 6))
        keep.pack(fill=tk.X)
        ttk.Label(keep, text="アップデートのとき、自動で残す本数:").pack(side=tk.LEFT)
        ttk.Spinbox(keep, from_=1, to=30, width=4, textvariable=self.keep_var, command=self._save_keep).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(keep, text="本(これを超えた古いものは、アップデートのたびに自動で削除されます)").pack(side=tk.LEFT, padx=(6, 0))
        self.keep_var.trace_add("write", lambda *_: self._save_keep())
        ttk.Label(self, textvariable=self.info_var).pack(fill=tk.X, padx=10, pady=(0, 8))
        attach_tooltips(self)
        self.reload()

    def _save_keep(self):
        try:
            n = max(1, min(30, int(self.keep_var.get())))
        except (tk.TclError, ValueError):
            return
        self.app.settings["update_backup_keep"] = str(n)
        save_settings(self.app.settings)

    def reload(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.rows = {}
        items = list_update_backups()
        for b in items:
            st = b["stamp"]
            stamp_text = f"{st[:4]}/{st[4:6]}/{st[6:8]} {st[9:11]}:{st[11:13]}:{st[13:15]}"
            iid = self.tree.insert("", "end", values=(b["version"], stamp_text, f"{b['size'] / 1024:,.0f} KB"))
            self.rows[iid] = b
        total = sum(b["size"] for b in items)
        self.info_var.set(f"{len(items)}本 / 合計 {total / 1024 / 1024:.1f} MB    保存先: {update_backup_dir()}")

    def _selected(self) -> List[dict]:
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def _remove(self, items: List[dict]):
        errors = []
        for b in items:
            try:
                os.remove(b["path"])
            except OSError as e:
                errors.append(f"{b['name']}: {e}")
        self.reload()
        if errors:
            messagebox.showerror("削除できませんでした", "\n".join(errors[:10]), parent=self)

    def _delete_selected(self):
        items = self._selected()
        if not items:
            messagebox.showinfo("情報", "削除するバックアップを選んでください。", parent=self)
            return
        if messagebox.askyesno("削除の確認", f"選んだ{len(items)}本のバックアップを削除します。\n元には戻せません。", parent=self):
            self._remove(items)

    def _delete_all_but_latest(self):
        items = list_update_backups()[1:]
        if not items:
            messagebox.showinfo("情報", "削除できるバックアップがありません(最新の1本だけです)。", parent=self)
            return
        if messagebox.askyesno("削除の確認", f"最新の1本を残して、{len(items)}本のバックアップを削除します。\n元には戻せません。", parent=self):
            self._remove(items)

    def _open_folder(self):
        d = update_backup_dir()
        try:
            os.makedirs(d, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(d)  # type: ignore[attr-defined]
            else:
                messagebox.showinfo("保存先", d, parent=self)
        except OSError as e:
            messagebox.showerror("エラー", str(e), parent=self)

    def _rollback(self):
        sel = self._selected()
        if len(sel) != 1:
            messagebox.showinfo("情報", "戻したい版を1本だけ選んでください。", parent=self)
            return
        if self.app.encoding_running:
            messagebox.showinfo("情報", "エンコード中は戻せません。終わってからやり直してください。", parent=self)
            return
        b = sel[0]
        if not messagebox.askyesno(
                "版に戻す",
                f"バージョン {b['version']} に戻して、アプリを再起動しますか？\n"
                "(今の版も、バックアップとして残します)\n\n"
                "※ 起動時の更新確認をONにしていると、また新しい版を勧められます。",
                parent=self):
            return
        try:
            with io.open(b["path"], "rb") as f:
                raw = f.read()
            install_update(raw)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("エラー", f"戻せませんでした。今の版はそのままです。\n\n{e}", parent=self)
            return
        messagebox.showinfo("版に戻す", f"バージョン {b['version']} に戻しました。再起動します。", parent=self)
        self.app._restart_app()


class LogManagerWindow(tk.Toplevel):
    """
    「ログを管理」: 実行ログ(まとめ_実行ログ.txt の中と、従来の1件ずつのtxt)を一覧にして、選んだものを
    「1つのtxtにまとめて」または「1件ずつ」書き出す・内容を見る・削除する。
    """

    COLS = (("time", "日時", 140), ("src", "元ファイル", 200), ("program", "番組名", 260), ("channel", "放送局", 110),
            ("diag", "診断", 60), ("kind", "保存場所", 90), ("size", "サイズ", 80))

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("ログを管理")
        self.geometry("1180x600")
        self.minsize(760, 380)
        self.entries: List[dict] = []
        self.rows: Dict[str, dict] = {}
        self.sort_state: Tuple[str, bool] = ("time", False)
        self.filter_var = tk.StringVar()
        self.only_check_var = tk.BooleanVar(value=False)
        self.info_var = tk.StringVar()
        self.q: "queue.Queue" = queue.Queue()
        self._gen = 0

        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill=tk.X)
        ttk.Label(top, text="絞り込み:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.filter_var, width=34).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="クリア", command=lambda: self.filter_var.set("")).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Checkbutton(top, text="診断が「要確認」のものだけ", variable=self.only_check_var,
                        command=self._render).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Button(top, text="ログを読み直す", command=self.reload).pack(side=tk.RIGHT)
        self.filter_var.trace_add("write", lambda *_: self._render())

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=8)
        self.tree = ttk.Treeview(mid, columns=[c for c, _l, _w in self.COLS], show="headings", selectmode="extended")
        self._labels = {}
        for c, label, w in self.COLS:
            self._labels[c] = label
            self.tree.heading(c, text=label, command=lambda col=c: self._sort_by(col))
            self.tree.column(c, width=w, anchor="e" if c == "size" else "w")
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.tag_configure("check", background="#fff2cc", foreground="#7f6000")
        self.range_select = RangeSelect(self.tree)
        self.tree.bind("<Double-1>", lambda e: self._view())
        self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])

        ops = ttk.Frame(self, padding=(8, 6, 8, 0))
        ops.pack(fill=tk.X)
        ttk.Label(ops, text="選んだログを:").pack(side=tk.LEFT)
        ttk.Button(ops, text="1つのtxtに書き出す...", command=self._export_merged).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="1件ずつ書き出す...", command=self._export_each).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="内容を見る", command=self._view).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="削除", command=self._delete).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="全選択", command=lambda: self.tree.selection_set(self.tree.get_children())).pack(side=tk.LEFT, padx=(14, 0))
        self.import_btn = ttk.Button(ops, text="従来の1件ずつのtxtを、まとめに取り込む", command=self._import_legacy)
        self.import_btn.pack(side=tk.RIGHT)

        ttk.Label(self, textvariable=self.info_var).pack(fill=tk.X, padx=10, pady=(6, 8))
        attach_tooltips(self)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(200, self._poll)
        self.reload()

    def _close(self):
        self._gen += 1
        self.destroy()

    # ---- 読み込み ----
    def reload(self):
        self._gen += 1
        gen = self._gen
        self.info_var.set("ログを読み込んでいます…")
        threading.Thread(target=self._load, args=(gen,), daemon=True).start()

    def _load(self, gen: int):
        folder = get_run_log_dir()
        with _LOG_STORE_LOCK:
            store_entries = scan_log_store(get_log_store_path()) if os.path.isfile(get_log_store_path()) else []
        entries = store_entries + scan_legacy_logs(folder)
        self.q.put((gen, entries))

    def _poll(self):
        try:
            while True:
                gen, entries = self.q.get_nowait()
                if gen == self._gen:
                    self.entries = entries
                    self._render()
        except queue.Empty:
            pass
        try:
            self.after(250, self._poll)
        except tk.TclError:
            pass

    # ---- 表示 ----
    def _time_text(self, e: dict) -> str:
        t = log_name_to_time(e["name"])
        return t.strftime("%Y/%m/%d %H:%M:%S") if t else ""

    def _matches(self, e: dict) -> bool:
        if self.only_check_var.get() and e["diag"] != "要確認":
            return False
        terms = self.app._norm_search(self.filter_var.get()).split()
        if not terms:
            return True
        hay = self.app._norm_search(" ".join((e["program"], e["src"], e["channel"], e["name"], e["diag"])))
        return all(t in hay for t in terms)

    def _sort_by(self, col: str):
        asc = not (self.sort_state[0] == col and self.sort_state[1])
        self.sort_state = (col, asc)
        self._render()

    def _entry_key(self, e: dict) -> str:
        return e["kind"] + "|" + e["name"] + "|" + str(e["offset"])

    def _render(self):
        selected = {self._entry_key(self.rows[i]) for i in self.tree.selection() if i in self.rows}
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.rows = {}
        norm = self.app._norm_search
        keyfn = {
            "time": lambda e: e["name"], "src": lambda e: norm(os.path.basename(e["src"].replace("\\", "/"))),
            "program": lambda e: norm(e["program"]), "channel": lambda e: norm(e["channel"]),
            "diag": lambda e: e["diag"], "kind": lambda e: e["kind"], "size": lambda e: e["length"],
        }[self.sort_state[0]]
        shown = sorted((e for e in self.entries if self._matches(e)), key=keyfn, reverse=not self.sort_state[1])
        reselect = []
        for e in shown:
            src = os.path.basename(e["src"].replace("\\", "/")) if e["src"] else ""
            iid = self.tree.insert("", "end", tags=("check",) if e["diag"] == "要確認" else (), values=(
                self._time_text(e), src, e["program"], e["channel"], e["diag"] or "-",
                "まとめ" if e["kind"] == "store" else "個別txt", f"{e['length'] / 1024:,.0f} KB"))
            self.rows[iid] = e
            if self._entry_key(e) in selected:
                reselect.append(iid)
        if reselect:
            self.tree.selection_set(reselect)
        for c, label in self._labels.items():
            self.tree.heading(c, text=label + ((" ▲" if self.sort_state[1] else " ▼") if c == self.sort_state[0] else ""))
        legacy = sum(1 for e in self.entries if e["kind"] == "legacy")
        total = sum(e["length"] for e in self.entries)
        self.import_btn.config(state=tk.NORMAL if legacy else tk.DISABLED)
        mode = "1つのtxtにまとめて保存" if get_log_mode() == "single" else "1件ずつ別のtxtで保存"
        self.info_var.set(f"{len(shown)} / {len(self.entries)}件を表示 / 合計 {total / 1024 / 1024:.1f} MB / "
                          f"従来の個別txt {legacy}件 / 今の保存方法: {mode}   ※ 黄色は診断が「要確認」")

    # ---- 操作 ----
    def _selected(self) -> List[dict]:
        sel = [self.rows[i] for i in self.tree.selection() if i in self.rows]
        sel.sort(key=lambda e: e["name"])
        return sel

    def _need(self) -> List[dict]:
        sel = self._selected()
        if not sel:
            messagebox.showinfo("情報", "ログを選んでください。", parent=self)
        return sel

    def _export_merged(self):
        sel = self._need()
        if not sel:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title=f"選んだログ{len(sel)}件を1つのtxtに書き出す", defaultextension=".txt",
            initialfile=f"{MERGED_LOG_PREFIX}{datetime.datetime.now():%Y%m%d-%H%M%S}.txt",
            filetypes=[("テキスト", "*.txt")])
        if not path:
            return
        try:
            export_logs_merged(sel, get_log_store_path(), path)
        except OSError as e:
            messagebox.showerror("エラー", f"書き出せませんでした: {e}", parent=self)
            return
        messagebox.showinfo("書き出し", f"{len(sel)}件を1つのtxtに書き出しました。\n{path}", parent=self)

    def _export_each(self):
        sel = self._need()
        if not sel:
            return
        folder = filedialog.askdirectory(parent=self, title=f"選んだログ{len(sel)}件を1件ずつ書き出すフォルダ")
        if not folder:
            return
        done, errors = export_logs_each(sel, get_log_store_path(), folder)
        msg = f"{done}件を、1件ずつ書き出しました。\n{folder}"
        if errors:
            msg += "\n\n書き出せなかったもの:\n" + "\n".join(errors[:10])
        messagebox.showinfo("書き出し", msg, parent=self)

    def _view(self):
        sel = self._selected()
        if len(sel) != 1:
            messagebox.showinfo("情報", "内容を見るログを1件だけ選んでください。", parent=self)
            return
        e = sel[0]
        win = tk.Toplevel(self)
        win.title(f"ログ: {e['name']}")
        win.geometry("980x640")
        box = scrolledtext.ScrolledText(win, wrap=tk.NONE, font=("Consolas", 9))
        box.pack(fill=tk.BOTH, expand=True)
        text = read_log_entry(e, get_log_store_path())
        box.insert("1.0", text)
        box.configure(state=tk.DISABLED)

    def _busy_encoding(self) -> bool:
        if self.app.encoding_running:
            messagebox.showinfo("情報", "エンコード中は、ログの削除・取り込みはできません。終わってからやり直してください。", parent=self)
            return True
        return False

    def _delete(self):
        sel = self._need()
        if not sel or self._busy_encoding():
            return
        total = sum(e["length"] for e in sel)
        if not messagebox.askyesno(
                "削除の確認",
                f"選んだログ {len(sel)}件({total / 1024 / 1024:.1f} MB)を削除します。\n元には戻せません。"
                "\n(必要なら先に書き出してください)", icon="warning", default="no", parent=self):
            return
        try:
            n = delete_log_entries(sel, get_log_store_path())
        except OSError as ex:
            messagebox.showerror("エラー", f"削除できませんでした: {ex}", parent=self)
            self.reload()
            return
        messagebox.showinfo("削除", f"{n}件を削除しました。", parent=self)
        self.reload()

    def _import_legacy(self):
        if self._busy_encoding():
            return
        legacy = [e for e in self.entries if e["kind"] == "legacy"]
        if not legacy:
            return
        if not messagebox.askyesno(
                "取り込み",
                f"従来の1件ずつのtxt {len(legacy)}件を、「{LOG_STORE_NAME}」に追記して、元のtxtを削除します。\n"
                "(中身は変わりません。あとから、ここで選んで書き出せます)", parent=self):
            return
        n = import_legacy_logs(legacy)
        messagebox.showinfo("取り込み", f"{n}件を取り込みました。", parent=self)
        self.reload()


class SeriesSortWindow(tk.Toplevel):
    """
    「作品ごとに仕分け」: 仕分け済みの放送局フォルダ(仕分け/放送局名/)の中で、作品名のフォルダに振り分ける。
    ファイルごとに、移動先(作品フォルダ・放送局直下・今のまま)を選べる。実行前に一覧で確認でき、
    直前の1回は「元に戻す」で戻せる。
    """

    KEEP = None  # 動かさない
    COLS = (("file", "ファイル", 300), ("program", "番組名", 260), ("channel", "放送局", 120),
            ("now", "今の作品フォルダ", 140), ("dest", "移動先(作品フォルダ)", 200))

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("作品ごとに仕分け")
        self.geometry("1120x640")
        self.minsize(760, 420)
        self.root_dir = get_sort_root()
        self.items: List[dict] = []
        self.dest: Dict[str, Optional[str]] = {}   # path -> None(動かさない) / ""(放送局直下) / 作品フォルダ名
        self.manual: set = set()                    # 手で指定した行(規則として覚える対象)
        self.rows: Dict[str, str] = {}              # iid -> path
        self.sort_state: Tuple[str, bool] = ("", True)
        self.filter_var = tk.StringVar()
        self.remember_var = tk.BooleanVar(value=True)
        self.info_var = tk.StringVar()
        self.rules: Dict[str, str] = dict(load_settings().get("series_rules", {}) or {})
        self._busy = False

        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill=tk.X)
        ttk.Label(top, text="絞り込み:").pack(side=tk.LEFT)
        ent = ttk.Entry(top, textvariable=self.filter_var, width=34)
        ent.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="クリア", command=lambda: self.filter_var.set("")).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(top, text="一覧を読み直す", command=self.reload).pack(side=tk.RIGHT)
        self.filter_var.trace_add("write", lambda *_: self._render())

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=8)
        self.tree = ttk.Treeview(mid, columns=[c for c, _l, _w in self.COLS], show="headings", selectmode="extended")
        self._labels = {}
        for c, label, w in self.COLS:
            self._labels[c] = label
            self.tree.heading(c, text=label, command=lambda col=c: self._sort_by(col))
            self.tree.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.tag_configure("move", background="#c6efce", foreground="#006100")
        self.tree.tag_configure("keep", foreground="#7a7a7a")
        self.tree.tag_configure("warn", background="#fff2cc", foreground="#7f6000")
        self.range_select = RangeSelect(self.tree)
        self.tree.bind("<Double-1>", lambda e: self._edit_name())

        ops = ttk.Frame(self, padding=(8, 6, 8, 0))
        ops.pack(fill=tk.X)
        ttk.Label(ops, text="選んだ行を:").pack(side=tk.LEFT)
        ttk.Button(ops, text="作品フォルダ名を入力...", command=self._edit_name).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="作品名の長さを指定...", command=self._set_length).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="動かさない", command=lambda: self._set_selected(None)).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="放送局の直下へ", command=lambda: self._set_selected("")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(ops, text="自動提案に戻す", command=self._reset_selected).pack(side=tk.LEFT, padx=(6, 0))

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill=tk.X)
        ttk.Checkbutton(bottom, text="手で決めた名前を、次回の自動提案に使う", variable=self.remember_var).pack(side=tk.LEFT)
        self.run_button = ttk.Button(bottom, text="実行(移動する)", command=self._run)
        self.run_button.pack(side=tk.RIGHT)
        self.undo_button = ttk.Button(bottom, text="直前の仕分けを元に戻す", command=self._undo)
        self.undo_button.pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Label(self, textvariable=self.info_var).pack(fill=tk.X, padx=10, pady=(0, 8))

        attach_tooltips(self)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.reload()

    # ---- 読み込み・表示 ----
    def reload(self):
        self.items = scan_series_items(self.root_dir)
        self.rules = dict(load_settings().get("series_rules", {}) or {})
        self.dest = dict(suggest_series_destinations(self.items, self.rules))
        self.manual = set()
        self._render()
        self._update_undo_button()

    def _update_undo_button(self):
        self.undo_button.config(state=tk.NORMAL if load_series_undo() else tk.DISABLED)

    def _matches(self, it: dict) -> bool:
        terms = self.app._norm_search(self.filter_var.get()).split()
        if not terms:
            return True
        hay = self.app._norm_search(it["program"] + " " + it["file"] + " " + it["channel"] + " " + it["cur_series"])
        return all(t in hay for t in terms)

    def _dest_text(self, it: dict) -> str:
        d = self.dest.get(it["path"])
        if d is None:
            return "(動かさない)"
        return d if d else "(放送局の直下)"

    def _is_move(self, it: dict) -> bool:
        d = self.dest.get(it["path"])
        return d is not None and series_key(d) != series_key(it["cur_series"])

    def _sort_by(self, col: str):
        asc = not (self.sort_state[0] == col and self.sort_state[1])
        self.sort_state = (col, asc)
        self._render()

    def _render(self):
        selected_paths = {self.rows[i] for i in self.tree.selection() if i in self.rows}
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.rows = {}
        shown = [it for it in self.items if self._matches(it)]
        col, asc = self.sort_state
        keyfn = {
            "file": lambda it: it["file"], "program": lambda it: it["program"], "channel": lambda it: it["channel"],
            "now": lambda it: it["cur_series"], "dest": lambda it: self._dest_text(it),
        }.get(col)
        if keyfn:
            shown.sort(key=lambda it: self.app._norm_search(keyfn(it)), reverse=not asc)
        moves = 0
        reselect = []
        for it in shown:
            move = self._is_move(it)
            moves += move
            d = self.dest.get(it["path"])
            tag = "keep" if d is None else ("move" if move else "keep")
            if it.get("deep") and move:
                tag = "warn"
            iid = self.tree.insert("", "end", tags=(tag,), values=(
                it["file"], it["program"], it["channel"], it["cur_series"] or "(放送局の直下)", self._dest_text(it)))
            self.rows[iid] = it["path"]
            if it["path"] in selected_paths:
                reselect.append(iid)
        if reselect:
            self.tree.selection_set(reselect)
        for c, label in self._labels.items():
            self.tree.heading(c, text=label + ((" ▲" if asc else " ▼") if c == col else ""))
        total_moves = sum(self._is_move(it) for it in self.items)
        self.info_var.set(
            f"{len(shown)} / {len(self.items)}件を表示  /  移動する予定: {total_moves}件(緑の行)"
            "  ※ 仕分けフォルダ内の放送局フォルダにあるファイルが対象です")

    # ---- 編集 ----
    def _selected_items(self) -> List[dict]:
        paths = {self.rows[i] for i in self.tree.selection() if i in self.rows}
        return [it for it in self.items if it["path"] in paths]

    def _need_selection(self) -> List[dict]:
        sel = self._selected_items()
        if not sel:
            messagebox.showinfo("情報", "行を選んでください。", parent=self)
        return sel

    def _set_selected(self, value: Optional[str], manual: bool = True):
        sel = self._need_selection()
        for it in sel:
            self.dest[it["path"]] = value
            if manual:
                self.manual.add(it["path"])
        if sel:
            self._render()

    def _edit_name(self):
        sel = self._need_selection()
        if not sel:
            return
        current = self.dest.get(sel[0]["path"])
        initial = current if current else suggest_series_name(sel[0]["program"])
        name = simpledialog.askstring(
            "作品フォルダ名", f"選んだ{len(sel)}件を入れる作品フォルダ名を入力してください。\n"
                              "(空欄にすると、放送局フォルダの直下へ置きます)",
            initialvalue=initial, parent=self)
        if name is None:
            return
        self._set_selected(series_folder_name(name))

    def _set_length(self):
        sel = self._need_selection()
        if not sel:
            return
        base = clean_program_title(sel[0]["program"])
        n = simpledialog.askinteger(
            "作品名の長さ",
            f"番組名の先頭から何文字を作品名にしますか?(選んだ{len(sel)}件すべてに使います)\n\n"
            f"例: 「{base}」\n  →  7 なら「{base[:7]}」(話数や[二]などは除いた名前の先頭から数えます)",
            initialvalue=min(len(self.dest.get(sel[0]["path"]) or suggest_series_name(sel[0]["program"])), max(1, len(base))),
            minvalue=1, maxvalue=200, parent=self)
        if not n:
            return
        for it in sel:
            self.dest[it["path"]] = series_folder_name(clean_program_title(it["program"])[:n])
            self.manual.add(it["path"])
        self._render()

    def _reset_selected(self):
        sel = self._need_selection()
        if not sel:
            return
        auto = suggest_series_destinations(self.items, self.rules)
        for it in sel:
            self.dest[it["path"]] = auto.get(it["path"])
            self.manual.discard(it["path"])
        self._render()

    # ---- 実行・元に戻す ----
    def _build_plan(self) -> List[Tuple[str, str, dict]]:
        plan = []
        for it in self.items:
            if not self._is_move(it):
                continue
            target = resolve_series_target_dir(self.root_dir, it["channel"], self.dest[it["path"]])
            if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(os.path.dirname(it["path"]))):
                continue
            plan.append((it["path"], target, it))
        return plan

    def _run(self):
        if self._busy:
            return
        if self.app.scanning or self.app.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は仕分けできません。", parent=self)
            return
        plan = self._build_plan()
        if not plan:
            messagebox.showinfo("情報", "移動するファイルがありません。", parent=self)
            return
        groups: Dict[str, int] = {}
        for _p, target, it in plan:
            label = os.path.relpath(target, self.root_dir)
            groups[label] = groups.get(label, 0) + 1
        lines = [f"  ・{k}  ({v}本)" for k, v in sorted(groups.items())]
        preview = "\n".join(lines[:15]) + (f"\n  ...ほか{len(lines) - 15}フォルダ" if len(lines) > 15 else "")
        if not messagebox.askyesno(
                "仕分けの確認",
                f"{len(plan)}本(mkv/mp4と対のcsv)を、次のフォルダへ移動します。\n"
                "移動先に同名のファイルがあるものは、動かさずに残します。\n"
                "実行後は「直前の仕分けを元に戻す」で戻せます。\n\n" + preview + "\n\n続行しますか?", parent=self):
            return
        self._busy = True
        self.run_button.config(state=tk.DISABLED)
        self.info_var.set("移動中...")
        self.update_idletasks()
        moved, errors = execute_series_moves([(p, t) for p, t, _it in plan])
        if moved:
            save_series_undo(moved)
        if self.remember_var.get():
            self._remember_rules([it for _p, _t, it in plan if it["path"] in self.manual])
        self._busy = False
        self.run_button.config(state=tk.NORMAL)
        self.reload()
        self.app.after(0, lambda: getattr(self.app, "_done_loaded", False) and self.app.refresh_done_list())
        msg = f"{len(moved)}本を移動しました。"
        if errors:
            msg += "\n\n動かせなかったもの:\n" + "\n".join(errors[:10]) + (f"\n...ほか{len(errors) - 10}件" if len(errors) > 10 else "")
            messagebox.showwarning("仕分け", msg, parent=self)
        else:
            messagebox.showinfo("仕分け", msg, parent=self)

    def _remember_rules(self, moved_items: List[dict]):
        settings = load_settings()
        rules = dict(settings.get("series_rules", {}) or {})
        for it in moved_items:
            name = self.dest.get(it["path"])
            if not name:
                continue
            base_key = series_key(clean_program_title(it["program"]))
            key = series_key(name)
            if not base_key.startswith(key):
                key = base_key
            if key:
                rules[key] = name
        settings["series_rules"] = rules
        save_settings(settings)

    def _undo(self):
        moved = load_series_undo()
        if not moved:
            messagebox.showinfo("情報", "元に戻せる仕分けの記録がありません。", parent=self)
            self._update_undo_button()
            return
        if not messagebox.askyesno(
                "元に戻す", f"直前の仕分けで動かした {len(moved)}本を、元の場所へ戻します。\n"
                            "空になった作品フォルダは削除します。続行しますか?", parent=self):
            return
        restored, errors = undo_series_moves(moved, self.root_dir)
        clear_series_undo()
        self.reload()
        self.app.after(0, lambda: getattr(self.app, "_done_loaded", False) and self.app.refresh_done_list())
        msg = f"{restored}本を元の場所へ戻しました。"
        if errors:
            messagebox.showwarning("元に戻す", msg + "\n\n戻せなかったもの:\n" + "\n".join(errors[:10]), parent=self)
        else:
            messagebox.showinfo("元に戻す", msg, parent=self)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"m2ts エンコーダー v{APP_VERSION}(録画番組名ビューア/エンコードキュー)")
        try:
            self._app_icon = tk.PhotoImage(data=APP_ICON_PNG_B64)
            self.iconphoto(True, self._app_icon)   # True: 以降に開く窓(ツールの別ウインドウ)にも同じアイコン
        except tk.TclError:
            pass
        self.geometry("980x760")
        self.minsize(700, 500)

        self.folder = get_script_dir()
        self.rplsinfo_path: Optional[str] = None
        self.results: List[Tuple[str, str, str, str, str]] = []
        self.worker_queue: "queue.Queue" = queue.Queue()
        self.scanning = False
        self.recursive_var = tk.BooleanVar(value=load_settings().get("recursive", "0") == "1")
        self.include_m2ts_var = tk.BooleanVar(value=True)
        self.include_rpls_var = tk.BooleanVar(value=False)
        # ノイズ検査: m2tsパス -> 検出したノイズ区間 [(開始秒, 終了秒)](ファイル名への記載に使う)
        self.noise_ranges: Dict[str, List[Tuple[float, float]]] = {}
        self._queue_kind = "encode"  # "encode"(エンコードキュー) or "noise"(ノイズ検査のみ)
        self._auto_released = 0  # 今回のキューで、完了により自動で外した設定の件数

        # iid -> 行データ (元パス、チェック状態、割り当てバッチ、状態など)
        self.row_data: Dict[str, dict] = {}
        # 一覧の並び順(絞り込みで非表示の行も含む)と、番組名の絞り込み文字列
        self._row_order: List[str] = []
        self.filter_var = tk.StringVar()
        self.done_filter_var = tk.StringVar()

        # バッチ登録情報
        # 埋め込んである既定のバッチのうち、まだ登録されていないものを
        # 自動的に追加登録しておく(実ファイルは作成せず、実行時に一時ファイルとして
        # 展開する方式。起動のたびに差分だけ追加され、既に登録済みのものや
        # ユーザーが削除したものには影響しない)
        self.bat_scripts: List[Dict[str, str]] = load_bat_scripts()
        synced = register_embedded_defaults(self.bat_scripts)
        if synced != self.bat_scripts:
            self.bat_scripts = synced
            save_bat_scripts(self.bat_scripts)
        self.bat_name_to_path: Dict[str, str] = {}

        self.encoder_avail: Optional[Dict[str, bool]] = None  # 使えるエンコーダー(起動時に裏で調べる)
        self._encoder_lock = threading.Lock()
        # 設定(再生ソフトのパスなど)
        self.settings: Dict[str, str] = load_settings()
        set_active_encoder(resolve_encoder(self.settings.get("encoder", "auto"), None))  # 「自動」は、調べ終わるまでNVIDIA
        self._init_target_folder()
        self.noise_check_var = tk.BooleanVar(value=self.settings.get("noise_check", "1") != "0")

        # エンコードキュー関連
        self.encode_queue: "queue.Queue" = LogTeeQueue()
        self.encoding_running = False
        self.stop_requested = False
        self._current_process: Optional[subprocess.Popen] = None
        self.diagnostic_report: List[
            Tuple[str, Optional[str], str, List[Tuple[str, int, List[Tuple[float, str]]]]]
        ] = []

        self._build_ui()
        self._setup_tooltips()
        # 前回、途中で終わったログを、まとめに追記する。保存期間を過ぎた分の整理も(裏で)する
        threading.Thread(target=lambda: (fold_leftover_run_logs(), prune_log_store()), daemon=True).start()
        threading.Thread(target=self._detect_encoders_bg, daemon=True).start()  # 使えるエンコーダーを裏で調べる
        self._refresh_bat_combo()
        if getattr(self, "_folder_note", ""):
            self.after(300, lambda: self._append_log("[対象フォルダ] " + self._folder_note))
        if self.settings.get("auto_update_check", "1") != "0":
            # スキャンの前に更新を確認する。新しい版があれば先に案内を出し、答えたあとでスキャンを始める。
            # 確認が遅い(ネットが遅い・つながらない)場合は待たず、3秒でスキャンを始める
            self._scan_started = False
            self._update_decided = False
            self.after(100, lambda: self.check_for_update(manual=False, startup=True))
            self.after(3000, self._start_scan_fallback)
        else:
            self.after(100, self.start_scan)

    def _start_scan_once(self):
        if getattr(self, "_scan_started", True):
            return
        self._scan_started = True
        self.start_scan()

    def _start_scan_fallback(self):
        if not getattr(self, "_update_decided", False):  # 確認の結果が出ていなければ待たない
            self._start_scan_once()

    def _setup_tooltips(self):
        attach_tooltips(self)
        for widget, text in (
            (self.filter_entry, "番組名・ファイル名で絞り込みます。スペース区切りで複数語(すべて含むものだけ表示)。\nひらがな/カタカナ、全角/半角、大文字/小文字は区別しません。"),
            (self.channel_combo, "チャンネルを選びます。選んだら右の「このチャンネルを選択」を押してください。"),
            (self.bat_combo, "エンコード設定(おまかせ・プリセット)を選びます。「選択した行に適用」で行に割り当てます。"),
        ):
            Tooltip(widget, text)

        def on_map(event):
            w = event.widget
            if isinstance(w, tk.Toplevel):
                self.after_idle(lambda: attach_tooltips(w))
        self.bind_all("<Map>", on_map, add="+")

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------
    def _build_ui(self):
        top_frame = ttk.Frame(self, padding=8)
        top_frame.pack(fill=tk.X)
        self.folder_label = ttk.Label(top_frame, text=f"対象フォルダ: {self.folder}")
        self.folder_label.pack(side=tk.LEFT)
        self.folder_change_button = ttk.Button(top_frame, text="フォルダを変更...", command=self._change_folder)
        self.folder_change_button.pack(side=tk.LEFT, padx=(10, 0))
        self.folder_reset_button = ttk.Button(top_frame, text="このアプリのフォルダに戻す", command=self._reset_folder)
        self._update_folder_ui()

        self._build_menu()

        # ---- ① 対象: スキャンと検索対象 ----
        scan_frame = ttk.Frame(self, padding=(8, 0, 8, 6))
        scan_frame.pack(fill=tk.X)
        self.rescan_button = ttk.Button(scan_frame, text="再スキャン", command=self.start_scan)
        self.rescan_button.pack(side=tk.LEFT)
        ttk.Label(scan_frame, text="  検索対象:").pack(side=tk.LEFT)
        self.include_m2ts_check = ttk.Checkbutton(
            scan_frame, text=".m2ts", variable=self.include_m2ts_var, command=self.start_scan
        )
        self.include_m2ts_check.pack(side=tk.LEFT, padx=(6, 0))
        self.include_rpls_check = ttk.Checkbutton(
            scan_frame, text=".rpls", variable=self.include_rpls_var, command=self.start_scan
        )
        self.include_rpls_check.pack(side=tk.LEFT, padx=(10, 0))
        self.recursive_check = ttk.Checkbutton(
            scan_frame,
            text="サブフォルダも検索する",
            variable=self.recursive_var,
            command=self._on_recursive_toggled,
        )
        self.recursive_check.pack(side=tk.LEFT, padx=(16, 0))

        # ---- タブ(m2ts / エンコード済み) ----
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 2))
        self.tab_m2ts = ttk.Frame(self.notebook)
        self.tab_done = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_m2ts, text="  m2ts(エンコード前・変換状況)  ")
        self.notebook.add(self.tab_done, text="  エンコード済み(mkv/mp4。m2tsを削除済みのものも含む)  ")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # ---- 番組名の絞り込み ----
        filter_bar = ttk.Frame(self.tab_m2ts, padding=(8, 4, 8, 2))
        filter_bar.pack(fill=tk.X)
        ttk.Label(filter_bar, text="番組名で絞り込み:").pack(side=tk.LEFT)
        self.filter_entry = ttk.Entry(filter_bar, textvariable=self.filter_var, width=40)
        self.filter_entry.pack(side=tk.LEFT, padx=(6, 4))
        ttk.Button(filter_bar, text="クリア", command=lambda: self.filter_var.set("")).pack(side=tk.LEFT)
        self.filter_count_var = tk.StringVar(value="")
        ttk.Label(filter_bar, textvariable=self.filter_count_var, foreground="#555555").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(filter_bar, text="(スペース区切りで複数語。番組名・ファイル名が対象)", foreground="#888888").pack(
            side=tk.RIGHT)
        self.filter_var.trace_add("write", lambda *_a: self._apply_filter())

        # ---- 一覧表示 (Treeview) ----
        tree_frame = ttk.Frame(self.tab_m2ts, padding=(8, 0, 8, 4))
        tree_frame.pack(fill=tk.BOTH, expand=True)

        # クリックで昇順/降順ソートできる列("見出しラベル")。
        # ソート状態(self._sort_state)はヘッダークリック時に更新する。
        self._sortable_columns: Dict[str, str] = {
            "file_name": "元ファイル名",
            "program_name": "録画番組名",
            "channel": "チャンネル",
            "broadcast_date": "放送日",
            "converted": "変換済み",
            "bat": "使用設定",
            "status": "状態",
            "diag": "エンコード診断",
        }
        self._sort_state: Dict[str, bool] = {}

        columns = ("file_name", "program_name", "channel", "broadcast_date", "converted", "bat", "status", "diag")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        for col, label in self._sortable_columns.items():
            self.tree.heading(col, text=label, command=lambda c=col: self._sort_by_column(c))
        self.tree.column("file_name", width=150, anchor=tk.W)
        self.tree.column("program_name", width=220, anchor=tk.W)
        self.tree.column("channel", width=110, anchor=tk.W)
        self.tree.column("broadcast_date", width=90, anchor=tk.CENTER)
        self.tree.column("converted", width=70, anchor=tk.CENTER)
        self.tree.column("bat", width=130, anchor=tk.W)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.column("diag", width=110, anchor=tk.CENTER)

        # 行の色分け用タグ (変換済み=緑, 未変換=赤)
        self.tree.tag_configure("converted_yes", background="#c6efce", foreground="#006100")
        self.tree.tag_configure("converted_no", background="#ffc7ce", foreground="#9c0006")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<Button-3>", self._on_tree_right_click)

        # Shift+クリック / Shift+↑↓ / Ctrl+クリックの範囲選択(起点をマウスとキーボードで共通にする)
        self.range_select = RangeSelect(self.tree)

        # ---- ② 選択 ----
        # Ctrlキー/Shiftキーを使ったTreeview標準の複数選択(selectmode="extended")を
        # そのまま利用する。行をクリック、Ctrl+クリックで追加選択、Shift+クリックで
        # 範囲選択ができる。
        select_frame = ttk.LabelFrame(self.tab_m2ts, text="① 対象を選ぶ", padding=(8, 2, 8, 4))
        select_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Button(select_frame, text="全選択", command=self._select_all_rows).pack(side=tk.LEFT)
        ttk.Button(select_frame, text="選択解除", command=self._deselect_all_rows).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Label(select_frame, text="   チャンネルで選択:").pack(side=tk.LEFT)
        self.channel_combo_var = tk.StringVar()
        self.channel_combo = ttk.Combobox(
            select_frame, textvariable=self.channel_combo_var, state="readonly", width=22
        )
        self.channel_combo.pack(side=tk.LEFT, padx=(6, 6))
        ttk.Button(
            select_frame, text="このチャンネルを選択", command=self._select_rows_by_channel
        ).pack(side=tk.LEFT)
        self.channel_include_converted_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            select_frame,
            text="変換済みも含める",
            variable=self.channel_include_converted_var,
        ).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(select_frame, text="(Ctrl/Shift+クリックで複数選択)", foreground="#666666").pack(
            side=tk.RIGHT
        )

        # ---- ③ 設定を割り当てる ----
        apply_frame = ttk.LabelFrame(self.tab_m2ts, text="② どの設定でエンコードするか決める", padding=(8, 2, 8, 4))
        apply_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(apply_frame, text="適用する設定:").pack(side=tk.LEFT)
        self.bat_combo_var = tk.StringVar()
        self.bat_combo = ttk.Combobox(
            apply_frame, textvariable=self.bat_combo_var, state="readonly", width=48
        )
        self.bat_combo.pack(side=tk.LEFT, padx=(6, 6))
        self.apply_bat_button = ttk.Button(
            apply_frame, text="選択した行に適用", command=self.apply_bat_to_checked
        )
        self.apply_bat_button.pack(side=tk.LEFT)
        self.clear_bat_button = ttk.Button(
            apply_frame, text="選択行の設定を解除", command=self.clear_bat_from_selected
        )
        self.clear_bat_button.pack(side=tk.LEFT, padx=(6, 0))
        self.clear_all_bat_button = ttk.Button(
            apply_frame, text="すべて解除", command=self.clear_bat_from_all
        )
        self.clear_all_bat_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(apply_frame, text="設定の編集...", command=self.open_settings_editor).pack(side=tk.RIGHT)

        # ---- ④ 実行 ----
        encode_frame = ttk.LabelFrame(self.tab_m2ts, text="③ 実行", padding=(8, 2, 8, 4))
        encode_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        self.start_encode_button = ttk.Button(
            encode_frame, text="エンコード開始", command=self.start_encoding
        )
        self.start_encode_button.pack(side=tk.LEFT)
        self.stop_encode_button = ttk.Button(
            encode_frame, text="中断", command=self.request_stop, state="disabled"
        )
        self.stop_encode_button.pack(side=tk.LEFT, padx=(6, 0))
        self.noise_check_button = ttk.Checkbutton(
            encode_frame,
            text="エンコード後にノイズ検査する(ソフト/CUDAデコードを比較してCSVに記録)",
            variable=self.noise_check_var,
            command=self._on_noise_check_toggled,
        )
        self.noise_check_button.pack(side=tk.LEFT, padx=(20, 0))

        self._build_done_tab()

        # ---- ログ表示 ----
        log_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        log_frame.pack(fill=tk.BOTH, expand=False)
        self._log_toggle_btn = ttk.Button(log_frame, text="▼ 実行ログ(クリックで折りたたみ)", command=self._toggle_log_panel)
        self._log_toggle_btn.pack(anchor="w")
        self._log_body = ttk.Frame(log_frame)
        self._log_body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self._log_frame = log_frame
        log_frame = self._log_body
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=10, font=("Consolas", 9), state=tk.DISABLED, wrap=tk.NONE
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # ---- ステータスバー ----
        self.status_var = tk.StringVar(value="準備中...")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=4)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_menu(self):
        """たまにしか使わない機能は、メニューバーにまとめる"""
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="再スキャン", command=self.start_scan)
        file_menu.add_command(label="一覧をCSVに保存...", command=self.save_csv)
        file_menu.add_separator()
        file_menu.add_command(label="終了", command=self.destroy)
        menubar.add_cascade(label="ファイル", menu=file_menu)
        self.csv_button = MenuEntryProxy(file_menu, 1)

        tool_menu = tk.Menu(menubar, tearoff=0)
        sort_menu = tk.Menu(tool_menu, tearoff=0)
        sort_menu.add_command(label="まとめて仕分け(チャンネル別→作品ごと)...", command=self._sort_channel_then_series)
        sort_menu.add_separator()
        sort_menu.add_command(label="チャンネル別に仕分け", command=self.sort_into_channel_folders)
        sort_menu.add_command(label="作品ごとに仕分け...", command=self._open_series_sort)
        tool_menu.add_cascade(label="仕分け", menu=sort_menu)
        tool_menu.add_separator()
        tool_menu.add_command(label="ファイル名の記号を全角に修正", command=self._fix_semicolon_filenames)
        tool_menu.add_command(label="縦横比を直す...", command=self._open_aspect_fix)
        tool_menu.add_separator()
        tool_menu.add_command(label="二重にエンコードしたファイルを探して削除...", command=self._open_duplicates)
        tool_menu.add_command(label="変換済みm2tsを削除...", command=self._delete_converted_m2ts)
        menubar.add_cascade(label="ツール", menu=tool_menu)
        self.sort_button = MenuEntryProxy(tool_menu, 0)
        self.fix_names_item = MenuEntryProxy(tool_menu, 2)
        self.delete_converted_button = MenuEntryProxy(tool_menu, 6)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="エンコード設定...", command=lambda: self.open_settings_editor("preset"))
        settings_menu.add_command(label="バッチファイル管理...", command=lambda: self.open_settings_editor("bat"))
        settings_menu.add_separator()
        self.encoder_var = tk.StringVar(value=self.settings.get("encoder", "auto"))
        encoder_menu = tk.Menu(settings_menu, tearoff=0)
        for key, label in ENCODER_CHOICES:
            encoder_menu.add_radiobutton(label=label, variable=self.encoder_var, value=key,
                                         command=self._on_encoder_changed)
        encoder_menu.add_separator()
        encoder_menu.add_command(label="使えるエンコーダーを調べる...", command=self._show_available_encoders)
        settings_menu.add_cascade(label="エンコーダー(映像の圧縮に使うもの)", menu=encoder_menu)
        settings_menu.add_command(label="再生ソフトを選ぶ...", command=self._choose_player)
        settings_menu.add_command(label="再生ソフトの指定を解除", command=self._reset_player)
        settings_menu.add_separator()
        self.force_cuda_var = tk.BooleanVar(value=self.settings.get("force_cuda", "0") == "1")
        settings_menu.add_checkbutton(
            label="常にCUDAデコードで変換", variable=self.force_cuda_var, command=self._on_force_cuda_toggled
        )
        self.split_var = tk.BooleanVar(value=self.settings.get("tssplitter_split", "1") == "1")
        settings_menu.add_checkbutton(
            label="切替のある録画は、TsSplitterで分割してから変換", variable=self.split_var, command=self._on_split_toggled
        )
        menubar.add_cascade(label="設定", menu=settings_menu)

        log_menu = tk.Menu(menubar, tearoff=0)
        log_menu.add_command(label="ログを管理(選んで書き出す・削除)...", command=self._open_log_manager)
        log_menu.add_command(label="ログフォルダを開く", command=self._open_log_folder)
        log_menu.add_command(label="画面下の実行ログをtxtに保存...", command=self._save_log_as)
        log_menu.add_separator()
        log_menu.add_command(label="エンコード診断結果を表示(全件)", command=self.show_all_diagnostics)
        log_menu.add_separator()
        self.log_mode_var = tk.StringVar(value=get_log_mode())
        save_menu = tk.Menu(log_menu, tearoff=0)
        save_menu.add_radiobutton(label="1つのtxtにまとめて保存(おすすめ)", variable=self.log_mode_var,
                                  value="single", command=self._on_log_mode_changed)
        save_menu.add_radiobutton(label="1件ずつ別のtxtで保存(従来)", variable=self.log_mode_var,
                                  value="each", command=self._on_log_mode_changed)
        save_menu.add_separator()
        save_menu.add_command(label="ログフォルダのtxtを1つにまとめる...", command=self._merge_log_files)
        log_menu.add_cascade(label="ログの保存方法", menu=save_menu)
        log_menu.add_separator()
        log_menu.add_command(label="ログ(txt)を全削除...", command=self._delete_all_logs)
        menubar.add_cascade(label="ログ", menu=log_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="アップデートを確認...", command=lambda: self.check_for_update(manual=True))
        self.auto_update_var = tk.BooleanVar(value=self.settings.get("auto_update_check", "1") != "0")
        help_menu.add_checkbutton(
            label="起動時に更新を確認する", variable=self.auto_update_var, command=self._on_auto_update_toggled
        )
        help_menu.add_command(label="メニューの説明...", command=self._open_menu_guide)
        help_menu.add_command(label="旧版のバックアップを管理...", command=self._open_backup_manager)
        help_menu.add_separator()
        help_menu.add_command(label="バージョン情報", command=self._show_about)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)
        self._help_menu = help_menu

        # 「ヘルプ → メニューの説明」で一覧表示するための、メニューの一覧
        self._menu_groups = [("ファイル", file_menu), ("ツール", tool_menu), ("設定", settings_menu),
                             ("ログ", log_menu), ("ヘルプ", help_menu)]

        self.configure(menu=menubar)

    # ------------------------------------------------------------------
    # スキャン処理
    # ------------------------------------------------------------------
    def _init_target_folder(self):
        """起動時の対象フォルダを決める: 起動時に渡されたフォルダ > 前回指定したフォルダ > このアプリのフォルダ"""
        chosen: Optional[str] = None
        if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
            chosen = os.path.abspath(sys.argv[1])        # フォルダをpywにドラッグ&ドロップした時など(記憶はしない)
        else:
            saved = str(self.settings.get("target_folder", "") or "")
            if saved and os.path.isdir(saved):
                chosen = saved
        self._folder_note = ""
        if not chosen and self.settings.get("target_folder"):
            self._folder_note = f"前回指定した対象フォルダが見つからないため、このアプリのフォルダを使います: {self.settings.get('target_folder')}"
        self.folder = chosen or get_script_dir()
        set_target_folder(chosen)

    def _update_folder_ui(self):
        self.folder_label.configure(text=f"対象フォルダ: {self.folder}")
        custom = os.path.normcase(os.path.abspath(self.folder)) != os.path.normcase(os.path.abspath(get_script_dir()))
        if custom:
            if not self.folder_reset_button.winfo_ismapped():
                self.folder_reset_button.pack(side=tk.LEFT, padx=(6, 0))
        else:
            self.folder_reset_button.pack_forget()

    def _apply_folder(self, path: Optional[str], remember: bool = True):
        if self.scanning or self.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は、対象フォルダを変えられません。")
            return
        new_path = os.path.abspath(path) if path else get_script_dir()
        self.folder = new_path
        set_target_folder(path)
        if remember:
            if path:
                self.settings["target_folder"] = new_path
            else:
                self.settings.pop("target_folder", None)
            save_settings(self.settings)
        self._update_folder_ui()
        self._done_loaded = False
        self.start_scan()

    def _change_folder(self):
        chosen = filedialog.askdirectory(parent=self, title="対象フォルダを選択(m2ts / rplsがあるフォルダ)",
                                         initialdir=self.folder, mustexist=True)
        if chosen:
            self._apply_folder(os.path.normpath(chosen))

    def _reset_folder(self):
        self._apply_folder(None)

    def _on_recursive_toggled(self):
        self.settings["recursive"] = "1" if self.recursive_var.get() else "0"
        save_settings(self.settings)
        self.start_scan()

    def start_scan(self):
        if self.scanning or self.encoding_running:
            return

        self.rplsinfo_path = find_rplsinfo()
        if not self.rplsinfo_path:
            messagebox.showerror(
                "エラー",
                "rplsinfo.exe が見つかりません。\n"
                "このファイルと同じフォルダに rplsinfo.exe を置くか、\n"
                "PATH の通ったフォルダに置いてください。",
            )
            self.status_var.set("rplsinfo.exe が見つかりません")
            return

        extensions = tuple(
            ext
            for ext, enabled in ((".m2ts", self.include_m2ts_var.get()), (".rpls", self.include_rpls_var.get()))
            if enabled
        )
        if not extensions:
            for row in self.tree.get_children():
                self.tree.delete(row)
            self.results = []
            self.row_data = {}
            self._row_order = []
            self.status_var.set(".m2ts / .rpls のどちらか一方は検索対象にチェックしてください。")
            return

        files = collect_target_files(self.folder, recursive=self.recursive_var.get(), extensions=extensions)
        for iid in list(self._row_order) + list(self.tree.get_children()):
            if self.tree.exists(iid):
                self.tree.delete(iid)
        self.results = []
        self.row_data = {}
        self._row_order = []

        if not files:
            scope = "サブフォルダを含めて" if self.recursive_var.get() else ""
            ext_label = " / ".join(extensions)
            self.status_var.set(f"'{self.folder}' {scope}内に {ext_label} ファイルが見つかりませんでした。")
            if not self.recursive_var.get():
                # このフォルダ直下には無くても、サブフォルダの中にある録画は多い(例: 〇/STREAM/00001.m2ts)
                try:
                    in_sub = collect_target_files(self.folder, recursive=True, extensions=extensions)
                except Exception:
                    in_sub = []
                if in_sub and not getattr(self, "_sub_prompted", False):
                    self._sub_prompted = True
                    if messagebox.askyesno(
                        "サブフォルダに録画があります",
                        f"このフォルダの直下には {ext_label} がありませんが、\n"
                        f"サブフォルダの中に {len(in_sub)} 件見つかりました。\n\n"
                        "「サブフォルダも検索する」をONにして、もう一度スキャンしますか?",
                        parent=self,
                    ):
                        self.recursive_var.set(True)
                        self._on_recursive_toggled()
            return

        self.scanning = True
        self.rescan_button.state(["disabled"])
        self.status_var.set(f"スキャン開始... (0/{len(files)}件)")

        thread = threading.Thread(target=self._scan_worker, args=(files,), daemon=True)
        thread.start()
        self.after(100, self._poll_queue)

    def _scan_worker(self, files: List[str]):
        total = len(files)
        converted_names_cache: Dict[str, List[str]] = {}

        for index, path in enumerate(files, start=1):
            base_name = os.path.basename(path)
            info = get_program_info(self.rplsinfo_path, path)
            info_source_path = None

            # 録画番組名やチャンネル名が分からないm2tsは、BDAV構成の対応するrplsから
            # 自動で情報を取得しなおす(右クリックの「rplsから番組情報を再取得」と同じ処理)
            if info is None or not info[1].strip() or not info[2].strip():
                rpls_path = find_paired_rpls(path)
                if rpls_path:
                    rpls_info = get_program_info(self.rplsinfo_path, rpls_path)
                    if rpls_info is not None and rpls_info[1].strip():
                        info = rpls_info
                        info_source_path = rpls_path

            if info is None:
                program_name = NO_PROGRAM_INFO
                channel_name = "(不明)"
                broadcast_date = ""
            else:
                _, program_name, channel_name, broadcast_date = info
                if not program_name.strip():
                    program_name = NO_PROGRAM_INFO
                if not channel_name:
                    channel_name = "(不明)"

            file_dir = os.path.dirname(path)
            # 同名番組(別日放送)を取り違えないよう、録画日付が異なる変換済みは除外して照合する
            converted = is_source_converted(
                file_dir, base_name, program_name,
                date_digits=normalize_date_digits(broadcast_date), cache=converted_names_cache,
            )

            self.worker_queue.put(
                (
                    "progress", path, base_name, program_name, channel_name, broadcast_date, converted, index, total,
                    info_source_path,
                )
            )
        self.worker_queue.put(("done",))

    def _poll_queue(self):
        try:
            while True:
                item = self.worker_queue.get_nowait()
                if item[0] == "progress":
                    (
                        _, full_path, base_name, program_name, channel_name, broadcast_date, converted, index, total,
                        scan_info_source,
                    ) = item
                    mark = "〇" if converted else "✕"
                    tag = "converted_yes" if converted else "converted_no"
                    self.results.append((base_name, program_name, channel_name, broadcast_date, mark))

                    iid = self.tree.insert(
                        "",
                        tk.END,
                        values=(base_name, program_name, channel_name, broadcast_date, mark, "(未設定)", "待機中", "-"),
                        tags=(tag,),
                    )
                    self.row_data[iid] = {
                        "path": full_path,
                        "program_name": program_name,
                        "channel": channel_name,
                        "broadcast_date": broadcast_date,
                        "converted": converted,
                        "info_source_path": scan_info_source,
                        "output_path": None,
                        "bat_path": None,
                        "bat_name": None,
                        "status": "待機中",
                        "diag_label": "-",
                        "diag_issues": [],
                    }
                    self._row_order.append(iid)
                    if self.filter_var.get().strip() and not self._row_matches(iid):
                        self.tree.detach(iid)
                    self.status_var.set(f"処理中... ({index}/{total}件)")
                elif item[0] == "done":
                    self.scanning = False
                    self.rescan_button.state(["!disabled"])
                    self.status_var.set(f"完了: {len(self.results)}件のファイルを処理しました。")
                    self._refresh_channel_combo()
                    self._update_filter_count()
                    pending = getattr(self, "_pending_update_info", None)
                    if pending is not None:
                        self._pending_update_info = None
                        if not self.encoding_running:
                            self.after(300, lambda info=pending: self._confirm_and_update(info))
        except queue.Empty:
            pass

        if self.scanning:
            self.after(100, self._poll_queue)

    def save_csv(self):
        if not self.results:
            messagebox.showinfo("情報", "保存するデータがありません。先にスキャンを実行してください。")
            return

        path = filedialog.asksaveasfilename(
            initialdir=self.folder,
            initialfile="番組情報一覧.csv",
            defaultextension=".csv",
            filetypes=[("CSVファイル", "*.csv")],
        )
        if not path:
            return

        try:
            with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["元ファイル名", "録画番組名", "チャンネル", "放送日", "変換ファイル(mkv/mp4)"])
                writer.writerows(self.results)
            messagebox.showinfo("保存完了", f"'{path}' に保存しました。")
        except Exception as e:
            messagebox.showerror("エラー", f"保存に失敗しました:\n{e}")

    # ------------------------------------------------------------------
    # 一覧選択操作 (Ctrl+クリック / Shift+クリックによる複数選択に対応)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 変換済みm2tsの削除
    # ------------------------------------------------------------------
    def _sort_channel_then_series(self):
        """チャンネル別の仕分けを行い、終わったら続けて「作品ごとに仕分け」の画面を開く"""
        self._sort_outcome = None
        self._chain_series = False
        self.sort_into_channel_folders()
        outcome = getattr(self, "_sort_outcome", None)
        if outcome == "started":
            self._chain_series = True  # 仕分けが終わった時に、作品ごとの画面を開く
        elif outcome == "empty":
            self._open_series_sort()  # チャンネル別に移すものが無ければ、そのまま作品ごとへ

    def _open_series_sort(self):
        """作品ごとに仕分けるウインドウ(開いていれば前面に出す)"""
        if self.scanning or self.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は開けません。")
            return
        win = getattr(self, "_series_win", None)
        try:
            if win is not None and win.winfo_exists():
                win.lift()
                win.focus_force()
                return
        except tk.TclError:
            pass
        if not os.path.isdir(get_sort_root()):
            messagebox.showinfo("情報", "「仕分け」フォルダがまだありません。先に「チャンネル別に仕分け」を実行してください。")
            return
        self._series_win = SeriesSortWindow(self)

    def _open_duplicates(self):
        """二重にエンコードしたファイルを探すウインドウ(開いていれば前面に出す)"""
        if self.scanning or self.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は開けません。")
            return
        win = getattr(self, "_dup_win", None)
        try:
            if win is not None and win.winfo_exists():
                win.lift()
                win.focus_force()
                return
        except tk.TclError:
            pass
        self._dup_win = DuplicateEncodeWindow(self)

    def _open_aspect_fix(self):
        """縦横比を直すウインドウ(開いていれば前面に出す)"""
        win = getattr(self, "_aspect_win", None)
        try:
            if win is not None and win.winfo_exists():
                win.lift()
                win.focus_force()
                return
        except tk.TclError:
            pass
        self._aspect_win = AspectFixWindow(self)

    def _fix_semicolon_filenames(self):
        """
        過去のバージョンで、禁止文字の代替として使われていたASCIIプレースホルダ
        (; @ $ { } ~ `)がファイル名に残ってしまっている mkv/mp4 (および同名csv) を、
        まとめて本来の全角記号に戻す。現在のフォルダ設定(再帰検索の有無)に従って検索する。
        """
        if self.scanning or self.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は実行できません。")
            return

        placeholder_chars = set(PLACEHOLDER_TO_FULLWIDTH.keys())

        def has_placeholder(name: str) -> bool:
            return any(ch in name for ch in placeholder_chars)

        targets: List[str] = []
        if self.recursive_var.get():
            for root, _dirs, files in os.walk(self.folder):
                for name in files:
                    if has_placeholder(name) and name.lower().endswith(CONVERTED_EXTENSIONS + (".csv",)):
                        targets.append(os.path.join(root, name))
        else:
            try:
                entries = os.listdir(self.folder)
            except Exception as e:
                messagebox.showerror("エラー", f"フォルダを読み取れませんでした:\n{e}")
                return
            for name in entries:
                path = os.path.join(self.folder, name)
                if os.path.isfile(path) and has_placeholder(name) and name.lower().endswith(
                    CONVERTED_EXTENSIONS + (".csv",)
                ):
                    targets.append(path)

        if not targets:
            messagebox.showinfo("情報", "修正対象のファイルは見つかりませんでした。")
            return

        preview_names = [os.path.basename(p) for p in targets[:10]]
        preview_text = "\n".join(preview_names)
        if len(targets) > 10:
            preview_text += f"\n...ほか{len(targets) - 10}件"

        confirmed = messagebox.askyesno(
            "確認",
            f"{len(targets)}件のファイル名の記号を本来の全角文字に修正します。\n\n" + preview_text,
        )
        if not confirmed:
            return

        fixed = 0
        skipped = []
        for path in targets:
            new_path = restore_colon_in_output_filename(path)
            if new_path and new_path != path:
                fixed += 1
                # 対応する row_data / output_path があれば更新しておく
                for data in self.row_data.values():
                    if data.get("output_path") == path:
                        data["output_path"] = new_path
                for i, entry in enumerate(self.diagnostic_report):
                    if entry[1] == path:
                        self.diagnostic_report[i] = (entry[0], new_path, entry[2], entry[3])
            else:
                skipped.append(os.path.basename(path))

        message = f"{fixed}/{len(targets)}件を修正しました。"
        if skipped:
            message += "\n\n修正できなかったファイル(同名ファイルが既にある等):\n" + "\n".join(skipped[:10])
            messagebox.showwarning("一部スキップしました", message)
        else:
            messagebox.showinfo("完了", message)

        self.status_var.set(f"ファイル名修正: {fixed}/{len(targets)}件")

    def _delete_converted_m2ts(self):
        """
        変換済み(mkv/mp4が存在する)m2tsファイルを削除する。
        - 選択中の行があれば、その中の対象のみ
        - 選択が無ければ、一覧に表示中の対象すべて
        いずれの場合も、対象は「拡張子が.m2ts」かつ「変換済み」の行のみ。
        rplsファイルや未変換のファイルは対象外。mkv/mp4は絶対に削除しない。
        """
        if self.scanning or self.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は削除できません。")
            return

        def is_target(iid: str) -> bool:
            data = self.row_data.get(iid)
            if not data or not data.get("converted"):
                return False
            if data.get("noise_state") in ("pending", "interrupted"):
                # ノイズ箇所の記録が終わるまでは、元のm2tsを絶対に削除しない
                return False
            return data["path"].lower().endswith(".m2ts")

        selected_iids = list(self.tree.selection())
        if selected_iids:
            target_iids = [iid for iid in selected_iids if is_target(iid)]
            scope_label = "選択中の"
        else:
            target_iids = [iid for iid in self._visible_iids() if is_target(iid)]
            scope_label = "表示中の" if self.filter_var.get().strip() else "一覧内すべての"

        if not target_iids:
            messagebox.showinfo("情報", f"{scope_label}変換済みm2tsファイルが見つかりませんでした。")
            return

        preview_names = [os.path.basename(self.row_data[iid]["path"]) for iid in target_iids[:10]]
        preview_text = "\n".join(preview_names)
        if len(target_iids) > 10:
            preview_text += f"\n...ほか{len(target_iids) - 10}件"

        confirmed = messagebox.askyesno(
            "削除の確認",
            f"{scope_label}変換済みm2tsファイル {len(target_iids)}件を削除します。\n"
            "この操作は元に戻せません(ごみ箱には入らず、完全に削除されます)。\n"
            "対応するmkv/mp4は削除されません。\n\n"
            f"{preview_text}\n\n続行しますか?",
            icon="warning",
        )
        if not confirmed:
            return

        deleted = 0
        errors = []
        for iid in target_iids:
            data = self.row_data.get(iid)
            if not data:
                continue
            path = data["path"]
            try:
                os.remove(path)
                deleted += 1
                self.tree.delete(iid)
                del self.row_data[iid]
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        self.status_var.set(f"{deleted}件のm2tsファイルを削除しました。")

        if errors:
            error_text = "\n".join(errors[:10])
            if len(errors) > 10:
                error_text += f"\n...ほか{len(errors) - 10}件"
            messagebox.showerror("一部のファイルを削除できませんでした", error_text)

    def sort_into_channel_folders(self):
        """
        変換済みのmkv/mp4と、対になるcsvを、チャンネルごとのフォルダ
        (スクリプトと同じフォルダの「仕分け」→「チャンネル名」)へ移動する。
        m2tsは移動しない。同名ファイルが仕分け先にある場合は連番を付ける。
        「エンコード済み」タブを表示中はそのタブの一覧を、m2tsタブでは一覧の行(選択中の行があれば
        その行だけ)を対象にする。
        """
        if self.scanning or self.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は仕分けできません。")
            return
        if self._on_done_tab():
            self.sort_done_list(selected_only=bool(self.done_tree.selection()))
            return

        selected = [i for i in self.tree.selection() if i in self.row_data]
        target_iids = selected if selected else self._visible_iids()
        scope_label = "選択中の" if selected else ("表示中の" if self.filter_var.get().strip() else "一覧内すべての")
        if not target_iids:
            messagebox.showinfo(
                "情報",
                "仕分けする対象がありません。先にスキャンを実行してください。\n"
                "(m2tsを削除済みのmkv/mp4は「エンコード済み」タブで仕分けできます)",
            )
            return

        # 移動対象を計画する(移動はまだしない)
        plan: List[Tuple[Optional[str], str, str, str]] = []  # (iid, 動画のパス, 仕分け先フォルダ, チャンネル名)
        skipped_unknown = 0
        skipped_unconverted = 0
        already_sorted = 0
        root = get_sort_root()
        for iid in target_iids:
            data = self.row_data[iid]
            if not data.get("converted"):
                skipped_unconverted += 1
                continue
            folder_name = channel_folder_name(data.get("channel", ""))
            if not folder_name:
                skipped_unknown += 1
                continue
            output_path = self._find_existing_output(iid)
            if not output_path:
                skipped_unconverted += 1
                continue
            dest_dir = os.path.join(root, folder_name)
            out_dir = os.path.normcase(os.path.abspath(os.path.dirname(output_path)))
            dest_norm = os.path.normcase(os.path.abspath(dest_dir))
            if out_dir == dest_norm or out_dir.startswith(dest_norm + os.sep):  # 作品フォルダの中も仕分け済み
                already_sorted += 1
                continue
            plan.append((iid, output_path, dest_dir, data.get("channel", "")))

        self._confirm_and_run_sort(
            plan, scope_label, skipped_unknown, skipped_unconverted, already_sorted,
            hint="※ m2tsを削除済みのmkv/mp4は、「エンコード済み」タブで仕分けできます。",
        )

    def _confirm_and_run_sort(
        self,
        plan: List[Tuple[Optional[str], str, str, str]],
        scope_label: str,
        skipped_unknown: int,
        skipped_unconverted: int,
        already_sorted: int,
        hint: str = "",
    ):
        """仕分け計画を確認ダイアログで見せ、了承されたら移動を始める"""
        root = get_sort_root()
        self._sort_outcome = "empty" if not plan else "ask"
        if not plan:
            messagebox.showinfo(
                "仕分け",
                "移動するファイルはありませんでした。\n"
                f"(仕分け済み {already_sorted}件 / チャンネル不明 {skipped_unknown}件 / 未変換 {skipped_unconverted}件)"
                + ("\n\n" + hint if hint else ""),
            )
            return

        channels = sorted({os.path.basename(d) for _i, _p, d, _c in plan})
        preview = "\n".join(f"  ・{c}" for c in channels[:12])
        if len(channels) > 12:
            preview += f"\n  ...ほか{len(channels) - 12}チャンネル"
        confirmed = messagebox.askyesno(
            "仕分けの確認",
            f"{scope_label}変換済みファイル {len(plan)}件(mkv/mp4と対のcsv)を、\n"
            f"{root}\n"
            "の中のチャンネル別フォルダへ移動します。\n"
            "m2tsは移動しません。同名のファイルがある場合は番号を付けます。\n\n"
            f"{preview}\n\n"
            f"(チャンネル不明 {skipped_unknown}件 / 未変換 {skipped_unconverted}件 / 仕分け済み {already_sorted}件 は対象外)\n"
            + ("\n" + hint + "\n" if hint else "")
            + "\n続行しますか?",
        )
        if not confirmed:
            self._sort_outcome = "cancel"
            return
        self._sort_outcome = "started"

        self.scanning = True  # 仕分け中は、スキャン・エンコードを開始させない
        self.sort_button.state(["disabled"])
        self.rescan_button.state(["disabled"])
        self.status_var.set(f"仕分け中... (0/{len(plan)}件)")
        self._sort_queue: "queue.Queue" = queue.Queue()
        thread = threading.Thread(target=self._sort_worker, args=(plan,), daemon=True)
        thread.start()
        self.after(100, self._poll_sort_queue)

    # ------------------------------------------------------------------
    # 「エンコード済み」タブ(m2tsを削除済みのmkv/mp4も含めて、チャンネル別に仕分ける)
    # ------------------------------------------------------------------
    def _build_done_tab(self):
        tab = self.tab_done
        bar = ttk.Frame(tab, padding=(8, 6, 8, 2))
        bar.pack(fill=tk.X)
        self.done_reload_button = ttk.Button(bar, text="一覧を更新", command=self.refresh_done_list)
        self.done_reload_button.pack(side=tk.LEFT)
        ttk.Button(bar, text="全選択", command=lambda: self.done_tree.selection_set(
            self.done_tree.get_children())).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(bar, text="選択解除", command=lambda: self.done_tree.selection_remove(
            self.done_tree.get_children())).pack(side=tk.LEFT, padx=(6, 0))
        self.done_sort_selected_button = ttk.Button(
            bar, text="選択した行をチャンネル別に仕分け", command=lambda: self.sort_done_list(True))
        self.done_sort_selected_button.pack(side=tk.LEFT, padx=(16, 0))
        self.done_sort_all_button = ttk.Button(
            bar, text="未仕分けをすべて仕分け", command=lambda: self.sort_done_list(False))
        self.done_sort_all_button.pack(side=tk.LEFT, padx=(6, 0))
        fbar = ttk.Frame(tab, padding=(8, 2, 8, 2))
        fbar.pack(fill=tk.X)
        ttk.Label(fbar, text="番組名で絞り込み:").pack(side=tk.LEFT)
        ttk.Entry(fbar, textvariable=self.done_filter_var, width=40).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Button(fbar, text="クリア", command=lambda: self.done_filter_var.set("")).pack(side=tk.LEFT)
        ttk.Label(fbar, text="(スペース区切りで複数語。番組名・ファイル名が対象)", foreground="#888888").pack(
            side=tk.RIGHT)
        self.done_filter_var.trace_add("write", lambda *_a: self._render_done())
        self.done_info_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.done_info_var, foreground="#555555", padding=(8, 0, 8, 2)).pack(fill=tk.X)
        ttk.Label(tab, text="「サブフォルダも検索する」のチェックに従って、対象フォルダ内のmkv/mp4を探します(「仕分け」フォルダ内は仕分け済みとして表示)。",
                  foreground="#555555", padding=(8, 0, 8, 2)).pack(fill=tk.X)

        frame = ttk.Frame(tab, padding=(8, 0, 8, 4))
        frame.pack(fill=tk.BOTH, expand=True)
        columns = ("file", "program", "channel", "date", "where", "state")
        self.done_tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for col, label, width, anchor in (
            ("file", "ファイル名", 230, tk.W), ("program", "番組名", 220, tk.W),
            ("channel", "チャンネル", 130, tk.W), ("date", "放送日", 90, tk.CENTER),
            ("where", "場所", 150, tk.W), ("state", "仕分け", 90, tk.CENTER),
        ):
            self.done_tree.heading(col, text=label, command=lambda c=col: self._sort_done(c))
            self.done_tree.column(col, width=width, anchor=anchor)
        self._done_labels = {c: l for c, l, _w, _a in (
            ("file", "ファイル名", 0, 0), ("program", "番組名", 0, 0), ("channel", "チャンネル", 0, 0),
            ("date", "放送日", 0, 0), ("where", "場所", 0, 0), ("state", "仕分け", 0, 0))}
        self._done_sort: Tuple[str, bool] = ("", True)
        self._done_all: List[dict] = []
        self.done_tree.tag_configure("sorted", background="#c6efce", foreground="#006100")
        self.done_tree.tag_configure("unsorted", background="#fff2cc", foreground="#7f6000")
        self.done_tree.tag_configure("unknown", background="#ffc7ce", foreground="#9c0006")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.done_tree.yview)
        self.done_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.done_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.done_range_select = RangeSelect(self.done_tree)
        self.done_rows: Dict[str, dict] = {}
        self._done_loaded = False

    def _on_done_tab(self) -> bool:
        try:
            return self.notebook.select() == str(self.tab_done)
        except tk.TclError:
            return False

    def _on_tab_changed(self, _event=None):
        if self._on_done_tab():
            self.refresh_done_list()

    def refresh_done_list(self):
        """対象フォルダ(と仕分けフォルダ)の mkv/mp4 を、対のcsvの内容と一緒に一覧にする"""
        if self.encoding_running or self.scanning:
            return
        for iid in self.done_tree.get_children():
            self.done_tree.delete(iid)
        self.done_rows = {}
        root = get_sort_root()
        try:
            outside = find_orphan_videos(self.folder, self.recursive_var.get(), [])
        except OSError:
            outside = []
        inside = list_sorted_videos(root) if os.path.isdir(root) else []
        known_channels = {d.get("channel", "") for d in self.row_data.values()}
        known_channels |= {os.path.basename(d) for d in list_channel_dirs()}

        entries: List[dict] = []
        for path in outside + inside:
            is_sorted = os.path.normcase(os.path.abspath(path)).startswith(
                os.path.normcase(os.path.abspath(root)) + os.sep)
            csv_path = os.path.splitext(path)[0] + ".csv"
            has_csv = os.path.isfile(csv_path)
            channel = ""
            program, date, start_time = "", "", ""
            if has_csv:
                channel = read_channel_from_sidecar_csv(csv_path, known_channels) or ""
                program, date = read_program_info_from_sidecar_csv(csv_path)
                start_time = read_start_time_from_sidecar_csv(csv_path)
            if is_sorted:
                state, label = "sorted", "済"
                if not channel:
                    _rel = os.path.relpath(path, root).split(os.sep)
                    channel = _rel[0] if len(_rel) > 1 else os.path.basename(os.path.dirname(path))
            elif channel_folder_name(channel):
                state, label = "unsorted", "未"
            else:
                state, label = "unknown", "不明"
            where = os.path.relpath(os.path.dirname(path), self.folder)
            entries.append({
                "path": path, "channel": channel, "state": state, "label": label,
                "file": os.path.basename(path), "program": program, "date": date, "time": start_time,
                "channel_text": channel or ("(不明)" if has_csv else "(csvなし)"),
                "where": where if where != "." else "(対象フォルダ直下)",
            })
        self._done_all = entries
        self._done_loaded = True
        self._render_done()

    def _done_row_matches(self, entry: dict) -> bool:
        terms = self._norm_search(self.done_filter_var.get()).split()
        if not terms:
            return True
        haystack = self._norm_search(entry["program"] + " " + entry["file"])
        return all(t in haystack for t in terms)

    def _sort_done(self, col: str):
        """見出しクリックで昇順/降順に並べ替える(クリックするたびにトグル)"""
        ascending = not (self._done_sort[0] == col and self._done_sort[1])
        self._done_sort = (col, ascending)
        self._render_done()

    def _render_done(self):
        """絞り込みと並び順を反映して、一覧を作り直す"""
        if not hasattr(self, "done_tree"):
            return
        for iid in self.done_tree.get_children():
            self.done_tree.delete(iid)
        self.done_rows = {}
        shown = [e for e in self._done_all if self._done_row_matches(e)]
        col, ascending = self._done_sort
        if col:
            key_field = {"channel": "channel_text", "state": "label"}.get(col, col)
            shown.sort(key=lambda e: str(e[key_field]).lower(), reverse=not ascending)
        counts = {"unsorted": 0, "sorted": 0, "unknown": 0}
        for e in shown:
            counts[e["state"]] += 1
            iid = self.done_tree.insert(
                "", "end", tags=(e["state"],),
                values=(e["file"], e["program"], e["channel_text"], e["date"], e["where"], e["label"]),
            )
            self.done_rows[iid] = {"path": e["path"], "channel": e["channel"], "state": e["state"]}
        for c, label in self._done_labels.items():
            arrow = (" ▲" if ascending else " ▼") if c == col else ""
            self.done_tree.heading(c, text=label + arrow)
        filtered = bool(self.done_filter_var.get().strip())
        self.done_info_var.set(
            (f"{len(shown)} / {len(self._done_all)}件を表示  /  " if filtered else f"{len(shown)}件  /  ")
            + f"未仕分け {counts['unsorted']}件  /  仕分け済み {counts['sorted']}件  /  "
            f"不明(csvが無い等) {counts['unknown']}件   ※チャンネルは対のcsvから読みます"
        )

    def sort_done_list(self, selected_only: bool):
        """「エンコード済み」タブの未仕分けの行を、チャンネル別に仕分ける(選択行のみ/全件)"""
        if self.scanning or self.encoding_running:
            messagebox.showinfo("情報", "スキャンまたはエンコード中は仕分けできません。")
            return
        if not self._done_loaded:
            self.refresh_done_list()
        iids = list(self.done_tree.selection()) if selected_only else list(self.done_rows.keys())
        if selected_only and not iids:
            messagebox.showinfo("情報", "仕分ける行を選択してください(または「未仕分けをすべて仕分け」)。")
            return
        root = get_sort_root()
        plan: List[Tuple[Optional[str], str, str, str]] = []
        unknown = already = 0
        for iid in iids:
            row = self.done_rows.get(iid)
            if not row:
                continue
            if row["state"] == "sorted":
                already += 1
            elif row["state"] == "unknown":
                unknown += 1
            else:
                plan.append((None, row["path"], os.path.join(root, channel_folder_name(row["channel"])), row["channel"]))
        self._confirm_and_run_sort(
            plan,
            "選択中の" if selected_only else ("絞り込み表示中の未仕分けの" if self.done_filter_var.get().strip() else "未仕分けの"),
            unknown, 0, already,
            hint="※ チャンネル不明のものは、対になるcsvが無い、またはチャンネルを読めなかったファイルです。",
        )

    def _sort_worker(self, plan: List[Tuple[str, str, str, str]]):
        moved = 0
        renamed = 0
        errors: List[str] = []
        for index, (iid, video_path, dest_dir, _channel) in enumerate(plan, start=1):
            try:
                os.makedirs(dest_dir, exist_ok=True)
                stem, video_ext = os.path.splitext(os.path.basename(video_path))
                src_csv = os.path.join(os.path.dirname(video_path), stem + ".csv")
                target_stem, numbered = numbered_pair_target(dest_dir, stem, video_ext)
                new_video = os.path.join(dest_dir, target_stem + video_ext)
                shutil.move(video_path, new_video)
                if os.path.isfile(src_csv):
                    try:
                        shutil.move(src_csv, os.path.join(dest_dir, target_stem + ".csv"))
                    except OSError as e:
                        errors.append(f"{os.path.basename(src_csv)}(csv): {e}")
                moved += 1
                if numbered:
                    renamed += 1
                self._sort_queue.put(("moved", iid, video_path, new_video, index, len(plan)))
            except Exception as e:
                errors.append(f"{os.path.basename(video_path)}: {e}")
                self._sort_queue.put(("progress", index, len(plan)))
        self._sort_queue.put(("done", moved, renamed, errors))

    def _poll_sort_queue(self):
        finished = False
        try:
            while True:
                item = self._sort_queue.get_nowait()
                if item[0] == "moved":
                    _, iid, old_path, new_path, index, total = item
                    data = self.row_data.get(iid)
                    if data and data.get("output_path") == old_path:
                        data["output_path"] = new_path
                    for i, (src, out, label, issues) in enumerate(self.diagnostic_report):
                        if out == old_path:
                            self.diagnostic_report[i] = (src, new_path, label, issues)
                    self.status_var.set(f"仕分け中... ({index}/{total}件)")
                elif item[0] == "progress":
                    _, index, total = item
                    self.status_var.set(f"仕分け中... ({index}/{total}件)")
                elif item[0] == "done":
                    _, moved, renamed, errors = item
                    finished = True
                    self.scanning = False
                    self.sort_button.state(["!disabled"])
                    self.rescan_button.state(["!disabled"])
                    self.status_var.set(f"仕分け完了: {moved}件を移動しました。")
                    if getattr(self, "_done_loaded", False):
                        self.refresh_done_list()
                    message = f"{moved}件を仕分けしました。"
                    if renamed:
                        message += f"\n(同名のファイルがあったため、{renamed}件は番号を付けました)"
                    if errors:
                        text = "\n".join(errors[:10])
                        if len(errors) > 10:
                            text += f"\n...ほか{len(errors) - 10}件"
                        messagebox.showwarning("一部移動できませんでした", message + "\n\n" + text)
                    else:
                        messagebox.showinfo("仕分け完了", message)
                    if getattr(self, "_chain_series", False):
                        self._chain_series = False
                        self.after(100, self._open_series_sort)
        except queue.Empty:
            pass
        if not finished:
            self.after(100, self._poll_sort_queue)

    def _visible_iids(self) -> List[str]:
        """絞り込みで表示されている行(一覧の並び順)"""
        return [i for i in self.tree.get_children("") if i in self.row_data]

    def _select_all_rows(self):
        self.tree.selection_set(self._visible_iids())

    def _deselect_all_rows(self):
        self.tree.selection_remove(self._visible_iids())

    @staticmethod
    def _norm_search(text: str) -> str:
        """検索用に正規化する(全角/半角・大文字小文字・ひらがな/カタカナの違いを無視する)"""
        folded = unicodedata.normalize("NFKC", text or "").casefold()
        return "".join(chr(ord(ch) - 0x60) if "\u30a1" <= ch <= "\u30f6" else ch for ch in folded)

    def _row_matches(self, iid: str) -> bool:
        terms = self._norm_search(self.filter_var.get()).split()
        if not terms:
            return True
        data = self.row_data.get(iid)
        if not data:
            return False
        haystack = self._norm_search((data.get("program_name") or "") + " " + os.path.basename(data.get("path", "")))
        return all(t in haystack for t in terms)

    def _apply_filter(self):
        """番組名の絞り込みを反映する(合わない行は一覧から外す。並び順は保つ)"""
        self._row_order = [i for i in self._row_order if i in self.row_data and self.tree.exists(i)]
        selected = set(self.tree.selection())
        for iid in self._row_order:
            self.tree.detach(iid)
        visible = [i for i in self._row_order if self._row_matches(i)]
        for index, iid in enumerate(visible):
            self.tree.reattach(iid, "", index)
        keep = [i for i in visible if i in selected]
        if keep:
            self.tree.selection_set(keep)
        self._update_filter_count()

    def _update_filter_count(self):
        total = len(self._row_order)
        if self.filter_var.get().strip():
            self.filter_count_var.set(f"{len(self.tree.get_children(''))} / {total}件を表示")
        else:
            self.filter_count_var.set("")

    def _sort_by_column(self, col: str):
        """
        見出しクリックで指定列を昇順/降順にソートする(クリックするたびにトグル)。
        文字列として(大文字小文字を無視して)比較する。放送日は "YYYY/MM/DD" 形式
        で保持しているため、文字列比較のままで日付順と一致する。
        絞り込みで非表示の行も含めて並べ替える(絞り込みを解除したときも同じ順になる)。
        """
        ascending = not self._sort_state.get(col, False)
        self._sort_state = {col: ascending}

        order = [i for i in self._row_order if i in self.row_data and self.tree.exists(i)]
        order.sort(key=lambda iid: self.tree.set(iid, col).lower(), reverse=not ascending)
        self._row_order = order
        self._apply_filter()

        arrow = " ▲" if ascending else " ▼"
        for other_col, label in self._sortable_columns.items():
            self.tree.heading(other_col, text=label + (arrow if other_col == col else ""))

    def _refresh_channel_combo(self):
        """スキャン結果から見つかったチャンネル名の一覧をコンボボックスに反映する"""
        channels = sorted({data.get("channel", "") for data in self.row_data.values() if data.get("channel")})
        self.channel_combo["values"] = channels
        if self.channel_combo_var.get() not in channels:
            self.channel_combo_var.set(channels[0] if channels else "")

    def _select_rows_by_channel(self):
        channel = self.channel_combo_var.get()
        if not channel:
            messagebox.showinfo("情報", "チャンネルを選択してください。")
            return

        include_converted = self.channel_include_converted_var.get()
        matched_iids = [
            iid
            for iid in self._visible_iids()
            for data in [self.row_data[iid]]
            if data.get("channel") == channel and (include_converted or not data.get("converted"))
        ]
        if not matched_iids:
            if include_converted:
                messagebox.showinfo("情報", f"'{channel}' に一致するファイルが見つかりませんでした。")
            else:
                messagebox.showinfo(
                    "情報",
                    f"'{channel}' の未変換ファイルが見つかりませんでした。\n"
                    "(変換済みのファイルも選びたい場合は「変換済みも含める」にチェックしてください)",
                )
            return

        self.tree.selection_set(matched_iids)
        suffix = "" if include_converted else "(未変換のみ)"
        self.status_var.set(f"チャンネル '{channel}' の{len(matched_iids)}件を選択しました。{suffix}")

    # ------------------------------------------------------------------
    # 右クリックメニュー (元・エンコード後のファイルを再生/場所を開く / rplsから情報再取得)
    # ------------------------------------------------------------------
    def _on_tree_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self.row_data:
            return

        current_selection = self.tree.selection()
        if iid not in current_selection:
            # 右クリックした行が選択範囲外なら、その行だけを単独選択にする
            self.tree.selection_set([iid])
            current_selection = (iid,)
        self.tree.focus(iid)

        selected_iids = [i for i in current_selection if i in self.row_data]

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="元のファイルを再生", command=lambda: self._play_file(iid))
        menu.add_command(label="元のファイルの場所を開く", command=lambda: self._open_containing_folder(iid))
        output_path = self._find_existing_output(iid) if self.row_data[iid].get("converted") else None
        if output_path:
            menu.add_command(label="エンコード後のファイルを再生", command=lambda: self._launch_player(output_path))
            menu.add_command(label="エンコード後のファイルの場所を開く",
                             command=lambda: self._open_folder_for_path(output_path))
        else:
            menu.add_command(label="エンコード後のファイルを再生(まだありません)", state="disabled")
            menu.add_command(label="エンコード後のファイルの場所を開く(まだありません)", state="disabled")
        menu.add_separator()
        menu.add_command(label="エンコード診断を見る", command=lambda: self._show_diagnostic_for_row(iid))
        menu.add_separator()
        if len(selected_iids) > 1:
            menu.add_command(
                label=f"rplsから番組情報を再取得(BDAV用) - 選択中の{len(selected_iids)}件",
                command=lambda: self._fetch_info_from_rpls_bulk(selected_iids),
            )
        else:
            menu.add_command(
                label="rplsから番組情報を再取得(BDAV用)",
                command=lambda: self._fetch_info_from_rpls(iid),
            )
        menu.add_separator()
        noise_label = "ノイズ検査(ソフト/CUDA比較)を実行してCSVに記録"
        if len(selected_iids) > 1:
            noise_label += f" - 選択中の{len(selected_iids)}件"
        if not (self.encoding_running or self.scanning):
            menu.add_command(label=noise_label, command=lambda: self._begin_noise_check(selected_iids))
        else:
            menu.add_command(label=noise_label, state="disabled")
        reencode_menu = tk.Menu(menu, tearoff=0)
        for item in self._all_bat_entries():
            reencode_menu.add_command(
                label=item["name"],
                command=lambda n=item["name"]: self._reencode_with_bat(selected_iids, n),
            )
        label = "別のバッチで再エンコード"
        if len(selected_iids) > 1:
            label += f" - 選択中の{len(selected_iids)}件"
        if not (self.encoding_running or self.scanning):
            menu.add_cascade(label=label, menu=reencode_menu)
        else:
            menu.add_command(label=label, state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_noise_check_toggled(self):
        self.settings["noise_check"] = "1" if self.noise_check_var.get() else "0"
        save_settings(self.settings)

    def _open_containing_folder(self, iid: str):
        data = self.row_data.get(iid)
        if not data:
            return
        self._open_folder_for_path(data["path"])

    def _open_folder_for_path(self, path: Optional[str]):
        if not path or not os.path.isfile(path):
            messagebox.showerror("エラー", f"ファイルが見つかりません:\n{path}")
            return

        if sys.platform == "win32":
            try:
                # ファイルを選択した状態でエクスプローラーを開く(カンマを含む名前にも対応)
                reveal_in_explorer(path)
            except Exception:
                try:
                    os.startfile(os.path.dirname(path))
                except Exception as e:
                    messagebox.showerror("エラー", f"フォルダを開けませんでした:\n{e}")
        else:
            messagebox.showinfo("情報", f"このOSでは自動で開けません:\n{os.path.dirname(path)}")

    def _apply_noise_tag_to_output(self, output_path: str, seconds: float) -> Optional[str]:
        """
        エンコード後ファイルの名前の末尾(拡張子の直前)に「(27分22秒ノイズ)」のような
        タグを追記してリネームする。row_data / diagnostic_report 内の該当パスも
        あわせて更新する。成功したら新しいパスを、失敗したら None を返す。
        """
        tag = f"({format_minutes_seconds(seconds)}ノイズ)"
        return self._apply_tag_text_to_output(output_path, tag)

    def _apply_tag_text_to_output(self, output_path: str, tag: str, replace_noise_tags: bool = False) -> Optional[str]:
        """
        出力ファイル名の末尾(拡張子の直前)にtagを付けてリネームする。対になるcsvも同じ名前に揃える。
        replace_noise_tags=True なら、既に付いているノイズ関連のタグ((…ノイズ…))を外してから付け直す。
        成功したら新しいパスを、失敗したら None を返す。
        """
        if not output_path or not os.path.isfile(output_path):
            messagebox.showerror("エラー", f"ファイルが見つかりません:\n{output_path}")
            return None

        directory = os.path.dirname(output_path)
        base, ext = os.path.splitext(os.path.basename(output_path))

        if replace_noise_tags:
            base = re.sub(r"\([^()]*ノイズ[^()]*\)", "", base)
        elif tag in base:
            messagebox.showinfo("情報", "このタグは既にファイル名に付与されています。")
            return None

        new_path = os.path.join(directory, base + tag + ext)

        if new_path == output_path:
            messagebox.showinfo("情報", "このタグは既にファイル名に付与されています。")
            return None
        if os.path.exists(new_path):
            messagebox.showerror("エラー", f"同名のファイルが既に存在します:\n{new_path}")
            return None

        try:
            os.rename(output_path, new_path)
        except Exception as e:
            messagebox.showerror("エラー", f"リネームに失敗しました:\n{e}")
            return None

        # 対になるcsv(ノイズ検査の結果を記録したもの)も、同じ名前に揃えておく
        old_csv = os.path.splitext(output_path)[0] + ".csv"
        new_csv = os.path.splitext(new_path)[0] + ".csv"
        if old_csv != new_csv and os.path.isfile(old_csv) and not os.path.exists(new_csv):
            try:
                os.rename(old_csv, new_csv)
            except OSError:
                pass

        # 一覧・診断結果の記録内にある古いパスを新しいパスに更新しておく
        for data in self.row_data.values():
            if data.get("output_path") == output_path:
                data["output_path"] = new_path

        for index, (src, out, label, issues) in enumerate(self.diagnostic_report):
            if out == output_path:
                self.diagnostic_report[index] = (src, new_path, label, issues)

        self.status_var.set(f"'{os.path.basename(new_path)}' にリネームしました。")
        return new_path

    # ------------------------------------------------------------------
    # ノイズ検査(ソフト/CUDAデコードのフレーム比較)
    # ------------------------------------------------------------------
    def _run_noise_inspection(self, m2ts_path: str) -> Tuple[Optional[dict], str]:
        """
        元のm2tsを、ソフトウェアデコードとCUDAデコードの両方で全フレーム復号し、
        フレームごとのハッシュを比べる。戻り値は (比較結果, 実施できなかった理由)。
        検査に使う一時ファイル(.md5・ログ)は、終わったら必ず削除する。
        """
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return None, "ffmpegが見つかりません"
        avail = self._encoder_avail_ready()
        if avail is not None and not avail.get("nvenc"):
            return None, "NVIDIAのGPUが使えないため(CUDAデコードと比べる検査です)"

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        tmpdir = tempfile.mkdtemp(prefix="m2ts_noise_")
        try:
            md5_paths: Dict[str, str] = {}
            for kind, use_hw, label in (("sw", False, "ソフトウェアデコード"), ("hw", True, "CUDAデコード")):
                out_path = os.path.join(tmpdir, kind + ".md5")
                log_path = os.path.join(tmpdir, kind + ".log")
                cmd = [ffmpeg, "-v", "error", "-nostdin", "-nostats"]
                if use_hw:
                    cmd += ["-hwaccel", "cuda"]
                cmd += [
                    "-i", m2ts_path, "-map", "0:v:0", "-an", "-sn",
                    "-vf", "format=yuv420p", "-f", "framemd5", out_path,
                ]
                self.encode_queue.put(("log", f"[ノイズ検査] {label}で全フレームを復号中: {os.path.basename(m2ts_path)}"))
                with io.open(log_path, "wb") as log_file:
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=log_file,
                        creationflags=creationflags,
                    )
                    self._current_process = proc
                    try:
                        while True:
                            try:
                                proc.wait(timeout=0.5)
                                break
                            except subprocess.TimeoutExpired:
                                if self.stop_requested:
                                    kill_process_tree(proc)
                                    proc.wait()
                                    return None, "中断されました"
                    finally:
                        self._current_process = None
                if self.stop_requested:
                    return None, "中断されました"

                has_output = os.path.isfile(out_path) and os.path.getsize(out_path) > 0
                if use_hw and (proc.returncode != 0 or not has_output):
                    tail = ""
                    try:
                        with io.open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                            lines = [x.strip() for x in lf if x.strip()]
                        tail = lines[-1][:80] if lines else ""
                    except OSError:
                        pass
                    return None, f"CUDAデコードを実行できませんでした({tail})" if tail else "CUDAデコードを実行できませんでした"
                if not has_output:
                    return None, "ソフトウェアデコードで出力が得られませんでした"
                md5_paths[kind] = out_path

            return compare_framemd5(md5_paths["sw"], md5_paths["hw"]), ""
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _noise_inspect_and_record(
        self,
        m2ts_path: str,
        iid: str,
        output_path: str,
        diag_label: str,
        diag_issues: List[Tuple[str, int, List[Tuple[float, str]]]],
    ) -> Tuple[str, List[Tuple[str, int, List[Tuple[float, str]]]]]:
        """
        ノイズ検査を実行し、結果(ログ診断で見つかった怪しい秒数も含む)を、出力ファイルと対の
        csvの末尾に必ず記載する。記録が終わるまで、元のm2tsは削除対象から外す。
        戻り値は、検査結果を反映した (診断ラベル, 診断項目)。
        """
        data = self.row_data.get(iid, {})
        result: Optional[dict] = None
        reason = ""

        if self.noise_check_var.get():
            data["noise_state"] = "pending"
            self.encode_queue.put(("rowstatus", iid, "ノイズ検査中"))
            result, reason = self._run_noise_inspection(m2ts_path)
            if self.stop_requested:
                data["noise_state"] = "interrupted"
                self.encode_queue.put(("log", "[ノイズ検査] 中断されました(元ファイルは削除対象になりません)"))
                return diag_label, diag_issues
        else:
            reason = "設定でノイズ検査をOFFにしている"

        issues = [item for item in diag_issues if item[0] != _NOISE_DIFF_CATEGORY]
        hash_ranges: List[Tuple[float, float]] = []
        if result is not None and result.get("status") == "ok":
            hash_ranges = [(s, e) for s, e, _n in result["ranges"]]
            if result["ranges"]:
                entries = []
                for start, end, frames in result["ranges"][:_MAX_ENTRIES_PER_CATEGORY]:
                    span = f"約{end - start:.1f}秒間、" if end - start >= 1.0 else ""
                    entries.append((
                        start,
                        f"{_seconds_to_hms(start)} 付近 (〜{_seconds_to_hms(end)} {span}{frames}フレーム)",
                    ))
                issues.append((_NOISE_DIFF_CATEGORY, len(result["ranges"]), entries))
                if diag_label == "OK":
                    diag_label = "要確認"
            self.encode_queue.put((
                "log",
                f"[ノイズ検査] 全{result['total']}フレーム中 食い違い{result['bad_frames']}フレーム → "
                f"ノイズ区間{len(result['ranges'])}件",
            ))
        elif result is not None:
            self.encode_queue.put(("log", "[ノイズ検査] 両デコーダの出力が大きく異なり、比較できませんでした"))
        else:
            self.encode_queue.put(("log", f"[ノイズ検査] 実施できませんでした: {reason}"))

        self.noise_ranges[m2ts_path] = hash_ranges

        csv_path = os.path.splitext(output_path)[0] + ".csv"
        rows = build_noise_csv_rows(result, reason, issues, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            write_noise_block_to_csv(csv_path, rows)
            self.encode_queue.put(("log", f"[ノイズ検査] 結果をcsvに記録しました: {os.path.basename(csv_path)}"))
            data["noise_state"] = "done"
            data["noise_note"] = "検査済" if (result is not None and result.get("status") == "ok") else "ログのみ"
        except Exception as e:
            data["noise_state"] = "interrupted"
            self.encode_queue.put(("log", f"[ノイズ検査] csvへの記録に失敗しました(元ファイルは削除対象になりません): {e}"))

        return diag_label, issues

    def _begin_noise_check(self, iids: List[str]):
        """選択した行(エンコード済み)に対し、ノイズ検査だけを実行する"""
        if self.encoding_running or self.scanning:
            messagebox.showinfo("情報", "エンコード中・スキャン中は実行できません。")
            return
        targets = [iid for iid in iids if iid in self.row_data and self.row_data[iid]["path"].lower().endswith(".m2ts")]
        if not targets:
            messagebox.showinfo("情報", "ノイズ検査は、.m2tsファイルの行でのみ実行できます。")
            return
        if not self.noise_check_var.get():
            self.noise_check_var.set(True)
            self._on_noise_check_toggled()
        self.encoding_running = True
        self.stop_requested = False
        self._queue_kind = "noise"
        self.diagnostic_report = []
        self._set_controls_running(True)
        self._append_log(f"=== ノイズ検査開始 ({len(targets)}件) ===")
        thread = threading.Thread(target=self._noise_check_worker, args=(targets,), daemon=True)
        thread.start()
        self.after(100, self._poll_encode_queue)

    def _noise_check_worker(self, iids: List[str]):
        total = len(iids)
        for index, iid in enumerate(iids, start=1):
            if self.stop_requested:
                self.encode_queue.put(("stopped",))
                return
            data = self.row_data.get(iid)
            if not data:
                continue
            output_path = self._find_existing_output(iid)
            if not output_path:
                self.encode_queue.put(("log", f"[ノイズ検査] 変換済みファイルが見つからないためスキップ: {os.path.basename(data['path'])}"))
                continue
            previous_status = data.get("status", "")
            label = data.get("diag_label", "-")
            if label in ("-", ""):
                label = "OK"
            try:
                label, issues = self._noise_inspect_and_record(
                    data["path"], iid, output_path, label, data.get("diag_issues", [])
                )
            except Exception as e:
                self.encode_queue.put(("log", f"[ノイズ検査] 例外: {e}"))
                continue
            self.encode_queue.put(("diag", iid, label, issues, output_path))
            self.encode_queue.put(("rowstatus", iid, previous_status))
        self.encode_queue.put(("all_done",))

    def _get_player_path(self) -> Optional[str]:
        """
        再生ソフトの実行ファイルを返す。設定で選んだもの → (旧版の)VLCの設定 → 入っていればVLC の順に探す。
        どれも無ければNone(その場合はWindowsの既定のアプリで開く)。
        """
        for key in ("player_path", "vlc_path"):
            path = self.settings.get(key)
            if path and os.path.isfile(path):
                return path
        return find_vlc()

    # ---- エンコーダー(NVIDIA / Intel / AMD / CPU) ----
    def _detect_encoders_bg(self):
        """起動時に、使えるエンコーダーを裏で調べる(ffmpegが無ければ何もしない)"""
        self._encoder_avail_ready()
        try:
            self.after(0, self._apply_active_encoder)
        except Exception:
            pass

    def _encoder_avail_ready(self, force: bool = False) -> Optional[Dict[str, bool]]:
        """使えるエンコーダーの調べ結果(未調査なら、いま調べる)。ffmpegが無ければNone"""
        with self._encoder_lock:
            if self.encoder_avail is None or force:
                ffmpeg = find_ffmpeg()
                if not ffmpeg:
                    return None
                self.encoder_avail = detect_available_encoders(ffmpeg)
            return self.encoder_avail

    def _current_encoder(self) -> str:
        choice = self.settings.get("encoder", "auto")
        if choice == "auto":
            return resolve_encoder("auto", self.encoder_avail)
        return resolve_encoder(choice, None)

    def _apply_active_encoder(self):
        set_active_encoder(self._current_encoder())

    def _on_encoder_changed(self):
        self.settings["encoder"] = self.encoder_var.get()
        save_settings(self.settings)
        self._apply_active_encoder()
        label = _ENCODER_LABEL.get(self._current_encoder(), "")
        self.status_var.set(f"エンコーダー: {label}")

    def _show_available_encoders(self):
        self.status_var.set("使えるエンコーダーを調べています...")

        def worker():
            avail = self._encoder_avail_ready(force=True)
            self.after(0, lambda: done(avail))

        def done(avail):
            self._apply_active_encoder()
            self.status_var.set("")
            if avail is None:
                messagebox.showinfo("エンコーダー", "ffmpegが見つかりません。", parent=self)
                return
            lines = [f"{'○' if avail.get(k) else '×'} {_ENCODER_LABEL[k]}" for k in ENCODER_AUTO_ORDER]
            chosen = _ENCODER_LABEL.get(self._current_encoder(), "")
            messagebox.showinfo(
                "使えるエンコーダー",
                "ffmpegで、短い映像を実際にエンコードして調べました。\n\n" + "\n".join(lines)
                + f"\n\n今使うもの: {chosen}\n(「自動」のときは、上から順に、使える最初のものを選びます)",
                parent=self,
            )

        threading.Thread(target=worker, daemon=True).start()

    def _choose_player(self):
        selected = filedialog.askopenfilename(
            title="再生に使うソフトの実行ファイルを選択",
            filetypes=[("実行ファイル", "*.exe"), ("すべてのファイル", "*.*")],
        )
        if not selected:
            return
        self.settings["player_path"] = selected
        save_settings(self.settings)
        messagebox.showinfo(
            "再生ソフト",
            f"{os.path.basename(selected)} を再生に使います。\n"
            + ("時刻を指定して再生できるソフトです。" if player_seek_args(selected, 1.0) is not None
               else "このソフトは時刻の指定に対応していないため、時刻からの再生では、ファイルを開くだけになります。"),
            parent=self,
        )

    def _reset_player(self):
        self.settings.pop("player_path", None)
        self.settings.pop("vlc_path", None)
        save_settings(self.settings)
        messagebox.showinfo(
            "再生ソフト",
            "再生ソフトの指定を解除しました。\nVLCが入っていればVLCで、無ければWindowsの既定のアプリで開きます。",
            parent=self,
        )

    def _launch_player(self, path: str, start_seconds: Optional[float] = None):
        player = self._get_player_path()
        if not player:
            # 再生ソフトが指定されていない(VLCも無い)ときは、Windowsの既定のアプリで開く
            try:
                if sys.platform == "win32":
                    os.startfile(path)  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("エラー", f"ファイルを開けませんでした:\n{e}")
                return
            if start_seconds is not None:
                self._append_log(
                    f"[再生] 再生ソフトが未指定のため、既定のアプリで開きました。{format_minutes_seconds(start_seconds)}付近へは、"
                    "手で移動してください(メニュー「設定」→「再生ソフトを選ぶ」で、時刻指定ができるソフトを選べます)。")
            return
        cmd = [player, path]
        if start_seconds is not None:
            extra = player_seek_args(player, start_seconds)
            if extra is None:
                self._append_log(
                    f"[再生] {os.path.basename(player)} は時刻の指定に対応していないため、ファイルを開くだけにしました。"
                    f"{format_minutes_seconds(start_seconds)}付近へは、手で移動してください。")
            else:
                cmd += extra
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            messagebox.showerror("エラー", f"再生ソフトを起動できませんでした:\n{e}")

    def _play_file(self, iid: str):
        data = self.row_data.get(iid)
        if not data:
            return
        self._launch_player(data["path"])

    def _play_file_at(self, path: Optional[str], seconds: float):
        if not path or not os.path.isfile(path):
            messagebox.showerror("エラー", f"ファイルが見つかりません:\n{path}")
            return
        self._launch_player(path, seconds)

    def _apply_rpls_info_to_row(self, iid: str) -> Tuple[bool, str]:
        """
        BDAV構成(.../<番号>/STREAM/xxxxx.m2ts, .../<番号>/PLAYLIST/xxxxx.rpls)の
        場合に、STREAM内のm2tsに対応する同名のrplsファイルをPLAYLISTフォルダから
        探して情報を取得しなおす。m2ts単体からはタイトルが取得できない場合の救済策。
        成功した行には info_source_path を記録し、以後のエンコード時にも
        (対応するバッチが対応していれば)rplsの方を情報取得元として使わせる。
        戻り値: (成功したか, メッセージ)
        """
        data = self.row_data.get(iid)
        if not data:
            return False, "行データが見つかりません"
        m2ts_path = data["path"]

        stream_dir = os.path.dirname(m2ts_path)
        rpls_path = find_paired_rpls(m2ts_path)

        if not rpls_path:
            return False, (
                "対応するrplsファイルが見つかりません: "
                + os.path.join(os.path.dirname(stream_dir), "PLAYLIST", os.path.splitext(os.path.basename(m2ts_path))[0] + ".rpls")
            )

        if not self.rplsinfo_path:
            self.rplsinfo_path = find_rplsinfo()
        if not self.rplsinfo_path:
            return False, "rplsinfo.exe が見つかりません"

        info = get_program_info(self.rplsinfo_path, rpls_path)
        if info is None:
            return False, "rplsファイルから情報を取得できませんでした"

        _, program_name, channel_name, broadcast_date = info
        if not channel_name:
            channel_name = "(不明)"

        converted = is_source_converted(
            stream_dir, os.path.basename(m2ts_path), program_name,
            date_digits=normalize_date_digits(broadcast_date),
        )
        mark = "〇" if converted else "✕"
        tag = "converted_yes" if converted else "converted_no"

        data["program_name"] = program_name
        data["channel"] = channel_name
        data["broadcast_date"] = broadcast_date
        data["converted"] = converted
        data["info_source_path"] = rpls_path
        self.tree.set(iid, "program_name", program_name)
        self.tree.set(iid, "channel", channel_name)
        self.tree.set(iid, "broadcast_date", broadcast_date)
        self.tree.set(iid, "converted", mark)
        self.tree.item(iid, tags=(tag,))
        return True, "OK"

    def _fetch_info_from_rpls(self, iid: str):
        success, message = self._apply_rpls_info_to_row(iid)
        if success:
            data = self.row_data.get(iid)
            base_name = os.path.basename(data["path"]) if data else iid
            self.status_var.set(f"'{base_name}' の情報をrplsから再取得しました。")
            self._refresh_channel_combo()
        else:
            messagebox.showerror("エラー", message)

    def _fetch_info_from_rpls_bulk(self, iids: List[str]):
        success_count = 0
        failures = []
        for iid in iids:
            ok, message = self._apply_rpls_info_to_row(iid)
            if ok:
                success_count += 1
            else:
                data = self.row_data.get(iid)
                base_name = os.path.basename(data["path"]) if data else iid
                failures.append(f"{base_name}: {message}")

        self.status_var.set(f"{success_count}/{len(iids)}件、rplsから情報を再取得しました。")

        if success_count > 0:
            self._refresh_channel_combo()

        if failures:
            text = "\n".join(failures[:15])
            if len(failures) > 15:
                text += f"\n...ほか{len(failures) - 15}件"
            messagebox.showwarning(
                "一部取得できませんでした",
                f"{success_count}/{len(iids)}件は成功しました。\n\n以下は失敗しました:\n{text}",
            )

    def _refresh_row_values(self, iid: str):
        data = self.row_data[iid]
        bat_display = data["bat_name"] or "(未設定)"
        self.tree.set(iid, "bat", bat_display)
        self.tree.set(iid, "status", data["status"])

        diag_label = data.get("diag_label", "-")
        diag_issues = data.get("diag_issues", [])
        if data.get("noise_state") == "pending":
            diag_display = "ノイズ検査中"
        elif diag_label == "-":
            diag_display = "-"
        elif diag_label == "OK":
            diag_display = "OK(検査済)" if data.get("noise_note") == "検査済" else "OK"
        else:
            total_count = sum(count for _category, count, _entries in diag_issues)
            diag_display = f"{diag_label}({total_count}件)"
        self.tree.set(iid, "diag", diag_display)

    # ------------------------------------------------------------------
    # バッチ管理
    # ------------------------------------------------------------------
    def _preset_options_map(self) -> Dict[str, Dict[str, object]]:
        """プリセット名 -> 設定。組み込み(読み取り専用)+ユーザー保存分(同名ならユーザー側を優先)"""
        result: Dict[str, Dict[str, object]] = {name: opts for name, opts in BUILTIN_PRESETS}
        user = self.settings.get("user_presets")
        if isinstance(user, dict):
            for name, opts in user.items():
                if isinstance(opts, dict):
                    result[str(name)] = opts
        return result

    def _all_bat_entries(self) -> List[Dict[str, str]]:
        """バッチ + エンコード設定(プリセット)を、割り当て用の一覧として返す"""
        entries: List[Dict[str, str]] = []
        for name in self._preset_options_map():  # おまかせ → 組み込み設定 → 自作設定 の順
            entries.append({"name": PRESET_LABEL + name, "path": PRESET_PREFIX + name})
        for item in self.bat_scripts:  # 最後に、従来のバッチ
            entries.append({"name": BAT_LABEL + item["name"], "path": item["path"]})
        return entries

    def _refresh_bat_combo(self):
        entries = self._all_bat_entries()
        names = [item["name"] for item in entries]
        self.bat_combo["values"] = names
        self.bat_name_to_path = {item["name"]: item["path"] for item in entries}
        if self.bat_combo_var.get() not in names:
            self.bat_combo_var.set(names[0] if names else "")

    def apply_bat_to_checked(self):
        bat_name = self.bat_combo_var.get()
        if not bat_name:
            messagebox.showinfo("情報", "適用する設定がありません。メニューの「設定」から登録してください。")
            return
        bat_path = self.bat_name_to_path.get(bat_name)
        if not bat_path:
            return

        checked_iids = list(self.tree.selection())
        if not checked_iids:
            messagebox.showinfo("情報", "リストの行を選択してください(Ctrl+クリックで複数選択できます)。")
            return

        for iid in checked_iids:
            self.row_data[iid]["bat_path"] = bat_path
            self.row_data[iid]["bat_name"] = bat_name
            self._refresh_row_values(iid)

        self.status_var.set(f"{len(checked_iids)}件に '{bat_name}' を割り当てました。")

    def _clear_bat(self, iids) -> int:
        """指定した行に割り当てた設定を外す。外した件数を返す"""
        count = 0
        for iid in iids:
            data = self.row_data.get(iid)
            if data and data.get("bat_path"):
                data["bat_path"] = None
                data["bat_name"] = None
                self._refresh_row_values(iid)
                count += 1
        return count

    def clear_bat_from_selected(self):
        if self.encoding_running:
            return
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo("情報", "解除する行を選択してください。")
            return
        count = self._clear_bat(selected)
        self.status_var.set(f"{count}件の設定を解除しました。" if count else "選択した行に割り当てた設定はありません。")

    def clear_bat_from_all(self):
        if self.encoding_running:
            return
        count = self._clear_bat(list(self.tree.get_children()))
        self.status_var.set(f"{count}件の設定をすべて解除しました。" if count else "割り当てた設定はありません。")

    def open_settings_editor(self, tab: str = "preset"):
        """エンコード設定とバッチの管理を、1つの画面のタブにまとめたもの"""
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_set()
                    return
            except tk.TclError:
                pass
        dialog = tk.Toplevel(self)
        self._settings_dialog = dialog
        dialog.title("設定の編集")
        dialog.geometry("1060x640")
        dialog.transient(self)
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill=tk.BOTH, expand=True)
        preset_tab = ttk.Frame(notebook)
        bat_tab = ttk.Frame(notebook)
        notebook.add(preset_tab, text="エンコード設定(チェックボックスで作る)")
        notebook.add(bat_tab, text="バッチファイル(上級者向け)")
        self.open_preset_editor(host=preset_tab)
        self.open_bat_manager(host=bat_tab)
        if tab == "bat":
            notebook.select(bat_tab)

    def open_preset_editor(self, host=None):
        """チェックボックスでエンコード設定を組み立てる(ffmpegコマンドをその場でプレビュー)"""
        if host is None:
            dialog = tk.Toplevel(self)
            dialog.title("エンコード設定")
            dialog.geometry("900x560")
            dialog.transient(self)
            host = dialog
        else:
            dialog = host.winfo_toplevel()

        builtin_names = [name for name, _ in BUILTIN_PRESETS]

        left = ttk.Frame(host, padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left, text="設定一覧(★=組み込み)").pack(anchor=tk.W)
        listbox = tk.Listbox(left, width=44, height=20, exportselection=False)
        listbox.pack(fill=tk.Y, expand=True)

        right = ttk.Frame(host, padding=8)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        name_var = tk.StringVar()
        container_var = tk.StringVar(value="mkv")
        audio_var = tk.StringVar(value="copy")
        deint_var = tk.StringVar(value="none")
        catv_var = tk.BooleanVar()
        subs_var = tk.BooleanVar()
        cuda_var = tk.BooleanVar()
        hvc1_var = tk.BooleanVar()
        aspect_var = tk.BooleanVar(value=True)
        qp_var = tk.StringVar(value="32")
        first_audio_var = tk.BooleanVar()
        auto_var = tk.BooleanVar()
        auto_select_var = tk.BooleanVar()

        name_row = ttk.Frame(right)
        name_row.pack(fill=tk.X)
        ttk.Label(name_row, text="名前:").pack(side=tk.LEFT)
        ttk.Entry(name_row, textvariable=name_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        ttk.Checkbutton(
            right, text="おまかせ(ファイルごとに全部自動で決める。下の項目は、ffprobeが使えない時だけ使われます)",
            variable=auto_select_var,
        ).pack(anchor=tk.W, pady=(6, 0))

        def group(title):
            frame = ttk.LabelFrame(right, text=title, padding=6)
            frame.pack(fill=tk.X, pady=(6, 0))
            return frame

        g = group("出力形式")
        ttk.Radiobutton(g, text="mkv(ARIB字幕を入れられる)", variable=container_var, value="mkv").pack(side=tk.LEFT)
        ttk.Radiobutton(g, text="mp4", variable=container_var, value="mp4").pack(side=tk.LEFT, padx=12)
        subs_check = ttk.Checkbutton(g, text="ARIB字幕を入れる(mkvのみ)", variable=subs_var)
        subs_check.pack(side=tk.LEFT, padx=12)
        postmux_var = tk.BooleanVar(value=False)
        postmux_check = ttk.Checkbutton(
            g, text="字幕は最後に合体(試験的)", variable=postmux_var
        )
        postmux_check.pack(side=tk.LEFT, padx=4)

        g = group("録画の種類")
        ttk.Checkbutton(
            g, text="CATVの録画(scan_all_pmts等の読み込み設定を付ける)", variable=catv_var
        ).pack(anchor=tk.W)
        ttk.Radiobutton(g, text="ステレオ/二か国語をそのまま(language=jpn/eng)",
                        variable=audio_var, value="copy").pack(anchor=tk.W)
        ttk.Radiobutton(g, text="モノラル二か国語を 主音声/副音声/主副 に分離(AAC)",
                        variable=audio_var, value="mono").pack(anchor=tk.W)

        ttk.Checkbutton(
            g, text="音声は1本目だけ使う(存在しない音声で失敗する番組用)",
            variable=first_audio_var,
        ).pack(anchor=tk.W)

        ttk.Checkbutton(
            g, text="ffprobeで調べて、空の字幕・存在しない音声を自動で外す(数十秒かかる)",
            variable=auto_var,
        ).pack(anchor=tk.W)

        g = group("映像")
        ttk.Label(g, text="インターレース解除:").pack(side=tk.LEFT)
        for label, value in (("なし", "none"), ("yadif=1", "yadif"), ("bwdif=1", "bwdif")):
            ttk.Radiobutton(g, text=label, variable=deint_var, value=value).pack(side=tk.LEFT, padx=6)
        ttk.Label(g, text="  QP:").pack(side=tk.LEFT)
        ttk.Spinbox(g, from_=0, to=51, width=4, textvariable=qp_var).pack(side=tk.LEFT)
        g2 = ttk.Frame(right)
        g2.pack(fill=tk.X, pady=(4, 0))
        ttk.Checkbutton(g2, text="CUDA(GPU)でデコードする(ソフトウェアデコードのノイズ対策)",
                        variable=cuda_var).pack(anchor=tk.W)
        ttk.Checkbutton(g2, text="-aspect 16:9 を指定", variable=aspect_var).pack(anchor=tk.W)
        hvc1_check = ttk.Checkbutton(g2, text="mp4に hvc1 タグを付ける(iPhone/Mac等で再生する場合)", variable=hvc1_var)
        hvc1_check.pack(anchor=tk.W)

        ttk.Label(right, text="生成されるffmpegコマンド:").pack(anchor=tk.W, pady=(8, 0))
        preview = tk.Text(right, height=7, wrap="word", font=("Consolas", 9))
        preview.pack(fill=tk.BOTH, expand=True)

        def current_options() -> Dict[str, object]:
            return normalize_encode_options({
                "container": container_var.get(), "catv": catv_var.get(), "subs": subs_var.get(),
                "audio": audio_var.get(), "deint": deint_var.get(), "cuda": cuda_var.get(),
                "hvc1": hvc1_var.get(), "aspect": aspect_var.get(), "qp": qp_var.get() or 32,
                "audio_tracks": "first" if first_audio_var.get() else "all",
                "auto": auto_var.get(), "auto_select": auto_select_var.get(),
                "sub_postmux": postmux_var.get(),
            })

        def update_preview(*_args):
            is_mkv = container_var.get() == "mkv"
            subs_check.configure(state="normal" if is_mkv else "disabled")
            postmux_check.configure(state="normal" if is_mkv and subs_var.get() else "disabled")
            hvc1_check.configure(state="normal" if not is_mkv else "disabled")
            if not is_mkv:
                subs_var.set(False)
            command, _ext = build_ffmpeg_command(current_options())
            postmux_command = build_postmux_command(current_options())
            if postmux_command:
                command += "\n\n(エンコード後、字幕だけを合体)\n" + postmux_command
            preview.configure(state="normal")
            preview.delete("1.0", tk.END)
            preview.insert("1.0", command)
            preview.configure(state="disabled")

        for var in (container_var, audio_var, deint_var, catv_var, subs_var, cuda_var, hvc1_var,
                    aspect_var, qp_var, first_audio_var, auto_var, auto_select_var,
                    postmux_var):
            var.trace_add("write", update_preview)

        def load_options(options):
            o = normalize_encode_options(options)
            container_var.set(str(o["container"]))
            audio_var.set(str(o["audio"]))
            deint_var.set(str(o["deint"]))
            catv_var.set(bool(o["catv"]))
            subs_var.set(bool(o["subs"]))
            cuda_var.set(bool(o["cuda"]))
            hvc1_var.set(bool(o["hvc1"]))
            aspect_var.set(bool(o["aspect"]))
            qp_var.set(str(o["qp"]))
            first_audio_var.set(o["audio_tracks"] == "first")
            auto_var.set(bool(o["auto"]))
            auto_select_var.set(bool(o["auto_select"]))
            postmux_var.set(bool(o["sub_postmux"]))
            update_preview()

        names_in_list: List[str] = []

        def refill(select: Optional[str] = None):
            options_map = self._preset_options_map()
            user = self.settings.get("user_presets") if isinstance(self.settings.get("user_presets"), dict) else {}
            names_in_list[:] = list(options_map.keys())
            listbox.delete(0, tk.END)
            for name in names_in_list:
                mark = "★ " if (name in builtin_names and name not in user) else "   "
                listbox.insert(tk.END, mark + name)
            if select in names_in_list:
                index = names_in_list.index(select)
                listbox.selection_set(index)
                listbox.see(index)

        def on_select(_event=None):
            sel = listbox.curselection()
            if not sel:
                return
            name = names_in_list[sel[0]]
            name_var.set(name)
            load_options(self._preset_options_map()[name])

        listbox.bind("<<ListboxSelect>>", on_select)

        def save_preset():
            name = name_var.get().strip()
            if not name:
                messagebox.showinfo("情報", "名前を入力してください。", parent=dialog)
                return
            user = self.settings.get("user_presets")
            if not isinstance(user, dict):
                user = {}
            if name in builtin_names and name not in user:
                messagebox.showinfo(
                    "情報", "組み込みの設定は上書きできません。別の名前を付けて保存してください。", parent=dialog
                )
                return
            user[name] = current_options()
            self.settings["user_presets"] = user
            save_settings(self.settings)
            self._refresh_bat_combo()
            refill(name)

        def delete_preset():
            sel = listbox.curselection()
            if not sel:
                return
            name = names_in_list[sel[0]]
            user = self.settings.get("user_presets")
            if not isinstance(user, dict) or name not in user:
                messagebox.showinfo("情報", "組み込みの設定は削除できません。", parent=dialog)
                return
            if not messagebox.askyesno("確認", f"「{name}」を削除しますか?", parent=dialog):
                return
            user.pop(name)
            self.settings["user_presets"] = user
            save_settings(self.settings)
            self._refresh_bat_combo()
            refill()

        def apply_to_selection():
            name = name_var.get().strip()
            options_map = self._preset_options_map()
            if name not in options_map or normalize_encode_options(options_map[name]) != current_options():
                # 未保存の変更がある/新しい名前 → 保存してから適用
                save_preset()
                options_map = self._preset_options_map()
                if name not in options_map:
                    return
            self.bat_combo_var.set(PRESET_LABEL + name)
            self.apply_bat_to_checked()

        buttons = ttk.Frame(right)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="この名前で保存", command=save_preset).pack(side=tk.LEFT)
        ttk.Button(buttons, text="削除", command=delete_preset).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="保存して選択行に適用", command=apply_to_selection).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="閉じる", command=dialog.destroy).pack(side=tk.RIGHT, padx=6)

        refill(names_in_list[0] if names_in_list else None)
        first = self._preset_options_map()
        if first:
            first_name = list(first.keys())[0]
            refill(first_name)
            name_var.set(first_name)
            load_options(first[first_name])

    def open_bat_manager(self, host=None):
        if host is None:
            dialog = tk.Toplevel(self)
            dialog.title("バッチファイル管理")
            dialog.geometry("640x400")
            dialog.transient(self)
            dialog.grab_set()
            host = dialog
        else:
            dialog = host.winfo_toplevel()

        listbox = tk.Listbox(host, activestyle="dotbox")
        listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        def refresh_listbox():
            listbox.delete(0, tk.END)
            for item in self.bat_scripts:
                if item["path"].startswith(EMBEDDED_BAT_PREFIX):
                    path_display = "(組み込み・ファイル生成なし)"
                else:
                    path_display = item["path"]
                listbox.insert(tk.END, f"{item['name']}   —   {path_display}")

        refresh_listbox()

        ttk.Label(
            host,
            text=(
                "「(組み込み・ファイル生成なし)」の項目は同梱の既定バッチです。実行時に一時ファイルとして"
                "展開し、終わったら削除するため、AppDataやフォルダ内に永続的なファイルは作成されません。"
            ),
            padding=(8, 0, 8, 4),
            wraplength=600,
        ).pack(fill=tk.X)

        button_frame = ttk.Frame(host, padding=8)
        button_frame.pack(fill=tk.X)

        def add_bat():
            path = filedialog.askopenfilename(
                title="バッチファイルを選択",
                filetypes=[("バッチファイル", "*.bat"), ("すべてのファイル", "*.*")],
                parent=dialog,
            )
            if not path:
                return
            default_name = os.path.splitext(os.path.basename(path))[0]
            name = simpledialog.askstring(
                "名前を入力", "リストに表示する名前:", initialvalue=default_name, parent=dialog
            )
            if not name:
                name = default_name
            self.bat_scripts.append({"name": name, "path": path})
            save_bat_scripts(self.bat_scripts)
            refresh_listbox()
            self._refresh_bat_combo()

        def remove_bat():
            sel = listbox.curselection()
            if not sel:
                return
            index = sel[0]
            self.bat_scripts.pop(index)
            save_bat_scripts(self.bat_scripts)
            refresh_listbox()
            self._refresh_bat_combo()

        def edit_bat():
            sel = listbox.curselection()
            if not sel:
                return
            index = sel[0]
            item = self.bat_scripts[index]
            path = item["path"]

            if path.startswith(EMBEDDED_BAT_PREFIX):
                # 組み込みバッチには実ファイルが無いため、まず保存先を選んでもらい、
                # 書き出したうえでその場所を今後の実行対象として登録し直す
                key = path[len(EMBEDDED_BAT_PREFIX):]
                content = DEFAULT_BAT_SCRIPTS.get(key)
                if content is None:
                    messagebox.showerror("エラー", "組み込みバッチの内容が見つかりません。", parent=dialog)
                    return
                export_path = filedialog.asksaveasfilename(
                    title="編集用に保存する場所を選択",
                    initialfile=key,
                    defaultextension=".bat",
                    filetypes=[("バッチファイル", "*.bat"), ("すべてのファイル", "*.*")],
                    parent=dialog,
                )
                if not export_path:
                    return
                try:
                    # UTF-8で保存する(ffmpegのメタデータ引数(主音声/副音声等)がchcp 65001区間で
                    # 正しく渡るようにするため)。全角コロン置換は使わず半角ハイフンにしているので
                    # コードページ起因の文字化けは発生しない。
                    with io.open(export_path, "w", encoding="utf-8", newline="\r\n") as f:
                        f.write(content)
                except Exception as e:
                    messagebox.showerror("エラー", f"保存に失敗しました:\n{e}", parent=dialog)
                    return

                item["path"] = export_path
                save_bat_scripts(self.bat_scripts)
                refresh_listbox()
                self._refresh_bat_combo()
                messagebox.showinfo(
                    "保存しました",
                    f"'{export_path}' に保存しました。\n"
                    "これ以降、このバッチはこのファイルを使って実行されます。",
                    parent=dialog,
                )
                path = export_path

            if not os.path.isfile(path):
                messagebox.showerror("エラー", "ファイルが見つかりません。", parent=dialog)
                return
            try:
                if sys.platform == "win32":
                    # os.startfile(path) だと既定の動作(=バッチの実行)になってしまうため、
                    # メモ帳を明示的に指定して開く
                    subprocess.Popen(["notepad.exe", path])
                else:
                    messagebox.showinfo("情報", f"このOSでは自動で開けません:\n{path}", parent=dialog)
            except Exception as e:
                messagebox.showerror("エラー", f"開けませんでした:\n{e}", parent=dialog)

        def rename_bat():
            sel = listbox.curselection()
            if not sel:
                return
            index = sel[0]
            current_name = self.bat_scripts[index]["name"]
            new_name = simpledialog.askstring(
                "名前を変更", "新しい表示名:", initialvalue=current_name, parent=dialog
            )
            if not new_name:
                return
            self.bat_scripts[index]["name"] = new_name
            save_bat_scripts(self.bat_scripts)
            refresh_listbox()
            self._refresh_bat_combo()

        def reset_defaults_to_embedded():
            default_names = {os.path.splitext(filename)[0] for filename in DEFAULT_BAT_SCRIPTS}
            targets = [item for item in self.bat_scripts if item["name"] in default_names]
            if not targets:
                messagebox.showinfo("情報", "リセット対象の既定バッチが見つかりません。", parent=dialog)
                return

            confirmed = messagebox.askyesno(
                "確認",
                f"以下の{len(targets)}件を、実ファイルを使わない組み込み方式に戻します。\n"
                "(実ファイル自体は削除されず、そのまま残ります。不要であれば手動で削除してください)\n\n"
                + "\n".join(item["name"] for item in targets)
                + "\n\n続行しますか?",
                parent=dialog,
            )
            if not confirmed:
                return

            self.bat_scripts = [item for item in self.bat_scripts if item["name"] not in default_names]
            self.bat_scripts = register_embedded_defaults(self.bat_scripts)
            save_bat_scripts(self.bat_scripts)
            refresh_listbox()
            self._refresh_bat_combo()
            messagebox.showinfo("完了", f"{len(targets)}件を組み込み方式に戻しました。", parent=dialog)

        ttk.Button(button_frame, text="追加...", command=add_bat).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="削除", command=remove_bat).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_frame, text="編集...", command=edit_bat).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_frame, text="名前変更", command=rename_bat).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(button_frame, text="閉じる", command=dialog.destroy).pack(side=tk.RIGHT)

        maintenance_frame = ttk.Frame(host, padding=(8, 0, 8, 8))
        maintenance_frame.pack(fill=tk.X)
        def export_defaults_to_folder():
            folder = filedialog.askdirectory(title="既定バッチの出力先フォルダを選択", parent=dialog)
            if not folder:
                return

            written = []
            errors = []
            for filename, content in DEFAULT_BAT_SCRIPTS.items():
                target_path = os.path.join(folder, filename)
                try:
                    # UTF-8で保存する(理由は edit_bat 側のコメント参照)
                    with io.open(target_path, "w", encoding="utf-8", newline="\r\n") as f:
                        f.write(content)
                    written.append(filename)
                except Exception as e:
                    errors.append(f"{filename}: {e}")

            message = f"{len(written)}/{len(DEFAULT_BAT_SCRIPTS)}件を出力しました。\n出力先: {folder}\n\n"
            message += (
                "これらは最新版(修正済み)の内容です。既存の古い実ファイル(例: AppDataのencode_scripts内)を"
                "上書きしたい場合は、出力したファイルで置き換えてください。\n"
                "(このアプリ自体の登録を変更するものではありません。登録を組み込み方式に戻すには"
                "上の「既定バッチを組み込み方式に戻す」を使ってください)"
            )
            if errors:
                message += "\n\n失敗:\n" + "\n".join(errors)
                messagebox.showwarning("一部失敗しました", message, parent=dialog)
            else:
                messagebox.showinfo("完了", message, parent=dialog)

        ttk.Button(
            maintenance_frame, text="既定バッチを組み込み方式に戻す", command=reset_defaults_to_embedded
        ).pack(side=tk.LEFT)
        ttk.Button(
            maintenance_frame, text="既定バッチを任意のフォルダに出力...", command=export_defaults_to_folder
        ).pack(side=tk.LEFT, padx=(6, 0))

    # ------------------------------------------------------------------
    # エンコードキュー
    # ------------------------------------------------------------------
    def _save_log_as(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="ログを保存", defaultextension=".txt",
            initialfile=f"{datetime.datetime.now():%Y%m%d-%H%M%S}_実行ログ.txt",
            filetypes=[("テキスト", "*.txt")],
        )
        if not path:
            return
        try:
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.log_text.get("1.0", tk.END))
        except OSError as e:
            messagebox.showerror("エラー", f"保存できませんでした: {e}")

    # ---- アップデート ----
    def _on_split_toggled(self):
        self.settings["tssplitter_split"] = "1" if self.split_var.get() else "0"
        save_settings(self.settings)

    def _on_force_cuda_toggled(self):
        self.settings["force_cuda"] = "1" if self.force_cuda_var.get() else "0"
        save_settings(self.settings)

    def _on_auto_update_toggled(self):
        self.settings["auto_update_check"] = "1" if self.auto_update_var.get() else "0"
        save_settings(self.settings)

    def _open_menu_guide(self):
        win = getattr(self, "_guide_win", None)
        try:
            if win is not None and win.winfo_exists():
                win.lift()
                win.focus_force()
                return
        except tk.TclError:
            pass
        self._guide_win = MenuGuideWindow(self)

    def _open_backup_manager(self):
        win = getattr(self, "_backup_win", None)
        try:
            if win is not None and win.winfo_exists():
                win.lift()
                win.focus_force()
                return
        except tk.TclError:
            pass
        self._backup_win = BackupManagerWindow(self)

    def _show_about(self):
        messagebox.showinfo(
            "バージョン情報",
            f"m2ts エンコーダー\nバージョン {APP_VERSION}\n\n配布元: https://github.com/tatata17/m2ts-encoder",
            parent=self,
        )

    def check_for_update(self, manual: bool = False, startup: bool = False):
        """バックグラウンドで更新を確認する。manual=Trueは結果を必ずダイアログで知らせる"""
        if getattr(self, "_update_checking", False):
            return
        self._update_checking = True
        result_queue: "queue.Queue" = queue.Queue()

        def worker():
            try:
                result_queue.put(("ok", fetch_update_info()))
            except Exception as e:
                result_queue.put(("err", e))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                kind, value = result_queue.get_nowait()
            except queue.Empty:
                self.after(300, poll)
                return
            self._update_checking = False
            if startup:
                self._update_decided = True
            if kind == "err":
                if startup:
                    self._start_scan_once()
                if manual:
                    messagebox.showerror("アップデート", f"更新の確認に失敗しました。\nネットワークに接続できているか確認してください。\n\n{value}", parent=self)
                return
            info = value
            if not is_newer_version(str(info["version"])):
                if startup:
                    self._start_scan_once()
                if manual:
                    messagebox.showinfo("アップデート", f"最新の版です。(バージョン {APP_VERSION})", parent=self)
                return
            try:
                self._help_menu.entryconfig(0, label=f"アップデートを確認... (新しい版 {info['version']} があります)")
            except Exception:
                pass
            if not manual:
                self._append_log(f"[アップデート] 新しい版 {info['version']} があります。メニュー「ヘルプ」→「アップデートを確認」から更新できます。")
                if self.encoding_running:
                    return   # エンコード中は邪魔しない(ログとメニューの表示だけ)
                if self.scanning:
                    self._pending_update_info = info   # スキャンが終わってから案内を出す
                    return
                updating = self._confirm_and_update(info)   # 起動時の確認でも、更新の案内を自動で出す
                if startup and not updating:
                    self._start_scan_once()   # 更新しない場合は、案内に答えたあとでスキャンを始める
                return
            self._confirm_and_update(info)

        self.after(300, poll)

    def _confirm_and_update(self, info: Dict[str, object]) -> bool:
        """更新の案内を出し、更新を始めたらTrue(しない・できないならFalse)を返す"""
        if self.encoding_running:
            messagebox.showinfo("アップデート", "エンコード中は更新できません。終わってからやり直してください。", parent=self)
            return False
        notes = str(info.get("notes", "")).strip() or "(細かい修正です。詳しくは、更新履歴(GitHubの CHANGELOG.md)を見てください)"
        if not messagebox.askyesno(
            "アップデート",
            f"新しい版があります。\n\n現在: {APP_VERSION}\n最新: {info['version']}\n\n【更新内容】\n{notes}\n\n"
            "更新して、アプリを再起動しますか?\n(今の版は自動でバックアップします)",
            parent=self,
        ):
            return False
        self.status_var.set("アップデートをダウンロード中...")
        result_queue: "queue.Queue" = queue.Queue()

        def worker():
            try:
                result_queue.put(("ok", download_update_source(info)))
            except Exception as e:
                result_queue.put(("err", e))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                kind, value = result_queue.get_nowait()
            except queue.Empty:
                self.after(300, poll)
                return
            if kind == "err":
                self.status_var.set("アップデートに失敗しました。")
                messagebox.showerror("アップデート", f"ダウンロードに失敗しました。今の版はそのままです。\n\n{value}", parent=self)
                self._start_scan_once()
                return
            if self.encoding_running:
                messagebox.showinfo("アップデート", "エンコードが始まったため、更新を中止しました。", parent=self)
                return
            try:
                backup_path = install_update(value)
            except Exception as e:
                self.status_var.set("アップデートに失敗しました。")
                messagebox.showerror("アップデート", f"置き換えに失敗しました。今の版はそのままです。\n\n{e}", parent=self)
                self._start_scan_once()
                return
            messagebox.showinfo(
                "アップデート", f"バージョン {info['version']} に更新しました。再起動します。\n\n(旧版のバックアップ: {backup_path})", parent=self
            )
            self._restart_app()

        self.after(300, poll)
        return True

    def _restart_app(self):
        script = os.path.abspath(__file__)
        try:
            subprocess.Popen([sys.executable, script], cwd=os.path.dirname(script))
        except Exception as e:
            messagebox.showerror("アップデート", f"自動で再起動できませんでした。手動で起動し直してください。\n\n{e}", parent=self)
            return
        self.destroy()

    def _toggle_log_panel(self):
        if self._log_body.winfo_ismapped():
            self._log_body.pack_forget()
            self._log_frame.pack_configure(fill=tk.X, expand=False)
            self._log_toggle_btn.configure(text="▶ 実行ログ(クリックで開く)")
        else:
            self._log_body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
            self._log_toggle_btn.configure(text="▼ 実行ログ(クリックで折りたたみ)")

    def _delete_all_logs(self):
        folder = get_run_log_dir()
        try:
            files = [os.path.join(folder, n) for n in os.listdir(folder) if n.lower().endswith(".txt")]
        except OSError:
            files = []
        if not files:
            messagebox.showinfo("ログを全削除", "削除できるログ(txt)がありません。", parent=self)
            return
        if not messagebox.askyesno(
            "ログを全削除",
            f"「ログ」フォルダ内のtxt {len(files)}件をすべて削除します(まとめファイルも含む)。\n"
            "元に戻せません。よろしいですか?\n(必要なら先に「1つにまとめる」で保存してください)",
            icon="warning", default="no", parent=self,
        ):
            return
        ok = 0
        failed = 0
        for fp in files:
            try:
                os.remove(fp)
                ok += 1
            except OSError:
                failed += 1  # 実行中のログなど
        msg = f"{ok}件削除しました。"
        if failed:
            msg += f"\n{failed}件は使用中などで削除できませんでした。"
        messagebox.showinfo("ログを全削除", msg, parent=self)

    def _merge_log_files(self):
        folder = get_run_log_dir()
        files = []
        try:
            for name in os.listdir(folder):
                if name.lower().endswith(".txt") and not name.startswith(MERGED_LOG_PREFIX):
                    path = os.path.join(folder, name)
                    files.append((os.stat(path).st_mtime, name, path))
        except OSError:
            pass
        if not files:
            messagebox.showinfo("ログをまとめる", "まとめられるログ(txt)がありません。", parent=self)
            return
        files.sort()
        path = filedialog.asksaveasfilename(
            parent=self, title=f"ログ{len(files)}件を1つのtxtにまとめて保存",
            defaultextension=".txt", initialdir=folder,
            initialfile=f"{MERGED_LOG_PREFIX}{datetime.datetime.now():%Y%m%d-%H%M%S}.txt",
            filetypes=[("テキスト", "*.txt")],
        )
        if not path:
            return
        try:
            total = 0
            with io.open(path, "w", encoding="utf-8", newline="\n") as out:
                for i, (mt, name, fp) in enumerate(files, 1):
                    try:
                        with io.open(fp, "r", encoding="utf-8-sig", errors="replace") as f:
                            body = f.read()
                    except OSError as e:
                        body = f"(読み込めませんでした: {e})"
                    stamp = datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M:%S")
                    out.write(f"{'=' * 70}\n### [{i}/{len(files)}] {name}  (更新: {stamp})\n{'=' * 70}\n")
                    out.write(body.replace("\r\n", "\n").rstrip("\n") + "\n\n")
            total = os.path.getsize(path)
        except OSError as e:
            messagebox.showerror("エラー", f"保存できませんでした: {e}", parent=self)
            return
        messagebox.showinfo(
            "ログをまとめる",
            f"{len(files)}件を1つにまとめました({total / 1024 / 1024:.1f}MB)。\n{path}\n"
            "元のログは消していません。", parent=self)

    def _on_log_mode_changed(self):
        self.settings["log_mode"] = self.log_mode_var.get()
        save_settings(self.settings)

    def _open_log_manager(self):
        win = getattr(self, "_log_win", None)
        try:
            if win is not None and win.winfo_exists():
                win.lift()
                win.focus_force()
                return
        except tk.TclError:
            pass
        self._log_win = LogManagerWindow(self)

    def _open_log_folder(self):
        folder = get_run_log_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("エラー", f"開けませんでした: {e}")

    def _append_log(self, line: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_controls_running(self, running: bool):
        state_disabled = "disabled" if running else "!disabled"
        for widget in (
            self.rescan_button,
            self.csv_button,
            self.sort_button,
            self.apply_bat_button,
            self.clear_bat_button,
            self.clear_all_bat_button,
            self.done_reload_button,
            self.done_sort_selected_button,
            self.done_sort_all_button,
            self.bat_combo,
            self.start_encode_button,
            self.recursive_check,
            self.include_m2ts_check,
            self.include_rpls_check,
            self.delete_converted_button,
            self.fix_names_item,
        ):
            try:
                widget.state([state_disabled])
            except tk.TclError:
                widget.configure(state=("disabled" if running else "readonly"))
        self.stop_encode_button.state(["!disabled"] if running else ["disabled"])

    def start_encoding(self):
        if self.encoding_running or self.scanning:
            return

        ordered_iids = [i for i in self._row_order if i in self.row_data] or list(self.tree.get_children())
        visible_set = set(self.tree.get_children(""))
        queue_items = [iid for iid in ordered_iids if self.row_data.get(iid, {}).get("bat_path")]
        missing = len(ordered_iids) - len(queue_items)

        if not queue_items:
            messagebox.showinfo("情報", "バッチが割り当てられたファイルがありません。")
            return

        hidden_queued = [iid for iid in queue_items if iid not in visible_set]
        if hidden_queued:
            answer = messagebox.askyesnocancel(
                "確認",
                f"番組名の絞り込みで非表示の行に、設定が割り当てられたファイルが{len(hidden_queued)}件あります。\n\n"
                "はい … それらも含めてエンコードする\n"
                "いいえ … 表示中のものだけエンコードする\n"
                "キャンセル … 中止",
            )
            if answer is None:
                return
            if not answer:
                queue_items = [iid for iid in queue_items if iid in visible_set]
                missing = len([i for i in ordered_iids if i in visible_set]) - len(queue_items)
                if not queue_items:
                    messagebox.showinfo("情報", "表示中のファイルにバッチが割り当てられていません。")
                    return

        if missing:
            proceed = messagebox.askyesno(
                "確認",
                f"{missing}件のファイルにバッチが未設定です。これらはスキップされますが続行しますか?",
            )
            if not proceed:
                return

        self._begin_encoding(queue_items)

    def _begin_encoding(self, queue_items: List[str]):
        """指定した行(batが割り当て済み)のエンコードキューを開始する"""
        self.encoding_running = True
        self.stop_requested = False
        self._queue_kind = "encode"
        self._auto_released = 0
        self.diagnostic_report = []
        for iid in queue_items:
            self.row_data[iid]["diag_label"] = "-"
            self.row_data[iid]["diag_issues"] = []
            self._refresh_row_values(iid)
        self._set_controls_running(True)
        self._append_log(f"=== エンコードキュー開始 ({len(queue_items)}件) ===")

        thread = threading.Thread(target=self._encode_worker, args=(queue_items,), daemon=True)
        thread.start()
        self.after(100, self._poll_encode_queue)

    # ------------------------------------------------------------------
    # 変換済みファイルの再エンコード(別のバッチで作り直す)
    # ------------------------------------------------------------------
    def _find_existing_output(self, iid: str) -> Optional[str]:
        """この行の既存の変換済みファイル(mkv/mp4)のパスを探す。なければ None"""
        data = self.row_data.get(iid)
        if not data:
            return None
        old = data.get("output_path")
        if old and os.path.isfile(old):
            return old
        m2ts_path = data["path"]
        file_dir = os.path.dirname(m2ts_path)
        # 仕分け済み(仕分けフォルダ内)のファイルも含めて探す
        return find_converted_path(
            file_dir,
            os.path.basename(m2ts_path),
            data.get("program_name", ""),
            normalize_date_digits(data.get("broadcast_date", "")),
        )

    def _reencode_with_bat(self, iids: List[str], bat_name: str):
        """
        選択した行を、指定したバッチで作り直す。既存の変換済みファイルは
        「<ファイル名>.old」へ退避してからエンコードする(失敗時は元に戻す)。
        """
        if self.encoding_running or self.scanning:
            messagebox.showinfo("情報", "エンコード中・スキャン中は実行できません。")
            return
        bat_path = self.bat_name_to_path.get(bat_name)
        if not bat_path:
            messagebox.showerror("エラー", f"バッチが見つかりません: {bat_name}")
            return

        targets = [iid for iid in iids if iid in self.row_data]
        if not targets:
            return

        plans: Dict[str, Optional[str]] = {iid: self._find_existing_output(iid) for iid in targets}
        with_old = [os.path.basename(p) for p in plans.values() if p]
        without_old = sum(1 for p in plans.values() if not p)

        message = f"{len(targets)}件を、バッチ「{bat_name}」で再エンコードします。\n\n"
        if with_old:
            shown = "\n".join(f"  ・{n}" for n in with_old[:8])
            if len(with_old) > 8:
                shown += f"\n  ...ほか{len(with_old) - 8}件"
            message += (
                "既存の変換済みファイルは「〜.old」に名前を変えて退避します。\n"
                "(再エンコードが成功しても残ります。不要なら手動で削除してください。"
                "失敗した場合は自動で元に戻します)\n" + shown + "\n\n"
            )
        if without_old:
            message += f"※既存の変換済みファイルが見つからなかった{without_old}件は、退避せずにエンコードします。\n\n"
        message += "続行しますか?"
        if not messagebox.askyesno("再エンコードの確認", message):
            return

        for iid in targets:
            data = self.row_data[iid]
            data["bat_path"] = bat_path
            data["bat_name"] = bat_name
            data["reencode_plan"] = plans[iid]
            data["status"] = "待機中"
            self._refresh_row_values(iid)
        self._begin_encoding(targets)

    def _stash_previous_output(self, old_path: str) -> Optional[str]:
        """既存の出力を「<名前>.old」へ退避し、退避先のパスを返す。失敗したら None"""
        if not os.path.isfile(old_path):
            return None
        stash = old_path + ".old"
        n = 1
        while os.path.exists(stash):
            stash = f"{old_path}.old{n}"
            n += 1
        try:
            os.rename(old_path, stash)
        except OSError:
            return None
        return stash

    def _settle_reencode(
        self, original_path: str, stash_path: str, new_output: Optional[str], diag_label: str
    ) -> Optional[str]:
        """
        再エンコード完了後の後始末。成功なら退避した旧ファイルをそのまま残し、
        失敗なら新しい(不完全な)出力を片付けて旧ファイルを元に戻す。
        戻り値は、最終的に「この行の変換済みファイル」とするパス。
        """
        new_ok = bool(new_output) and os.path.isfile(new_output) and diag_label != "失敗"
        if new_ok:
            self.encode_queue.put(
                ("log", f"[再エンコード] 完了。元のファイルは「{os.path.basename(stash_path)}」として残しています。")
            )
            return new_output

        if new_output and os.path.isfile(new_output):
            try:
                os.remove(new_output)
            except OSError as e:
                self.encode_queue.put(("log", f"[再エンコード] 失敗した出力を削除できませんでした: {e}"))
                return new_output
        if os.path.exists(original_path):
            self.encode_queue.put(("log", f"[再エンコード] 元の名前のファイルが既にあるため、退避分を戻せません: {stash_path}"))
            return original_path
        try:
            os.rename(stash_path, original_path)
        except OSError as e:
            self.encode_queue.put(("log", f"[再エンコード] 元のファイルを戻せませんでした({e})。退避先: {stash_path}"))
            return None
        self.encode_queue.put(("log", "[再エンコード] 失敗したため、元のファイルを元に戻しました。"))
        return original_path

    def request_stop(self):
        if not self.encoding_running:
            return
        self.stop_requested = True
        self._append_log("中断が要求されました。現在のファイル終了後に停止します。")
        if self._current_process is not None:
            try:
                kill_process_tree(self._current_process)
            except Exception:
                pass

    def _encode_worker(self, iids: List[str]):
        work = list(iids)
        pos = 0
        while pos < len(work):
            iid = work[pos]
            pos += 1
            index, total = pos, len(work)
            if self.stop_requested:
                self.encode_queue.put(("stopped",))
                return

            data = self.row_data[iid]

            # 再エンコードの場合は、既存の変換済みファイルを先に退避する
            plan = data.pop("reencode_plan", None)
            if plan:
                stash = self._stash_previous_output(plan)
                if stash is None:
                    self.encode_queue.put(
                        ("log", f"[エラー] 既存ファイルを退避できませんでした(他のソフトで開いていませんか?): {plan}")
                    )
                    self.encode_queue.put(("status", iid, "退避失敗", index, total))
                    continue
                data["reencode_old"] = (plan, stash)
                self.encode_queue.put(("log", f"[再エンコード] 退避: {os.path.basename(plan)} → {os.path.basename(stash)}"))

            self.encode_queue.put(("status", iid, "エンコード中", index, total))

            # 本チャンネル⇔サブチャンネルの切替がある録画は、先にTsSplitterで分割する
            can_split = self._can_split(data)
            tool = None
            if can_split:
                changed, detail = detect_ts_service_change(data["path"])
                if not changed:
                    changed, detail = detect_head_timestamp_reset(data["path"])
                if changed:
                    self.encode_queue.put(("log", f"[分割] 録画に切替(サービスの切替、または先頭の別の映像)があります: {detail}"))
                    tool = self._ensure_tssplitter()
                    if tool is None:
                        self.encode_queue.put(("log", "[注意] TsSplitter.exe を用意できないため分割できません。このままエンコードします(失敗する場合があります)"))
                    else:
                        new_iids = self._split_row(iid, tool)
                        if new_iids:
                            work[pos:pos] = new_iids
                            continue

            self._last_diag_label = None
            self._last_cuda_failure = False
            try:
                returncode = self._run_bat(data["path"], data["bat_path"], iid)
                if self.stop_requested:
                    status = "中断"
                elif returncode == 0:
                    status = "完了"
                else:
                    status = f"エラー(code {returncode})"
            except Exception as e:
                returncode = 1
                status = "エラー"
                self.encode_queue.put(("log", f"[例外] {e}"))

            # 失敗したときは、切替が見つけられなかっただけかもしれないので、分割して試しなおす
            failed = (returncode != 0 or self._last_diag_label == "失敗")
            if failed and can_split and not self.stop_requested:
                tool = tool or self._ensure_tssplitter()
                if tool is not None:
                    why = "CUDA(GPU)でのデコードに失敗したため" if self._last_cuda_failure else "エンコードに失敗したため"
                    self.encode_queue.put(("log", f"[分割] {why}、TsSplitterで分割してから試しなおせるか調べます(録画の途中の切替が原因のことがあります)"))
                    new_iids = self._split_row(iid, tool)
                    if new_iids:
                        work[pos:pos] = new_iids
                        continue
            if failed and self._last_cuda_failure and data.get("split_from") and not data.get("cpu_decode") \
                    and not self.stop_requested:
                # 分割で作ったファイルは中身が正常でも、映像の形式によってはCUDAが受け付けないことがあるので、
                # このファイルに限りCPUデコードでやりなおす(通常のファイルは自動では切り替えない)
                data["cpu_decode"] = True
                self.encode_queue.put(("log", "[やりなおし] 分割したファイルでCUDA(GPU)のデコードに失敗したため、"
                                              "このファイルだけCPUでデコードしてやりなおします"))
                self.encode_queue.put(("status", iid, "待機中", index, total))
                work.insert(pos, iid)
                continue
            if failed and self._last_cuda_failure:
                self.encode_queue.put(("log", "[注意] CUDA(GPU)でのデコードに失敗しています。"
                                              "メニュー「設定」の「常にCUDAデコードで変換」をOFFにすると、CPUでデコードします"))

            self.encode_queue.put(("status", iid, status, index, total))

        self.encode_queue.put(("all_done",))

    def _ensure_tssplitter(self) -> Optional[str]:
        """TsSplitter.exe のパスを返す。置かれていなければ、埋め込みのものを取り出す"""
        tool = find_tssplitter()
        if tool is not None:
            return tool
        tool, error = extract_embedded_tssplitter()
        if tool is None:
            self.encode_queue.put(("log", f"[分割] TsSplitter.exe を取り出せませんでした({error})"))
            return None
        self.encode_queue.put(("log", f"[分割] 埋め込みの TsSplitter.exe を取り出しました: {tool}"))
        return tool

    def _can_split(self, data: dict) -> bool:
        """この行を、TsSplitterによる分割の対象にしてよいか"""
        if self.settings.get("tssplitter_split", "1") != "1":
            return False
        if data.get("split_from"):
            return False  # 分割でできたファイルは、もう分割しない
        return data["path"].lower().endswith((".m2ts", ".ts"))

    def _split_row(self, iid: str, tool: str) -> List[str]:
        """TsSplitterで分割し、できたファイルを一覧に行として追加する。追加した行のiid一覧を返す(分割しなければ空)"""
        data = self.row_data[iid]
        path = data["path"]
        self.encode_queue.put(("log", f"[分割] TsSplitterで分割します: {os.path.basename(path)}(番組情報とPMTの切替ごと)"))
        pieces, error = run_tssplitter(
            tool, path,
            on_line=lambda line: self.encode_queue.put(("log", f"[分割] {line}")),
            should_stop=lambda: self.stop_requested,
        )
        if error:
            self.encode_queue.put(("log", f"[分割] {error}。分割せずに進めます"))
            return []
        if len(pieces) < 2:
            # 1本にしかならないなら、分割する意味がない(できたファイルは片付ける)
            for piece in pieces:
                try:
                    os.remove(piece)
                except OSError:
                    pass
            self.encode_queue.put(("log", "[分割] 分割しても1本だったため、分割せずに進めます"))
            return []
        # 5秒以下の短いファイルは、切替の境目にできたゴミなので削除する(長さが読めないものは残す。全部が短い場合も消さない)
        lengths = {piece: probe_duration_seconds(piece) for piece in pieces}
        junk = [pc for pc in pieces if lengths[pc] is not None and lengths[pc] <= SPLIT_JUNK_SECONDS]
        if len(junk) == len(pieces):
            junk = []
        for pc in junk:
            try:
                os.remove(pc)
                self.encode_queue.put(("log", f"[分割] {os.path.basename(pc)} は{lengths[pc]:.1f}秒しかないため、ゴミとして削除しました"))
            except OSError as e:
                self.encode_queue.put(("log", f"[分割] {os.path.basename(pc)} を削除できませんでした({e})"))
        pieces = [pc for pc in pieces if pc not in junk]
        pieces = merge_split_pieces(pieces, log=lambda line: self.encode_queue.put(("log", line)))

        # 分けたファイルには番組情報が残らないことがあるので、番組名・チャンネル・放送日・名前の取得元は、
        # 元のファイルのものを使う(同じ名前になるときは、出力に「(2)」「(3)」の連番が付く)
        info_source = data.get("info_source_path") or path
        rows = []
        for piece in pieces:
            rows.append({"path": piece, "program_name": data.get("program_name", ""), "channel": data.get("channel", ""),
                         "broadcast_date": data.get("broadcast_date", ""), "info_source_path": info_source})
            self.encode_queue.put(("log", f"[分割] → {os.path.basename(piece)}"))
        holder = {"event": threading.Event(), "iids": []}
        self.encode_queue.put(("addsplit", iid, rows, holder))
        holder["event"].wait(30)
        new_iids = holder["iids"]
        self.encode_queue.put(("split_done", iid, len(new_iids)))
        self.encode_queue.put(("log", f"[分割] {len(new_iids)}本に分けました。続けて、分けたファイルをエンコードします(元のファイルは残してあります)"))
        return new_iids

    def _add_split_rows(self, src_iid: str, rows: List[dict]) -> List[str]:
        """分割でできたファイルを、元の行のすぐ下に追加する(元の行と同じ設定を割り当てる)"""
        src = self.row_data.get(src_iid, {})
        try:
            index = self.tree.index(src_iid) + 1
        except Exception:
            index = tk.END
        order_pos = self._row_order.index(src_iid) + 1 if src_iid in self._row_order else len(self._row_order)
        new_iids = []
        for k, r in enumerate(rows):
            base_name = os.path.basename(r["path"])
            iid = self.tree.insert(
                "", index if index == tk.END else index + k,
                values=(base_name, r["program_name"], r["channel"], r["broadcast_date"], "✕",
                        src.get("bat_name") or "(未設定)", "待機中", "-"),
                tags=("converted_no",),
            )
            self.row_data[iid] = {
                "path": r["path"], "program_name": r["program_name"], "channel": r["channel"],
                "broadcast_date": r["broadcast_date"], "converted": False, "info_source_path": r.get("info_source_path"),
                "output_path": None, "bat_path": src.get("bat_path"), "bat_name": src.get("bat_name"),
                "status": "待機中", "diag_label": "-", "diag_issues": [], "split_from": src.get("path"),
            }
            self._row_order.insert(order_pos + k, iid)
            if self.filter_var.get().strip() and not self._row_matches(iid):
                self.tree.detach(iid)
            self.results.append((base_name, r["program_name"], r["channel"], r["broadcast_date"], "✕"))
            new_iids.append(iid)
        return new_iids

    def _run_bat(self, m2ts_path: str, bat_path: str, iid: str) -> int:
        """1件分のエンコード。実行ログは全行そのまま ログ/ フォルダのtxtにも保存する"""
        handle = open_run_log(m2ts_path)
        if handle is not None:
            self.encode_queue.sink = handle
            self.encode_queue.write_file(
                f"# {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {m2ts_path}\n"
                f"# 番組: {self.row_data.get(iid, {}).get('program_name', '')} / "
                f"チャンネル: {self.row_data.get(iid, {}).get('channel', '')}"
            )
        try:
            return self._run_bat_inner(m2ts_path, bat_path, iid)
        finally:
            self.encode_queue.sink = None
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                if os.path.basename(os.path.dirname(handle.name)) == LOG_WORK_DIR_NAME:
                    fold_run_log_file(handle.name)    # まとめ_実行ログ.txt に追記して、作業用のtxtを消す

    def _remove_stale_outputs(self, m2ts_path: str, reason: str, keep_main: bool = False) -> None:
        """途中で止まった出力(<m2ts>.mkv/.mp4 など)を消す。
        残っていると ffmpeg が上書きを拒否し、未完成のファイルが完成品として扱われてしまうため。"""
        for ext in CONVERTED_EXTENSIONS:
            for candidate in (m2ts_path + ext, m2ts_path + ".withsub" + ext):
                if keep_main and candidate == m2ts_path + ext:
                    continue
                if os.path.isfile(candidate):
                    err = None
                    for _attempt in range(6):  # 止めた直後はffmpegがまだファイルを掴んでいることがあるので少し待つ
                        try:
                            os.remove(candidate)
                            err = None
                            break
                        except OSError as e:
                            err = e
                            time.sleep(0.5)
                    if err is None:
                        self.encode_queue.put(("log", f"[掃除] {reason}: {os.path.basename(candidate)} を削除しました"))
                    else:
                        self.encode_queue.put(("log", f"[掃除] {os.path.basename(candidate)} を削除できませんでした({err})"))

    def _run_bat_inner(self, m2ts_path: str, bat_path: str, iid: str) -> int:
        temp_bat_path: Optional[str] = None
        self._remove_stale_outputs(m2ts_path, "前回途中で止まった出力が残っていたため")

        if bat_path.startswith(PRESET_PREFIX):
            # エンコード設定: 設定からバッチ内容を生成し、一時ファイルとして実行する
            preset_name = bat_path[len(PRESET_PREFIX):]
            options = self._preset_options_map().get(preset_name)
            if options is None:
                self.encode_queue.put(("log", f"[エラー] エンコード設定が見つかりません: {preset_name}"))
                return 1
            if normalize_encode_options(options)["auto"]:
                self.encode_queue.put(("log", "[自動判定] ffprobeで字幕・音声・映像の中身を調べています(ファイル全体を読むため時間がかかります)..."))
                streams, error = probe_streams(m2ts_path)
                if streams is None:
                    self.encode_queue.put(("log", f"[自動判定] 失敗({error})。設定どおりに実行します"))
                else:
                    options, notes = resolve_auto_options(
                        options, streams, self.row_data.get(iid, {}).get("channel", "") or ""
                    )
                    for note in notes:
                        self.encode_queue.put(("log", f"[自動判定] {note}"))
            if self.row_data.get(iid, {}).get("cpu_decode"):
                options = dict(options)
                options["cuda"] = False
                self.encode_queue.put(("log", "[設定] 分割したファイルのやりなおしのため、CPUでデコードします"))
            elif self.settings.get("force_cuda", "0") == "1" and not normalize_encode_options(options)["cuda"]:
                options = dict(options)
                options["cuda"] = True
                self.encode_queue.put(("log", "[設定] 「常にCUDAデコードで変換」がONのため、CUDAデコードで変換します"))
            if self.settings.get("encoder", "auto") == "auto":
                self._encoder_avail_ready()  # 未調査なら、ここで調べる
            self._apply_active_encoder()
            encoder = get_active_encoder()
            if encoder != "nvenc":
                self.encode_queue.put(("log", f"[設定] エンコーダー: {_ENCODER_LABEL[encoder]}"
                                       + ("(CUDAデコードはNVIDIAのGPU専用なので使いません)" if normalize_encode_options(options)["cuda"] else "")))
            fd, temp_bat_path = tempfile.mkstemp(suffix=".bat", prefix="m2ts_encoder_")
            os.close(fd)
            with io.open(temp_bat_path, "w", encoding="utf-8", newline="") as f:
                f.write(build_preset_batch(options))
            actual_bat_path = temp_bat_path
            bat_dir = get_script_dir()
            display_bat_name = PRESET_LABEL + preset_name
        elif bat_path.startswith(EMBEDDED_BAT_PREFIX):
            # 埋め込みバッチ: 実行するその場だけ一時ファイルとして書き出し、
            # 終わったら削除する(永続的なファイルを残さないため)
            key = bat_path[len(EMBEDDED_BAT_PREFIX):]
            content = DEFAULT_BAT_SCRIPTS.get(key)
            if content is None:
                self.encode_queue.put(("log", f"[エラー] 埋め込みバッチが見つかりません: {key}"))
                return 1
            fd, temp_bat_path = tempfile.mkstemp(suffix=".bat", prefix="m2ts_encoder_")
            os.close(fd)
            # UTF-8で書き出す(ffmpegのメタデータ引数(主音声/副音声等)がchcp 65001区間で
            # 正しく渡るようにするため)。コロン置換は半角ハイフンを使っているので、
            # コードページ起因の文字化け(全角コロンのバイト境界ずれ)は発生しない。
            with io.open(temp_bat_path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(content)
            actual_bat_path = temp_bat_path
            bat_dir = get_script_dir()
            display_bat_name = os.path.splitext(key)[0]
        else:
            actual_bat_path = bat_path
            bat_dir = os.path.dirname(bat_path) or self.folder
            display_bat_name = os.path.basename(bat_path)

        if not bat_path.startswith(PRESET_PREFIX) and self._current_encoder() != "nvenc":
            self.encode_queue.put(("log", "[注意] バッチファイルは、書かれているエンコーダーのまま実行します"
                                          "(多くはNVIDIAのhevc_nvenc)。「エンコーダー」の設定は、エンコード設定(プリセット)にだけ効きます。"))
        try:
            return self._run_bat_process(m2ts_path, actual_bat_path, bat_dir, display_bat_name, iid)
        finally:
            if temp_bat_path and os.path.exists(temp_bat_path):
                try:
                    os.remove(temp_bat_path)
                except Exception:
                    pass

    def _rename_to_target(self, path: str, target_path: str) -> Optional[str]:
        """pathをtarget_pathへリネームする。既に同名なら何もせず、衝突する場合は安全のため諦める。"""
        if path == target_path:
            return path
        if os.path.exists(target_path):
            return path
        try:
            os.rename(path, target_path)
            return target_path
        except OSError:
            return path

    def _finalize_sidecar_csv(
        self,
        m2ts_path: str,
        directory: str,
        program_name: str,
        safe_title: str,
        date_digits: str,
        new_csv_names: Optional[List[str]] = None,
        csv_stem: Optional[str] = None,
    ) -> None:
        """mkv/mp4と対になっているcsv(rplsinfoの出力)も、同じ命名規則でリネームする"""
        if csv_stem:
            # 動画に連番を付けた場合は、csvも同じ名前(連番つき)に揃える
            csv_target_name = csv_stem + ".csv"
        else:
            csv_target_name = f"{safe_title},{date_digits}.csv" if date_digits else f"{safe_title}.csv"
        csv_target_path = os.path.join(directory, csv_target_name)
        if os.path.isfile(csv_target_path):
            # 既に正しい名前のcsvがある(再エンコード等)。バッチが作り直した仮のcsv
            # (<m2ts>.csv)は同じ内容の重複なので片付ける(日付付きの名前=この録画専用の場合のみ)
            orphan = m2ts_path + ".csv"
            if date_digits and os.path.isfile(orphan):
                try:
                    os.remove(orphan)
                except OSError:
                    pass
            return  # 既に正しい名前になっている

        # 1) バッチがまだリネームしていない(ffmpeg実行前の)決め打ちパスを確認
        csv_candidate = m2ts_path + ".csv"
        if os.path.isfile(csv_candidate):
            self._rename_to_target(csv_candidate, csv_target_path)
            return

        # 2) バッチが既にリネーム済みの場合は、まず「今回のエンコードで新しくできた/更新された
        #    csv」だけを対象にする(同名番組の別日分のcsvを取り違えないため)
        candidates = build_match_candidates(os.path.basename(m2ts_path), program_name)
        source_base = os.path.basename(m2ts_path)

        def _matches(name: str) -> bool:
            base, _ext = os.path.splitext(name)
            if is_other_date_file(base, date_digits, source_base):
                return False
            return is_converted_match(candidates, [normalize_name(base), normalize_name(strip_trailing_date(base))])

        if new_csv_names:
            matched = [n for n in new_csv_names if _matches(n)]
            if len(matched) == 1 or (matched and len(new_csv_names) == len(matched)):
                self._rename_to_target(os.path.join(directory, matched[0]), csv_target_path)
                return
            if not matched and len(new_csv_names) == 1:
                self._rename_to_target(os.path.join(directory, new_csv_names[0]), csv_target_path)
                return
            if matched:
                self._rename_to_target(os.path.join(directory, matched[0]), csv_target_path)
                return

        # 3) 差分から特定できなかった場合のみ、録画日付が異なるものを除いてあいまい一致で探す
        try:
            entries = os.listdir(directory)
        except Exception:
            return
        for name in entries:
            if name.lower().endswith(".csv") and _matches(name):
                self._rename_to_target(os.path.join(directory, name), csv_target_path)
                return

    def _finalize_output_filename(
        self,
        output_path: Optional[str],
        info_source: str,
        m2ts_path: str,
        new_csv_names: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        エンコードが完了した出力ファイル(mkv/mp4)と、対になるcsvを、
        rplsinfo.exeから取得した番組名(+録画日付)をもとにPython側で正しい
        ファイル名へリネームする。
        cmd.exeのバッチ内置換(コードページ依存の文字化けや、*/</>等の構文エラーの
        原因になっていた)には頼らず、Pythonのファイル操作(Unicodeのまま扱え、
        コードページに依存しない)で直接行う。
        失敗した場合は、従来の簡易的なプレースホルダ復元にフォールバックする。
        """
        if not output_path or not os.path.isfile(output_path):
            return output_path

        if not self.rplsinfo_path:
            self.rplsinfo_path = find_rplsinfo()
        if not self.rplsinfo_path:
            return restore_colon_in_output_filename(output_path)

        result = get_program_name_with_date(self.rplsinfo_path, info_source)
        if not result or not result[0]:
            return restore_colon_in_output_filename(output_path)

        program_name, date_digits = result
        directory, filename = os.path.split(output_path)
        _, ext = os.path.splitext(filename)
        safe_title = sanitize_title_for_filename(program_name)
        stem = f"{safe_title},{date_digits}" if date_digits else safe_title
        target_name = stem + ext

        final_path = output_path
        csv_stem: Optional[str] = None
        current_stem = os.path.splitext(filename)[0]
        if re.fullmatch(re.escape(stem) + r"\(\d+\)", current_stem):
            # 既に連番つきの正しい名前になっている(再実行など)。番号を振り直さない
            csv_stem = current_stem
        elif target_name != filename:
            target_path = os.path.join(directory, target_name)
            if os.path.exists(target_path):
                # 既に同名のファイルがある場合は、上書きせず、空いている連番「(2)」「(3)」…を付ける。
                # 対になるcsvも同じ名前に揃えるため、動画とcsvの両方が空いている番号を選ぶ。
                for number in range(2, 1000):
                    numbered_stem = f"{stem}({number})"
                    numbered_path = os.path.join(directory, numbered_stem + ext)
                    numbered_csv = os.path.join(directory, numbered_stem + ".csv")
                    if not os.path.exists(numbered_path) and not os.path.exists(numbered_csv):
                        target_path = numbered_path
                        csv_stem = numbered_stem
                        break
                else:
                    target_path = ""
            if target_path:
                try:
                    os.rename(output_path, target_path)
                    final_path = target_path
                    if csv_stem:
                        self.encode_queue.put((
                            "log",
                            f"[同名あり] 既に同じ名前のファイルがあるため、連番を付けました: {os.path.basename(target_path)}",
                        ))
                except OSError:
                    final_path = output_path
                    csv_stem = None

        self._finalize_sidecar_csv(
            m2ts_path, directory, program_name, safe_title, date_digits, new_csv_names, csv_stem
        )

        return final_path

    def _run_bat_process(
        self, m2ts_path: str, actual_bat_path: str, bat_dir: str, display_bat_name: str, iid: str
    ) -> int:
        comspec = os.environ.get("ComSpec", "cmd.exe")

        # cmd.exe は /c の後ろの文字列を「自分自身のコマンドライン」として
        # 再解釈するため、通常のリスト形式の引数渡し(list2cmdline)だけでは
        # ファイル名中の ^ ( ) & | などの記号が誤解釈されてしまう。
        # 対策として、cmd.exe の「先頭と末尾が " で囲まれていれば外側の
        # クォートを1組取り除く」という仕様を逆手にとり、
        #   "comspec" /c ""batファイル" "引数""
        # のように全体をもう1段クォートで包んで渡す。
        inner = '"{bat}" "{arg}"'.format(bat=actual_bat_path, arg=m2ts_path)
        full_cmd_line = '"{comspec}" /c "{inner}"'.format(comspec=comspec, inner=inner)

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        # バッチがサブフォルダに置かれていても rplsinfo.exe / ffmpeg 等を
        # bare command (パス無し)で呼び出せるよう、このスクリプトのフォルダを
        # 子プロセスの PATH の先頭に追加しておく
        env = os.environ.copy()
        env.update(PRESET_BAT_ENV)
        env["PATH"] = get_script_dir() + os.pathsep + env.get("PATH", "")

        # 「rplsから番組情報を再取得」済みの行は、埋め込みバッチ内の rplsinfo.exe 呼び出しも
        # そのrplsファイルを情報源として使うよう伝える(対応していないバッチでは単に無視される)
        info_source_path = self.row_data.get(iid, {}).get("info_source_path") or ""
        env["RPLSINFO_SOURCE"] = info_source_path

        # エンコード前のmkv/mp4/csvの状態を控えておき、終了後の差分(新規作成/更新された
        # ファイル)から「今回の出力」を特定する。同名番組(別日放送)が並んでいても、
        # 既に変換済みの別の回のファイルを取り違えないようにするため。
        file_dir_for_snapshot = os.path.dirname(m2ts_path)
        snapshot_before = snapshot_output_files(file_dir_for_snapshot)

        self.encode_queue.put(
            ("log", f"--- 開始: {os.path.basename(m2ts_path)}  (バッチ: {display_bat_name}) ---")
        )

        process = subprocess.Popen(
            full_cmd_line,  # 文字列で渡すことで、Python側の再クォートを行わせない
            cwd=bat_dir,
            env=env,
            stdin=subprocess.DEVNULL,  # bat内の pause / set /p を待たせずに素通りさせる
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self._current_process = process
        collected_lines: List[str] = []

        try:
            for line in iter_process_lines(process.stdout):
                if line:
                    collected_lines.append(line)
                    self.encode_queue.put(("log", line))
                if self.stop_requested:
                    kill_process_tree(process)
                    break
        finally:
            process.wait()
            self._current_process = None

        self.encode_queue.put(("log", f"--- 終了 (code={process.returncode}) ---"))

        if self.stop_requested:
            self.encode_queue.put(("log", "[中断] ユーザー操作で停止しました(このファイルは未完成です)"))
            # 合体の段階まで進んでいれば、1回目の出力(映像+音声)は完成品なので残す
            merging = any(l.startswith("[MERGE]") for l in collected_lines)
            self._remove_stale_outputs(m2ts_path, "中断したため未完成の出力を", keep_main=merging)
            if merging:
                self.encode_queue.put(("log", "[中断] 合体の途中で止めました。字幕・解説放送なしの完成品(1回目の出力)は残してあります"))

        if not self.stop_requested:
            diag_label, diag_issues = analyze_ffmpeg_log(collected_lines, process.returncode)
            if any(("Not overwriting" in l) or ("Error opening output file" in l) for l in collected_lines):
                if any("bitstream filter" in l for l in collected_lines):
                    diag_issues = list(diag_issues) + [("出力ファイルを作れませんでした(音声の形式に合わない設定でした)", 1, [])]
                else:
                    diag_issues = list(diag_issues) + [("出力ファイルを作れませんでした(同名のファイルが残っていました)", 1, [])]
                diag_label = "失敗"
            if any(l.startswith("[MERGE-FAILED]") for l in collected_lines):
                # 1回目は成功しているが、後から合体するはずの音声・字幕が入っていない
                diag_issues = list(diag_issues) + [("合体失敗(解説放送・字幕などが入っていません)", 1, [])]
                if diag_label == "OK":
                    diag_label = "要確認"

            # エンコード直後に、このファイルの変換済み(mkv/mp4)状態と
            # 実際にできあがったファイル名を特定する(全体の再スキャンは不要にするため。
            # また、診断結果にエンコード後のファイル名も併記するために使う)
            program_name = self.row_data.get(iid, {}).get("program_name", "")
            file_dir = os.path.dirname(m2ts_path)

            # ffmpegは常に "<m2tsパス>.mkv"/".mp4" へ直接出力するため、まずはこの
            # 決め打ちのパスを確認する(バッチ内のリネームが失敗していても確実に見つかる)。
            # 見つからない場合のみ、バッチ側のリネームが既に成功しているとみなして
            # あいまい一致検索(find_converted_file)にフォールバックする。
            output_path = None
            for ext in CONVERTED_EXTENSIONS:
                candidate_path = m2ts_path + ext
                if os.path.isfile(candidate_path):
                    output_path = candidate_path
                    break

            # バッチ側のリネームが成功していた場合は、エンコード前後の差分から
            # 「今回新しくできた/更新されたmkv・mp4」を特定する
            new_names = diff_output_files(snapshot_before, snapshot_output_files(file_dir))
            new_video_names = [n for n in new_names if n.lower().endswith(CONVERTED_EXTENSIONS)]
            new_csv_names = [n for n in new_names if n.lower().endswith(".csv")]
            if output_path is None and new_video_names:
                if len(new_video_names) > 1:
                    # 複数ある場合(想定外)は、番組名が一致するものを優先する
                    candidates = build_match_candidates(os.path.basename(m2ts_path), program_name)
                    preferred = [
                        n for n in new_video_names
                        if is_converted_match(candidates, [normalize_name(os.path.splitext(n)[0])])
                    ]
                    new_video_names = preferred or new_video_names
                output_path = os.path.join(file_dir, new_video_names[0])

            # 差分から特定できなかった場合のみ、録画日付が異なるものを除いたあいまい一致にフォールバック
            if output_path is None:
                date_digits_hint = normalize_date_digits(self.row_data.get(iid, {}).get("broadcast_date", ""))
                output_file_name = find_converted_file(
                    file_dir, os.path.basename(m2ts_path), program_name, date_digits_hint
                )
                output_path = os.path.join(file_dir, output_file_name) if output_file_name else None

            # 失敗した変換の出力(中身のない/壊れたmkv・csv)は名前を付け替えずに片付ける。
            # 残しておくと「番組名,日付.mkv」というゴミになり、分割後の成功分と名前も衝突する
            if diag_label == "失敗" and not self.row_data.get(iid, {}).get("reencode_old"):
                junk = set(new_video_names) | set(new_csv_names)
                if output_path:
                    junk.add(os.path.basename(output_path))
                removed = []
                for name in sorted(junk):
                    junk_path = os.path.join(file_dir, name)
                    # 変換前から存在し更新されていないファイルには触れない(newに含まれるか、決め打ちの出力のみ)
                    if name in snapshot_before and name not in new_names:
                        continue
                    try:
                        os.remove(junk_path)
                        removed.append(name)
                    except OSError:
                        pass
                if removed:
                    self.encode_queue.put(("log", f"[掃除] 失敗した変換の残骸を削除しました: {', '.join(removed)}"))
                output_path = None

            # バッチ内のcmd.exeによる置換に頼らず、Python側で番組名から直接
            # 正しいファイル名を組み立ててリネームする(コードページ/構文問題を回避するため)
            output_path = self._finalize_output_filename(
                output_path, info_source_path or m2ts_path, m2ts_path, new_csv_names
            )

            # 再エンコードだった場合は、結果に応じて旧ファイルを残す/元に戻す
            reencode_old = self.row_data.get(iid, {}).pop("reencode_old", None)
            if reencode_old:
                output_path = self._settle_reencode(reencode_old[0], reencode_old[1], output_path, diag_label)

            # エンコード後問題ないか/ノイズの出ている箇所を、ソフト/CUDAデコードの比較で調べて
            # csvに記録する(記録が終わるまで元のm2tsは削除対象にならない)
            if output_path and diag_label != "失敗":
                diag_label, diag_issues = self._noise_inspect_and_record(
                    m2ts_path, iid, output_path, diag_label, diag_issues
                )
            elif iid in self.row_data:
                self.row_data[iid]["noise_state"] = "na"

            converted = output_path is not None

            # 診断結果もログファイルの末尾に残す(貼れば全部分かるように)
            self.encode_queue.write_file("")
            self.encode_queue.write_file(f"# ===== 診断結果: {diag_label} =====")
            self.encode_queue.write_file(f"# 出力: {output_path or '(見つかりません)'}")
            for category, count, entries in diag_issues:
                self.encode_queue.write_file(f"# - {category}: {count}件")
                for seconds, text in entries[:30]:
                    self.encode_queue.write_file(f"#     {seconds:.1f}秒  {text}")

            self._last_diag_label = diag_label
            self._last_cuda_failure = any(
                ("cuvidCreateDecoder" in l) or ("Failed setup for format cuda" in l) for l in collected_lines
            )
            self.encode_queue.put(("diag", iid, diag_label, diag_issues, output_path))
            self.encode_queue.put(("converted", iid, converted))
        else:
            # 中断された場合: 再エンコード中だったなら、途中までの出力を片付けて元のファイルを戻す
            reencode_old = self.row_data.get(iid, {}).pop("reencode_old", None)
            if reencode_old:
                file_dir = os.path.dirname(m2ts_path)
                partial = None
                for ext in CONVERTED_EXTENSIONS:
                    if os.path.isfile(m2ts_path + ext):
                        partial = m2ts_path + ext
                        break
                if partial is None:
                    new_names = diff_output_files(snapshot_before, snapshot_output_files(file_dir))
                    videos = [n for n in new_names if n.lower().endswith(CONVERTED_EXTENSIONS)]
                    if videos:
                        partial = os.path.join(file_dir, videos[0])
                restored = self._settle_reencode(reencode_old[0], reencode_old[1], partial, "失敗")
                self.encode_queue.put(("converted", iid, restored is not None))

        return process.returncode

    def _poll_encode_queue(self):
        try:
            while True:
                item = self.encode_queue.get_nowait()
                if item[0] == "status":
                    _, iid, status, index, total = item
                    if iid in self.row_data:
                        self.row_data[iid]["status"] = status
                        self._refresh_row_values(iid)
                    self.status_var.set(f"エンコード中... ({index}/{total}件) - {status}")
                elif item[0] == "log":
                    self._append_log(item[1])
                elif item[0] == "addsplit":
                    _, src_iid, rows, holder = item
                    try:
                        holder["iids"] = self._add_split_rows(src_iid, rows)
                    finally:
                        holder["event"].set()
                elif item[0] == "split_done":
                    _, src_iid, count = item
                    if src_iid in self.row_data:
                        d = self.row_data[src_iid]
                        d["status"] = f"分割して変換({count}件)"
                        d["bat_path"] = None
                        d["bat_name"] = None
                        d["diag_label"] = "-"
                        d["diag_issues"] = []
                        self.diagnostic_report = [e for e in self.diagnostic_report if e[0] != d["path"]]
                        self._refresh_row_values(src_iid)
                elif item[0] == "rowstatus":
                    _, iid, text = item
                    if iid in self.row_data:
                        self.row_data[iid]["status"] = text
                        self._refresh_row_values(iid)
                elif item[0] == "diag":
                    _, iid, diag_label, diag_issues, output_path = item
                    if iid in self.row_data:
                        self.row_data[iid]["diag_label"] = diag_label
                        self.row_data[iid]["diag_issues"] = diag_issues
                        self.row_data[iid]["output_path"] = output_path
                        # 出力ができたら、割り当てた設定は自動で解除する(次の「エンコード開始」で
                        # 同じファイルを再エンコードしてしまわないように)。失敗は再試行できるよう残す
                        if (self._queue_kind == "encode" and diag_label != "失敗"
                                and self.row_data[iid].get("bat_path")):
                            self.row_data[iid]["bat_path"] = None
                            self.row_data[iid]["bat_name"] = None
                            self._auto_released += 1
                        self._refresh_row_values(iid)
                        # やりなおしたファイルに、前回の結果(失敗など)が残らないように入れ替える
                        self.diagnostic_report = [e for e in self.diagnostic_report if e[0] != self.row_data[iid]["path"]]
                        if diag_label != "OK":
                            source_path = self.row_data[iid]["path"]
                            self.diagnostic_report.append((source_path, output_path, diag_label, diag_issues))
                elif item[0] == "converted":
                    _, iid, converted = item
                    if iid in self.row_data:
                        self.row_data[iid]["converted"] = converted
                        mark = "〇" if converted else "✕"
                        tag = "converted_yes" if converted else "converted_no"
                        self.tree.set(iid, "converted", mark)
                        self.tree.item(iid, tags=(tag,))
                elif item[0] in ("all_done", "stopped"):
                    self.encoding_running = False
                    self._set_controls_running(False)
                    if self._auto_released:
                        self._append_log(
                            f"[設定の解除] 出力ができた{self._auto_released}件は、適用した設定を自動で解除しました"
                            "(次のエンコード開始で再エンコードされません)。失敗した行は設定を残しています。"
                        )
                        self._auto_released = 0
                    if item[0] == "all_done":
                        if self._queue_kind == "noise":
                            self.status_var.set("ノイズ検査が完了しました。")
                            self._append_log("=== ノイズ検査が完了しました ===")
                        else:
                            self.status_var.set("エンコードキューが完了しました。")
                            self._append_log("=== 全ファイルのエンコードが完了しました ===")
                        self._show_diagnostic_summary()
                    else:
                        self.status_var.set("エンコードキューを中断しました。")
                        self._append_log("=== 中断されました ===")
                        messagebox.showinfo("中断", "エンコードキューを中断しました。")
        except queue.Empty:
            pass

        if self.encoding_running:
            self.after(150, self._poll_encode_queue)

    def _show_diagnostic_summary(self):
        """エンコード完了直後、失敗・ノイズ疑いのあったファイルをまとめて表示する"""
        if not self.diagnostic_report:
            if self._queue_kind == "noise":
                messagebox.showinfo("完了", "ノイズ検査が完了しました。\nノイズの疑いは検出されませんでした。")
            else:
                messagebox.showinfo(
                    "完了",
                    "すべてのファイルのエンコードが完了しました。\n"
                    "失敗やノイズの疑いは検出されませんでした。",
                )
            return
        self._show_diagnostic_dialog(self.diagnostic_report, title="エンコード診断結果")

    def show_all_diagnostics(self):
        """メイン画面のボタンから、前回記録した診断結果をいつでも見返す"""
        if not self.diagnostic_report:
            messagebox.showinfo(
                "情報", "表示できる診断結果がありません。エンコードを実行すると記録されます。"
            )
            return
        self._show_diagnostic_dialog(self.diagnostic_report, title="エンコード診断結果(全件)")

    def _show_diagnostic_for_row(self, iid: str):
        """一覧の右クリックから、その行(1ファイル分)だけの診断結果を見る"""
        data = self.row_data.get(iid)
        if not data:
            return
        diag_label = data.get("diag_label", "-")
        diag_issues = data.get("diag_issues", [])
        base_name = os.path.basename(data["path"])

        if diag_label == "-":
            messagebox.showinfo("情報", f"'{base_name}' はまだエンコードを実行していません。")
            return
        if diag_label == "OK" or not diag_issues:
            messagebox.showinfo("診断結果", f"'{base_name}' に問題は検出されませんでした。")
            return

        entry = (data["path"], data.get("output_path"), diag_label, diag_issues)
        self._show_diagnostic_dialog([entry], title=f"エンコード診断結果 - {base_name}")

    def _show_diagnostic_dialog(
        self,
        entries: List[Tuple[str, Optional[str], str, List[Tuple[str, int, List[Tuple[float, str]]]]]],
        title: str = "エンコード診断結果",
    ):
        """診断結果をツリー表示するウィンドウを開く(全件表示・単一ファイル表示の両方で使う共通処理)"""
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("760x520")
        dialog.minsize(500, 300)
        dialog.transient(self)

        ttk.Label(
            dialog,
            text=(
                f"{len(entries)}件のファイルで確認が必要です。"
                "(項目をクリックすると開いて詳細が見られます。"
                "時刻の項目は右クリックで、その時刻からの再生ができます)"
            ),
            padding=8,
            wraplength=720,
        ).pack(fill=tk.X)

        report_frame = ttk.Frame(dialog, padding=(8, 0, 8, 8))
        report_frame.pack(fill=tk.BOTH, expand=True)

        report_tree = ttk.Treeview(report_frame, show="tree")
        report_vsb = ttk.Scrollbar(report_frame, orient="vertical", command=report_tree.yview)
        report_tree.configure(yscrollcommand=report_vsb.set)
        report_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        report_tree.tag_configure("file_fail", foreground="#9c0006")
        report_tree.tag_configure("file_warn", foreground="#9c6500")

        # ツリーの各項目のiid -> {"seconds":..., "source_path":..., "output_path":...}
        # (ファイル行・種類行は seconds=None、時刻行だけ実際の秒数が入る)
        node_info: Dict[str, Dict[str, object]] = {}

        for source_path, output_path, diag_label, diag_issues in entries:
            base_name = os.path.basename(source_path)
            output_name = os.path.basename(output_path) if output_path else "(変換ファイル無し)"
            total_count = sum(count for _category, count, _entries in diag_issues)
            file_tag = "file_fail" if diag_label == "失敗" else "file_warn"
            file_node = report_tree.insert(
                "",
                tk.END,
                text=f"【{diag_label}】 {base_name} → {output_name} (計{total_count}件)",
                open=len(entries) == 1,
                tags=(file_tag,),
            )
            node_info[file_node] = {"seconds": None, "source_path": source_path, "output_path": output_path}
            for category, count, cat_entries in diag_issues:
                group_node = report_tree.insert(
                    file_node, tk.END, text=f"{category} - {count}件", open=False
                )
                node_info[group_node] = {
                    "seconds": None,
                    "source_path": source_path,
                    "output_path": output_path,
                }
                for seconds, display_text in cat_entries:
                    leaf_iid = report_tree.insert(group_node, tk.END, text=display_text)
                    node_info[leaf_iid] = {
                        "seconds": seconds,
                        "source_path": source_path,
                        "output_path": output_path,
                    }
                overflow = count - len(cat_entries)
                if overflow > 0:
                    report_tree.insert(group_node, tk.END, text=f"...ほか{overflow}件省略")

        def on_report_right_click(event):
            item_iid = report_tree.identify_row(event.y)
            if not item_iid or item_iid not in node_info:
                return
            report_tree.selection_set([item_iid])
            info = node_info[item_iid]
            seconds = info["seconds"]
            source_path = info["source_path"]
            output_path = info["output_path"]

            def refresh_after_rename(new_path):
                if not new_path:
                    return
                # entries内の該当パスも更新し、ダイアログを開き直して表示を最新化する
                for i, (src, out, label, issues) in enumerate(entries):
                    if out == output_path:
                        entries[i] = (src, new_path, label, issues)
                dialog.destroy()
                self._show_diagnostic_dialog(entries, title=title)

            def rename_with_noise_tag():
                refresh_after_rename(self._apply_noise_tag_to_output(output_path, seconds))

            # このファイルの怪しい区間(ログ診断+フレーム比較)をまとめたもの
            file_issues = next((iss for src, _out, _lab, iss in entries if src == source_path), [])
            all_ranges = merge_noise_ranges(
                noise_ranges_from_issues(file_issues) + list(self.noise_ranges.get(source_path, []))
            )

            def rename_with_all_ranges():
                tag = build_noise_name_tag(all_ranges)
                base_len = len(os.path.splitext(os.path.basename(output_path))[0])
                if base_len + len(tag) > _NOISE_NAME_MAX_LENGTH:
                    if not messagebox.askyesno(
                        "ファイル名が長すぎます",
                        "ノイズ箇所が多く、秒数を全部書くとファイル名が長くなりすぎます。\n"
                        f"代わりに「{NOISE_TAG_CSV_REF}」の印だけ付けますか?(秒数はcsvに記録済みです)",
                        parent=dialog,
                    ):
                        return
                    tag = NOISE_TAG_CSV_REF
                refresh_after_rename(self._apply_tag_text_to_output(output_path, tag, replace_noise_tags=True))

            def rename_with_csv_ref():
                refresh_after_rename(
                    self._apply_tag_text_to_output(output_path, NOISE_TAG_CSV_REF, replace_noise_tags=True)
                )

            menu = tk.Menu(dialog, tearoff=0)
            if seconds is not None:
                menu.add_command(
                    label="元のファイルをその時刻から再生",
                    command=lambda: self._play_file_at(source_path, seconds),
                )
                if output_path and os.path.isfile(output_path):
                    menu.add_command(
                        label="エンコード後のファイルをその時刻から再生",
                        command=lambda: self._play_file_at(output_path, seconds),
                    )
                    menu.add_command(
                        label=f"この時刻({format_minutes_seconds(seconds)})をファイル名に追記してリネーム",
                        command=rename_with_noise_tag,
                    )
                else:
                    menu.add_command(
                        label="エンコード後のファイルをその時刻から再生(ファイルが見つかりません)",
                        state="disabled",
                    )
                menu.add_separator()
            if output_path and os.path.isfile(output_path) and all_ranges:
                menu.add_command(
                    label=f"ファイル名にノイズ箇所の秒数を全部記載してリネーム({len(all_ranges)}区間)",
                    command=rename_with_all_ranges,
                )
                menu.add_command(
                    label="ファイル名には「ノイズ有(csv参照)」の印だけ付けてリネーム",
                    command=rename_with_csv_ref,
                )
                menu.add_separator()
            menu.add_command(
                label="元のファイルの場所を開く",
                command=lambda: self._open_folder_for_path(source_path),
            )
            if output_path:
                menu.add_command(
                    label="エンコード後のファイルの場所を開く",
                    command=lambda: self._open_folder_for_path(output_path),
                )
            else:
                menu.add_command(
                    label="エンコード後のファイルの場所を開く(ファイルが見つかりません)",
                    state="disabled",
                )
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        report_tree.bind("<Button-3>", on_report_right_click)

        def save_report_as_text():
            path = filedialog.asksaveasfilename(
                title="診断結果をテキストで保存",
                initialdir=self.folder,
                initialfile="エンコード診断結果.txt",
                defaultextension=".txt",
                filetypes=[("テキストファイル", "*.txt")],
                parent=dialog,
            )
            if not path:
                return

            lines = []
            for source_path, output_path, diag_label, diag_issues in entries:
                base_name = os.path.basename(source_path)
                output_name = os.path.basename(output_path) if output_path else "(変換ファイル無し)"
                total_count = sum(count for _category, count, _entries in diag_issues)
                lines.append(f"【{diag_label}】 {base_name} → {output_name} (計{total_count}件)")
                for category, count, cat_entries in diag_issues:
                    lines.append(f"  {category} - {count}件")
                    for _seconds, display_text in cat_entries:
                        lines.append(f"    {display_text}")
                    overflow = count - len(cat_entries)
                    if overflow > 0:
                        lines.append(f"    ...ほか{overflow}件省略")
                lines.append("")

            try:
                with io.open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                messagebox.showinfo("保存完了", f"'{path}' に保存しました。", parent=dialog)
            except Exception as e:
                messagebox.showerror("エラー", f"保存に失敗しました:\n{e}", parent=dialog)

        button_frame = ttk.Frame(dialog, padding=(0, 0, 0, 8))
        button_frame.pack()
        ttk.Button(button_frame, text="テキストで保存", command=save_report_as_text).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(button_frame, text="閉じる", command=dialog.destroy).pack(side=tk.LEFT)


TASKBAR_APP_ID = "tatata17.m2ts-encoder"

# ウインドウとタスクバーに使うアイコン(64x64のPNG)。他のpywと見分けるための、フィルム+再生マーク
APP_ICON_PNG_B64 = (
    "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"
)


def set_taskbar_identity() -> str:
    """
    Windowsのタスクバーは、同じpython.exeで動く窓を1つのアイコンにまとめてしまう。
    このアプリ専用のID(AppUserModelID)を、プロセスに付けて、他のpywとは別のアイコンとして表示させる。
    戻り値は結果の説明(ログ用)。
    """
    if sys.platform != "win32":
        return "Windows以外"
    try:
        import ctypes
        func = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        func.argtypes = [ctypes.c_wchar_p]
        func.restype = ctypes.c_long
        hr = func(TASKBAR_APP_ID)
        return "プロセスにID設定 " + ("成功" if hr == 0 else f"失敗(0x{hr & 0xFFFFFFFF:08X})")
    except Exception as e:  # noqa: BLE001
        return f"プロセスにID設定 例外({e})"


def set_window_taskbar_identity(tk_window) -> str:
    """
    ウインドウ自体にもIDを付ける(プロセスのIDだけでは分かれない環境の保険)。
    SHGetPropertyStoreForWindow で PKEY_AppUserModel_ID を書く。結果の説明を返す。
    """
    if sys.platform != "win32":
        return "Windows以外"
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                        ("Data4", ctypes.c_ubyte * 8)]

        def make_guid(text: str) -> GUID:
            import uuid
            u = uuid.UUID(text)
            g = GUID()
            g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
            for i, b in enumerate(u.bytes[8:]):
                g.Data4[i] = b
            return g

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                        ("r3", ctypes.c_ushort), ("ptr", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

        tk_window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()
        iid = make_guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")   # IID_IPropertyStore
        store = ctypes.c_void_p()
        get_store = ctypes.windll.shell32.SHGetPropertyStoreForWindow
        get_store.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        get_store.restype = ctypes.c_long
        hr = get_store(hwnd, ctypes.byref(iid), ctypes.byref(store))
        if hr != 0 or not store.value:
            return f"ウインドウにID設定 失敗(0x{hr & 0xFFFFFFFF:08X})"
        text = ctypes.create_unicode_buffer(TASKBAR_APP_ID)
        pv = PROPVARIANT()
        pv.vt = 31   # VT_LPWSTR
        pv.ptr = ctypes.cast(text, ctypes.c_void_p).value
        key = PROPERTYKEY(make_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5)   # PKEY_AppUserModel_ID
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtbl[6])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        hr = set_value(store, ctypes.byref(key), ctypes.byref(pv))
        release(store)
        return "ウインドウにID設定 " + ("成功" if hr == 0 else f"失敗(0x{hr & 0xFFFFFFFF:08X})")
    except Exception as e:  # noqa: BLE001
        return f"ウインドウにID設定 例外({e})"


# ----------------------------------------------------------------------
# 埋め込みの TsSplitter.exe (TsSplitter Ver 1.26。同梱の説明書に「改変や再配布はご自由にどうぞ」とあります)
# ----------------------------------------------------------------------
_TSSPLITTER_SHA256 = "c6569f39d3e3af59707fd0045f4154c129ab737fddc84133f1ffa35eec15f65c"
_TSSPLITTER_B64 = (
    "eNrsfXt8VNW1/0xmkkySCWeQCUYJEmVs0ya1wWBNnMQbISDWqJMHCdYo9Io48sOKMFHajiFxZmgmJ4NYwIqKFcFKLVqUh1EeJgRJ"
    "UISAiCiIoNSeGK+GhxAekt/6rr3PZBJC672/x1+GD3vOWfu19tqvtddae51bfjXPYDIYDGb6391tMDQYxF++4d//ddL/AcPeHGBY"
    "Hffe5Q3GwvcuL3XfNzN1+owH7p3x6/tT7/71b37zgCf1P+9JnVH5m9T7fpNacFtJ6v0PTL7nqsTEeIcs49ATsZ++cPK+ev3/1VkX"
    "179Iv4+OsNe/xb+x9Yv511yfSr9TukbWP89p3fWNDB8i0w+sX0a/xffd7UY5F8LZNcZgKDSaDa1vtN2qww4aTMYEo8VgmBRlMMwT"
    "ME+Z0WCw0cP0KEENPNsEnQyGnl9Dm53hs3aYmI78Yov8Df/wn6MlyuDCQ6PdsPJf0LbtwShDyr+Ir14T1buPCE+/8cLpr/LcM8tD"
    "vzdPiBIITYrqjRj9pRL0qhmTf+35tcHwxUTZ9kk6DXr+qN78q0Qyw4SvBxKyUZyZf3una7xqxswZd9PzStlmrrPz/PIMP/z98PfD"
    "3w9/P/z98PfD3w9/P/z98PfD3w9/P/z9P/1rMXY+OMrQPuc7g2Eb/srUIy0xAGkzCXSiwGExeuLKtNBZg8G32axuuWuTWSSUf83b"
    "ev9N7XZr94wyTF7Ch+2isiXm3aMMWZtdoQKHdfJSANUjQY/Doo2hErMagwUOe+hWa0tM9oJRhqndwRvsLTckK8hae4NZLXA4XNqv"
    "PqM8W9RCyh9MRAG33+XbbNPRYHyR2VflsM2wqmNtLu3gGUY2q7FlrANlBcem1o61qdvvav/zWYOhN76+31I2s3qDrTlE//svb975"
    "5anbqUTNdTaCRFPP9EciokdDJD3KIwhiiyCIVfU6Usu1v5yRVEme2h2mi8vXYpVkIQKVE2W0MYckUWw6USZGUqXnr6hkfJnqcdjL"
    "3Wa/wTDVUKbu1SxjjQb1a99mq9qc3lFnqbWm+RqN/q2Vx1Uf5BrBOQhrms0UthCWONr7nAZPvlujirRBp6nqTmpp4IRnCIOoVG31"
    "GCO13toy1txNf+q5jqis7mBuupr1xnWU4tgLhEOyr9nsm+awGStfnUhUuvOO2wndMrWzvGYLqnoL9cxTYwKNHsWlpZxmarbEoHG+"
    "LWbfN8bKzyfe1UzptWQQLcalfXeK09wVOQbLs7pzqqxVI9SxZnWAaq8p1j6kVPwWzK3xjTUb6dk31tpNGZ1jbV5TsMpMGWbvoN9g"
    "lSVYZZ3Ya0iro22E0P05o61em2+02Zgz2uyNbRnN4h91tEVN8OXWGCqT3OtBmv9EVSUAbjYHzY/j0QTqW8rV3Hlv/JwJ4RttMao3"
    "W6hcZ+vEu1CWhZs42mpEJabgaGtkLzakZFDBT0RFGeTACfodyQRS/Y5U+hmvrnCk0W+ZutqRSb/l6npHNv3SCLItaTCNNrhXYmIZ"
    "gtMcacFChz3odTiCpY4Uik/VBg4wGkKFjgzfZou6JX17hyl0k6HOVms3Yjjsqjye1ah21xWaHbX1Zgc1WAySr9UW9WSdRbycDK13"
    "ICp9i6+lW+S/zehrQdQJtbWpPYo6vpWmsdV3yHRsGQ1Xe1FogSONchS7QvWOTGr6+CLtFPAocGT7NttDLmO47PRNvq4oZU4VSbVU"
    "Gjahp0GnrMZ+MCpwpKhtIv48zDYRZn2QUo+qpQ47UCumBwfhFvIzUi6JYzG9jyTcXNpdAzCs7b689URLg+I/gq7yOpINnuvcEGVR"
    "I9IoIVqVYaVWaeNt1Ba/I9OKoWkNuaKmqIRR1JTA1spv0zft7DI1dlxM8Q7KRG0l+va0No/ErwZl7lwKiRqOrBOUYF4kNRq7PcXK"
    "xoKRtCh6bcDLTEPT5NtiRHJKHJrsMPRO7+ycGaV+jWik6lMfx894BbFbCjKuPA8fUP8P9edoNpc6bO5zpp7WFmtJVL9az0OOmjnx"
    "rjuztmkTiDg1mzFeI2YQ5bVQ/5h5EXIeLadlzu796Wyzs+shR4m6I71VPTDk42CFI+WOWfbZ0b5T3Q8lprcM2UO4TfTtMt7VnN4y"
    "ccieiBnuyytFT9CqVq5+pATWEVa+vAWic16hFzXP9e0oQ125sfqzfMU/lQSNJ240pTZgvnpilbU3mn2N0aGRsep2Za0x0Fh5sbL2"
    "BqOvCY9W+ejTjJ4BgcY3IEydHevb2k1L2Vbqvri6sSZHZ+5Bz5j/fmYlcJAgooBGJfA+vZwYG9uo+D/CkL01rvrQAGVt0yJl2abY"
    "poOxaquydmy8+vGihNaEj+vKEpRl71qqPzunrN20qOmQJQGx1oSPCRpL77EJrXVjExM+btMAUNY2Lkr4WE168tAow/CkZyjkFL7T"
    "3ZXWYCKgwaGALkEgkrmKS4q08ejmvbSDqF/WNBs+um2Q7wOD+sGrQ9Vm7amUKINjQO3YOHofTO919F5L6H3w6gB68yL2XO3YBHqP"
    "pfdp9B61r/auxNqx1rrbTHVNjszcTCUwiDqierY5VgnE8VO0TQl0ExWoR2LQbEvTQYvaSW+xaDYeotDCY5ZFTV9YEjrFM0iE117t"
    "S+ikffBdZVmT0dSIZiYs5VYmigYiLBbJi4tc2m++05t5VDZzj0FtVve8eom2agg168YYfhuovcBvsfwWp/2J3yz8ZtSC/BZXd2O8"
    "Y3bj57HxzbU3xtMMuKM5sE/x/5Qa1ZBmHm0ILWMVR06yR/E1mvNmEch7lJNVn84nylQOrttZ/Vlm9WmizrcYBRPN1WdiOy450ZSq"
    "+A/rgNeVwF6DTrDthn4J9qVOsC+VZd9aiED0Lp51gtGrur2xI1b9Vlm23aisbV5k2prQugRUSTgqiKTuHf6x70x3paI2qXsECQXx"
    "XGVF2rVnL0g276WRZPvNpZFkm3RpJNmKL9XJRkRzzI7fWztRkK0XvzI+tMLR+WV3d4Mtifa9Z88YiSt0u+8Nc1A1Xz1DP2IvfDsY"
    "sFKqkrJyV2jMccFMBe/pVEPJBPWdilIDKfQQHKM9YtU8g4hPMWrf0XpO/NWY1uCY9cExK4JjVgbHrPadMgbHnA2OOVwbMBAz1TLm"
    "KyOvxBdTHrVSUx/5SrVudG+mjbRI++RzLLwWTPmWMa1I1/7aAEpm3+jeRgmKtfWRCdZzgseRwLzRvRu8nPZ0OIHSEl1BKxenuR9p"
    "qJb9XMvD4TRpoRuNzgAapISuBWdln1McHPOVtpM3JvPSedRH7ZmygsNcwXXhzPdHZD6NGW6dw+t4UWghGsoF3RxPGxa3m/eryO23"
    "en10N+1jFYp/B0WHNnAi2k1v5N20sfLElCVfUY1TgrHtryQK9DsZ/YbPJAZK4EFqXQQWnnPcBHcXaIXqPx8gkwbHNCj+e6kYF2FD"
    "OiVG1KXt4XgrFeVPAiNw52HCg6KJH2R+o5rfrqhMF7l6N8AVChkHiuYOxOY8u0O0Uk8KfiWiubmx8ZVDeyJ78xPpm2qtsf1VQtkS"
    "Ky/uL+bCGa74dxkql2uv7abmjmmgNoTJUeRrNmqbE3WKBLqJmsE7D6vjG4q1FxUeEO0OqxgLZ3ksXHVIHwvxS7MxVKKtoqMMC9FR"
    "Sjg6aarL5c6nFNqXOVx++74EMazNCzGs/3GwpyAka1+fIOqxLkQ9WyKiCxC9OEHUY+d6XoyIHofoKll4ChdeGxFdiOiJsnAHF35f"
    "RLQL0fmy8Awu/JcR0aWIvlwWPpILT4+InoDoKFl4LhdujYjORfTn8aLwAi78vz6NmK2l+mx9K17UUMg1bA2nsbdET5Jplk6mh/Yn"
    "4kVdpVzXcz0JGzgNEouE98taK7jWh3sScpqW6Ml61QWy6slc9a19S6xGiX6UOERWPY2rvjKc8JKWaCSCCrYl2q8X+19xon4P13/y"
    "QJ/Upt6p34oTSHhF+w9EtL9abz8j8UScQMIv2t83YVQ44f2y/nrR/r4JTeGEBbLqBaL9ByK6Z4GOXqqs9Rmu9acH+tDoSdDoGRR2"
    "0iJqXca1Gnta3Sfh0ueQeqtFVL2Sq37/k4iql+lVv2ARVTdw1X/vmwYNbq+RtTZyrWrfNGhr+52yrlau697INMv1unJkXW1c1+jI"
    "NOv1NEmyrr1c17DINA16miOxXNfUGPdBrs1zQK4wlVcLOqwACVZSQLVVz4ohVntjLE5fsS7tJovYh57D1FkeywhNjXZrjFJ6uKCf"
    "cc5oGkMrZK2K/3dcBp3joyPLmBwrdxJG+Df7e3bT6Fkya8dPQJkuxvWWcIKfClyRaKkXAWZrVuPSWjzXI5iHTjQLHN3mJ4DhgP19"
    "upyzh7O074kR2FifADYH9+mph/dXWUS+Z2NE9yU/ASSX7+uvlh6cpsfI5Y5x+t2/qaUnX7bAbqrZPZLxW0etoXe5OxylvNk3mBX/"
    "QEqWtW8jzkDz1KbQLGOdTZzwT6a3ODsV35FogyGwr1IxbS/SfhtjNCx1U+Ed9/jOGAXsHsCmAVbkOxNVeSlgRQTL2sVHUGXBpmCS"
    "B9HX+M6YKocg+mpEb6VoX5dRWdAUTGxEfJLvjLnShviLUOR0gkFiNuYrdbymWh9Vm2h/64vezKHVuSMyPBdT5JbzImd8TkDfmWil"
    "3kG8UXsaNYSIkcvEeGVfeJ/EKYt6I3sUEcMcDWIEh56NGm1gkqibUGp4E2aKPA6pls20Zyp13mUJRFROzqUFzYsNhLdnuDN6JI3X"
    "R6KX4scZ7SJgVfRS/FArRPmyZfZHuQ4hH4msaGbqvOrcqzM8l6ibROMiz99o3iFunl2pL6fm0fFi7ljI5KK7ouTMvdasD4ACbvOb"
    "H+sTLoPGE507qrNpog2EaKMlerOcPtpCs5hv0+ik3H7cJCa/yV3IY/Xhj8Nke87ApWffYGqJfi5Kn7bNlGHpMlAPC1V/42kJRaCT"
    "f2YG5ZBUveUrottyJgn1dC0GRrNRbQpy7P+ky+3eQHuORN3idjHq6z8Ko36/UaJuUfwXIVnTRojZehfm67Ioc45HYTwA3SqTEYgu"
    "ChZ8sk2gSQiQIK/0kzbKJ89zvREdPq/OPCL3Os+Q3Auie4Dacl2ljZrLeJu8C9pfAN2afZrBMxHygmwKKh9Qx7epY7ZNNUzNLSau"
    "d7vRYBqze6ph0Pi9DHibAfsBOOieN9FI57KOEeotbep4zkISmaURWdyN9xQjhaKOaVNvoRRuHNpc1ERKFBzTGBy/WR3fqI7ZHLrz"
    "yeD4J4NjnmkZg842aI9sxfjaLUeKeoumjqfDz+N602h89urqRzcRB9r+qlEs+2Z3BS9gI/eG++FevR9o5tUZuR/Moh/Op6evy6zM"
    "uceod8c3RqNB9sVX6IPwGrHZfN6ASaszD6BuuJy6YaiOq+Tfe3XG3urcAb0644n2P4c74xZ0xs/RGXf3ouxN7/XpjGwG7Keu6Bim"
    "U3hqLpF3mEhJ6Tpi9P6UvaWZKC4YMOBAutBMoRrCs8rPoTtrg7fUBsfXt4yZF49uONHSqxtoMN7ylRiP548w5dFt1AkdP8cOm/0z"
    "z4/FwUk/8kw7G3nkoWPFHa0EGHPYSFSlQsS5jA5iSv1FR7q7s07kVB5W/JdRH+Vcg12AwPyMjcdjDV4D/iR4DRitHPlcQYuIMnc2"
    "4emG2kBU5CrrTjJMH2Wgs4sV56/xhmKKwDIU4maHT2Tv0enT/RyNGvdyCs5LY0Gaj7vQhDSKhEi2O8lMBTu3LEXFlUPdDZRPO0bb"
    "ia8xnw7X0bx30kl/EElT3ZY/jUIOC+fwpHW3qbalkykfCaWjppq722ihvElNZMhAdRQBgtfgxZ1K+bRn9ULHUqFqIuqjoou6k6xU"
    "3FSjaLogifbCOZLBu1d8RnnnUbBlzFmjmoSiyoq1LDqwqa0kRXZuDyZOQp7Ks54i1ai67FON3bt8ecz0qRwFaHIlwTsuoqMEAfDX"
    "8E56vqF5qgFpwfwZetKmeMyUNgpxocAE2iRc1PS7SXyEzdfi2wAQNuCsfTlD0YfBRDfl9GTkDAU/4bnI7UVLpySKs+MXVJl7HiCl"
    "ErIbIqw7Wz2x7mUE7oh2r0bsL0SsezNefiJecu5cT6laRaq9iLBFpjLJVEMh8aCEmkjYhbh/WmUczl9vWZ6kfo1+y0o/OUNxWNwo"
    "IBsFBKfLNwXkTQHBcfQNAXlDQHDSbRCQBkDKy0j457bRk/Z7rivZnYaX3+gVgyn1XJEzFBzobKI8fjERgxzTQeOpO2kyKUXVPOyD"
    "bhLIGbTKT2kfnIB+GLMCyqQxK9XOh6K1PZ+BYoerfgVRxU0GZ+VKOphQcUY+QU1A99HfjGjtZeg1x69Xx7QWY8ST5KNI3a4VWni+"
    "UrYg10UJ/ZSwZgtmhq/DWPlK1j41CdUWa98dMESgz0hOehDtx4CqulIObBol5u5dSzBYXcGhAIkRHBxaIZB3NnviXNrfDkglp3rL"
    "8R6d4h1qCCK2rPe03xETVfM2pHLqP+5s1rB4+/LcLHgPhUg+6J5ME7F9Bj31kue5M0DoEpOcSmeMPD/dkwDN06H/kNDnAP2xDt0h"
    "oZmLCDpQh74hodWAnomS0KUSyt36Dx0aktBWpN2hQx+W0C5A39Chv5bQcU8RdKkOvVlC3YCGdOg1EloL6MM6dJiErgT01zo0TkIP"
    "AnqzDj1mEFDL0wS9Rod+IqG5gA7ToS0SOgvQOB36qoQ+B+gxo77+Seg2QD/RoQEJNTxD0BYd+oCEZgL6qg69XUKrAX1ah46W0OWA"
    "BnTozyT0OKAP6NCLJdS+mKC361CjhBYCOlqHdnQbRNsA/ZkO/UBClwF6sQ59S0LbADXq0L9K6FlAOwwSOl9Cs58l6Ac69BEJrQf0"
    "LR16r4Q2APpXHVokoV8BOl+HOiU09c8EfUSHXimh0wG9V4cqEtoIaJEOPXVOQDVAnTr0cwnNfY6gV+rQ9yR0OqCKDn1dQhsBPYVK"
    "AF0iobYlBP1ch6oSWgDoezq0UkInAPq6Dp0oocsBXaJDb5LQvYCqOjRLQjsBrdShQyU0/3mCTtShsRJaDehNOvTId7I3Ac3Sofsk"
    "tBPQoTr0bQnNXkrQWB36dwmdB+iRcxK6SEIPArpPh/okNG0ZQd/WofdLqBfQv+vQcgldCegiHXqDhBpeIKhPh6ZL6DhA79ehSXq5"
    "gJbr0O6zkr6A3qBD2yW0E9B0Hfq+hOb/haBJOnSDhM4DtPs7CX0xsoR2Hfq4hDYi7fs69PcSanuRoBt06D16bYC+qENv02sD9HEd"
    "miOhewH9vQ4dLqGZywl6jw5NlFA/oLfp0JNnJB0AzdGhhyS0C9DhOvRdCeV1PVGHrpHQcX8l6MmzEvpnCZ0F6CEdGows4V0dOlNA"
    "m2Gfk9ejXSqKsM6xSOucpqytwdpskigGa3M5zOewgMNxHHYeQnicwy5Y5hRSbrmHktYsUsNVRAZG6hxkIN19KiU0q08gI50zHmyj"
    "nBxFM+lDZgNa+JXttOYcDz91yaeaLUBLi/uEdCoDirSv9whzmNsj6xuvfuU73NVQ8QtK6CJRd48VyYRf4GRhKSnLOlGunipjy5AC"
    "shLxkHXIakctuB+PYxb9z6D/mfS/lP5PCF6z1wy2fz+FWuVOwYBcA9lgZbyaCL6JzEySy9yp1WSMonWxpMFK3Po44jUeGV7u3obO"
    "ORHFewHYi3rGg6wHLt0pOIus7g5bR5w8HardS5BRsMjGylsF5+OGpRAdqe6NB18+mflya6jCkV9CQWqJa2kpgZYgJTUqjf4XEndf"
    "bHF17yI2irLWnDO0xRq8y8gOY1Iszhv1jskDwH4VOtLIkMN9EZVOcdOMGBHaT3n5smc1CvlNvXkSwckAZZJVN0DpoEwoCJlQkKuc"
    "Spz2UyJAkTb0K86NFAQodndy+2nzIqMIGN6QgMYzpBwZUC3sSFAtNW7Vd7Ja1DhA1Di4p0ZCHW/vdpua68YZBfSEmnj8r9B6d1EY"
    "tExRE8/iwWWeEhxncUe/RAesBYwgEHUbRcunXUHVvmlAZL1jOuGgBfcRN4eCKLVHpp4lU3t/FJG6GqnvoNS+zak5eRCRkyFHBf0f"
    "5ylzV0PxR9VR8e4oH85xHVFiMLR4id0cEi8OB5yMyPYjmcylbY5MdjyOk+nloi/pfwH9n0b/3Wp3uda5nQehO5+knOVu19lRMH6a"
    "RkZO0ymFl3Pk8ZjNw5ilUjKCeduA69BlGK15bXjOa8Up7pvLuOqprnL3Xrx/2vNuOAsWsud95RmwEPp7iXs5VGd/73nvwvufe9LD"
    "JEB7TLxLVKfTANW8PUlgIqBNE+8kt26l16XbELQh2A3khxZ+BsbdxWGPNQc10qbPGI/DpiaCL7/vhIEODsFnO5Fx44REhCs4XMmh"
    "ZQBCK4d2DpM5TOEwlUMHhTkbR+K50JFSVax2q09k0Js6Jw2hdV6RNmsXVRoBDObO883Bq1EVP88iOw5Ic7LpwRsT3JgRLnX2Sthu"
    "NR2Md7YIcHBjJodcJWeoGpm19U3IjE5+psxrOvlRQmuRdhprxVzEmiBjNm0tKncFuXYtYyjTL/hsLpeTj/DZAg7HMaSQQxeHpRxO"
    "4LCCw0kcTubQzeE0DqdzCR4OZzHEy2G1IN9ehA0fIzaZnkNP2G0UzilURhveuBoaC4vsnnnBJ7PpSB5M3hJFU9lcs4mPde3Gyn8u"
    "QZ+BDONQ2LN7v0CYwgUXUrhljotC+mn9iH+s+Ak+m8qJHRymcZjBYSaHIznM5jCXw3wOCyh8ZMCirE3pm4j2wTloHXWELb2FDZeC"
    "G/1oysZaDus5nMfhkxw+w2Ejh5sRzm3lprdxuJvDvRzu5/Agh4c5pcbPnRwe57CLw7NcmmEfj0wOrRzaPkdsK1NjG4dtHO6mUPG/"
    "RdimNyn+x/nXc2cOn5k9P4bFmm/TueLQnONWOq+nvoSz71wbBsgDMUK9zToBarNqDUCA72s85wo9wanTXoJtgkh9g0z9NxidQDyh"
    "JiZT9BQ1KYV+ltp2FRieu+wl2BsdbysgS4ikLvp5/jQFHb9XEzlDkg0Zltg5la2TkE86/vVow5SlXRR2jM9hgzZPTk6el+UzqDaY"
    "iOnqidsSDYQMHZlqokXUahV1ERR10U+HfQmkHUuRrYWTTxxXYAjNxVPRecv93ONmAZ4eawiv94s+6O6WIKTEko+lfpbcj7zYj4iQ"
    "ltG0ON/6D6baSNpwfJsdvi47DE2V+jlnqAiWty5ZxsO46lek+PGM75Gt2Uj2xlIr5w7P9QBA9tXWW/ZF0ORKyLOM5d1tOSzq6okR"
    "ki7EZJ3I2tcRq693iYepSVTo3Us0elDb0nc2nTY7j84s8XkTLPHeNIqKS29q6jKT+DdBy96pZ2kpoGi2LTb6mm0dr/dOZwunC1Ix"
    "Ms38jYdp1IWezfwJtXajO627m8yjHZjfZOin4xNLKqLHMMe9VhIUmHj7omj1Cetl3d3OiytjgnPxFFS2mMiYxkz2VFgBpjkcxspm"
    "dQ6iAo3eQS7tNG+D5hYGsU31nEk/1iM/0SMBEpETwpGNeuSEcOTkcORSPXKyjMxqJOyCczLpNTjHzeE0Dqdz+CSHz3CYeQTh7mMI"
    "J/Ozm8LaOdM4PHwUYdpRwJ/jNMs4XM7hCg5Xc9jA4X4ODyKcuwDlzx2JMudajyO0Ibz1cPBW7U1ekp44jIRPmBn8VfDWzuBcOydM"
    "RjgnhUMHhW6WEtNuQM+hORkUkkTiYuK3LqN5nHPXWRLRZe2gfqo667wePC+9D6f30K1dZOMZrV1Mz84znvvJeHxn+vsNs59PvP7k"
    "l02nE9VNTdow0ya1675uGNKbKKfzI9oUbZ6rcE0hvZkmQgrxh8RDprCpveldMqu8jComQ3q/kOlVOGyVn9LSNFKNKXapLVr1Zj6E"
    "BK8nthQyvnOH544nifvTMFJMBN+btW9qVElJUXAo8y9Dmed+mTqwhLgbl5qEJCXFVHGpdgUx2szxioy+zSnMJBP7OqobRrEc1bmI"
    "sDBGCwYePPLAJBRpJK4/ZL52YKkjQ3uZzjx5sGWnUh1K/UGaIUKcuLTgyChD1Y3hCV1swQUGnJNSXWXlzFUR7929i041V/CySnQQ"
    "3LqLjjaDBzPDm0L1M3OeMxQnBk8BwQpJ/Eg2ANM/5RQF4u0/P2XL9MKikhKtgp6pVPCAhaFSR0Exwcb1wArAClslF0+WPe4JL0ET"
    "Wmvg8iaA7s2e23MooaeEsk8rLgGvTQnJHDRWFBNDxUzriKeeKSzWTpHNAiFfQC1zEx9XzaUdOBBO6O6wqsBCa0PCbkHaJWgU5XKY"
    "Wkw7nK3qp8SjEWRpIZQjf7BC8UUDRu2sdt7oKQuZv8NKkd7pPKC+r/hwg6L6uhsrU1jZH7JeV51zY2U8LbCmHaSg9B6hwGP1bTI6"
    "98zY274OS8zHpg+dSSha1KL8AQrFrF05SauhsQkMpEPhkgnfEI9V4MhXAs/TfMghbrgygQzXU7uVwC4LzEhvJjvQ0VG+Q8PYpDgn"
    "CTod3AxQj3iitSd20RAcb1PHWKkXUorYWJ8GMe0HaLobLGUZxeRq77kwhFN8Xd2KvxZWiIyReg2wM30aMjudWySScwxYicRA5Oj0"
    "Y4ETYhhWJZSVlGtHB/FWK4b1Gxi96duLTOfKyWzvrLhxYvWdMyr1d8GihcbbIjGSe8bwoI/p7gdvKBiOVbeH5d/5FkLbVkxBKtkC"
    "l4pzoYP+Jwt8ykyny6EL8jhwoYZ6N4WnUpGaiLTFpiaXNp6QI9YaAzir28hY5+RB7I57LZ6LnSc9g0jlZZsOMA9ts9Hj8JRrJZvE"
    "CbnAManSTr0wWfG/g+lNudCGLDq/ZMoknI+m3aQgJ0sivXQOHXMU/zIDP7kV/1PofR6lJfvFdCH5HJ5oXFMP4cxeREeVKJy2rt2P"
    "IVs5lZrkpinyJMQbIq5IGyLibv3E74C7k/3LHND+7h9qWTPK8OnBE5tvqBy6BEd52vecnXTqT1bm/s7Ia0JyOww6fV8bGRqcDCjR"
    "sf0OMcRLnWdmp3jjqXkup8eRNtNOT2nqGUrsomSlHWbEkLI0pbxMe42sbJ3vey+ZHeOkzntooJAe0GUokh+0P8HXiqZeROnqRLpU"
    "mS5ZpAvZ3+NJtLPh3ilTppz8suN2Sm6h5HeI5JfJ5IP15CHWpMnEGZQ4ihJfxYmJf4G5fjwyKHN+x1wFMonU7U2n6cZI09fDTEfR"
    "aLr1dDddvsFscG6p+pXzCKfyJoWsN4mkYqMArTquC2OJPUSPcnZ6LzFtjSg8IoeFOIpkcc+FVoCgqIduUgk5Rgb99+TkQYWn+B89"
    "g20Cg19NwkQgVXP+KAWCpAkdRloO/Y5GqPOWg/fVfnuGj9mthn7MfKF3fxTsMCXA0t8ntvG7QGOVQubfmolYmwqHffYx6kf6lcm3"
    "+B37GeO+91UU/3IC03I7stEgWEmYtRdrt58TSIjspmO4w4FK+9jHEJ1mOugWDwonq2PdXiDC+HjFS2x83IN23/wzHgW+HQ6S3ej8"
    "IklTkJikKVyukKagNTRPcmkeZfeQceCX55Hx6tN9yDivLx139qJjn/s2oGRiL0r20NBm1GnYi4RL+pAwGdy4Nvi7/knYqz5JPxT8"
    "P6VfgOmX2i/9uFxBv6xGagAcCmGJSFFb79sKfsb3BsQKhtAi/Chz842QeVYmtojqUsddZ+i4HqeEVLpo5BlCN35c1D4mdgNOYNrb"
    "rPe3dlyyZCW91yWuxtlHZK6t54QSc7Ut8tYX8OBbX/3dR1OP4tqXuI2WUHMKPV314wbfgSGjMRUvklMR2x0j0si7f65ABBk0InTV"
    "5Q3v3/KfNmSI0TO4NwuR2GZ0U8eAInerkLZt5hF/5mTksLkAutJepT98mXUCzjh28ZkrRalfCFN6Ph4FthL529hr1eVQ9xaCDasa"
    "jLEL/b17G4/dh06K2gscuYQoqoXAM5eQRKJiGvdoHHGMl/yTLl0Y1NMq76xT49XOJVhfSCbZ/YURunSXduILIzNcKUYxKr8yyLMj"
    "ySTdu7m6WK4uBVURsMh9nKDad5RQG/sPDJxUMokRo7i94QTviNOpXflZWxtw9qUrGZ4Y59HKqKAtmsdSkzFvwppSg/eL4mLBIRRr"
    "V/H1T9qP2/9ABwcWFBcXu2gB9bKVmxKOximFJKU9RmxB5pQoZmMHHRgygdndLKc1tzdHG3RGGpt8KNcSmocx5vxwKdiYYJ5g6ZYL"
    "UZujOvtGT6p28VMY2or/jxiTtZx8x1LBms3mOzsuYrbyo3yfDWv6zJLQJi+sEabs9ko97YlVd2hXbI3gufL75bnKmee6/cYenssO"
    "dJnlYsRMW3pXP6eCmK6NyJq1T4wvdTBtjleqc9OISXS+6xmizsnEU3PVQPDp841SegagfirpXEF0b6G1MZfGTnYJL480Bo4eJsaj"
    "C5LrFfoCWUT7U76W+C2P9tUX3Gs+EVN3eX97DWGSIFfI2Sd5nxkpk9IYz+5/jXwVErYY0b6S0IKRK+RoxIrj0r48qa+Vy3utlefd"
    "76D18kqakNkXWi/VRLFgKj2491lvZ9QQDzSy736zXKyX2cbI/WZkOU2bMOGKtb3H+hBNz9+Hdu/1ol0/+0tcmHo9dCs09r8/L2OC"
    "+ZlgGG6lmM7aGyf6J1g/+zPoVXhBeiUJel18YXo9yrRKkHn5/mqYXoU99KKZkmoQ8rpU7DSXIbGUt/S/2WT3bDbLL7zZrOjZbCYc"
    "7XezEbhwQtmKPqv3ZRe6Yvx995kVPfvM7iPfe59Z2WefWcn7zPwjkYOIrkTfZPj+yIK4vTeZVKV+ce9Nxmzsb5OxGMObzEDZBC8t"
    "Fh5HNlb/y8QWgUT6JkOc9+qD2GRoc9lbrm4qo8oKtSUH+eSdW1RCq8uCg4L5miAVT+PkTuO5iurq4i57oVPsMDQgCOgSO8zTX7BM"
    "BYIFHNhJ9rNDnJTEWxy9QWiHocPjmaai4759GEHqfKgMsrqdHyr1xejoVdCH0Mnu56oKbYhzB5lU+aBQuK+R19jWqii1NScPxl2e"
    "hCIy9BsvbC1VFQUVadnfCBcGPryyHE7tZFmlUj8DJsnzufwPPb9QfVx+S1WCq5juZMlSOLpYS36D9qt1rJpZlyo0KcF10NHk5MEk"
    "XwkloCwfSp5KdoBTqRPqOnFeXoJo9TTJfGxZm6ZSxy9yw/FisSvoYdWYR5v+vJGkEENOB7pnx3vJncNMM4lWu4Urgz+RI1CBL1U4"
    "lXqsiPooU/s509zmy8PVGIMnSZ2PJCGuvlj78xPcYqfXMVk/8imPeak4bzIdBycpvukgu1VOXUF/GmaiHq6X2I/HeSe26lUMoY0n"
    "VbQvxOmmGou1PVyRpabA4Vov1oVSX5uBzm+TIQ3zvjQ7nkAuep8041kaUqlF2s7XQXHZHuJhtOzvQLaCAdKsX6lvxhF2PpRBgV2e"
    "YaoKVVBga1US7cTa708LdbwPQAOfTRldGsgddKVmahRV6xWlUQcEF/BRXAuhH7ooX7k2DtWrojYip9o5lTZLD/lguA9p5ks0gNcf"
    "xR3FrMZAN526uqtzM+M9sbDUbfEe459HEnvBnC2hcUYIIpXQm4IUdvWI8+Qjg8T+Vp0bk0Fp6SB/kvLjB/m/F2wg1uMLpE2t1GGo"
    "MGSNKdIKdgthOvX/yUeS4EdB5B8QH87vLHV4Z1/sxcl81sOK82ToVoF5/ViaHSTisJEPDgpZh8k0IXo8clbvJ3IzQuYn37AIJI0M"
    "B+p5mbMXB1Xo9LRv1gj/KzxUXNqbHXL24ZUF3d2iTMzv50EpdQLPasy/SWL+MQ/0mOD2g+sAFImKtD+uwSycoM8/KAvV+aiWdf7E"
    "S7uT/8br31e8Ak+LElvo9B5GRVSevoXllFFs8HFlV8QQdGkWHeMCfb2YP07i+xLjO1nge73qmybwHaSvPsD7Q8nfczK6q7QaGLMm"
    "c900HW834+06H+/bOy6M97i+eN9/EniP0/F2fSnxHifxzsnDlT1l7iK4jBAnnKzG9DOhVdCHhlToRmu+QQjvPzQLbDQIUiFG8m2E"
    "4oTY2omUM8cHFSvdqGcXD362NA2Yo9iqYFKctLawiN3BPVjaTsQD7hO6qgfphE/PpAjDvhHDgyW9Df5ubNLfjY/VhVTHHUxf8wCh"
    "HONDk+tv2GNu+JLpsl/uqJ3zeu2nMdLzST9OT8TWDxEjBrMPinRaZOaWMqclz2UTmPQH2ntX8T+qgUS7dqL4XQY2PrKHW1HBrfj9"
    "96mi3/PneRVht42R0nbp+MQtiY5pBz1inFAtUpdo179BSph6BvHmTSZR7smMkqaFN+9+ixNjkctL7Cnv6wYYm9g6rsO2IfnRWmu2"
    "7M6QEEIQcxdpEjON6qtLmv43mMTUusy+vFm8r6SGTU8wC+JrcFS46aCY+mJOskLWUHkdXBJ5R+qb68/aeQeUGwDtDV9+SBc7fFgL"
    "YIQ1+p/SbxEGsqxL8U9Av/SsF4PD8+7QP8W8G9zPWUmsGEyawTzvvj3Wa73Y+4VY8GgS9awZNWCVhWsc8ppU8w0/d10dnmnUjUr9"
    "grPA7UnpNSUa8+s5JkquIEq9MNsBUYq0kZ8ybmGDnh/JGCie3NpgEUvP49RVB0k96lzFStKn93/Bcngb6deaV8FXEt0UhDGZ4jdS"
    "heQBKb1VaNfae7Rriv8fuND2e0vO782UT6V8zn2kjngUDycVf4sZK0lO9DNCUp5N/3M91zlnWmZcot2FNPSkaKXyKVr7JSp+gq+l"
    "zIWLqaLiMrfnb7jwUCvZmOcEDe43iCyXaBeHi0kMF2NCMXO5mDkohtx4Ya3BuPHyYB7yBfeiJ0rYekX0Ik3GcfBDIIYZcTcjxDmD"
    "eFA7H3k2okBRzTOvUdR/EDbDcfLJe0agViFRG655X9ORnPGajqT7NT33Xa9B+ay6HOo40nK4UorUccn0a6dfG/1aSQsCeU9GsavI"
    "XQsa/Ocf+FpNmAbzwxUNClcUF66o+1W9om9f/d4VEZX8oNJeptK3h5lK9UyljL7+is6jVKw4SohKq2WlyUYS0ar5KQMLWBphxzBv"
    "MedBW4QhrtS/igML1Q4LkKx9WSecv0T2G15lzigDN+GqMdMn7pesWaDbe4mY2uVa8T/gQGuvelR75HODcPskaQNn6LQCZkA/5Pwt"
    "SvxmJfMhLBIhHyklkIOg/92OFTjKxYm2eqPEKtfbKwXlmYSZFMXrx7BOye/KDl9nZPYSw62sRKt/3yh8ZUF27s7mwld8zoV/xcu5"
    "rR8By15DeL3vT5ifAEGbEBJ8K5OFBdD7+gpXcLKMsMekPSCfRn/KQSljSWYZyxwxATSxwZgOQLRlOq92595eAumn/4V8ZX9/8oK9"
    "M2r6kxfsP08erR8/y8t0ibk7fwWuKPh7T3sXs/B6K2AMiR6czES+8bM+c/o8eRH6sbCnH8u/FrurUCFmOIswTFpfIQkaDTyYANBR"
    "E6xtRvuQM1h+xYqbRTt3hcGbSGVV0E34Q7ykE2wcYDQlirQjBwWstZu6rYIXWvjz0g/ppKXP1sWf0v5DZGiJBoj5SFrPyciWzG3J"
    "zva1F4Sdre5fDtJZ7RerIy2DKwazfzkIc0vgYA67UxndIFsMvwrwMDdrME83WsuzLiVGbbEbGmX/j+nZ94iBPE2J22Wkw7wU7reM"
    "5Igr4VLhiItvf8KO2JOgrH3Y7NsSjZeQ9Vp1p7I2ytkMn1qjjNB2N8OnFj+yTy1n85vSp9Y78Km1i7R2gbWXUH8Umao/66w+TXdN"
    "X7wEu4O/KLbu1+baZxzP0QCkDSgfNgJ1N0Rjv1D8X6MLi+KqPxsAb1q6vy1yn3QD+9vqrLshQfiacpyDKy12nkSR1rqbEhlOHre+"
    "iIU/qrZ2vMHB0lRDwsd8yZNjSsr45FtBNhk1bSzioBujxN9mEmik9pseUD2rZIPPOODPSBtPEUFYhiysAGsLt3SUwUWLEfW3q2wq"
    "7C8n0HgYOfVXxAg8vIMlJaUuVSp2i0js6VhPDXbXrsBSW/cpi6e9sNHaMqDm3FpIoUNzkiGLNl//MziaA3kLrjf+rAsSnX5dlsHW"
    "oK7g2ihlLThB3yEFmlllbeH1JmVtm+8zo2lXU3uMaVcC9VzhtTGEfamytvTaaPVj3+fDKEPT5zGOxoR3c/MrK6kRybT0+LqiH75P"
    "WVuBAgquNfs+NzV9bkloNjXiX9OX0QlwOTfjxppT3WSK5vkPZ6Eje3bOiYJrY0yVV3MRXdFVedxu7CzLIXVayc19+oBYCf2O54x8"
    "RdQ+nZXXsuH1sXAOUHsxJVrvqB7Mt9g/xWk/ZCGT+eEh6x6enPnkfQ6SouDiZAIEAyl7QKXgYgu/IZFvw94PQLqH1dBqeghsVReu"
    "pF/vvbPNgV0P/VpdsxvQE+qGNkCLCNr90M0kPyjRvl3JjGt615CjZPXA8UFOPdtGkpfuh+NbAigafeDb4HhfHOQLKi9W24KLUUVw"
    "ISqUUZ4rJDAAYHDxcn5eQWFL4LkPxN0ANVALuT5JQxT/3MG8V8HaJr/nQvJn7+ljkW4knNHef++80dooQL8qp1GKYVYmB626lzq7"
    "QjuyjUdhqirEHTTeSrEkkrlIiUtUX8Y6DGL33Ad5TT22H/3kAJNPwGLRT1lbQ4EncWYQ+gnXWfLi5pnm3ONxqzY83kaPN9MdRjyP"
    "o+cC1WXB8w30nEf8Bp6vo+df+JqifY1236mrvW+2P5YkNnxoZY4IlqA0aGn3J7EqqSPR1xTVYfE1mTpMviYzZYFvTCV0O6L58Epn"
    "qUJ+8Ypz53/gZQPaRKdTBYWzDYtUvUBflN6Ztc95LGzQ4irXLpeyULbIasA3TugUTQYt5Jriox6Dlkeisk6oW3oZs8gLnL9yHqsq"
    "k0Yswm5Gml0lw+wq08VGR2WmLlhf5dL/NLa+cmCmMAckrK84VZGprVh7vFPorBin8BUJ03b1Gth2hVIsodyYoNB6Wa93vkt7OG4P"
    "d5PROSu+0NSHH6z+jxs9F2t7qvj+yt1ql2mLs1nGjVdbSD/l1n47m4fbLOfCDBqtlT8nZCe4dIHZeK3uFKaCnfa4Cd2Vl6tcuvDa"
    "KBAxnePqRaEPPQYjLgxj0ZxgEuu1AuvINVtoDV9/iX+JPVQWUJvzxTRRFxbGGViSGwzx/CxW17C+C7LcEOu7IMsNuOjpQrLc4Bei"
    "8wIoyqVN+0jsqfzKe2poApej1MNURV3owduHnuFqwIunlqpLwrIZkuk6RWnBDYhUQ5PkeXhajDwIkv7nI8FuxFxI/yMqFBwy8hGH"
    "/A8Y4y4EmLIUa617JY4TdBwXljJWpO8LuRlbkqYGpgv8WNa19B8SLwDFyI/ayBrSaxaIewUZZLC/pouImMMiGIJUkAnrmtQD8A6B"
    "9vsfgjuthWmi/VR+piif2z1aLz+T2429TQ2kvQ+fx2T+dlKZezIeiZX6b+IFMf8ZD+Z3kX623q5Cx0isj5yV6seEQCqNdVxVGget"
    "gTIX8oP7TiBDmXZoiUEIWEsobqQ6xlBOrlI/6iWyHkBoF6lva8dmi9Mzo+MMALWWwO5DgnLMLIRiYnggV2AhuW8XC5pvIY1wlBjJ"
    "UHbmap9/ILj3DaCRwXOJXg3pcUlSXa6+p/20mmXVkrpK/b1R7EK2gkYxCd0kf3TIIPijN3RHpbeZaTkz7WC2SLgaZV5IuBrtYYsC"
    "jb3ZosAuJbDQ0MMWHVQCsG1qCbTJO2PkKJJ00eVRvoPDyINkwqYgt/nEDbGNnknE6MQ5BoDvOZ8xIkekRQlgjMgRKXFF4J4EZxTJ"
    "FtG79ER6LFawT8wrEUc0DtabKtfFeuv/ZN+ftwlUhA3iO84mJfBLY28+MTmST0xWuRlqa/r2mib0Qc2pFSYwNnaw/hswJmlnj6WX"
    "NxGbvqeYVhKaZ2mOA9COPU7kbuCILUZREIcQtu/zNZ5VaqFbZU+xbzhehlYtHfnU65w5lRf5NDM2ik3kz8g88yta+u5R1l6trM1J"
    "P1k5hjoCnl/ROZ5fhsFXRYKzwuCLI8EpDI5LP+K5iLgGaiCbgM5OoAFPDkTonbQAjZ7B6kLGk5yWfGl2fqzMxbLcMTx9MbeBdoL0"
    "AzXNzVDVHjA1V1tSWwJMCcFDZPvo0GBkTx8Y4jyw639MJog0BAuJNbrCxBXiwKE8mgRV0gYz2KE1hj18DAWzQFqONW9HcAfMUmvP"
    "R4K4f7XH3kZiZlZhSpk/9VfEKHhoCuUXUXxmMfkeX79ZMg1kZeliC0ZS90k7HnfGy5CJvbdbcAn1bJVYJLgEFbf4aBz1oHTF+Sgp"
    "56N0djMz1pPJ0coePg+kEBZqAK1zlQPPMu32F5k/KKBFAoz3SBeawHy2IpBNAzvOpz2JLKx63KWMbOpuIc3ojewGZinXWHrR8MHN"
    "5yF81+bzEL55s6QhmeyCckRDMhTlg0C+4M20Wc2MVj40Y0ArFRwXYcA09L8MTiv4vs5pAS3JaalrnsTuuOGZDyLR+rj5PLRams9D"
    "azWBQD0QD41DTIpgoIvKy9DN2sC/MI8LGmYDrWxBR1rGWzYxwuNYcUOmt7T1kMBE0nEF03EvrpENZb49gprvqwuZkgHUo4aAeLG6"
    "EK3A7vXcC9iH0ZVqpxpA/6LaCkIGNU2C4u4RJKH1whiycQkIi9K3DCl1TCh2wQQDZlPu/S9jCx6/CzTLxikCZ6ru91sCSG4UMnUU"
    "WYidSKz0wUDPsSDIOAR5hCn+l3Rrb1LvYQcipdW2g7x14J4fNKla+65IGTL1wV+aiEAh7NaBrUGeqEo9lkhIpqB4zaA2ZWp58AhK"
    "bnitJVrXU9h0S+Pkdkd+ytQubSjiAwJoLaGtb+wOXZe4ryqsD8yWusNmoU9shj4vAuZsFvrEZCXEWqcjzmNIcb3UAh4TWsBjPfrF"
    "82ISvydM6hevl7pEgmO51s6+HtYjinzx4XykP3RI/WHqTMV5TOgPSaBdBq1ThSO5CjcCktm6molDjFzeQZ0orD88xaS3l2uNi4RY"
    "Rd+W78e2LPpW8UONgKHEKpsoZpszYJ9bN5Z2rDKciPVNKyc0jYUfQ6N0BsqkBOhmgGE57ervsZ9vuasTptnYzW7Fzo6XUMoIsv9f"
    "Sx9KcLb0yD1a+sg9WvrIPT5UAg/Bl/ho6Uv8PjjM2uUfHVs308zMEQ29upJoTALPZDLx77Ojk/Pw0fFkFUCuxU/XldCOvoN39ENi"
    "R0esNeE0QaVrcXpPTDiNHX0HdnSCcU4o7GhOZKMyX9OAmlNCwPAJMxjmET0ChhE9Aoa+jErljLqCEURK74hokic0fUnmcQqGOQkR"
    "RsSon0KI8KUUIrxPQgScXjOlECEbJZMQoWKE2XfQBD5GFyJ8E53QAiHC4JrTLEQYQENm3GwL1RSz3OQZSDuvxLW+tJudZkWIAOj4"
    "X2lnawOSqgUX9sxvsQ6wQmcDngxVV9Ns5rlLk3nix73sFZjxo+8xvKeNeEgwfjyfjTVbkJ4ueiUblcBq3AFYWA92eAyZGS2sgK9W"
    "fm/6LD50izm04KcOYquh3zLWRgl+gWSkR1vGMBrMopM+m4c1GQGQ0O/dbZL5L9WZ/wBWSzXESz4fi2oCEDt8+3cskwGciwZugASC"
    "lsngBhyFghsmc8h8whpIGoJrWiFaYKmHdvVzvLz/hEu5ZCGy5myQIgxLDos0HqaTAdJi/Y6SRxx5/xA3Ddncie14FkLrUdzCvDfz"
    "22sq6El7ayMciJktrGgSVky6xta0hQ5B38r7nZPUgD1OlPekrqst0hZu4yPUc7r1U297NRI8I+bfGGtJyorDjifGuGYkH1lGijNN"
    "CfSRT+qq22JteJ8a//v1ZUHiZKeiy0SVlbe65GUNVt2SMPfd3lX8N8vXd9JwT9Sz3KwoNMaMtqyM4s7CVU/tj09jTB7EcFlz+APe"
    "87Cdlqqnh5/D+YluO/pZ0OMqLTF4rl6SQpumaecgDwnMBPy5VILU+tkuQ90SaFTfmW0l4dbWmTG+pm5fm1GyHHRwvXddL9HThHXn"
    "iZ7GrGN2o0DdC0wJXEBLg1vbyFPK7GKpVJn2wJvMVzhw/HdB6TSJuAMIaciokeWqxCW4uwgrzd/I/JAvz8OTNEHKDrYvYstju29H"
    "d876NQuw7/ofZc9WQkn8W2l4UDkdfRAllQRmqcUu0q54RxzXJZuFo7m8Pbtct1djbfYCxyxzD6XTniKrY6l99saHtc/vNrGyKCh2"
    "cF3y9Di2H/8arBCwUppi7LGG8GeB1djedCg+5P8JrxckWIM6v5eRAy7/EtDUIuZDWDMu26gmsYI8kRXkttpxZs9PdFUviydY1av9"
    "vEkucoyVQLHyBomXrhq/6J0+qvEdDfB5yKf+ek5ZpA1v5R4Mrl8j1rwKackByw2pE3+vVdYl+uA/0ID4fu4niC2eeySe9eMfRPI/"
    "Lq2hRVS1obQHgeAtho4fSXyDY8hJ0dY+KKeEUc55xFA5uXpDCuwoQgH8eIh9c43XTtm5guoNe0XU3p6oA3aJOneQ50p1vCG4gCum"
    "Ydz0RXx6Z2jBVeipyA6q3jAJUt3QGvx4FNo8xmsLRUFbYgxhBqXW0MOTeIW8NSNwQvFT/9DIqJpOU4X4Kfo2CLEot+rn+yaZXe2q"
    "vCyrMRTKhOxlIESmivO052fQItGxtive+6VO7sSp9FGh7ZqHFxwLI2MRyMgdjHzQPSXqxlevfjtPiFHEZlbA92hKgwvnYQ8JABas"
    "D2Be0b2uNX7eWGq5N1iphM8/kEpqmIoPx0AR1bytoTCTZshfFkXqowoypSJqAj2U4QtPG6CJolWBNFA/HoR9SGighgwCD8c7IO2x"
    "RgitZrEiaoWYbC6ztHOOFpNzgk0Mvgr2mHmLuUjLa0BHmNkJn736eoPnRkrmimZOciD717E4WzxXExfeaCRu8twHElT5X85PPUMo"
    "rYYp2Zz+Pjo4SnZwbUKHhRSsmtHQCwsY98t15OO3ecIdNwp8JkVLkxiTNImxikUESxqGO6Gtfb6wZxGZbg17T5mzgbX65EiCJ4JS"
    "/zKsFRPcma9gaq3CtfaAW8wQasgQmiVz5Sxx8+Y/jUOIA3MYshFf7K4cVqbNEelQMODkDHRNT1o1wPJPLvBevUAPR8/i0MsFAoKy"
    "ruspyyPL6kkG2fWJGyAUa1YgmZJf74HkAuzzDfiCD15MrUJn+N/jnR9QegnHJilC+KX4yxTwrv8XBGBqqPMDsJTHKexHGEZcJgw/"
    "WYa5Zi9cRi3ef4gVTWs6WZtznIWtu3nctuOua4D35BDvyW3Dd9LkVfxtFGGiU9CgQhaFJtOxkc7js+203zbOHEAWUL6dRsD5lE7p"
    "0gMoHMfSIRtQAdw2BHCt0B6Z50PkgY2QHaYTWuqDvOfMuZsq07LohUw7fF0Jyh+eZ+lddcq8fEO3I2ChH83+IPdcinOcWXnsUYr3"
    "4pp0stOm+Dz0ph2fDu28xWcwtuPSqHZ4ek/6+mKCzNbTP1qA+M1In0+fSiuE6hD23Ck9/MOPV4X5h1O4u60NXhXBQUyAtyAy2gEI"
    "XANkASSGgD4VEh9Sqmq/eE1IUHShjjuXpkf7a9DE3kwVO2dRIzbwMWF0NwuHbE5L+9X0qGXI6PpnDRJnG3DGNVrN1oOzTeBs78F5"
    "5msROD/Dk1+b+Np5opfC1yLQniXQngS0JxHas19ltF1AeyTQnvaK8OkEf1jawiZhpLKOtYibk+nQrN35AKFLLoLzzsG5r/OA4n8C"
    "Qm1WYzi3eO0u7Y+N4hy8ozu4AVDSiBEztAY6BO8damBSXM+SyfszufVu4kWnIrofmzU6WSAn4YQMtJ/e8B7GLmDUbVyVLbgBr1I5"
    "scc7WiontoeVE1uEciLmPaE8WDM9nFwVQkzWeYh9PcgYQhWxvcfPqlK/MjqslCDNoFRKbBFKiVe2CV46lMZYvR4U6xWriIJrMjnM"
    "wHp1jTBjvRdmrKt5F8jqTv82tBAbeM3XCGmqZIYWM2NBgxcGdr510oR1BExYN9QzS2mINGH9TO5FJklYu9yLrHIvEh6Q2VxNe+XV"
    "iAPRWeOFTVg95epCO7NSZAPP5yHy+vkWf0huGtraGnYZTecGbETpTeoROjnMu6C9J8xWqXXi7EP8BelyC6noCTwEfvo9iv439qSy"
    "fLJyJ1EgCWilqWrbxoiS+XuE/Rb+74oNie22F4Fx5JTnnkniY3bwG6E9NZdtVCfJvXZyfNhGtWAj95RZ8v3TZUEes/SJFi0MVMHC"
    "wzUaCrtlLg7JGR050MIK+7Zaa0wPJ45B9N+0T+WZJ04If10jZkTkCYHsU02R9qmhjX042l++HGbCE4q0peuFnMAkFIQ6+11qC7Pf"
    "t27oxX7nAWubYL97f1+wh/9Gbpqw47fq/Dc5SuV6bD3yiBpcbIcxaoux5mt+oK+Bdl+NGYR5o9RvwkfGbsFAd+lIJUPOHCoUBsUT"
    "UgT5KxIQG2BDTCkPaeHmsQN77yvfd8aUqiF7nLhe6ZHW3iXrefB5xeDr7T/+e44/ni6UBbPFI2fL2XU9xfayveYCL2zeLdnJ4mPL"
    "dGKADHBdEqo0l0kzeAxdooz2vtrdXaYtvleMSTfvCHNp+fAxRkZScdGV0e3dwcXMlC9mBn2xEPJAChPagFUM3geuZi9GpNV/nb0Y"
    "DczhzQIuou99U6yU15LJJQuyKj+UZiZbiIUTBTOzH2TtUXANq1wEk7NmP4csVFvDQvPFNg6hqwoKVRZZ7LG1UgMLE9+OFttZqPRa"
    "OtGMIv9FlTahDI1jJq//Ly16BkF2vMkoSvFuaa9CMazvGc4qAlI/VtqlBsoRKbmv9l5rWqUEbmVz6M089i+tS8Q3MtSWutLM2FBB"
    "ZmzjIXP1Z0rUO7UWdQ3PqBZBPZrPWbuqDw2rOwJxhNz0i+pcUcrrm2AMWMzfW53+krCnKSlSu2i/KNT+/lfe7AuYR8unTwiUB+GE"
    "Z9xL56lfriEQuDcIR8gS7xnH5Exm4vIpQwGkJoof3kpzuEc9sBRLhhoGMlN8edNBWgcwDsXK66WsfpEiJfeTOBaIcaCNf0P42SfH"
    "jj2qrOCaRhYBbqawI411GguTWSWTwl3ZwLHr2UTpSbZDgtgxh7vVc7HyOrFCwdDuQ3ofsweQVCFmGr4QLC2+2Ui2GBrzuF/18Lge"
    "G6lpdgSZ+Q0y85szVB7meDfFt3ZgtqrB7YDnTjWA0yV1rqfYl4eP4xhcHsXdCv6IpFPYCjoS3W2v8OXJWr7mOqVBKkf62pNWC/+e"
    "WlTYnlSWSObpmBsh5scDzI/vHN7G/Pg2qF+3D2ohk9oLyLxmLg93fqd6Wlv9oujjctx9nMD2VEXLe6Ri1M8eLZ8AsqGswiRRdnFZ"
    "EYwLPdSoeUZYCrj3v8KO9I/z+e6Pr/OW8SSve8lqW4T9LJabqH9/WVUqrnwbqrGiKgHFGDbcIA4HWj0MpJF0U43eXa4i9HAahpOZ"
    "nQfQ0oNLxW7L37GemnDrLSSOmxmBrZSqmtUr8MUSmiD2E319VReCzUtvJv8oARwsHxoithJ8tvPsJmE0z+yhQZyiq88zL1YXoiYT"
    "lxO+PF+sPSUkqPX9XUc3cokdP+vX3qY0bG/jFzcTKzdJW4/JTJu5bKfPzCxxnIONbF6IeUktxG1XdeEkIROBOVY2q5ZJGYiLiUU8"
    "D9OAJMjG0zFMNlIXrgHZPOeRLYgmTzdGkAzn5fQtINksJllxkc5rb22SJPP+K5K5xMHdxKlgrS9Yhnvf+VckQ9qOn/bHD0zoTfkx"
    "TdKGKmz28btIQ437e1FsolEc/ZW1RbTcP6g7S9jj3KQERhuFIEC3CrFBEPCgtAqxSauQtvQ9NZvYKuS0sApJjDAEoQ/KhPxsB0Ie"
    "oYlNeYPhpBbuzw5kd392ILoF/P9zc5CB6UelOYitjzmITZqDBHRzEM3s3KvMLYo0ByEKhs1B3jUdqR4QaQ5CnFpmWOr214chdYO4"
    "rZn47Bur8w0P039bTb7h5/R/H/03GM3yL8oU8T37M1PC/rIb0qirta5ApLQu1S8+zxx2pe135BJIetNe4Sj0s3W5y4/bBsKmHDtg"
    "ZWxWY/s4s25O7jkCU3IlsBVSPGFOHtgAi1/miivNLO4q0/70khBlNZMw95GEMncmTaD2kzh6DX2SN4srkHzDV0SaEG2D2v0Tmc9I"
    "YzUxiWDmqTdacm40Y3umC0eXzsaH0DxmkuVFa4n0QreWUz3307fRorVzVfoFmONVLM51lWlt98svtZEHMI76qApuM9jfH017Y8cS"
    "Gp9pXLHn13xKDdaC9dWm0JtmrIHDD/LqSUmnBP3jU2lD7ZjJzgOJecwUN4RHar/aIu5f8Qe4qVrSwoCETM3x4CtH4sJxNoqdvUBM"
    "WBoERepJrfEuTtKrAkqfQSUU+AVXrnmrSTCwj6zg2AsI5Hcv/k5weYv5PLw4g0OcinMYUjlyCb45S3460psOkvzgNyI59QCXQVfC"
    "E+fxZ6ftwVBP3uBibCFSFSo/PhPPxljt0K+L3vIUwiqINKIlxaQ+PTpBF1RAwtrs/XnOYqy7VT+mT92XEvrOY2RtyTaW5K9xGGRJ"
    "tLW+p62bwBnoY8cimUiiBiYLNyfJlM1OGWw+FhzQMaw7yHFCHEB2pzQy4MpQ8WPWOI8pfmh8VZYLhJ5gY9GFaJcyd75BNzUllyp3"
    "9DIn7SRz0k6qJaGMlsHr+ShkbVi6cVXRya/T9zSdjpX33YycJ2cxwtmXqHzSKdIMf+9ra7owUxhOCkkHXazSvlyHujPj9Mt3ycQg"
    "pApSCwtXCMxM3CT9Xv0fNwspPstCAOu4X8qBmr03EFXyCN9B6AD94Dhnndjutncb10TgmaTbxE54RQpOCoXUNoXGGuelNv9yXRgz"
    "OO9YL+5PpWzEA3Gv6BjPj3IWw31+1WXlocWsjZtXRcfEr3kJb1nPl5ECJ2bvREtO5JsaPTY9Y6wv4EDfYVzDFMRj971tHu92/R3+"
    "H5YJpXsrbr3wuhP+ls2d8DaP1YkWvxUzsPiN9Pf6Vj3fh1l5JWHyo5rIFW3FlbxirccP6aXpp0T4OYROopFey2is7aVf6Z2K0m67"
    "kjeq1KwTvtP2YCasUZfA3Xh5cBpdxCzkIZbCFzLJGmANc5UaS43BAYc24JkExUqgzaALgIczwwkbyfVsZUFWHMS7mUN0W/UgWUCO"
    "I0hCJGQkINZIiHmc+k7TIXP6OyHrXHVn02fm9J1TDSHzvEX6jYBJ5Nle3bERFxPD/muCxmCRuaaJXax8bazsZAEL+bWi9nX8wnf6"
    "4so4XzQ8lRs70nynh+NtG79d6judhrc2fiMj/Z+QlU80nJgbfezxGB+/kxIMKxlrDAMPUOfsUb3+wrepreb0doI/nD7VOF59Vzv0"
    "D8hWyJC2XvieIF7ZyONNbSbVW9a7bFY+1ai+WzS+/fZbUVIXH/TzyQ9+FPty+IUzCb6evVc5k/Cdxtk/og11a1VqR7x+AKDvNdkD"
    "Bt44LhHXyZxN3q9gVNsWzRywoyUKe3L176NpPxrFYvCbY5S1JbF0PYaMaEzv1JVY1FN172Q1Vh/qrD41aSm8y4dmJnqiq09NrxxC"
    "h8fq06aHB0kZRGV8S/Rq+ZG3kHcYOU6AOETxtYvpkk34KGtJH1Fm5LKD1gDczkO9RzCTMEFiMLzTqyKWbu7M/ROrBFvMgb3yc1NV"
    "F+s1DlDtgRWUDOqSnZUmaqEqstecaiVaE5+yIRVmyaS7FOUFQ/YOfGaREwUXJtNLx8ipxpLx7d8WwgJ3K3L9hHLB2Im+aBHORe89"
    "ueilJZbl0lvMtKlmKo8Op4WNqUM+oKlPDKpp6Tx8H/JmczBxAR5KLMGkJ+mhbrT1+WeisP87jXI1IxbzLNhlmBkVaTkkjFQH0QVj"
    "ulRMOyF81NSVWIPCL42wFKldwLcO6ejKGkkHPLLWsfinqcvSdNpCVgv4unhdAPHk7wfMfPU7B7GXrnYkiivR34lrkuS80LCSflH3"
    "QPqNMQp4tPxFKw9uEZXbqN4EnCb9XKN+yZJ+Ffk7QP4mssuynxeBj8WcTW760kZ4AExlINVUIwRa7PGouKndMp5ih4ii4YRNm3wC"
    "w99KXHaIVdZv/BxJj0Gfc+wFxf8bo7QGxvdAf20Ukh4edovRo2oWNMk39U/fjzZw3jTVpo4zE/GYrDeflaSm2zh1+dZa0bSmUxbC"
    "i0mZoG4h2lIipnXJWetBikk2Cgbl/5So8aLlCd+HqB/fBqI2fZmstlJOwJrabWqbxJjI6ufGEnYXscRY1YiUTV9aiig1KKzFfctG"
    "ImlSTuMIrTO/Ky7Yb7YymcmHN5bHLpLbYcNT5r6MG0dEefaclcPfmVDqt9+ED6gl/z3KELneUIfBr6zi//tNOvEX9BC/WKsgkBqj"
    "3mpWyyxB4YCpbqxV74VbzspmENNEtCeC6+S/xWA9qBN//FnCVJKrtl4fiv8Tmv87YtO2KztV98dGF9gqYNN3CXVA1vvEcmfWfIYa"
    "yTghy7ywc+Uo3McKiX5xvjOj7ULDX20NTwBqiZ0V5QHuqXaLS84FbeIx0VOhDdxDzT099Db30Bk7zYX6IL5Zmj8OoifafNkpY16F"
    "kO/EXUOfTC6JDs2MrpyBZZesKWCWSAdR057QrZaQ19bt3DGzvDonrnJsXRHJAodNIUUw/S+KnkItmkIuDF5vy2pUXj8abr89gO96"
    "kBYqidwKxYtru972jtjgSI4gjbExVGiMcu6Y8VesqtrTR3ki88d1Ce2/RBnUM3x2nnsjRitdoPotUsBA1iqbdc7u/aT9AXgFPG2r"
    "vJ2O1LuvhP3lAHoCV0LtGjESean0vAuVnqmXPqTf0gdy6QMrb9NLV/yfZMky249coMz9Y2WZLUf6K3PDWJR5ESnhYbaRN0l0QdQg"
    "GLdG597qseTepgSOXYTdNoFW//aLsNv+njTvN5MAuMTe9E+L6RS9DOJNUE1q4899B3YRdzVLmbvuIiHPc+byfkQetGkv3+TtbH/+"
    "Iu4UfJ+FJHc4+IXM/Cat2BR/1UUYinSx6SK+D88biK8B9qLk1jkn23MRDaxoOZ68X7RPS+R7BZOlF7H6dMi7VX86C7xpvJs+kVJC"
    "nCxahDtZmNAp/rfZyxhLE9exNHHP8A8h+byKvi4B47rtQeEPtS4JlnUQLtYKj6IXkjEqC3rZ1RkWRMiRs3FLUPuv+WxXV8H3CUix"
    "zrZ1FVTPQdZH39bLvM42n9XN8KVQAZN96bfG5faA0x6xiG/NjiS9gjr/INq86jDCd4ZvJ9bVc4/qY0KooIPaNfwUGRB6XL686cy8"
    "3YgvcmqfVrJJqdq1BFByi3U0zIvuHk+emY/OHuY1O7tmXqImIUGx+xlU3PAks/jtx3DxbBUfPiKqImvqk8Tugvgq8PGWqPPl5TRy"
    "5Ba+/Oe74OW/4jKt/hXpgg2FF2sPiFtl0J6skiry7eTMTb8A+Dg7dwlfAPT1dwHwulekUym2cPHpWvX1iWGt+odLWOa2OTF8AfB8"
    "fwM+qVtHNqLRP15mL1biEFiktT4nzmOrWL0+X979G62q4bt/vsi7fy++LFGaHk6u+li9Pp/V66tYvc6oqgnOHZHa9d/CdE+nKrnP"
    "irzy53pZuqES2nVyyy1cT7E0YR3LAtaxdl26r1sH+8ZBQntZrO1YgsEiXNcd7cd1ndcB93Wl2poScl3Hl6nZdV03ua4j+wbhum7/"
    "ffJWBETrGaqJLkLMWtLrDmAiaULVZq3zRiG6gAnregf0RfThMxQx+395Y8mJXf7Mu+eB51dN+pH428W9bL0HsfGpaaqxiI4no8YJ"
    "n3R+LkmeA9lijj3TFcjDoffl2Yl0gEIask3PJ/90xFK4tBH3gcyETRndD35GjBbfOilbXmgMe5wrK9d++5j0OFcoBgRMGek+i3bZ"
    "82F3cx+52Zedfj0E7uaK8WE37TTo65NDBldThi/ucTdnI37ke/ubs4f9zdn+//qbI41SyD6gWNsd6ONvztafv7lCeV9kXI+/OXvY"
    "35yd/c3BSb1dEIUIkviKPqmmwrp/63PcRpgYV9Dx0hWcjwmhPXqv+Fpu2NfZqyZON/m+RvqiG7yeNdAcTafTXNbW9O+gqAv5WTUa"
    "ms/WI9+w9QiUY0J2g68RsL88XzZtnLD7y1GF7Uh6pO3IMWES0CAtCNdfIlTijUOFwnwzWyqownZkxmNwfyY14dsiNeFRfTThFep8"
    "u1S579fN6eny0GKu67DuNKzPeoQmGv+9dzIibI8BSb0oX2jFv3jm/0r5dHXRZqCPPfAXHmQDhOl8oE8F590H+F7lE9IN0pYb5EYd"
    "jUzmm82AtQq77tah+L7iNP6QUqu0D9lmkpYk9DGfp3Vn2P2XVc/rPpdn6inPME14O8vlU4eun6q1xvbYk2CU9bYn6WvO3ceeRGwe"
    "0qr79vnS31mkPcnN0EVjOpmaQqsDbKXdywFaxjN9DEza6+AAjVWEg4u1UU9FOEATGwoP1YHhne6/njrPvrthYD/23bTflcr9bqBY"
    "ff+CqVmq73d7xQ0uoNriC197oflUAwevZvb0gG+sCR9o7ONBTDcvloD5ZG7C+wxdVBgU5J2+SsHX0JgzCPogEwZm8gOR6y+XU01O"
    "lM2WnqkmjGlafGEjlJNq5NSLklMv7K+uryXKhJ7519Yz/7YsYgT2/ov5EfXvxq/K1ihNxiL9pqO4t/K/+hTdb6H/2n4LpInqQxoL"
    "2jCaDaxaxffFWrFW5tzHJpSZPl4JjCp9igPiqkQW/my2sQxuGHFUTJ8cITKqxPloOX+XDSK4dvoGK6+HQZUNV1QYLLT49OtDoVUY"
    "pm+x5UqMs6llTrb4tlW3d1COj61XEsh46k9iyd4qffNtMfu+MVbuUH210nDAKqvwYZ2mkywt7uv4K68+NhLxsTULc5pBHzP3PrZm"
    "8bE1yzq2ZlnH1izroIljT3tzQWLVh+/GqiqE3aYWak0UGRHNh8RbHfkoH0+J7LglR8T18wM7W+xs+trSpNl8XwzDxTs4IpIzhsSq"
    "whtCVYZzFW4fVg7xrVtvgZjvoqn4WIQDbJr2WpsUl3La2XG63PQK5yr2y3FpWH4KNTSWpRLt6zVCiKoLIYpLtITDBGrB2U1SA+16"
    "LA0OVU/kXIPrNJ77c1YhpqqELEf1xnLz7DXkWHtSDwX4K7oja3z8ahRQI5eKXdwHApG7iVUAiyJnrxRvwVX80V2G6WP0u5pvzPDO"
    "uTitg7GykUgrO4pP85PFbvmYmT0tpNKjH4/r8nGGU/wP88veE3ipnwqPgzMdgRPe69RBdES/nKSINCAvVUenRR4PcCyofF7MlxJH"
    "sXbHQrHMjXbwqpNAlkc/U0dbyMYW1qt0IKHS6YQzSmYhy7vbJgpOOCs40xKcaZZrjxIaz36HkV5ngt954l8zwet5LhOvitOY9tK4"
    "C7PCO+/qxQozVsQO3/dEHy/OKiJCAmnto1zRH6v5rNmbM1YewwcNvHHO9Xwynelh/pgz6tvBzj/28d9cqKcgPjnENWmD8/4Fryzu"
    "hevs8rOzbTq7LE7DM+oFx9x9J4bUXpZ7Mtc8hTTMgmhe/lATLexM1mCJoyoOK/votODoXCxc0vR2vXTD0ni5XNN5rVf3nyYqtDDG"
    "vK6PHsmL+hVzhCc4336SH0Vuw/oyXqSWfNVnDY9a0Huh7W2P8+/X75ut5y/er8z/Hov391m29dbzdx99+6m5rggG5HLok+8m4o62"
    "GuljRDRa6DOBoycHR7uDvrNbsfoa3tFX35FGufpm7aL1d1NwbrZYe0fTxyRdWuYfxcK7CyUMkOvuh+roSc4m+qJaCRU5jZaSkpSg"
    "uncb1vb9HK7ci3A1hwcZchjhfI3Drt0Il+8VTkKqXDkzU6p+pI62qzenkkciscSW2CLWV/BdRAVKPJU/G8OiXu5jl5b2qS6eomJQ"
    "3uw14bXtlyg5lxY23f7jZjsKNte5tKo79NfgyDrfaLuR6jf+PgVTZ3Sq1xScaae8s7fTb3BmcnBmCg1LGzEjn4UFxtPoWxNYuJTA"
    "TfiWk5A/0XSZFbT0iNkeShWqUxakVR3oK2pjQdvMLClou+tAf4K20iwI2uyRwrvUVCm8yzhwAeHdML3M+H7LNGTB0KaV1XZrMvC8"
    "lZ//mhEWp3qGNkDCqVogTLsUH2TYCgGoOQ/6Qq+2hAV2ZNZZNSzCv6TTvgH7P5172Euk0dnl/SoUaqSF/i2juESf6fvtcoOH7h6y"
    "EjLHqPibqGa16CyEf1U/IVUs4L6mFcxPOEco/rWpQlzfZCYJ4NdgRdhlMhkiC71mdxSKrXpRaqKoO1AA3ykjRL69jFcnFOoMgMeh"
    "C/gocEMF39rjy3tS23LsBc9P1dA8diXEsbywhcTdTa/CK2QJuRBmDtpKqsr3i8e3vzJCdsWS/ed3xTzui/kjZF9U7e+vLzwjIOyO"
    "rnZGwQGAEvjRZawgJun1zaQoLIkn5S+E2ActpiYCJUCa/X7IM5DuSpXQ1fubLTu/JGMr0iaK2/clcSRQxQWr0Gir6R36fh+01NYN"
    "+IC14hsGxVh2nGegsnacMVRgiXJumfFNexwrQl1m+shNtLDbCo2MwrWjkL06q5s0zVRyfuiPHtjSbsqZftZzdU6mJyVnuhmBBYHV"
    "k+JrYfdt3dSijouoc8hJWwuctLXASRsZHHfblQBsVrO2qpt8s85CQ0zfTh/mo5u1nst8syw03nyzrAYqSPqBs3v3UkHneXvDDf+Q"
    "+Y8ha01wZAjf4Ma9SHuc/B6B7w0h6E1QRzhHLmTRMdh1OVJIdH+g4zL4QL2vEYDQWhQQWp+G48AbdsHDkd0t9CAVg+CSwhYUdnfy"
    "U25B8cU9+lkgfp4UP8+In+fEzzLxs1z8rBA/K8XPauE1kkXVvluieC+YJ+7HzRLfUyAr6XEmdIeuk67OTqQB7iHPy0juig4VGKOd"
    "bWCXjCJjvuKD+R3b80XlNlZefWJUFKlGruJuHUVl/dIs7pOamvKEpn6QUCFmY4S3Q3OUG6cEzrFhwigaBjOiSTKcKvN0hlKeztra"
    "9Lk5tI5HQMsFR0C44z7pr+MoQgk8JUZAy//RCPBiBLx1/gjo2/8b+u3/S2Xfrzq/72GYHiqNioJkT3l05Tl2swSV6x/kp9nrbjVO"
    "gVIJKJC9OD3vnELTZYqpjSzFlddbVfMG6OxDKeLH/lbIPg8fArQu5A/bm+pico2ejNwoT1quzePIVSpHUIdjv2g00+KOEQaVxqzK"
    "S4PCCrNjIFxeAkwnKmHYLb/O6qHZG+0Uew5/xPnRpu/YkV6qal6IkxcJzciqPG8gd/RkXso+UXG+ngyFpaCBb72JV8lQhinE16F5"
    "IQwKJQf0zrtsMG2BVt1Zz0uoEngLoIAmTEKJAaBR1GGjCdl08H8T9/VxUVZp/zPMAAMMzqiomJiaWBZWFlrSaGE6QLtSg8ggKdju"
    "lkvkluHcvhQgNGDc3k7ZpvvUru3W2u7jbu7ms2XZpgVigFqm2Yulu8tuVIfGNkpDTGR+3+s697yhtj2/3x8/PzL323k/17nOda5X"
    "s9bIvYSwQtNXDafTGujAEkyd7U/SZOfIaE4PxYg3vAg4ZZgPp67zssXzOrnc1nmnyKcn5NM0+bRJPk2XT0/Lp2z59Kx8mi2ftsin"
    "PPm0VT7NkU/b5JNLPr0on+YdNgQFSxhWwqE4yfIukmXdSFNckyW77ttFJ7lY6r82Wb0+azulgX4Ip6V/kpkBROiQGauO6OccTT6r"
    "vp1sA00WrVCdxMmGLFq903kusYfk2WgmWE7SwCIZKZRqkyS4FEiRAFzbzgKpXRcSSO0YKJDa+R0CqZpVUQKp+1ax9GkeHIjCGCGS"
    "u0K0qCoDRBJJOlgnyEN22b97QBLfGzgLOwwjxhKdl8rz4DRSbC/nYe+WTkOoThxnAyuN8rP0YrowvcqNiqtQ/QYGF3HVSg6eyn5L"
    "l8JPK5pCmvwF5e+SoOm2GubaYURovDaydKt1/G6pyWwYMJynx/eShOuuoIRroeNg1WWrzY6vlo/T+jNOax+NOkINWDl0dSzSLbdm"
    "HBi1Ww6X30z32mjKR5x6rSUoBdNOizdvIDmYbd1vwLVbbXH02h7amEyTxGIvWf9GFnuR81Efi7026mIvaf54OOTzcv95fV6ODou9"
    "Nj4e5fNy5ZqQ2Gt7WOzFSt4UM1UzBLXUEUcu6PeyBWKv0eGYJLN0BuNT0X4vQ8zAuaJjjRR7DT5H1TzS4SVlADid/HmUw8sPGnQF"
    "RBZ4SYyRRWbig7JGN9GSkC1JDIuudKPTwyGj0/0ho1M9At5jP9dbzFIxtgGQVnIqN0fdzlIxqdmva4x6snT70paaQS4oYuDY/8Of"
    "R5mYzrstSqV2ckixNmu0FIKtiWFNXYr2PVfsX3PO8b8wSgQ2HyTZQvGXafLc7zhB537Hmchz/4e3coWFdOxPlW4wFZ5Nu65pG/SC"
    "+cWkoAhsDsWY1f6+uqzKCtFX3jK3rr8AvjoKCB7uTz4UdbhPYW/n5OmSVG+zrwxGZZrIZ/nDBoQ8n1O1czWF1p5Inpgqt9Hu4xKz"
    "btUdovHB/U+AEu0pfVobjtrWKVHyLtVjZBcj5NPzTnYDM+XhkKTry/wwSOiO0I6IFPreEJRygeKe8VBYygVxUup5RFyp5w2p9Jx0"
    "gXaqOkU/odROv/g88qnv9U6Xb503bVi+5bNeXCB6KyJkW/Q9Sqa1UJdpzY+KoVR0bgwlHhd4rsh6PDge7APtmwY+ZsLGNqVQ5UUp"
    "/jJHntGPMtg5WshxycYwT5zRhtSTzhotBV6/Nen+PmTcad8mKfE6krFJhmbd0LiBnfD6fLqhtJ2cBJJyBpz4J4XtKfDSewMQ6twI"
    "e+nxkTKvz3WZlyUsSIiSeZki7KVrPBHWnyHG+/lkXrcH7aWj+DVzH4rirbSDXxNh/8nclf9g/0lD3xAp8ToYlnidrIsuPcr+6fuX"
    "DxguCrkulFbTvxxQ8gVKPTceblTBkcyh4CibwkbT7ZawaOquAjaabtdj9rwZHzKattUFA/ucvyyp4hApI6DyhhVIUZeDyFmar9Rz"
    "ZFy6POJ/YTkdknS5xH0rz2M5fZsOuxzCDPLsF9efK+26sW6AtOvMfSFzaoT7mbc6UtoVMqcm6Z5uTh1YHSXtmkkdGnneeJphe2qW"
    "684Vseui/BmJmgEu3mBj4jED264M2lX7+YaNqoEQnunjOdqhO7vZqXM5m4bpEse4CE9s59hRT7k/ciWZ9ZWkBc4nv7o97I6tO+yO"
    "LW41T0JvCNrPsacmMfZ/gveNLMHabaSWd4eDZv2hJqrwaCYotXZ/AHZxZ7QLM0LXcbqogYnTqU2CzVgJmxgrsepWDLW0opZCK+Cs"
    "yVrKRuJTQb+fJFiOAzWjZf/C8qs0qWMm5VfqdhYtbV8f9q33FJtdbw9JrvT9FtCn/nqg5fUXVZKAuFjnnn4o7a4z98Jkx6r6wpbX"
    "Wcnst/spllg9xRKrp8JOZvRYBk9Jp6UssfKxxIrN4Gz1/zJIm6zZbN/yLhsUs2QnQ2tgCY6PZVgtOoN14wAZls5jreeb7yO/ugJ0"
    "xzRIr3aFpFdFFHmb/cVsP7/0aiyyZEfLrvaQ7KpIXPursOyK2Ltzi8RtCKkstUD1Pj06JVJudXfWdtnT9oh4snpHQ/KrJ5zRL0l+"
    "1SDlV3zxNlAZJINwNOgCrO0swOKyVz/fdQ8NI7tTtzXcbwh+qCnW53sjF93A9VnXF4iJzuiX6pT1/6v6VL6q21lgxl/Oo9Idt54c"
    "v5G+/TOsa59MivZRGvNBRfphpHofpT5PWt2RGvRRuvPQpZd681DJTYzSfP+/0Zv//urGUDBmHe/Mw9+pXnzkgtr1hu/Uro9rA3Zf"
    "yD4DJskY6neGAvDcCa/1/4YF5qDC8j46NY5cKiPQEicFxj46kiRLfFUyVmz1zxG5n/wsG6Wwx8maSxF5leTgF2vTmemYNb1hC3m6"
    "TJD4o9sfy+lwnGeTDl8KX231DgsFHIEnQAuTdKkk2oLNDpjXf0Ydm4mfrRC3J101tjWU66wEMvD2+ZYghXdVH7HSR/qmv9T8mdnx"
    "G2I/DOB3HfOP06ZvZ4m9Hmo5a+flqex4gi81MWoW0iGiSjydLJkzljaRw7paG5jhEVA1ZnjcUDPVZ64lXscLIV7Hes2iDsrSdGaH"
    "N8TsaGNmB2xFbqj6G5c1xDelVn2c8ETzpwg1SV2hAalrZSbcq5H8V2nPomqpvIRZ/Zc2XT3M4M5hxGpghYtIdY7YCM2paRWR6hvB"
    "vS+ofxHe/8JqG91hEtK28rt3pu8Qz+k60Cee9bhDWlNzQruqpCG3rfi/Lh6b3gZOwxSKTgU0EXUAVywUQKg9Lqy0UZ/LBFnXR2T3"
    "lKzrVu+tGeydLo2K5GGpuepLRzsM2CgRK2CzxTJ4y7Fv6mZNNWnaVJroV57GD8tjFFaCb3ZBFvM1GXefMUrfAm0xPPNS7NIWy6IY"
    "dkFwF3nkeDuQ2aRyABbdrWCDdDHIW+mu8Fb66rXBTZRjiVZh89ymyM3zRto84b3wn+quSZyLeIvqLt4q2ek9HN3yG94qd/FWyY7c"
    "K1yZPep23i458IW6nbbL4nLWGt81mcuawr/T+Hc6/2bz72z+zePfOfzr4l9iDIrVa6UgyFVcTohB3LdWIoo2chjF/JAGWsevDA7v"
    "T+pkqXreZQT8JdP6Un20arTkIzxHoEQyfRtpfen7i7WBeaqJWZyMYneEk9NE7DZjFj+U3EOJItgsaFdoRb1GKwwgNEw35cKwP0Nr"
    "Sk64yruFPu22R55Dw6P8aeirMYt5wDVxKl+lLn5nV7VJYq02o0lOPSEtOfUmnnrNJK3uKlwAADngbTH0ScxW5QBtXweDGgo3R2PE"
    "7v7AYK3pUwept5rVR56AoFp9bRN+fb+m4xISTmYAMTmaVfbUVQVuxKPLGECCuR1YDpeDxFM+VF9bSBLm157ey65e1jxLxa3Zwr9b"
    "+Xcb/77Ivzv4dyf/NvHvHv5t50Z4SG792kr+ncOluvi3it/U0u8j9fy7gWTbj8w+QtiN5vpyEiY0XIbGhgAlp5FCnRFdE0uTQMZc"
    "jPh5/pib/8g4KRqiDSHjjSvNGFnfU034JX57KPrkLczfgX1j0KOo3EAc3VW3UxhZ7RWCHblV6HOaleWxhfYH6Lp86Z+sHbz7HUb7"
    "665IlX5CxurUcdZg7A6DHa22R1YYdVYSqqiD3JthuNVIwnYpDA9yxwO+KZKdbcq6seZKjiJduNWnUjtkvHCjGpNlUuLaTMF9gv0w"
    "OG6s+iS40w5ifV5yZPjDvrZZWxicpZzuQXNwj9ANEwvna2ZprzgLcbLekXTSjjj9XDBMPxfoZ5s9fJB6fDZk9XNFyp3coTmsETKb"
    "tCDC+plBXoM2a96AM9HX90dj7wH6IKb/5A6KUkh3UFH4G406hUYNQOHNM6V1BUYCJ8UUF606BhcGkHUxkE6xTTIJVobCrdLwkJSb"
    "ptFTCH8MFw1lQoUSnTZV5eqGvwwjPh+Zsq3PGuwZHkUv/Fum91u0dlXm7E1RklHWgSHBssjIXJISiOVuequg6zl84qbcHWBY2HA1"
    "4yid3nBsuFyK3X/PZq3KqCwGc89QlprfswukmYylFfDMAg75nKxXh0O43gK2EOVHLMddLFlHMqQZgzSkDs1pDsOKzIADBBThg2le"
    "Z6M9VgWomqwrWSDbBH1n8gziak/uDBaJc7eUxUNy/b7W2vXpYEZl3IyRMFrjNhQWiN07Ixo6oBEoAY0oEr8Olopyfo1y5HigQtPZ"
    "4q4GvNC1GzRp2UVyS8LT2mAoro1wfK1YGmAzvmgPCtEd+6ZUfRw8daUHz1KjdDoDbkykBIkOZO/ypn6xYzsrFA4PHsmSpen14i3n"
    "P42NcWxnXcIRYVvsE3AY/N8+Por5Y7QTGu/Q8JBRJDMblTl6FD1b/a8gcEQ43wYWXD3iI/EjR1MI2pez/sYhNJOi11Ciqq8AR2vs"
    "NCLuoi7FTgPdLsv6OoZ9lTZ8TqQ1+6PS2DeVKxjm5ETZOcZQHZGvVpJ0RrxVpkdfWUgON8liFvFXyPkm8rhIQnWS9XtLWWy0lMON"
    "SLHRQbKdnbKNFnnyvRQeToYyGUuLlg6jgfe1hj0sWGsKR19BkLiF5zbrlnObdR1ekZ8orYF6Ru/hvY5dby3Ey6eo4IJCYo0XCy07"
    "FIVlMrVvcmGxHoVlZimbc60kf6j0ZUkBB5Y9Qi2fzy0v/Jn0ABbRZg4isOuJqDZvKT2nzRtLz2nzQ6VBYZ8shRvDbTl3QH+/8PwD"
    "Ws/N2rnEMGAod21hF1xbo5o1+Nxm9S88p1n+hcGh3BQeSupfAdvFPUVlFpIftiUi+6YLDWXPggsP5VZus2XJOUP5Lrs4O/ie7ieL"
    "2BzlR7YRz/ToPcH4lTs4fuX7Qa/dELS3NbTrIR2rBmfuzfJRhBLbhmaVb8gVtlw9t0Fp0fcUrx4paHfwUlLu0NgXtyZjTICzeVsw"
    "iGSOXknVDD3siTJFSlxcYt2KKClPutYgy2BrABncYt5Q6WbF4kiCJ6c+qSPcYnbI5qxbQXyWpq6PrNweEgi0GY2SAGNKBVd77R9I"
    "z2nhKlNkfGHvrjumkl7uIzUIE6gjAsfGO/HOV22GcWt1pLLV1WC1XxcImKRGQwq4mFLjqm6gxtWry3WNK9/GZycFAhCyTXk5aC9v"
    "q/+APLv2+HaVoxYtHrgqK0vuhMqEoAmtZxTyNnBel+h9KZz3V7FSUgMFJehiNf9vkG1GaL+1o2IlTe86IvVwRRVGFzDv8d+eH/NO"
    "CE5z/kFlZJgbFmzihEbGwJqzHd0pC6LeIu8uikgNdPlXiqTek7WdarQ9stUcQrqOjdSYqO4mRHSXUpIgijNW7e+qpOddS2Shz5sk"
    "Dv5vDiPGMXS2L4yJwMH3lZyzQheWnLNCbyn5Pjh42fzvwsFqeTTK0MNylXObKGBzRPyr+UHHfGCAEScQNZASgBhMNaxjhQd20jhH"
    "k3ot8NNYwA77np4fEc23Xeplcc6H5zOOmUwRfVUJ/hB+U91tjnYkIv1m7SkaGu39qquhJPDR8sszPqJgxdqHrCYwe+VI+LSEBWJg"
    "uT1jIyUc1ezdzcoCluCzvq5cuuY0++OTbvlmSwePIcTuEg/8NOjake2PgsORzcMxPWo49hdHTEg5e9feUXyBqMW/KdZnagOH/kbV"
    "5RyubA5PWzkX4RJ73cagfg4FNNMtiUP43SWOLZaTNaB1Lm7dnKjWXVmsT5aqa4lv4IEvEHe6db/ZLm2DPkuYAZc+ZUDZJ9wXmKyP"
    "3PpkBScqOzhRNHvByZp+7mSt1CerSp+slTxZ0wdMlnymAGLUmD08U7KF0ifn7Lm8G4S2jrnirbvC9MPE8J6g+VbGcKTRGN1jYGgD"
    "cYlf3iU3kOAIhjaQhbSB8PKUG8g7WRs3xdAGslvlG9pAJA7YYojYOggH2BqWMT88hGHn4VRV/5BErb7thByq5nmr2w2eW4M7idP7"
    "mtxJpgcR7833R+0k12traCcJImwdU0O0j4gTMclyRxnK50QcWEwfONatp03MM5MUgWU7182XRl52drAWS0pekvyeYYAlhzzZ7DjN"
    "m09pHHOIu4ripBdGyZw0kVd2Y2HXdXFBpeUduhZkipJAIku+hYOfGN8PY20NhjhdzH1QapTpR920K9q8Oy3BkJpBj4XSUQTukwA7"
    "CFJVkKi/O+SrGm4lLxH4lsDqtqQRixcWqS5rep+0bB7nUw9yqi82MFfpxYYp8jJNXqbLS7a8zJaXPHmZIy8ueSH2km/O4IDjNEve"
    "ccxWX2BG1wvM6HqBGV0vMKPrBWZ0vcCBrrwc3opV1xhEbd7/4jOxbA6UpGtvSvbcgeNpUHcRMTxjpALjIdvL+2wv7z2Xl6sx19Z0"
    "UF3HbCkvj5ux9iYboluDsFITcXzP8rAV7GTFLGOM3wad02KzCYAgdVh9VYmxuskJyzYf8gRYtTIlJswKVhAedMnntJ0uwcmKVOf4"
    "hBVhEFR/Ce1WDpAnI83MeErRzL68f90slehjzRwvG3EnzkiuU6r6OGsTPh6MJlz1A+0FPY7wZSFXAqPPdSVA8YNvuVce8b1Sl2rS"
    "j6Ts1hvy6cb28bDKnxYyn09GCCPYCdn0nGxfP1ekZlzAgF5qarTZfKOJt2IK+f/+8X+yoJfqQ8tSLmw29MsrdGN00HrFFH9worju"
    "xwMs6IfOhQX9ny1h9aFoC/oKaKiQGtGP2f9pUtAJ3YtlAwzoyaksDOjngtQxJkQaBb040IB+TqQBvUxDdt0woAfIFIjuy8mPAGsU"
    "wTrrPn18SOkH4fW0JFU7v4XnBmb3RHHEdSU1YvfALkb6GWcLT/VVEo+LkXMjxQOmoHjgPPyfSPPL7rAFz/FF38HDD/KAguV9hyGP"
    "KUKiQQeK2Aj7ywg+0CtXY61I20s25Ml8R/VKQ0dmoXsvaEsJe531EfY8w3VbSpj0lJadx6TnXWlKCaseq/p42JISZObjLJLUGAFp"
    "jIA0RkDssEPVGAFpLJR+nLnsjzOX/XE2o4SzsJoS3cDw6ihTytYLmFKGTH0mh019CsWs50JGPlwYFbz6+XBAsBfYBeGuK1kHOoWD"
    "iVs3EnLQdpNvQ7l5QM/N9IZLnPqjZNOsY5+Auj/VkkvIpSC5D4x0KbjDTMF63p8c6U/QYOet1mJnMLDa+UA4L90yV2y7lz10Qtnj"
    "cCGnsdt52aH4b8dR8VRalMfCuuOGWI6OdCWFR3eX0xMiQWEfBDLQvhFpldJBqn/ZYOan1N6Yyy7SHScqT5aVZjYtqNtDWVq09/ll"
    "8bJS32vEzkQ6JU9rzdg9g9Zc9ZWOL7W2FddrgdppuRBKCqNDLD/pv0w7kNHuq6P0M+CO1bBiuG/2Ors/aUY2xrwaHtPr7Qj4wkXT"
    "Dn6i8g+ZTZk9r7wmtXzJ9fF67YE+6N/FInT8/f3wravfBrQHEB2o2qy1QW/4AUvwtVF7wBq8j9EesAfvodQf51vV792dWhegqqv+"
    "oB2wPd/u7bUsgmNmwrbNT3r/FW/a3dxrgoba3xz7besC5KOrFVOnD4A+ns+QX8dibQZFpfdZv6ElmHHa0bbs2qD+37RcZQw7nfel"
    "TKbxvCEXAq1mI3bw05aqr/AjZbZtle9lNi1qefMZDm+fTKUWFvm20FA53irWTi+7GZB7BON5U65yJTR+T/XjoDaFC3Y014zwpVyv"
    "+9NA+QlcvqMd8rJ2D9ktQYrlOFu5ZxHNX4vWtqh0QQgmbC/ZVRjnuIzNn8fDc6O8i/P+C24cLfIhlh+s9CCJD7ftpaUxSe+rBTAc"
    "cZmQWi1IkXdm779MagH242wTbIjUmWllLcUV5cQA6BUtQLFr4wFa9QiedDfopukv2x7+Ea6FtpeOqBf7FjqMvttiMNIPf2OUYcdJ"
    "QB+vus105Ra5LXTL7XFb6dbMt3a6NfFtiiYDg+IW3syJcDJ6O4zeGrtBdaepOWM9Rb5VcY4ztocf4zoKYjKb1o5bO9PIoc3xzLFB"
    "d1M0p0RC/DkTVTc5mMaw3BKr7Z5ACsOmJhSatNvUlNT8ZELOxAT3JO1tb02KIVT0dd+v6Mmqe8p3Fj05wT2Fik7FtuebiVi7toeP"
    "MvU4WHVPA1avSYP9iv5hN38gx2BGeKTNmW57mKwLvDUwZa4nLQVfQQxUsB/+lcxPKg7mRHjgdWfbHn5YZtV6m7+MV2tm0zWuWcR6"
    "P+ORgxHB5xi/2Qa1Jk/NmQOu9rcxVcXB9N6O1WqNy/bSKu5lG4xm1Jx5XkxATR7ctXq/NVVh9Iz03dtxEyfBfYye1qTmzPdi3mrm"
    "GDwLvN/GVtsZVMQvmaloXbCohao56O0YhIlGbC3VvZAoZx5MlBF/6HM5nNiibWoOBaOnsTQdEhSItll134kxvCPBfScKisB/IPAd"
    "B5aNL/xOBRDHgcp/6EvEe9wCZAm9jLqzAROpF2tHVijaq93YahyvniQ30S+Qs2g4g04ma5WX6+8hr8l3N5FXZnIcYep11Fi0v6+I"
    "ddSYl8UKAaTge5lohF2GsWy/+CD5gT6E115EjxsqH3enk0y6LdscdDzwhVF5n7YNkDsD/M/WHSeLE/jP1o7UnaEWAlfYHlZMzPrf"
    "wZE14d55okgBy60H1GqMZ5AvxwwX03niR3jlH1xRDuQ/hyjBcUskffE8d+557tzLeucmp1PnNi3izh2lzpn+5iizaP0cQnhJejo6"
    "WEYdjEdCxyILnyIWpqegM9+MRyMgwvPufI76bVDmltPhX5whK0zIN8wIDDiSX9Hsb7pH+qHP4b4jRkcPSkMpz48nWpFLkC9+TcWu"
    "4xfq5WC70bZDbELSvzF4LHRHJcjE91PiDZxYu9lMcTGfMbKtP0LaN/wCt5hdtlMrJM/xGCajcgX5YLLVk89WjJZdfEwb5botXATK"
    "ftI40z64IKXrEumGfjY52k2MYYflNOqU5XWmjZ+L5QSwUGqkvN4m+MV0FBF/70sz3BCT2krAvMzfEPD8yPYSUG6RIWOfkgf6yPsG"
    "aa7i/S3h95Mj318Tfp8a+X4kv3caMtoR8GTvDj3gSTsNJvmDH8PdSQk2a13jgC7x52/M0qOsVr+DgZUKMW7pZP4HM//4ddYf6U3N"
    "SNFK794+tywyW6O5l7PgH0ckOs+Cd2WKYfXYqjjvSrthWSpX+RBlrecBhlA9z67mpchsL4az0UireWb5ftM4WZcOBajSwuHoQI4N"
    "LrDKNCspjQQ8fT142yZi3qdLrjB4wuNJ/uy4nRL/MKoiuzGPYqKkDHalIcMkA1JCscgxn1KOo5Sbwil/OJZTFqYvYgKBlmQLidQ6"
    "bKBuR3H3NpvOBz/8qZE+beBPbQ91ylOwoasdBAetbzPI6whaMJGPORaKIWVNJzKewk1RnF6LLoYm/TnwrzY7mTRMIYo/lVhAYdun"
    "VzKZVpyYyEy+zDd38Nu9I5hgTIwmGNEvsxtE1e7itpxUGy2xHFYFaM0xG3wrjevD+shtrrngymwFXC0CnbTbbOD8yIstzF5p1XLM"
    "LrE8TZ4DmvTC1JyUxhxzWUSFhdoimt62OKoEiOdlLEu1DMo4WitjZG0mlq9ibNFusWS071j92+QbT3U1f5usO0hvAb62Mr5OLdZq"
    "cEpV4L/FP1y71ZLxdkTifc1dY0z7sFTyNbc14wP55fNwMY72ZZlajaUV8yQhDAS9q6ComMktcZpFGfa6NsbxNZZFhJet6LBWZnGc"
    "QZtNaHOhuwgketpcrVX8AaMfTpPcaSY1PsWU2dTyjMB9RnNzrzk0AsHvnkHhj47uyiTxZzIr549wlNthNjXLLEXacW9nL6fFVuXW"
    "pnL2nmKPUxt2nBK3ZxyAC/nT5uZvzY59y65GnywEs6RvaCmYqx3mPmndokUKaLytdnUqlbaoTPuktMXRrfWiR9eg8uIdHXgNxjkB"
    "lainTnGS6P0I0wwcAy0q7SLJwcgxM2LOsciLlS4ReWT74a8WrW/YW4jtFVP2DrQB3JaMQ83fJmIkpms5VhqHRMfBZZPltFhoWizU"
    "DVcBq+FobeJa2YG6NlJqp2lZQK1Desfb6MF9o4mBWog5SaE5Uaj5C85t/pvYhRG8YeZo3YuuI89SmSCupcccc4vW3FIIFqmFAMye"
    "dU8KqIGvsOetg+Gz9iCpkKRlnAXtj+i5jhPKmIoApPBYEndjeRfBTO+AWGSSi6N0wW4r5P/9aNdgypuTilyjtJwUF6dHSOiGwPLF"
    "3gexbq7WCs3+KwHIX3p77WpNSqUNDVnUSvu6LMY34LHQrN2a6j1t95WZK82aCTL1lmLTe+Q9MzNFsmSwHKmgGG0U9CXD7ZH9L+DV"
    "k4ae9WoraGu+SFtk0fZnHDhnrSkW0nDN7PFf7TiBjgxKY/eeY0PxMM6Owou3ojJ+3fzvMaavaTUVIfbC2yJAGyavdxTwFtLf3cOk"
    "xQnHCgsFPAVRsYKIir+MkhxZddoidakZzS3ZbQ+29xkG+KZQs7HjeGxaMoGwdijjIMAeANXjH+/A8Qm1/HQUDa7HUhcgaEYz3VT2"
    "NxknmvvNNIFFMH07Ehdcag5ZzunlSeKqUcGXUCg1nXLwIuElAfNQREFaAdNNon/0psqGqqkRTY0Y31Q3VDbKzA1Hiz1AjFB9ydjf"
    "fDoRDQ34xziomU1YPQ1fYCT/jSa+cJEMxZpxpjlApnHpJLQZS1GX+4kBXGYGJYY865Cs+bNE0xlQnProMc3puUgfvZXmRerkqNED"
    "vi0i7D4QYgi+HaLyGrwNvXKnmA463ls+mt4BdojJ7crwI/sB8RkoSQIii4HGP1VC9vUZQchO025NKSDIfjSJIXuWrK/yYpScBtD+"
    "tw7aKJWhsdVkoLIAuEUA26rB3wG2FsOA9cvrE13KKkspRt+/uoIaQXRISkaLXJpoQJFsQJHvXnNlApmuASv4zRRqgZoVizfo8XvY"
    "0WjYTC2mNlfG/gLT4bnicAohgpSMtmCDclIqTdrPDK3miYZSatI5LUIJZirGUiCaBzGCCu6MIfyHEDmvhkPkFOxIoxg5714c5AC9"
    "oTqPF7qLXT7nSRkTR72rW3MiaoDP1/EgPA9BCxUXMesi2OM4+5iDfhuMqxnqh2vF1oxDEfubXIH8tYm+WqK+yoX91591g9ULY28j"
    "BvA46cl8Z3LiXnTbvEuJEG49JPTcjveXUQNiTN3fI/cyK5DBJb2s79RqBKD0oNZWZ58RPWltOIbukdUyLnP1i0ttoE6rDe/iV3NC"
    "JzOFB9ceTO2ji0xcoB2B0hYNlauQNzv1KcolriVdg1zLhTLl2+fWtRA2KnTpGf6HDKlzzcjAUZVuOx8BgihlSEKxmfTSirHJijau"
    "iuifobrFNLVeIjv9NNVtOqKusKo4OeWau65gu3pKo/moarfYfpZ+rx8aMlsVj5PUD6gZ6vrR2FkSN97TxkKbdy0dRX5BFbjF1wk8"
    "pqYL4fPogeaRymjX+KXLt5HGD97dzoI8rMu1UInaauy1fXjtv1f2RyuCw39L3W76WNdMv3PFWWAGbm7nncQEp+Qu7bCcPUGWpGqu"
    "JVgxXyInwSXLhfxX6xeHyQb0NQ6VBMHlU9Qe7OP5zDDW6rd3rg7ANZAHlMmQIZLwkO9YntOK8I503Ia+Xf7JcICXBVr+8cy3xEGa"
    "nU9K5RYo6REsycbwkvQenxMKTgUZsVyFFUPKu1+8mSIvkSO5iTZ5+mSeXyupy4rfkoYNFj5F9pyITwvZTs46DJ7PGndzxokFeD1p"
    "9gYQ32/8xGDQ+Q32hr0rhmXuvXsv9bVAvGuXVvV77C3kY/CdU1/NoA/L/uEzp1PRdNI1SxM8spJvkkVbqGhr9/0ouiJYdAS+uSOy"
    "c2MLg8G33jgHyVg0l1nNfxfzquYfC9KmatERzWVVizoUqzaMtkEyRvGnynttKpGdGTgxgGbrN4N8fZ3iG2fA2wHhk0041egYIZ6T"
    "9Jp1BJKmIxA9uaN/AAKJSr7Mzm/f8ccSlWj2VRLWoAiHAMIgFjzS6sQmgk7kg0rUSecWtVSIxkRaCfhWZCHDm16kgTpW0buv6JQk"
    "mQ7z93yLTELYwNsGxS7ZwzaRkxgkBiicl2xfYphgRwy+lUZPQoFYY+PJI4rhBAxmTGdUHh11BiVVR3OToiGS4VBzCsThtYUX++8p"
    "GhhW+r6MAyDlqW1Y32jeMgTwy7cU+HLs6P7/kB8pZx+JpLkpFOEOYyNX8j69w3PpD30Vh+P1ZLSVNdk3063P1Q0evRMg+0B3AeQY"
    "b2sfiQVSyqYd1t7mNOIGEhW57T5ARas4S2yE8/QgTE8zPA+BP59/wi1H/KCBwIytf1nnOaBMJPB5QPk3dxgG7vcSnieH4bnueJrZ"
    "8F1b54eI/II4sCQD1r5G6CSoZ8PaEb8nfsd7pkVbZs3obu5PxDmTTo8WOHjMaAd59tdA4CZDxiG5L757hvBNdALiHH5l8xIDWDtw"
    "qEtPH9oJvzpv+mVDB74mucUB8bGRZ5MhGTR9qbW1oeMM71J0QdzGTroAk+IiPo2Xk9SLMKN4DibdSBeA9lPUyeA5KZEUGfiQhBzq"
    "LkoPXyX0u4tGgbaHqEJkfYAbq1gdz8RFGOYt2ED5aAaIn88Qv8Eqnexyu5o/TTR1N3+cGLm3/Z2VROgr4kZawyDeQsHnFmA/s9Lu"
    "RKNz2tjKDTHI5s1d9lPZad8aanyB9r74kgh1brUO92gOHXhpshjqDwVLkKOlX+R4CGOsPMfnWqg8bGe+/zIQS/Ra2X/fq/TkAuX7"
    "gVhDFfmookLtA+3v6kyLeNwkDUp+QZlliVgPpaZz1gPvMUvi5B5zDr0asT4SC8Rniecgeyp+2b/OWSG5SeddIdWlhnPpTwQR/Ups"
    "tmGU4mizieDOBNfP+rsi9oO0C+0Hp9Xq44RPu70HbN7+/uVm+Mi+RFuUuuO5P/7xj6c+1fYf6jr0uePQskE7gOQDGc2OIytMvikj"
    "ERPjVhJLlPatsGfuLRAxspOq0+KfH8ICxmWf+vJFgS//CGHouxODvSs6AmPzI9y3ZxYaJDo/rjo7ycnVXd0uEDQxgvUInJYdz8TM"
    "hGASbVQ6sV4aji4f612dSvR8rhmyzFwzUGWhy5djhF7BZXLu+btVKzZDp1a6BPH225EMiXGmVi3qilR1EZ05mlvNqedBdECpyvEI"
    "/tYvgn5FopllFcwuEx0LzkFfb+IwDNaHFTAwmMbmU4sOAMQrihicT0hCSxBgDtriCGdCGALMBAEWHqUHoyshlTFrqxmGVYAg0oOi"
    "F3bwBz+W3i4GQiQOplBXGclRJQvdwjcvFKASQuFTymdlAxgmjt2eMW7tGnWydr8ZR17tfou61KLdb1WXIoKK3bFb+Tg6h9acgThP"
    "kOeYicOwO6PN8ZUnPeOQtqrb22V3HFCnJ2qr4JAk0aytghAh0aKtsuJiVf6uS3FQXyoxJ2JpXTh2SzQO3V7l+CKuCFvkfjphW4AD"
    "sKS0NwCGH3nGuTM+L2Z5dt3nnPGwb/oV+haAvJ+DbdsyYL3MIfu2OBrS86wXJXK9WC64XjTFknlUVY4D9MEYzHGcoDONJ0FzWt3i"
    "cStEO18a5eA2lvapisX/EaBJq7ZgAgYDlwxORnhD/oyB/zLzaGGh+HXJebbbqPFt2Lv8UjefT67FnFTynFTynFTynHRBSEAY55g+"
    "LQ3vLB/jLkaGJH0otd4Tv4PMj8e34Z0VnyyKnj9mX1i1I46/eWZgHqD+QWzr14m6lvZWMKX02KASHqc7upAEOCt8fCwPVI6/KXuJ"
    "T94S5D90E7sBqgFvn3MmkXI07W8ZRxz9nrEZ/9YQ75HeyKCn1qsQcMFfEITNzrJSrWVBy/nog2GLv898Yes5HZqvaosnX58w8BPa"
    "xMeJwdngybJK9q//A54yVO8ZLvvfKkqSzpm3T4uJtj3fzDn2efT5Ov8aaibizLFPCc4X/HNdEjlfX9N81e2m2ZJL4rDyL0yZI5k6"
    "qMScaOlqh+8kjEJBgc/Z6woMm066ss5ehAKrQI7a5ivKa3/xhKHu0Lhbf9wPbstWin6Wj/3dE8uhHPe2IK9bU1KKKVAOb/p3ZVVb"
    "lFFiCFBDxfAydXIx/ROfMwmSorX6nVnVds/wLMVaOdgdUOwBxSJyXDxJ/uaAYi2mF9vZw5WVUr6ElMsGiRYosFRcUqJatK/8f6oY"
    "Pl9fkqi92E0zk2/HytCatUPQ4+lfzp7NniXB3Wkahsox3hkT/zyP7KOK3d7PbN5PbY7+skWKpWxRadcUvD/F9n/KMKhEQUcBWheV"
    "V5z4XSB9Y2fCTOiUtP2V7Um7zJVWb4fJ1B5Ib+i1zDQE0n0n6TuuK+lqwc8U/M3H3/hDa+Ma49fmGBtzjWtzYlBuY26MtxWeR7n0"
    "N0OlAyZCaTmV0dsaA0+llOr34TbINDipUguhsYGvjZFlHMWlHX9N+NuBv23424K/p/H3BP602Y90qrMf7cRV4CpwPY7rcVy7ce3G"
    "9SSuJ3HtxbUX1z5c+3xmCq5O/IdevTItQJ3uw58lcaYhDX/YdMsW7W1ZTy2MvJe919+Qb5rIEcFwBNP6PNf0+aqy+vRJSA9PQvLZ"
    "E7/rQ721SVTvqQ8x0pOTuL/BOTkt5ySD5qQ+keeEEq/fgPsd+OvA39oc0/hDjbkmBBylor/k0ftLRNHUNj1NeK7+jZQ8C40RKddH"
    "pEOi8Jz92+T9kppse8gN2ia67Cm4TMffbPzNwd88/C3E3534W5HEc5OGsUYwwEdScU3FFY4gHoXA4BEEmHgUysuPIPLto3AT8Qgk"
    "mI9acEWE6UfN0XMjx2g9fp/A3xb87UyKmJscE1odMRf8HD0Pke+i5g6LTHNCmkGqj55cubwzXVHLO8kcXN6X06LtyHLSoh3kCi/a"
    "D1z6Yr+lj7XdoM6EJeyGpYnhIFDOV4K8xYR2VKoTdI8/mXL8bi7piJd4bPSwv0A+fLq3pSd2yadwxPfaHfhVRnqT+Qlno//GFJRf"
    "Xw5qZzB26RK3L/+kIAMDSQ45T7ranCeZGLoXBb/Z9RiSd/0Jt109rNvlvQO01R0WQ5uhD4mkSAd72em2eHrWTMCul7pEJWnUdee4"
    "xQ2yQSU4vXiGBDJh7/TlXInOzN6fmg1tuRZ5sgJOJwEf6e6bZdFaAlUDgTWorCBjui2Ov8yyqDkIBI6zaLHnGlR4mUsYqcLe3GKx"
    "16VXmGP2pELRFiKJar3GBO9iMzZafJHcZnRkFTpipDI9CYH7zeINtLakRYpJY3eYK9FBN7OhMANDyGdTXFplkKZxBzyQon0l7hjw"
    "vs1I913P4HUo7/v9lGbiOXnTA+d/38Lvp5zzfs+A921Gyts1lerCZ+hTkp6KxeiJd4tc1FmiZ6eRo1aJpMgUEwakoLJEV39EClM4"
    "RUGbMZu+j59LQ0S1fR5Z1odnQymJCvQ2JxR4myDJvBvJTx0pGdVUkq1/2rwUgNhS5NuaPh956o5PNIU5Dg3PgrB2qw3sJ9fHbmc3"
    "smva0ipVWalWexav20guYxev823gS+nSxeucSxavu6t88bqf3bnp0YYnOH74VrLHb6BflQITgRcAkw8juYSiz9l9FeCBryP2rrOW"
    "lHfuzONb1XnQ5zxCCjTOWlAaTaqyTnW+GxjmWkpOTbXuwLA5S2mJHAQlkIc7AIm1oUexVMSIRBqVcsoUGDYbn5Aim2gFH3Uo860y"
    "sQU243VvbMETY4zAVBoFkauvXVNpoAOl7CHwK+3q6CeTChf9EwcDbFvWUrGwvPYVOqMuIvV4tbozswkbu+OUbWOTo025TLz7Q/R1"
    "mvgrLm2G4WTwwpjnMZmdLDNo3Comw6xnea7ko+dbvKf7lRTxpMy6mrOSSzL/QcfbVRZHcuqf5hkqU8Qq+X1R+PtmDWyLWIRyHIsU"
    "qtOqfej9eMw9RydqUIabnQr31UYPjmNPg24rUav7QLFr8GPVk202KukiNVSMN7+TWA903BVkJaY5O8XHYGS0BCYHhpVj9CYEwIPG"
    "Ac5WT1H/EPLVk+rtNUHPq82zIzDsThpm8eUPUIn/RShH98bYNu7+wSuk7zv+kOnQYtUdhy6Sbwr7YkjQjYbFao0Zf1b8Jao1E9Wa"
    "SWrNWLUmXa1JVWvSkF+xQEbWhQA6gWKf0+rC+HHTA1NSA8PuQG2njoxqGu+0Qm7VRaqlKCcuWB6XzbX4nBtc4WwLGUxs9fmUXsuJ"
    "63FuMHriFienwxHt4uSXjIvVnLis6i1Kclb1Vqqe2uO/HVAI4noLgGi+nv8gRsnnbHfRl8Cwefrbv+JtRcD2svNdF37eoZ+D9HOA"
    "fvbRTzvM0eazj0AocKru9Kzqp5WhWdXPIjQ1nnNStZx0NSctWOPTETWWnbfGvO9ToyVYYyoUR7Oqn6AaN+k1TuQaJwVrfCKixuNn"
    "z1fj+2e/R42/KNZrJJ1TzbkDU0SjvTjZUEsjrN6o1ti71qMk2iO3FBEGgyzZXRyYOue1eQbRBCo/MDUPt1o3me+I58llKrjoJSWV"
    "Vdo/Mv7uu8fsPWuuXOoWQxbRxub4pmTZD3YYLOS9A2LRVpDVrZV2F7B0iigqkxuQMgKcZbx2yNc36q89Gc1nYly+6U+Iv8Obaslm"
    "agA56lCvh1krti+83EwtATIlnTM66wHdVpgrxooXKAhLt1v8Ll86b+3hzJxaia1InV/W4r0UbgrKWiqs5U8TsnCBnSFuJ7nXXX0G"
    "6no8RqAEDKDgsqNlSMtuCRK2iKyhtPg86WbxKj4StANz57XQKZMcnK4hlbzMLxxvFHvum9H4AfbMcm0Nqco63vCUZU1UbtfW7JBP"
    "I/A01CVWYG0GXmJFvt/C6rCkRFvzYlQCdzjBqjspQeAlKk/cGH6f+QOZsUlmnI2M2doasuy7kpycQWKFBNoaMi58nXYKyJ1F4BZ6"
    "dVB/+uoWKozyi09vkQKw18jbnhY/o/19dGJE1hZqlYJz91eQFASuF6/fQnVWxPlqXAvqVvceeQ+pBmvxqD4J1ce7xK8pQdZ9fZ4h"
    "4I6FXz9MryHq+KGy1y0euIVPqjip6+MHPfclgGl34AM5aqBbTC562BH58GLkQ1P4Aa0pc5XWPShbk8B0Fr33PginYonMlZfPLfZ8"
    "5Yi2hnoYS4XhHbeC2mCBSsrqwiK0ZOn/p5aULiDyFdQDWjIKCUc4Wj1DiyuuK2HOyVjM5wEiOXAIh57J9UiQ6dYmgz8wsRg70Ask"
    "/uop8Yxyi6toX7vRUKLY6vo7qB0gQeYxCdJW1gLlMKyAJloBtwIVCf8cWjfPdBwBRslZ6rnEW7MEcQvEu/R66RLewceKd8FyxJoT"
    "P0IOZBfqEppMrBtfzhJtxg5AiqCdIWLxEM/c34yka+6hrEpnyzOUjOK2J0/5nG4savI0umlkV/bJO+lr47t8X/sB3e/k+x18z2ay"
    "yQfRGa2WnN1v7kR7qS+FpBeSAp/jZ2qudkPnMRUcocB1WKep9CeelkYnGKvkQvonnuEoTSm3KR+ULVpAxAZYNjj+l69nh5OFxUK5"
    "iQRi1rVxbFCgxMN881t8m36VMgUM3mmpnisrbC7fw7ScKqAd0McV2MMVZMsKGn/zKI9AuWsZgEkttYp1leSYu+u3tFtXQ51q+uS1"
    "Y+BxshchL35B5hVnrrLV06nM5a7IBjryz0AqI/yf9GYvW1V7ZpHHg53Tgm/epmz/WHyLUX5MIq7S+qOe2Nozk5R58rs9tpaX/k9C"
    "DbMFyaXffcNNQ2Jb/QRMUv1RW/1oUmV2Wn0rjLKl4pP7JSq2NdBxFLQRDh+lcqAgJwTbxUq4MjdHurE+Gu54rizdl5ONQRruKp+P"
    "4ipi9PRF/fLjGmrctNSyBZRiXmSKTJmitAVyi8LMo7PKi0zsVMQunizmFrFFbf0PcCKCz+GV5tZ4g5rqu5d0we2+0rxAZvkdKC4w"
    "dQPo8ApTeQEprIu/n6VCU0mIQe/LFyKJ/mnN0iBkhMan4SQ3IaDMD2SKt3L0LSnWeyf44oHZ6UH/RVYreQ6cNBmP1oiaJ4dqLZe1"
    "1lWlW/eg1qrGzC+yoAGk3KzluBxvwL3+UvJt6AocBo2cEFjuEvfMpjWSMw/YMvx6npjHr0m/KscFKwmtzZ/LQD19NukKUVGMqkoo"
    "0wfBssZElfVBsCyLfF2u3utS781bpN47R713HqmO2nHaWJL+dN1xwkIh4eZCzbmEJrwci8OjOvdoThwwdqrOJvEqjgOxdGzw5U1U"
    "81/05U3yzR8b+zyhwB41f4fqbLfVV5AKfPUeigHBd0tx56Z4PTfOUubU1sAmNqf8ThozZWlA2SO+nSWBqYeAyU3/xLccHT4FvNmk"
    "xer1i9UVMfgza84moMQYsDOde7rITadbXIp+vU4WX4427N3bll0CCG0XdqcOxPWPkB+RgLJDnJ2tz+dq711bQYi+idP2WRa1Eqyz"
    "Zr3zTRcMxYsVHTBs9bRWbS/PgnjnRdVIn4up8G7JhaiFVQWYVttgYGXRnFtfi/3jzYZsF8gmVPbpvcHFNzizR/Zo4te6JyJYISo7"
    "4bsprjCg7BRrHJJdqTR57BXmgPJiQGkS98uXqEwfISC7IBqTpX30VdCrBtFBWv7CRWWZby0Qi3Ds9L5xx16e03V1x8khbWhOlwJX"
    "fijO5FAIliqt19dA4eNcvoY9dCn38ggcdxXWtZFDBPGpBOIGiQIf4yNIFQF+2uTAsjxKKf44KzjK98XIzOK/qKFNsThBCpQq/l6o"
    "8xsaOvHoeUmblaflV6kNTLGDNwVruXv2xqkNdKjTcBx9k96br6mIIzUsum+gyDUucccNrCbryz8OSSuVjMgllIWL9Tb3wdYBHOa/"
    "zKRRSo1c0n/pluPECSFwpuRNZnVWnu1l7rdqxI4tRyCwnWoU32RJu+Dqqhhbw0kWKdM4eX9H1UKt3Kzlpmu3jZXtg1Wg2+ywI/K4"
    "PcA9Br/KRx/UjSSpJBWXPDP8I3G1Fu8uShKrbqQUVW9Awsl50N5Un7lNs6sjKEOxOVQIYubKLMpdFcbA8hRfw3HaXJebXRWryw8S"
    "okOEE9G8jp1WoJjrMpsW1z3r5ETGbG/v6sruciIEA1PvAKNM5naJEg/3kEjYbHCeJK8Jo6vGg2CDU0HeoKqMSoLsObhJmPl7mqzu"
    "wPr1lTfzkfwajacwsJ2GFaMp/kC7Jk9fiRxlFU6Cmzi3uWsnsTJ2UQamiq5EcYARgqXpkwPXB4YtleyCYaAuf4RyAsvmiRJcvT+Z"
    "Q9RtflVwmmOh6dHGFvaq+RoGpaWLCOrv/oyg3hOC+iciMdlS1FboBoHQon1drCrHPGmIkwGz1o+wiku61hjJQAv6uZPzuh4gz7z7"
    "25ydXEOpsNX/hHBW1hwZT6p2lXGWhIjaVTGL4N+LYON0eTnwWLG4iRykH2k4SovhLaatQQvZ6sl6rtbhsNW/wnyWDir5NdqJ/GCo"
    "dgKdXCdmafrSVpLxVIx+Zzk7SzyDAs4Ob6u1rp92kJp3ZvHWhU22gs5eMF3C6UtBnDUHiIDqjtjVNxUXYv3xInaJ8ooQTSKxxdYv"
    "9I2tQ1OOYRG1zp5x3CCOSOznMQWcwnSm9iYQqLn4tTVwSNWmLKfwVCC9/w5IZn6EHT6EIhCL/DQjB/j8zvPV5EEx+7LA9XL936Rj"
    "2aGFqEcosgoldpyz00/1zMIJwHsmtuZNKr9TiaVKYkUCKWhiMhmH/eoTfTYrUso7iEz973wizdTSDm+1JXb5GHEiK8jGkYTHPtk7"
    "YKlJhLguupkIWlXpFClEkdy61A6hG3jFFJJA+G7jE1OvWn0MFpX1x4mKs4q/4mhTAsqVua23LoFMbgVIAWQTv+eAVdAMsEJX46mz"
    "fEDsgF1kPRniZJVaPaPLCaZBw4hNN1LRGHREefF8KqO8oOwyvWwiiH1lS+Cq4CaUjVgiJ1BYT87SGMQ4iyXq26hcrjl2MC09Gikq"
    "Uplg9jZZXeVpoJPFwqkMKOJFolJAegsaAf+VWvUxUNeZR1HVqDuYQat04t7G9/5BxWLsCapuHjaMkpIgdW7lo22HeGwOGVwrnd7F"
    "S79kzpuSGlBSmNturWB+wO/Zu2kqzB3AnWxowuGkFZYWyk/EC9lkZGPR8paog7S8cjg51QY5kqnJOPgl83Eib6kSLx5F9Woc0Isj"
    "NvVv+DictNJD3y2i+scGxqo5lp5sDEaKN29pDKow+hPJIbOWbaaPzDplvn5KIZHrRO9jejyDs0rtvD/didFeblqsjiGJnuOEJ6Gu"
    "2o6Orl4+Wuy5XgcUCTPiV34Gly6oQWPeUghMx5I53xnNedxW/zbN6/wUJRclLx8FWSYci5ivWazGT0u7xjNmZm6uI9+u5vdVfjKt"
    "tJe2/5PeO5ae1Zx9Xf8kwjbyXXPXAQYee3FFwF2REFhqDgzzANMBehr+m74wk87b+4ByK/SMYTPrtHguWxsXyLfc0OK5GM2Cs3ps"
    "apPUIB2aM+1iz/icrFKL8iFKzYDk0gkJJs2UMaJw5TbxznW0QK4gHrA6xn8ldSfBLfpuIGbgNYWFA5ujpImnQzkiu0CWfcl58k3+"
    "Se+Plp7FmYk5tHBWAAhHbIHyJky4Hw4/JMyESX17qZTDkNzGl98tdmHtwHQQjNWTa4tS6ucZRysXe6vtBCz53ZrazpSWeeZ4p103"
    "JoQVU3ZtdR/RWPm9VDcQAtRfQABbmWX0a2be2kMvsRFq+quQ/ou1uGGvrf7nRAIWQjsP2U61mmRUa7uSBPmbraGBFhGGHfJRCEkh"
    "Hu0yejLqmzxXy5TKJ9qHSKf8yPsxeKvhZEhxPXlw/oLOBAvKFrVICaRneLAQWz3tQrpc8nNZiEd+RLaeBWWkub+oRR1B/tpQ52/+"
    "Gujvr9HiTAe93YHM3dpwnGP/YDAa6zzH6t/xTKrv8Vx8CrsJ4gFa6Yrx3qOO8KfCxBiKyLgbJI2NcQfdVS4VHjZQLoRlarysQ+lB"
    "J2wNK3S3RdRq8RcIE5iplfAwkQlLQSaIt2/QvfMHDgLftJRXEaU+bCVv0p7h5UuWMQffIp/jKHfgoOSMHSIOGr8YVoXPb1ZYxKKF"
    "hIdwQzFqSTTSjaB5pMkRg9JbyV+LpfLLMsmAwT5jwz44WINxKb4fkt+tlf6yFpJ8ubHtHVBGixMwMuR9TV/Q+z6T4RaGg8f3TBXg"
    "EmeEj1Qj8fpY54YiYSPbzgHZHo/IljWV8nmOasmNn1IMF8rrnWHfDhj3XFROV/GbRimNSJL9o3cl4iRGrXwbJGTlG0goCP9UfJ5Q"
    "5rmLyxu3zTSI/UA2r9WzYPL19bjglLLMFtn/U5VfeWfMA5MSNm+eUeV0J6boVQGmyZcO2L14K/k2qX9FNb8ACY8RNS/QmTCZPTlZ"
    "U3dSB+5Rp+7Ada3T/tsXcSU+g5Kr83F7pxHpIDm5wj+NNivQKOAkDff+rNOcVd1ZmQyaRKNJ/XfgoP/z8ia0d8eL1K8couvK36Tn"
    "PdxPeg7uJWOYXrQblIkqNwIt+zmUiUoIF9AhAq3jhW7Bh1X0oUVclENsJINcuGICL1srvTDyi5TgCyPrb8aGH4nc7emXj24xeppk"
    "+b40hU6Cn66j35c7yZzhIN8v1ujXrdJvx8P0u5fmy3gFJqbmetrX0jcTxIMnnKi35eesvWdt6SL5Xeht/6PyLSZgGk3AMKekSEjO"
    "BKWqMyRnIjRack00ZTL5E50y8a+SEqkTnNLzfmbTtIvl7X6x5OesY4gCkkUqF5BKOGkf9rdpY5SxwhwqtKLf5+x2lRNlK8pkPDv/"
    "ZpKNIzRZPTfRfh729Z9mE+Mak1EXz0sxW0ehVpaIcrdSy+dTt26czWqQKANEDlHMSjqROGNE3eTofs3vDFJc1xvJ9y9S2Z6i3rxH"
    "3bQHu9lGuT+CJX/1Mbf4nzgSeJX29eRY4UP8j4SThXUjQTCcPk92C4O87/eku8XJDRTcI9Y3nWVobtG5gaAVQVzvaZpoitf6/bE7"
    "toDq6slOX63kucUbG/RirnGLVzboxUxwiz8NKOap6GKqj4XLqfWMEr+6OrqXlR9zL0F4ZpV2eGYG8q2e6wO3mVcmajb4j5ip2vzx"
    "xeLyx6lbEIz2BhRaPw6nRaEs/sFafmejMeDsnJ6ogH3S2Zg6kPhKmUXEV/WxYvFZLM1MISFBK1QlEDIIClGjReLVuqRSx1j//FdQ"
    "Xum/GcPo9VwPJ4kwwYOHBvHvx2lAX32c6P9bhun0f3UsikJLctIgFUx0CdO11NiaNMjltBbw9QigV9LMz75ZShxp+iykjiUlp6PF"
    "w1dFi0zLwk2w0kzCwRLKApTlogQsyf1mKdaUTOhIaUosAfV7KN4teimRJA9SiF9iIRps0zdsb4VVwroiYPJgDCaJuKuix+Bv/5Q8"
    "zOpeQ4hOARy+DzjMqk7x4NyeElO1F7/pq1ugz1u49mK0xldj9L5CbGMj/NngmGJ7CTuSS3xKQRzzj9MysmuPMQnyElyDmG/2dkCB"
    "whO7dkyuv632zJVKnDc/NcYPLmuGYsJLaLSQo4dbiLdFAthsvkm3PUqrARvYFbVnJnsS2pwpidTnKWvjp6/0JE+fz6/IWNk/Djd2"
    "ukkEB1cZiuTKIE5lnj5fMedSFf/TLqPKQE1XgQ+c/baXrbf2NJs9Fttr+71dk/0XLT7VbDJ6rlm7v7brR7WnR+L1CpO3a6y3ea8j"
    "P2XZSLTYkuXsq7xMgXH28nF4NDOSHq85U2/bYlHGMk42QcGQdhD/Qq20z/Z8aYrpQyxR6jf8CbxGBLQyaotRudHbEUMkNdkM1K5I"
    "QBcnZSl9yy8T5Qja2ONMNbYZLiHqB+PUF/Db1zpT02N6WEJmalWdkHHTWTRGnYakMR7TqdK+qOkD9QwTHz3N5AEzu2BRGVOcQDJ8"
    "qnKFCM0g8Wl0if85q/OOw6QptpKBCbGVioeDKQH5TxDk/+CmMCpXLDrmAtZ9JCMaGdz1j5CugCGE8xjLvasSTL9jjERvv2f0duV6"
    "HS9d5Rbj1ut46RK3GLY+Gi/Fro/ES5HIzekW4tFwIcceDRdy8NHoQpoePX8htRDmNF8R3Zkn/i47gxWfVdqpjHeLxygMU68P9o7g"
    "SkKH+LPHaFPqxMaS/BhLjwfuKsU36rtKBnW8ZcdK7KMtz2SDtsAhsSKlTInfYcCR1x/naK2O11o305cK6LFbs+VxZvNkKFUqF1eY"
    "3epU+iZO3BT5IbbiIpBlme+8QuX6Y5+hlyrc2TWPhY/GutO974Ct/nlFfxlSNB4kN1nfej8bc09gIrR7e2M1qXuhmeNp3CwgB0ll"
    "KUa9BtlvrjstkKHqwCKi8UQpXFPUziBaiSy21V8SEUx1iSOT+CwN+pGb4GiuHDHjCGpdYSerFAT1huzHywpR3qaxIIdrQe9ycni6"
    "r07iz3cW6EVYBiS5cIklrnCJ9eeWeIMrukROwhq4haRiB93pf6jVvbZ6Ys9DvcPxtpKUVW21sTaPP4Fu6+vofFuNQzOwpbLCH0tI"
    "c2lWdSq9SFMW04s0z6Ks6rFKUVZ1ulJU61ioDKt90LhQsdU+GHOTklD7oGmhYoKDbZzPtBPEBI/Ly3G0rfim9sYblGvhRjIVVKfJ"
    "9hAxyhBFtiJQIA49KSXLZUZ/KhX6XJuzl7gjXSSFRg5Tq9Ewrrqv1gElcU+h7bU4l7j0a503leMfjkjjVwN/LvQkQAhnUZU+qEPX"
    "GHNQtXIY5OsljMlStbaMlixnyvJqVyFxLuxigaxV+wc4CYxcTOTMwNmHuzxHS+VsbzX8Xw2nTGnL82SmVHGpzOStJv9WLxAjT+nL"
    "UtKXX4Zzdh8lGStMMknXRqZ7Uw1yTDNOZClpK+7BJICUa/NYMNjLZYV2+ZiiP6bKxzT9cax8TOdHkXoZBuQfynCoR/Kmp04Wxz+S"
    "HGxWj+xVPpFKkc3+UW69ycuekP10jtX7SHoR8piu5aee+nDU3h2Esca3FyC1lp9Cb/AAtWdwP+QDVHJOHcFn+6gmaMQCxWJLt4jN"
    "jCvHgvVj1Fx9MK+42azNtSC+gzljX4aR4U7Lthdq8y04YsHhgLbSuvwyzfwymGWE9Mn94mxvswWqbthrazJ0NsY1MFao/FBvI1L3"
    "ZKeYlW6N4bXZc1EoQ34wQzxleN//Fm0T+8Agz9zb8E7VYG0f+Y/RUga7taUWk/XaMmhRNes0BVrlze8NUMsQl/BDN7VMze9WYd6T"
    "fxLMG9uatxmL9WlTHs5w9jqcJ5dfC58c+SlowNBQA968QldVGQ4+C/AHxKt9KtTbwShXulXnScphjcrxy2COUUTT5FjErcRXctpL"
    "FEBgN4oYDQuAgLMvq7Svss5/a09OiknJQ/+NkAy2+rPBbMrI73Xkn1xxJV5mK4O82AqVy5HMqIxD7DNXqjbXqlnXrr0lpfafxh7M"
    "3KlD45v94JulmDwfhmfdezwdI6DlWb35JwPefMEDwSq4wA7HoR2nVnfA5lat7m51BoyEMNYMJYV/Ut0/pk2py3CedDi7l2eeOySv"
    "XB7U3uG2m1QwlJ29NBbg0fWrzu7gmIwIZVlzeVCcrEpWKo0LnR95XFYiu6xuxZ211WBu/LQnFz1P8VafhN9c6rkHNqkBwzajf5R2"
    "W6p2i1Uz12nZKVv0980ipudgupGzTgJPZiJVkGsR7xHoVh+HaJQ4zMr11G+n8CegxFhqdmfA2ZtVCkV/0vnh3PFykm3e6k5+6KAd"
    "Qx9TnI/Gvgpa4eLrSTXAQjoRmU2i6HpyxQTiCWrDJEyA0VEctCfBl8s4peXZtVsgzUvpaTYSDWIXB0jcUOIfSXYLxT3NMeCM3oZG"
    "+mPFDyS/jKRAGLFiMZK4zKa2MOns3wAejrMzy5nq+aJ8K7gvMGUTD70LRWXrq6RxecQlOigSi/M4VhE8XM0Aqd2EwAzwKaPdJbx3"
    "dRrKG/Vcr1CuF0H3+NtBAJVTp265jjAGCSUtRM8Qp+TnlwTJBSk+uPv9ENG/SAwBr75i7AJTi6vCKJJOU6+AksUZqHDinchrJDlz"
    "L6kIuok8+Fh//wuVCQpxWD4Xi+2NzFgeSFcEppKy1Z9OkcBsLFXxbS9V0cLyHG+7EYEnYvdgu5b9q7CXN1In6qdSJ3BqVWmNdvI5"
    "zF49FJOlHQgUAVStINJwFvN/ogthgtUSOS405N6dAmTeYVAGMwu8U+dlUlKSQ2yhSsZM1XXF8u0rbwC6ygCey7egeP8XGHtZLYSY"
    "TqyJjrppP1n2sw5PUpvzGNvZOo+1iL0I/YAJCVY9jGq1Q0RQ3k6lN0+h0jtJ90RrtT3vtBudlmBtSZeTCIKr6tblU1Ed2DeFiyLY"
    "pQ6khJmxCMESYEwNB7TOPiKeSbmEP214IigtjcXMAhc7+3T0kQZTd/DRLRX98x3AdMfVok6o7T8KQywoIQnP2JCOKojhCgAbG/BA"
    "J3Yq68ReJu4ayzqxPxwbOrpRanHJuyESOpOMu1sRkPWenomgfQp9aZJiM5la1+aZadGMEGNkKbGh6rpySUD3AfCWrf5LHCGximwN"
    "n5KBLXDO27b64RT7Mzs9pulgb6Oz3/ZaU56tnlR38pQh2u5TB7fgpHaCWv2vfrUIPPyTWhJOGb7pg3pyzXme5Wtvi609nei5F47p"
    "i+yenzZatKRsjP20ov42ZzeH+pw9KDbRc6uWtHbOoAmUdBYlvDGYsLa634iUMTLlhEQlnVNeSilHUsqUYEqkMslUl4LBRLapmBaX"
    "ZgpMiQsMa9Q1O4+QuW+1QBSldW/h1lFttz1MAcY1k7G62zc7ztxjqEWoclSHimNs9ZUx7H1oFfjrtVmJyv21FrP/PtltZZw4fDGP"
    "5SsXR5/m178jdRIc2u4Kc8khgVB0+fZKk+q0E8oaN0XXqjhpY2mveICzE/tCPMS3Fh0IfoKG1Y49o1WfxD5nanNAvAZOFDwvHGRC"
    "1L7WOP0iW/2fSY0q2WNtjM+diXq6WN3c2Z0Hn2gj4G20dlqikjiTvrTGJ/oVNML/s4DTToArgAh8zkD0GCmJUoKCO6e3Whg8N2mm"
    "HgxMngfcgUCi55XW+GTNtDY/0DgnLtY/wVF9UonjD0+DjRiQ0q2fSmNdfg2NomQc7buznPDqnkt4d5hmkiOdDVGrBQyAtWD+54LQ"
    "dJ6k2aYeNhxk3T9bPR3Xb1trq9+7Mi63aw0pkzXBq/5ev83ba149FJVXDrrN9pItu/YVw2E6bIi1I2wv7bO9ptIjbN6TRdrooAzG"
    "/8BMR7tiNvWCJkgyHeiZiT6l50IHu7Egtiph7QgtqXHeoAl4YVKCT5fmZvT6h5w68iQcmLuoZz6zThV2ZlSfPCRc0jzuJBz1dZ0l"
    "2ZOHRw5dUKYEtcWb0+h0mX8cJCx2ZKsHSpvvjCFs7jyOM6etoZqJhO4uxUgOZZHV/z4gbhAgbrEXIBdLIGc6LxiwPSGG9WXLYu9p"
    "QAKJYnGX7LEtVm25udnZmOyu7Qwr3d7mfkfzsnG+vBgu1U7qGk4oqccnGhhiCHJIEO112mN02Igh+8MLwcbtDBvzgrBx2WJQVYme"
    "51FgsoHAo5fAg25O42aCZmqdHXdpov9yApd4mdbL8NJPo3o9m+bb5ft4LiM3BDMXEczAw7zPM8jcE0cwMyjGbwETGtLD3FxMAzBX"
    "19OEtbltFbFl2G1HiPRRQQQnJo2isJpdK4ki6P2ZraGcbu46buiqYKMH5oVgyxO0Xzx2FTNrMTPAzScukrj5yEWRuPkpA0cLaANq"
    "jmXUPE7su4gRwbZQOokIHj4gEcFeuHY/HetL8zE27pYIWkuyvTTnGrP3n0bP6y7x2aW64QIGdLLZ6Bke3mxeZ60AEP+d/uEiP1SF"
    "KOJKIy0agrv94Kt0LsI1l0npEKRAMMIYcikx1AIlnnxvv/EZaosS15M9z6gkeftjlLSe7EmoFyYhn08gRg9cQP9zAqOqEk+aW7yH"
    "+xIcjtdFQYLWC7kiJAPXTYjaeRoCOrOgpBW9gXCtWPx1JC0D6dQUqrYYb8tOjPe4KyPG2ztSjnf5yMjxfuTc8b59JI939sjo8R7x"
    "1vce7xUTosd7EA3X4X7JXPXbxCep5zMZCQ7wtkn6AB+cEOK5joV6JbhXIPT+kBotGq99M0To5dM5tsVzzA26GSRNkDPkc3bABK6T"
    "OINtzuMUF1fsXM1rIpDfqXWvJMq5MdXP6QrFqMdY26JVP5gUFJB9OggLOkY57cUou09cms4xdTF7ymCRGuoMNKs+8P+A5fN92B/J"
    "vng9SatBF/cqQ4Orm9xBJqaSXPvtiEnVp9SH8aode5bONUV9vHRSyifSVLopkAWinCjH+ADDc5omnh8h53TDiFAbWrX3mUcxYFIb"
    "RvCk3jMielJv3i8ntf27J1W5VMyWBVwxoACjLMC7L6Dt9i+Af7rx0VOfFkXaPSfPDarzGPwl+S8Sx4aHFlzncLngjuH41xGIljsc"
    "04o6xJNX6GDxyvjQunOLX10ilx32/keHRwA2fK2TyJ2FYan6RGjwuoQC5EToIntoVVUP1xfPqAvPR5tcVXk0Ffsvj1hVVw6XMzBk"
    "+H/AYmbun/h8WPT4Ne/93qtq3CUXxGJf9kdgsYdDVYhHh10Ii/3wcn0076FSW94coH/wstQ4sLilNkChZ/BaXYUgS9cP+FKLZ/G/"
    "LvyHuF6K/oWW24dk4+o7Pal/kML/P/Ap+m2YIvuTYWXst8B42A8LYnNYuwGKe6xusNB/yVqoERihPzCjcYSu23B5tF7DNG0/gnhA"
    "s4ESciKkjidlgS8abUElhcYRQX2BkLpC+3eqKxyAusIVurrCkLC6QrCUxeqIzHfoobE4Rn8OfpIyMLhl1dpr/2nKPFp7Oka5afEf"
    "YEaZBQ2hYu3GDHhZrJlU7HKLt1cSnhcV8dJLQ5sC/6XQ2F9l83acVXOs/njvrdaxkH8tQkaybVXjysiJg27qQRoxmeQvAboHYo2U"
    "2/NBqKxl8SloOGV7UtxiyUoSp233ERYjdUmynigjNFJOsGu7TLc2hHwTB1XFIUEKEbqVDgcztW0+olSYee0zb8ua5gGXqicbgjs3"
    "tb+LDraZ79ysFvVxEs28DUybnmav5+qsIosy2AWqDUmIh30xnV1Hkvk0OAox5AVjqv5JMSUAAVT38UEwx18PBqTSwcUFpmxzi51c"
    "SUsQYocwz9IC6+xOyH6cx8T6S+mAaxQdWSwbtpavp55NvZSDpUB0glFKppr8lxF8fyFo21H66P7F/vNbS914qb4YhlDVVDZrhbJN"
    "q/iWbFo3xEbYtLK38IZ0/LopCuDEWGITbFKVp1XlCdbs8sRSdGcYcdqGEHEkvhkcrcbx5huhU+UtVNb2sRSFRPu7bnQJlzCxxbqQ"
    "RIs3tazNS4/Ze/A04EqtXt+Y/xxsJ04blUzNRzWfOkRHz0vFs4Op/6iscUBli2RlXe/R8TPbDH+wMtgRdBGY9rHD0OYRZnjZ6nuI"
    "6I3vmW0y46DWRZqJtSPJvnYJWBh5KT5nPVgYLi0+MMWkfRUY9rR+7qNQajD/Saytfg6c5b+QjtqwTaQndtc2hDekRoJDsEl11sP+"
    "1raG3PJ773qW1EmVdWudzyECRkMcHYPjMvdOT0QFOAW71PxGkfYTbpVyER2ktkL1/Rc+qeZM8aYoWiKCZzs3ZbSaGqgKkmquedJE"
    "DHyZujwidR3e5wScz5KKdUWsz2eluM8oNn9rAU4Z9fQJbQsMe4J2ie6GHlv9bVQSSPVtLrevgZLLbgeGbdA7PYEOts5tRufTiNC9"
    "bix1qroR3f+NIZiRgkDqOVv5JjmqgE5yOVS9zWhbR86HAs4nAs6n/XdOB5dweowyyvbyoMx3cN7AgOzOyfE6n41R87eS/XJRo54k"
    "K6BsFX+GT8vFDudW8Co3cClPUys8oyuS57tU51bxSPi7R35HRRoPWJbzWdtDqwDnXT8hRfl4NujFtE9gtflNmT00naqy1dZAxrpB"
    "MN9mW3MXJcjfRnOYkb/J53zRwYC47DKtaFvAuW3tkJm13+JYjIpaDcnZGNpGO/3WVT9LLlkqD2ndyJPRXcGWtW7cDxzafXz02qAP"
    "7Rv8tC3DucnB7a70dhGIoXVgpTwV3TTOmb8tsyeqYdegYV7nthjby0NmzlzsReOSvc4nYha3GZIN2dk5OVr1+sWqne7q+gk6K9v+"
    "YxMvi2riJQOaaHuIFNa6kozhxj1rW3MlN+5ZWhVoHsC0gWJQlemNnKQVPYsGGpVnTQe4jYncPsiZlG34jwaaWuuqt80l/y5vkoFG"
    "+XNkwOAjdwsFPh9Hvmp+MmP3IRwrm11u/cjMAA27V88q2RcwAlpdvvqplAvCgfVk1RzqlifBpGxw9K9+158gaSRAEB5xWHw21DXV"
    "+bTtIdIZ81N8qPwNBQHuYEDZREbeejkQxWwgixUkjihKcz6Ns40bo014eqtnLE6TuIKN8J41ZImeQVDttxJ5fJnERNlU3KbaaRex"
    "u52LxBZOnEaobZuV0CuRbqYM5xPwYO4j1EzW+Yk7yDo/NZas80G3baMdYujYCLpNsUq67Xbrf6Db5liZbrvWGk23JTR9b7rt7tQL"
    "0m2/ijx9vp0Uots+SLoQ3fb4GH2reiE1dDhKJUnqUYRlxGnHopZ2q6UnxUxSYXaK8btJMtgbUIuOe0og2qQUYgK+ae3j99Gn0wHP"
    "TGLfVtszukd9a2tspfgYpFPAxsGvkvF9YQVI5m3SB8JWnQXTR8zOpBBrLQW3moEFD+WGWpaZiNJGqa4H4qcqEYE/T8B3dgs8SbcC"
    "4/Ju/OveYGRcz3VPUu0r41YfbuhZ8bamdOP0RElGchkkxjSEmrAFl8yjzK8Sz5PzvGmxSpL4eSI1htxJ8SnppH+X48zq+6tQ7bJ7"
    "CsMDfgVktMExsdWT0T+9dQ+Xx+9ndZ8Ap47kPQkmEBLSyJ1ULheZoeKFg7yddutQHYe2jldOIig9Nk9MFKqCQrpgzsJXkVV9yNyQ"
    "LroAHg8SPHpHh+DRLj5JYHisSJjf9cpAIJwg2hIYCP+ES0VCyAtNwy5dzMqD8R8A8VVI0FenVUFWbl02TCyXBVJEvorh0mPNcy7x"
    "+rALQurjZ0OQmiwmBNsBqdRAAP06LUhLDQ8K/p+c62LdPZPU3aMRDus7W4oL3WsHk3YziPD71t5vBB1epJ2i+JJryQPUDbs9I3Ce"
    "SGY9ZjwkwsD1RNkCqEK0yFetSpevJrD2RzE4cUykVzE37FFeWzvThFypaxfDBgcvPP/wPwc6eMGitbu73sJo+XIDeED0L/odwGGA"
    "B8woDsPFO0MchluDHAacarG6MDzgM5yfxVBy3wVZDDtqwywGqQaOXzv9ift1dXDvjIMQGMVAv2PPAl3bedTtuoqzmH2YCeTFdTMM"
    "hmxD/u1K5jPTcVO3gx5d0PNULllctyMVD0kQSnh3eHA3aPkg0HCNAre2jSSGIt3ctPJuAsRvwet6ndyvIEC7NpqWWeCwvtaJGFKG"
    "VAwR9xBFvYOqZ16qeqM7MGwH2ZxXEMMqiTPQyvQf1XJoUEjkjHN7DvgmR7Qaa91nAbBcQqlA74Mr5omre5uwBYlwmxFySis6Ytqt"
    "slrz5nrSaZaazcPW0e+MWvKvYmGL7Q5Q6A+CsoHlCiQ+adLEXAyysyabpcIudvGL3bdL4Zd4fwR9qbZUjBKvHSJ172EvohGbJ5HS"
    "zGagmM3tVDap23Iqi3iCUomFDfqLBPEwvUCtv4L0gexlwGf20KtnNlFjn2Ylr6kbPiVj3vVU1jKY58nlwhI6aIc0HybbQvz4ryKp"
    "p0VLgCdpmCX1kUZ0CUk9Nee7Eel/S+l3HQ4EdwBaW78YSYLGoxBLdmXjHeBWetvZ3PEZjdYx+h12hH5Hv0u/Uw/S74w38bt43bBe"
    "viQf58vodr7E7uHLhCa+XLkTl02PxnZ/Rl7xYLDOV/Nm8RnJbC2bT9JzQwfEwm2xkz8jcyG45aePmzvR6bbYI/hNMBua2mKP6cZE"
    "fGaC3SGyPGPh22N9xEwmDzybJ35G1oDiN0CoJYTgyRlPeRNr7pM3Hjix+4wMNiw025SmnMqOcsezd4B/QxzFYXqc1ASlEYpPiwM6"
    "uQzleNpWXA/7Z2rt8DyVogdJtsJF69FDnx86koR4o6dOaN2n7kRA1XYK5nDqU9OhykEOpFthqYxH9CvrcuOt4ACQm6lwvAiUYyU1"
    "fyiY3I0Id8B1wE7D675lL3yDgl74YruGqhyKzPutufKaUx8S9wKBCIJmFxyctMNiaqaLHZd98AcHRocn7sRzKDhRpvuc0jFrg/Sr"
    "WkL+HP9f/QGSB90L+QM8WXIBf4CWEvY9Z75d+gNspHSp+JmNv/KS7+kPkEr/z/4AuQ0X9Af4f3h7G7Cormt9fIYZYJCBGRUNKiqJ"
    "mJhgEhLUgAM6KIMYhQwSQKKo7TWWjGnjxzlqWlDIQMJwMoltc1tt0zTW3Fvbpm3apsZ81IAYUPMhJsbYxLQkMXomYxSVAAoy/3et"
    "fWaAiNf7e577/Hke5pyz9zr77LPP/lx7rffV0vDjcBz/rfg/gP8G/O/B/0v431X6f4UHSA9TAvTSZvzH43/qA/9/4AFuXRLCA7Qv"
    "uSYe4DMP8Dch4a0v4PwA/tsfuA4e4NYl/1s8QE73/wkPUEs7G4eF+L8f/0vxvxL/D+Nfwv8TS/6v8ABFGT2P313434P/d5b8H+EB"
    "UnuDTZbxXetRchTMcl+6veK8N/dr96XhG81YaMMi7N04RDWF03zSFVtqOwBYqUYYxjSpeyN5TIrYswmWrU0c9IdgUIUIIq+Q09TB"
    "E3S1B7ugNNKCgqqBhroUDRrQhFmZR+7mmTrMKqyNvkh/hOA4XWV5JAL/AMWyPFKciJ9lKassWyLxfx+CtpQgaMtyBD2yyo6fHzjx"
    "s2EFfjavQcT3ELblEYRt2YiwLVvWeHcT2oWXoXfmyzsVPBPzwS81z7gED3YE5W7YDANSGryr6CsdptRDyYdANE6H7fDzvZwMu1YL"
    "HZQj0R/J9xJS/3vuz7Z48lSgG49MPl8MwIJbxFSQAaxVeE5tVMqswFQ3fJB8BEsVw/Fk2HS3M5hsOwQuvgBBfyFsQ6ej92yEIcTJ"
    "YEmcRFyeyYAA3F0EcxZrMpyUFxWoC0NP8I8NFZtyRLBAH2IWaHo63oResYNe0T05iXpJNRs4dTvpVPgvWf+BAf3Y8KCpC2xGjJhi"
    "b7zJZWSlI7szFavbnmSniqvmw58PJ22lUb1b28wCGLP7SpvlCdITFSrjaZKF1Vtn+nRjOwbXKzCOfB82uK4JarIzON+7/yDN93bE"
    "4anQcsmxoEEyKm/5ydvQ6Z9AW+rRRWoh2e01w8zNdhZsaoF57haL+3Q7fC054cAHPJO7OT3cjCuXebkUU6Rm6ISCrdofqS7C/J7s"
    "X/jAaIr45OpY0jarMxAoFnqpDcKpdmevD3U3MJ0OaqEhiFfJbnV0Soa2NMMUM2vCeClxmUr3HiCTrsq2i//Fm2nwH1+OleQyydyp"
    "M0mRQKnU2bfrCbAyQAtA2DO1BUa9QaM8ACPxHVLoO+RbNXs2SXZnUokY5Lko3ReTQh/C5hYfgvQZUAOW0GXI8SualckwObqH4GqG"
    "4c5fiN0kzD9EQfH8FO1ztDqbDOTag5YGncSMEFGqjiAOaRrzsV6wvV1cIpkIzMfWs3GcGkv0LgQSKizWT/05aAV7F+GBgQTNWDfG"
    "/0+FxrKwOTnwmDXcJ1+09cjWujHq+0g+iB3awDZ8TRoeOnwmyE8hqZ74Z7GmyRcB8jnSq+o0YmXtoOgH7ck0hvZksmhP5m6skJLE"
    "nsxI3pORwvzverOo5zEmNzZ5s/pCZ1dCZ73aGT6Akz7AuyCjcMWqtklagZO9Wj44PqQ7dxjh8v2a7itS9lDpD083yVMJPOle2NBn"
    "0IwcKBCMmVNKexvBTzKMN2RjqVRb/W8haVP/jhTby6Jf7NrHr5yhhM3Uy3cMAyLpzO/o5cnDTkrjG1XrzKwweQwCh8/8jgHGF41G"
    "2NsPOym/r2DF3bR1XMORNuDjN3XtYy7U+Pow9z49kjmN4sRNJ7r2kf2T9MIqBRGU/nsIbab030L6/8Dy0V/nnpxIPUMTWtMLhOc0"
    "vYEWScfwkjfueP5D8ogOSDc4RWTgGLUBVIsqMhj3jyvvHuiLOrZcHeSLOoyAQAOtHiLwwz92auArSSPA/+Ozeod8lkn6H58VGLUf"
    "MXBT11Ib1SDq/pjAdDO57z9KGQk+atQBstwPZWE0wuNI6H52oG11x1BMYMcLWnwsnvsOzeJj+G7fpxMJWqB8DdUhD/qSAVklM0TZ"
    "1JKztP1fUO0E5gG0EblNEiWljDfxgtTzOBUnvxH1DbimV/ZsXtP8ONkxzW1+fAGu5+5ph5e+J6ccTydwNqAK/DgxWFMJ6fFhWiEy"
    "SgHOAxseVu/86wC/UMJnV1PMAjCsaiL3DCVBYwwGfQ1M59ccUF6BVu5a88vjwsiyQ/0XEWMhBJYdM4uD4lYqqdu4DdAHi6ftl7N0"
    "ibXoUSqlfCN6Fz+2rkaiIyhN7cRTWxG+nNHVVPZ/bmdgM6vas08gs8IfrHwrFefMaK1PtNQwwEdOklihHrhMgjlTxdVr4mqauHpR"
    "XGWIq+fEVba42iqucsXVY+JqaSZ9HQpYSwGuGDVtYrBgN5fDqGpsSQgVxVIdoM8gwdcw+/KA4i0R8BKBCQOgKzY/jHsnlai3/wWC"
    "NsZlk+LAR0ioK2b3bPjrl6gL/jwgkQnsp3SGrHjVWnQehEKLcolRW8cLKAkTHrGfz0sGVDKiupOj1Azy7gW1PLhBqV6Vp6E+lQSO"
    "lU+l407TV9SmyhP5wiwu4vnCyhfuTJJAm6S2sJOqPzyRM0lQJ8XA+ZpPyHEnaQdVDU5iB7WClnC68c3vZmFRTlJ8r2h+aCw7qTZZ"
    "at5h2Bu6x0nt3VLzOlXHA4QdPJ1uVyt76JQEOKfq9/ma0+P2WsbXlDTnV83rYW0SP0wdmcCIfw+Wb16JhYJIcFuPaLvIAtVTKTdY"
    "icdEhyrxtMGV+MGeYCUeR5X41t5vV2IM/ZhPECMQFG7LgxgcJRUPCG3m+kUh5SQrLDOEwtLizoCV0Ax3pg4zaT3BQ8cBbAFWcNZc"
    "yZQrjyx0dfhNha5v/IZCV2dg1HH6opGeBDxtCVTnz3TQDIVV588S1EiijkHgBo7TFUsE/u36QnDwiuc39vuiYfurmfBspenuNLj2"
    "atmQxye/LVnnS6b518iA2xyBt/SPUkf2Z2AcwbDECxA6zReqD9pyo8iX6rsYlIRIEzv6V9ykFc1YENmzMxwKRjFzwRgaNZjd/aTQ"
    "T1F/j4O2u8tPq/5tUDmJt9UxUuge6hNuJnIizHlbyJalS7ywYRq/q2aNDXXnMpM8wzVMfWSc8AOk67HlzwM30ZsDu5j/yBfgMHA+"
    "KDsZyDEFG2AKw8hg6OXENR+2oLlMmlnzGqO57yn0p02pnyAfeMpdY4PeaVe/pTdbbw76hsFz4Ti9wcoIzb83QLYK0WrEWE3hRxs1"
    "38MbIOzvY4XC2lN53B2wW2CRi7ee9g9KknrDN8n2EuZSRg4J19G2PEw7ydWsMwelutS92aST05G5hykhIPihFDgsob8YluZpxRDu"
    "KTsBQKAcNnFXp/BM8oQOqLDLzIXinSlRaVyheBF38xT/Y0rlceg68YDUMewlRzecAv2N3h0LgqRkkbHtrimlXZeUw42fhRsaWQWI"
    "ue+j83w303JyCqAslUixlQIHD+k7XjPf5NG7udIkKsNBeEFvtm/9Dc12QKCbAs328GGEtQ56ddzk/7TxdDhMPkRdOOz+bOLqg8EP"
    "1pxtMupL1OYrrNaUjUNtOZFxQhMKe03/jtM0rLmqG5/BBg4qsPtSDq0JZawMe+GyVGGqvrQQSqXNk9Qr7aHKypr0oy8EKyvsxXyZ"
    "YbQCKjN758JyNHrjCDhA37ARztDxto0R7soE24ZJ6hvfSuCngxLoYaA+q76k4j6v8VcVbah0m+DDBRYdOFIsVxppi77q0fBc94Fe"
    "O1aAja6V25d09dS+L4/wVj+MIt3+OnHkcUgs8uHuCYPXdKV1PHI+91sPHjvowdXCNtjQrT3DU2ka/JjlXYEBj3mTH0MhJjxjMzCl"
    "TN5q8kENZsD7aMC1ElrKFrqxuPz7CEw+jon5diiCDPAODfNmG85hba18rDRud6s5446BsqgdOkUDsfWN/Hh7saHbFT/yY0CBfuyh"
    "nSB4eyuXEXrAlTHyckmBul8LjR8U+icKRQoJysfbDd0jP1bvrSOwrG6nekRD89CwuBJ/I5AwsTRTvxocFR6M6oWrvmdQ1Fc7NLy/"
    "3u2cT2yYwOyYfU3MIz/Ohb+inrYIHNhJOYqsAawdWfE43pHGICogj0uXu6XRhGCo6rVnAtStg3MKS8sPli8h88j7y3V70VncEybs"
    "mnq9jmfRkZykIVdUY2pAy4rVXPLfL7W1WGrIxXcntyD2/fDWUePx3zqg6Xg2mZrtSbpm++Rhzfabh6EVKTF0Q3Ujt7PGdR+sSq98"
    "z1JzhRtIKyV6gU7TvIuhlbKhBQsk6e6KMMI9y/Ev4lb8lkED28rzmv8+qAl7t3Iebv5W861akVQ1MBOhhr7uWE56Jt1Z8d/+CIXP"
    "3A+2wZdi8/fJn8dEu7rFwIKXCuoNcDtbAN/56AIBwY7HZ6BHYhujQaOCcASKqDeAgr6/81ueK/IMJwGanOTAIaltrttB2CttFT9F"
    "136RUpjOCUTQtD+aXL0jqvKNVf516Oeqaz+BX3TnYvizNuXSxp+74Rt8n7agNaY0F7O/2SWhvE3zzJocENjwMqViB8cD9BtGnJr6"
    "c3VwnlaS9yBH/mEk1xJBH3uuu8dgefJ7tK3LHzcw6gTtFjf4h5NCot+RCe1Yna9Rr5cnroFSkny4mBjaCuJjKzD5rMltQWakuxy9"
    "IEfyPIj9PtTjXi0N6DAAbSL4kgDb0B4iMxJsRgVNzGcXR1OZRABGrzelTqfESqic+kCKOpIYUuNpJPb+yCrFYBFtOJxqTlPv+znm"
    "+vlEhC2uZ/+csY+mYB6wylI7kbqe1Wb3FVqrp4DAHbpT/C9MSvQU9krLvNnfB5/943FgIFz6uFUxIDIO8GUfqUfzqQnRY/UV2VsW"
    "0hYHsqGo8rtVFciKlMTZGpCNAz8bnI09P+NsxBP2NPEXUObpff3NyMiU6nTyHZNvc2dWPUNz4BvL6ahOsDPvFb6UFUv5KXD0wECJ"
    "CGJnXJg0Vf1BPpf51PRyszSyXBTPh8oBdY0WTrs4nlzzt/M2VctbMedtpppA1wtMykc+I250/8jcZ6khO0Qtxbdf4/FsHOJ8o4hZ"
    "A/o23pD+wRlygayF9fAt6eHxmN2C/QswScQJ8bhKHkwi0EDdfjcWYPJBNgSm+3nPNo5RvX5JpFzdhIcY+N+m0xhKJ7Tzu75Wx2sU"
    "eKreno5qKP0vk9o7MKm4UKZmP9GfKUov7n+b3qtBW+dE6lf/3UvTeKWMAFb+HQRYudlHU9h+l6wrz4Y2yAuDSrk0qNZuGC5mZ4Xq"
    "bx9hnVwbHMejlfW97rNRsBwgA8CQunQy+/i3ydbCkqAi7gzvPwPB+9fIRBOMRMtMhBNoVE9bQhMRK6Z5r+TOsbzizIaTtKeoWxaO"
    "ge4HO3SFJbDh8IKI0HVXAaZ2aKxQPFvnMGhEjsnpuht2JSKwByCs0d3UtbhSQ4GntECr0zUtFHiE4VqdFB7ndE0Phb+qCcc7XTNC"
    "gS8gsNgFTWNvdLcI+YkmBi/R20Jilf1pJjldyaHwBzXhKU7X1FCgUwuc6nTdHgq0aYEpTtcdocCb+5Od5nTdGQqP1YQTnK6UUOAl"
    "uwhMc7qyQ4EntcAMp8sRCjxsDyVrd7pyQuGvaMLZTte8UOBvtMBcpys3FOjVAhc6XfNDgZv6k4WJ5r2h8BWa8P1O14JQ4AItcLHT"
    "tTAUOEMLXOp05YUCb+xPdoXTlR8Kj9KEVzpd94UCO2aLwHKnKy0U+G8t8GGnKz0UeGh2KNk1TtfMUPhfNWHJ6bKFAn+lBW5yujJC"
    "gXVaYIXTlRkKXB9KljHHna5ZoajFQv7xGg6fHQq3a+F1HA4/2d5CAtxSp2jhT3J4Vkje2v+IrRw1JxT1zSxxyzMcPjcU/qkWvo3D"
    "p4TC39LCn+XwW0Phf5wVesTzHDUR46ZW/7VbXuDwxFD4D7VwwvF1lhusZEGmRS3Xol7iqChS/5d10zsSz8+c4KPQaXmeI7QkmNRo"
    "1vKw+iVLZKicG2h7bYNJ3cNHs/oSH63qLj7Gqc/zMV7dRscZ6o/5MlH18DFJrebjFPVRPk5V1/IxhSF8Axumqd/hI5DU+JimFvAx"
    "Q53PYH32wAa7OouDstUZfMxV7+DjQvVmPjrVCXy8Xx3Nx8VqLB+XqhF8XKH2naLjSrWTj+XqWT4+rJ7i4xr1X3yU1GN83KS+x8cK"
    "tfmUyAJv6ql7KHQ31SD1j3xax0wefEr1RP05n1K9UJ/k02dYxcCn9PXVDXxKH1xdzaf0gdUVfPoCu83xKX1G9V5+9tRlRJfBhAfu"
    "LYm615mhIzP163JCL3cUqS91C80mhj3a08oCju2ky4wvDbv0u/sIGE9/imEIPvP8ieDeYUF4sbpF8H3AFMusMVGw6tFzj+BXCXFj"
    "TFcibOHMbAK95atfsiIToK5PaiG/5RCYS0zf+pGgnPhPClkWNKvEiEMW/usTSgCtDBwM+Yb09fHyCFrnyt0tDhOl7JtJqogU6My+"
    "7KLZBKEcYz1IcAt230aarf3tDVZ7lrqMF/9LreoidEFs1JFPWDTZyd1Ej/Qf8aTgOULlhyGutIt388jQMgErCJK7TOZlcrd64SQV"
    "B4z+xpL+OwX6TssrP5pV7IoFx5HqArLU7TYy0+3gkc8SDIxHYBQFYuCz8sAownUM254R7eiQAKG0nzdn3gv4n8JKTdH5R9Sbqi6l"
    "VIyoupS+JabKl1Jnslel6WSf/56qSzYZBjMAtam31MUqXYRsc8H/OcAoifsCiz0A5lIxE5Z4DJUuFVouFnDdqQezEMmYNmE4cQta"
    "EmU6MwwAyOWY4tY4TCayGhTYBn9jEplLwLYLcGGqZ7/gMgBwAt9OgB58Ez3Yzaw2AgUjWA82w83GFv6M9tlf+oIrgtUWvk0LeU6E"
    "xNnCn9VCnhQh8bbw57WQH4qQBFv4C1pIuQhJtIXv0kKKOWRDkm36i1qFyv6iv0JZiZ3ABOSBdBBU0X5+O7bT5VHpmxNgR0hKrO7X"
    "uUbNCNNq1E8JXw4ASWgcXJ3kMK4cGQhmJ/duOapQ/fxzqj9tnjSkCtBuPYuMCYr0ysML1Tc/F1XnFRZ935NmeWVDmncupjujiqkn"
    "RT0QSJveuZjtxAXDTqZx1zsXM53RwbBWLQwTnRuCYW+kBTv8uZhUxAeD/0sTxWTHGQz7sRaGiU5BMKxSC8M8Z2yx1rE/1J/krU7X"
    "mGKyXseotkgTvc3puj8oOksLS3a6ioJht2lhmCUVB8NG9yd5u9NVEgwO3CNE73C6FgXD/FrYnU5XYTDso3tEQ2mRkgrVF6AvK1TL"
    "PxPFuoKPvepixvmz+goIRn9uwrVbz6RrtB50Enu5/fTARgHGCbIpnCozGwtG43e+0bPACMAUO2wZuj1zqU6gMqHm6KVwIPEAv14Q"
    "NrWgLooeUeNzapEmOUO7M/EaE9Pv2qiv5qb1XFuwPXEC1J74Rs9zAxoT1+HcEEh9LxTrVJ/Tl8WhezwK5SjUxJ4yMJa3eeQ9nrI3"
    "LDXRBlqwG9Pj5UTweuWklBsxfIMObA/G9SdmMIUmVAu1b4hq/SBss11hb1ahBqODOqr+J13rcXpCrQ+enlS38Gm5njo/x3F1DVNU"
    "APMTtpNtlpq1YaSbPmGpKQ8j5hqQeXAAYO1L+OS4pSaf/VuOeuKJg6KtzmiyZ5KRXMUF8svHdCEwql1z8khiDx013PLE2DCCenao"
    "ML+Ammrz7WllZ6UpXse5etPMt6WJlt2bAoSbEI30mo2WRMtu0zzbpc3n7fa0xQH5E/iswe5+gzGcHuMs1zGGN1Bf9sNiX92TrBEh"
    "WGr+zv4hMGFpI+k3SQ1SUt1IQF0FJXbtvg1xhWpeJcPA0i2PsSLyOKdOgiXw6Whj4TBNOLFfuIjVpa168qeFNrjouLeuj/G2x3jy"
    "DnifpilC3fItdQ9sqUNAg7eeeRrz3qkbs/leel+HN+8cDG/qh8/8QEq37J6PV37fdmjLjd5ncilrWM0VnVjVEqarypoD90C47J60"
    "7B5hO7RZxTtlZaWVBnCz3MjcDtC5IX8ACs/4CB9zi/cJLhnsAX5Edq7HEVJHIRAYRyFMVoWXwHC/oL8aD2YNO/EpCQ5iDTvIQUHW"
    "sNc/pdrOrGEvfcrtFJVAY2bgB4CfxcNbySAo8XDSoG7xcJKK4x0PJwRtn+fxF9k3tE196FPq7JuA+CEfVZdS8vIJ9X4+nlQX8vG4"
    "mo1j6id42lz/2969DcFpS7B9eiZ6nqNHtfCTc2WoLfmJrY/SGT3S+SM6YyBQbopo54Jz4JbaABa66r8/I2cOJethWzjvnVqVUQxU"
    "X7BGDlebn0Gk3ahtwkkj3KqpOu3TTwkF3an+7gSbGUBz8KYdOgB3xjf7P6JNrwle4zcNNGKnscYtkOJuiVeLp2nQZuYcd19Sxfvo"
    "eqAmcCexJGnYzsOYSSVjpr0UAq9XKPZGujdjQySmJPBBiWrD08BmV+puNoHhCzmsOMGSyxlZOookZYz+H/THn1q2RHDxmgLT3iJR"
    "sa/COJh2Uk7MgfqGzAXAnflJ+nhSGsB66pmpbD319W1B66nRL3DfBpCtaZzZ9Amwnmrx/8AVr178mr5gN0xwLGrB8X4jJ38BdmxK"
    "ddqu2AR5KhdEiVqQqm0F3VCirv6ENqDHhe5C5+eP9swifF3nJwO2q4O7KB8DVRuYzeptbNwh3qvYK14MxGfEnpckXHqxgT1cHb2T"
    "tllniH0lMAff/gL6UuAGqkYAlalApMkltPmmPcQ337RnBP8aTfQ7nM5pzv0P6iOV9qLUgHdZQkmheh+MycFq6dkMWkpArHs3W//w"
    "hz+wvQTURMnN9eb4uui5eXKX96nxuHEv1bf6OH3d8Kx8uYtn1eQOu7KH3GETBrrDbsMDCzHPrBnYe75JtwPziMuzriZ8G7JvB+1Q"
    "R72jvqahuZauE6Vkb5li2X3AsttgO7BxdHKj3el9JoaiXImL1F8z0o95br1hLqyqj0PjtgEOFNuISqbEywk4GVxbvplp0BCO0DDq"
    "BIPRJbijUB2/iXqPbE1AP1BA6ych1L2Ru5jUBssrCx3b4FIrxVYtjBhvrX8ynNL0Dycf5lEUlEhBSKXuyQgqJ7+puYZP+PUa/Xne"
    "x+kKjLO/JkqSg7c6qpSiKm9NLIUaWr0PJLp7xmw0Vy2MReJHqvYlAm7n8piNsRSQiICvEuusfoJEzLIdXveW4qXSZcaYe6rJpe1Z"
    "I7u0mctXUAuwQxOnfkr9XLdgw5u3Rhrv3gI2vBuUjeUaEd7bz7O9iLrYRzUwRq2izT6229hYDjUcILCI42IGpsljiweYcPQJE45i"
    "tfo4OTqQkGdeucLSuK1YGNgMgkp+ivRzMeq8Xq2KC1q0QuJSWEs6wr4+z/itfjTTCS3hdNQzpUQ3kkkDMYZDI03wZ7j7rsgjBop0"
    "sGeJu68XsFhYmNiN/ZH+/XQvLK+7GZe3OThRSRwwUcHmHs+81XKyo2EqGlqixYLY5ANWcPoepOkEKEka0vckUml8D87r7oaUzHY8"
    "YZ2fZgYl/fOCW8kQiRoX5ruwMOw6jCTen0OMWEWq50dGz3qz5fFugh2uPKsT7Bxe+Vx9bM1BQa5j2Z1D0wUfAe4OSOalw0QocxLJ"
    "rD4Ix6o2719SREn7b4M5MgEFWnbPAr+GH0XQVl+VgEhTtm08UtPPs3Vv+Aq77DkMMHpEIaxAMPGY4EsC4MeT63xKC/LVMpepudW/"
    "kKlhhGcuNl6tXk8S0nlglXJX1ipPSpbdfi/mpRfVESgV35f4sFULDeONdlvjhk6kvTkAop1pKELv3AmvMr2QyWSfL18CRaS6lMwj"
    "55o9hSbwcWOvowGbGuhe/H9Nn05fylK7tY+3XULDV/lmGr6AS1BFFXkjKQuA+6FaP6EvhB1/NR7VVFleju/GWMkENz/XiHkcFX4i"
    "mqQ6nTz7icDIUpODwFdJm4EqTZNn9yQdezpeuMJYf7RxbqntZT/0E9CfhGo5YMbLM0U9d6rbPyR0gGXlhYLXM/ARMd0IziSN7cZS"
    "+yktz2PUzMvBJjTXuPN5PzOY73yBj+adu/xzGNjvpLs7vNK6Slk417rKY3Y8g2C7X+WYTPrslTH1C+MT6uqsn1CET0RQna5ErxNP"
    "3UVdXfwJijsV4FYXyvZIbo2hjLcdpYyPp7DCwEeD2CxTkNk9hEbY5J9MyAuJ1T3irkL193SX+sCRoC4fnFrYQySQ9zuhkYAHmpMY"
    "HuD8dUUtZu6EcAoQkxCeUJBhTdMgA9iYI4MMYL+sCRrAZoYMYONhANuaNlYyzrlPxsArna2PrRsGY9i3+41h49W3WvuNYV8OGcMK"
    "f5dijSYNfzD5Jlv+sGE0f9int/zBmOQ/j/riPhhAOMw76yM4qllv2WlMWn8WXPf7EwU0N6/EyeEvroSw/2Uruf6N4EeVNYGLB0j7"
    "Zn6lma2DXmlE6JU+xL14nwnAdy2y2j7g0yMwYYBZh2ypH4a13hy81AS8lH9M6NJ0nxQeyIuTz9LNYXXxeF+F7gEOiMPsctYtjQgs"
    "9m3C16uboDYc7i+ExxhNHAVuRz4rcopLMGWahVsMTfD4xh6Jw3Skz5vRHrgHVgmBFHXDOg3zdBhs3oF+4kn3R1dG5HtkM2CIl+lt"
    "ZebNe9EKD9YS5OYSpVGz7jf3d5mC0PUugkqeWr6ilkg21xwVRCFg/FjKAcu1AHmyy0SmAa5of7Q443VeYGNCYJRurbA89codxeq9"
    "v6IGm9dLDtoP/ZCaP7jfyERrla0uF0lK0XYQwMWt82vW49C9+SfVN079zpyM8I3hVY3/9EfjKgsXhqrGS5a9jY2njF4porV+WM1B"
    "+SOyiIQP1rA5VZeyKoCQ8cBmk4CZ32hAsxNvWDHgDYmTSd1xjNSPykfVzazUrOfxwbWJJjNQB9GG9eRwmIKEh1l5OqG9jxxxY47J"
    "7r9bm/OoERr/qDwK5AoaLsswd77JyLwF4OQ2AfS1qxU06tT90eu7YFp7MMgPNTBX2rMdpsmERODSxxBmgpPQNrRHkxP8Hd6iGvVf"
    "aJTp4F+aQIwpwJKeUaIcU3tIYwpT1SZyTrR1L5eOEOS1KPLOTVTk336i4JJVt304qCCqSYUxnh75PxUHsX6a3atMBBzo+y6NZFqB"
    "fPNIEEGXsCOCCVg5gTBKQB9KQHqTb5qhNmr3yOZqlBwRqW6O9y/qzDGFyfdBfQfJqU5NdPjaIP/cmMAMlHMYylltRUu15ZhL5Rvp"
    "xgRsDnfu08txJerPr4gvEuU+pPcUY/KboOSb9ugMhC9tA/Pnc9fLoqUmngY98eyxj7ClGM3T70RGaQKZvsyKTywNi6HeEfxi/nnp"
    "y8ySDcIZwTzd4dL7EyAnT6OoO7W03vuB9soTwBD2nnruitbCLJQwgUcsi4fx3VUViMfPKRuvUYP4cx78YNDn/GvvwHp99UsOrtdL"
    "tOzdGcxeVHqOVYZCEs4mm8HHkOLejBp3myYVFZQa46SXuC34EloDiKfyvroBPLRBZB8J3HCY+SHdqkHQO+ZYVSOCtGv3Kjgy02Mx"
    "jufESeGusMX+SGW0OryX9UB/ewomtTnmwCgj1dUc0yp4PEjD8BsmGXdFwqANtbMJD/nre6EU7UjI2p/QgR5OyL11QEKodUbtXlpJ"
    "qT/EUgSeO3FKe+onokhtflFP8ZV8f2GOQbutyYvV1R2eSCkObMKgUBtdvrWGJumXhSdSBPjSlpmkBYicx0qAaJxFqpf7GFJ5MQqB"
    "DDArQJdcXvcY+TqL+1DxlyuzMVRGp02E+Nskns/djH8eh9+B8NtK1NZ3tTcsHdfg0tvL/+ClF4ob8ELxeLx/ZEsO5zowqpf0Dzkg"
    "6kXFNImlmvJu9VukPmGI9XeVPvXkJdJA0xSLdBHVPeoVWtXt53Mfn+9hFrQm6DPMa8X0mOa1RP0ZD8cDLeinwraGgHtHrlLy41d5"
    "gDGZn7DKA8RMz2IjJhAJUBesXlWdFmdSbqfKKE8uX4khwWUvUZ9+J1gONwUpUp/+kUDfGI74cqrD9LQPIXG7y+6dB/1XGIclcNgY"
    "cCJZq1vovbAKNguaW7JSDtN2i2hWgVZjVVpgcGyp+RIoCIDhfVcctonDfHF4NY6he9E/F7oSH/CtIyTfFNtdUoVld4pl95jki9Io"
    "9A2dll83eZeOCygXcVr7kJHm/Gv0lt2l+iEFcoVAGATChhS4RQgYIGCAwPBBAsTOS0JhlJc1Rttao7QZwkYIG4dM7Z8GTi0cAuFD"
    "CuwRAhEQiBhS4OdCIBICkdfMzzoCSFpjsq01cX5MEDYNmdp8kVoUBKKGFJgiBIZBYNiQApFCAGAXpdHXzM/npPddY7atNXN+zBA2"
    "D5naq2GcWgwEYoYU2CYEYiEQO6TARiEAyqVSyzXzs4jzY7WttVJ+Sq24wTpkareK1IZDaPiQAiYhMAICI4YUOK1ngZEQGHnN/JB7"
    "lLImzrY2jssHBD6lcUOmtl2kNgoCo4YU2CQERkNg9JACJUIAaMKlN1wzP3dzfuJta+M5P/EQjh8ytSiR2hgIDN0AVV50rxkLgbFD"
    "CrQIgXEQGHfN/BCxtrImwbY2QVoH4QQIJ1wlDJVLJSKxKi8dP1TkCkROQOSEoSLnIhKbCaUTr5EH+SbDPsOh5Mu2yxb34xi1DC2G"
    "w+7ARMsTH6P+B5L+0fw7eDw3+96jhuc8aSs4Ka217L5g2V1wMvkCEnyfEtznvX9EQLmAxD7E075E5JdDRe5B5ClEnhoq8peIPI3I"
    "01dFBstqA82jYZdUoEqVIgsqZEd9KyFLLZFNIDEfBHxDCtwuBL6CwFdDCpiFgB8C/mtm5zTzWp+xFZwJZufMkIm92ceJfQ2Br4cU"
    "eE4InIXA2SEFKoXAOQicu2Z2FnN22m0F7cHstA+ZWIpI7DwEzg8pYBEClMKFIQXOMoPpmosQuHjN7BwkRYuzw1bQQQ2toAM3dAyZ"
    "2vMitW8g9M2QAluEQCcEOocUWCYEuiDQdc38pHN+um0F3cHi6R4yseEisUsQuDSkAJHeQ+AyBC4PKXBYCPRAoOea2fk9zZ2dvbaC"
    "XukRkZ1eyFoGyMKwfwaSuYKoK1dHoVdZ04eoPkSNHBSFfYh9fnQV9gBtpyU3IgO0JP91o3dhVAB0OYxQS4weS3yF5FTo/MJW8EWw"
    "TL4Y8o2u9PAbndQa/dUCJ4RAsOFfLfC6EBi68QfL5Gc9VCanbQWng9k5PWRiPxCJqdfsAPJ6rtMBTO0Z1AEMnZ1Izo7fVuAPZsc/"
    "ZGL/vsyJnblmB7D38nU6gF9dHtQBDJ2dTZcpO+dsBeeC2Tk3ZGJOkVj7NTuAOy9fpwOIvTyoAxg6Oz6awzsv2gouBrNzccjEGi9x"
    "Yh3UBwzd/i9dr/1fGtT+h87OA5ydLltBF3c3XdQfDJnaXSK17mt2ANZL1+kAznUP6gCGzs8hskBz9tgKeoLF0zNkYr8RifVqHcDV"
    "AtVCINgNXC2wQggEO4Ohs2NjIdpdt6NLgLsKbVAM7BZ8Z7m2f24r+DyY4c+HfNz5Ln7cF9fsLFq7rtNZ/LlrUGcxdIbryezNecpW"
    "cCqYnVNDJvZdkdjpa3YWWV3X6SwSuwZ1FkNnp6eTsvOVreCrYHaGnjh80Dlo4nC1wF87r9NZ/LhzUGcxdHYe5uyctRWcDWZn6IlD"
    "duegicPVApM6r9NZhHUO6iyGzs6nZFHmvGAruBDMztATh79/M2jicLXAM99cp7NY/82gzmLo7ORzdjptBZ3cF3RS5zFkapM5tf+h"
    "szAKgW7qMIYU+KKDBS5Rh3HN/OztoPxcthVcDhbP0BOHn3UMmjhcLSB3XKezuL9jUGcxdHbuhNAqxdm3ylYAj5YOrv44QxeSfMFS"
    "c4xcrAfOJyy1I6ED8O3l/uEzW8FnXKifQf6zodv/Rc7D59fsQf588To9yFMXB/UgQ7/FQwQ36vzSVvBlsFCHnnlkXRw08xii/V+8"
    "Tg8SuDCoBxk6Ox9foOz4bAW+YHaGnnn89cJ1lh4/vnCdHmTNhUE9yNDZWcDZ+dpW8HUwO0PPPCZduM7SI+zCdXqQz84P6kGGzs4b"
    "5yk7520F57nynKceZcjUfnr+OmuPdeev04UUnB/UhQydn6mcn29sBd8Ei2foqYfx/HWWHl+0D1p6XC2wr33QdGPo7PyqnbJzyVZw"
    "KZidoWcecvt1lh73t1+nB0ltH9SDDJ2d2PaBvYil5tOruoSaQ9Qb7PO9So0wDyal0HtBEzk6eR8/syGY5D7aIf+a9SBZiC/WDynw"
    "jhCAprI4bEiBPwgBaCrzDTR7IYSywbMXj+B5HZiR4d9KRi4fkImrIheIDOSH+Z+7XjqJIp18vW8NI2jCbBbSyGCUb3mAcUBgWaUE"
    "Hnw2S1fyfJbuP+CwVbMrS6f+Euh5v87SHd2Zpfvmt1m6Ulyn4Tob16twffAXWbrfPZel+/tvsnTH/jtLNxPXY3F9M67n4foP26GH"
    "+VWW7uc7gET3X1m6BFz34hkmXN+K6+3bsnTfx/WjeOZ2PJNpZvp3cHa8CEuBwmLaXQdmpDyTPLLhA1Bcvom2XQOj4sSeqskznQT9"
    "GheWu3uTPAx7Gjs5MJwTgRetsD8hS9gWnQDJZ3VYelm8p6wb0E2RMKbxwC98usSOsulliYQRbYWrH8HaGgl8nfir42GWj+16Sw19"
    "4M0ZwHcB1O3Gad7s2aZM2qHcOFJdAWsBZT+2NRJagI9JJlNONeZv2P9qwtZbi46sDoF/R5sJ0kNe42ynS1eovvEiq/ZLNIRmIsCO"
    "Z6gjYgQk8h6TeF2Yuheq97B1aHepX4ZPRlmCyDycxxPwMv1vEgAtjrNYI4WhzdJ5NpBQTiiEFZIVpDxmehl1QzFZxoFJEFv9INQx"
    "DySpQQJwkMRDbReVbrZ/+httW7d4HzxDnr20l6r+YUloK9XKXPDt6lbC6JGTcAorC0qDOBm1VNWxzM+SUAU2cpgWCDMnQS9ERiSw"
    "T7LCT5qYI35BH6nHWLJO9v6otzaw4Qdis6GeKMUAbAWI5EUzC3rlvHrnFZxnzCy4It9T7+zD+c0zC/rkG+udAZxbZ+JNo92OXrhp"
    "967b558d1DH4c3CGCcT8Pn8GztBvzL/ivxtn6Gbm9/qniKf5LfUExhw3c7hstWdp5K+wP1gO2yrRfJIb/Rf+9/YYSoANMcxBQ4zz"
    "3pxAyBKjQDPFsF0sAfFpmXljotr8J7K5KGWLC+U8IBGf/W4Q6Ppdtqa0whu1SRpTrwOG2khX2HJiiX6csNvrInKaI2bmEAfs20qj"
    "ZE8bI2XAMBkIhkXmebbLcLJY/2i9tW50jj0tXlaBvrsbFaFel3En9iutYGuGEOCxi5sjluaI20B93CSN8IvwWfWmuli+FRYXCYi4"
    "he2/b6y6dIcUzxIJzRF35GjS1n5put4wHCUL2xbfH8mswzeBjTwGWtZTRaGKNE+mPp36qnbFc4B314xZkwkn+VvVh12QgTMeYDTo"
    "AnI0N5M1Lwon4YqVwJoi5rkDN1Scx4/FTa5IRS6DKpdwNwCyj7vIVcSgriwRKIAxGugNdrsJObaHzKUsNbPJ3CpemaN7PQ5q5cJ/"
    "vIRupUjtfSm4JadhPfQt5y9UTjuLew/6GRe6OfxdgsLG5rKwWrq5XId0ynvCCL/ptVAKluCm3msijWI1AlBQMATJKN2QVqxeIsGz"
    "NkOzy/Dq/rO4v7d+ji75AGzDp59geeotiA+BsrFRJEHDY3k35AqL1EWffCurhUImMO1K3L9YIuXbEndpL2NN1OvKW+vphXfczxYH"
    "/lRXh4ZeoAKFcbL7SgA0BoCvSYpzekWC2GvOeYlh02YUCUKEMnxjkMoY1MtFouilUbj4ukgU+8Qg1tDocipxdRq6CmG4zHBhZKC9"
    "Z82rwI6iHxuYKdZb2GI6DLBNzUZb17rz7P69ZxPJbPofZWAI/MoBkcVUFDHRIgWmlHoi1qmIDuKxG1dVp+c9wMbFSlaGobE6jRHF"
    "21MPrqreFB+tFyS2QfxjQvPJzTAcsLySFVdYbHllbQRNP0q82ab4DRPILgzsQLZL66LA5mz4p60HaLX79ICysB1bd0rYdQHD7Hky"
    "ANywl2gDe4EfCITyRer6gMDZzkSjSd7nXKT+hGs5QpIVe1KjOpGNCYJkw4nX4BHW4kF8vHQv2b6ayhvoWcNwof72r2QavwkpjmbK"
    "2lZ/5GCMCPUXhAU6iW5Uf8jCFaJIfS8TrIipvI3S2vsPwpqgiqkueEnk+Rrp+SoJkeBPf8H84u+EZ7aTbmoSHHNwPPyLhvAWS6MQ"
    "41/78mgHrHjpDunfZFAPMKdDhenpIK88vvoTs7vRbPjY9va6s6sbzIZ9oCM1pafDg1JTGkvDUOC1n8B6fWB6PTy4hMNkZ4Uw2fmK"
    "A9Di/0Xdav4KT143EaHnrwBqI6H51rIzUEw5ng+bSPo9Yrhk+6gyafVBs7J5qXtlugkRHD2eoucY/o182T6o+JxwVXWZoBVqUDav"
    "lKNaclYSq5R/WSacSxv4mtxV/PmZPw5ek1uqf1bmT4PXtXR9R6Y3eP0YXU/IfDp4TZQH/tjMn9B1JK7ryVB4w0pwVXxQ6tm8ElRa"
    "eMkC4J5ixuDJWQHTU6aiZPTSAyj5ne/QTyv9HKUPwVU5hoq6ON1phBvF+dWdZgM6WCD02prX+fHKBiBRLgPRZzgJoJwBgEr3q4v+"
    "xKxRieW6N3H14uuBgEaxdRwOpO6e6C0LpVFKkyusFCr+m/Bvwv/K5EY5W/31n4W163GgNDAd1Heo/6Ts7aAf/4rAxqXKB+oKhv+D"
    "Qa8S4X9AaXKrFinDrUZIyblSgrrtt0ELzmBH+v0lohf8017K3g768Y/eS++7g378w/bSG++gHw0LzKk+9UcG1i9NbYDRsF7QnaY7"
    "2uRIdFU3yGRpdpJMTbMPEzohEYC4e2DxhJcDAVmPUQbTOWrPUc+8FQiHa859Kz15rS3zVj7JNcwk3yFqESjclRiuSKPo0nAoPe9E"
    "5Rjg/1OFKlnqyR4OgJkT/k/UzhcJbTVEO62lMjGwcWVhoKgNnOQEBgHQL2I+N8EH4Oi79Ak4bnDGhpOrl8hVBHnvzFuJ3iD/NTRq"
    "rgkn6NMXAe7lWXB86fqdGhwrFMfDNDOpgPNO5RpyPTvukVuxhUCwveWMkVzZphzGPGsTPN8CsgSX/vtDk0q5JDgp/6G8upBm1Jsg"
    "Qv5A/8EDCWYV8HCTeFrv5BpDs2tMQmZB9ChIHkv677irP1ngRuqL1crXeVINS8pWD4iS4e5GQIuf7CKTZDKwXiEMxCILUAveWgm8"
    "6/xAQQkeE/5hkLQ9Rhizzl/M9URL4Be7+NP696aXrZF3F7qMb7adJWxEzohTvXtRkHr7F3UT6rFNDYL015wCl+lgfcRfhnX6wpqm"
    "psybVx1QcV9dRMXH/r9wGavB5rXzDJ0xSvCo+LW03LATsm9ceSK1G2mP1m4C00lO7f0942DbumR4+58ErMAaMmlsgTsRg448WSJA"
    "RypP6oE2s1QJ4jxCYkT5NCWEe8ophO+d9koWZh0ZlCZnA1NBbbp/jCDS7tRGEDgbYhC5YeAgUl15gq7hSmESmJxkJh0iZWhT9XsE"
    "Xbn7TBqwS2gxcEB1r6Y4YPKbaRUHP+c0WPrern4Np56BzCL7xTuklR0lB4ZWcmAArf37vlnsqxiHGXNlXFjFAfwmbdmHynhAkPvU"
    "R85z72WPsDpHYHO813HAiQkjhiSn2mIiG/cDNFUZTmHKUzyD3G3McreBuUTeD9ro2+FoDKCzvPgwP5FLJ4OQORJOVCAgD+ChLisM"
    "ehGcgkWbI47Aef3T6yMzNkkxGYs5iEj7/Dd58uLSYcg8liTlOBYwZiyWh81DWkgIyQHYa/sipbuEeKvhD6i+VMBOUspzB9ivsI1I"
    "WovOgOvasrsRU9y5u4ySybL3vPtsiv+GVb8z6AFeBdPfjDGw891ocKuJ3jUHbXLcehu4m5F3ky3vzLqCjXAkb7c51HXgqFLTQQw9"
    "EsFybGqDzXFyXerGcJvctmEqpI2AddPJNkznA3ndQMPKwkrXYZUiaLSDJy2hknX4niZPS4aePlGi/iSDFBeG5pFHKLYI7NDd9aBP"
    "o0Ly5eLL7zLuJbYXctevkm8BYfn97rYwKSa9rGPjmHVAkWvXbRyOOe+sdLljXTrh2bUHNtylngEkWqcjXt+iu4kwh4e5sVp053UE"
    "/KMRGoZV04PtKKMODF6IAKIe6lBtwzJy7u32mFhkJPm/5HV0HXcfgZUe5Q3k6ZVHdaEKRPFFHcvFqgKvGS4xOUlwdStHljfATdAP"
    "v+tcpvSJ04y/rTtSzmM6zD694C3pRTagIUCF8+vhVZIoXa6PyPiOlJ6xTpqasVGaqN64Y3Bd7r6fU8MadkEYuT+Z9cTQZ3Xn9eo9"
    "ZWZ/NELIUAfXYUAAyKmPmNlUItzVX6Pe9E1M+3S2ty01hIsHBkB3d6Hl6d/wEoRGdnx/S0043a9GS8W50jy3Gi/d6VaHsUucpfaH"
    "ZC1b1m2pPcakwmYQ1hNcsM53BD9RRWYfwZd1Osx2S+3LQsLu201+l452Fvu1iIa7x3/yChOsCn3uA2EeB9bDve623uh9KBJfDWtO"
    "umUJ9ydqT/Cvc6v3Sw+41VgpOxfIocjfaIzNMDoh39ouhxldR3ZUpdl/L+qGPLP6wd7Am0Tq0sE3T6fAyVGVvcGAJO2W4dV5Zlrz"
    "+UdygBWQ6gf9kRQIy0YuPUvtu2QBXtYubQx+IpexuPxhdH3qI4uCBtIrsQAolxSy1/+XM2hg7W4Op5SguPHbyis4snFApIkjwzDd"
    "Kq/jyBeCkaBM5TzAODn4zLQJ0lg17teDK4N/kZiBTCivYm9nK5zoRf1zqs/eoDl+E0o8Td3jAuENqKPkwA6or7x2GIR64j2LTZ7F"
    "CZ5cKy+QAUdlpzHC+VfypuVRAvAIrzST30vZYPbSxoHspfGSU7CXylnenCvubuvGEQTopL72Fk/VhWFqP/Nou8RA+xqxKbOemsF6"
    "mixTcI4fCIz+7zaeCnOlqa+yTiiGJD3GWL7D0IzH5bCnqAJNV6JTvemSWLNwNAigp0Wo03eQLx3flhAB4nVjBEkKL0/x3IwIvBys"
    "ekd4lhs9y82e5Sb4CC9PcN9nDQwEsQdOSt1faBbDJfHhfpr+EP9NiUZtE4elXHzRImdBAUbXEL6dmN7sJwTwlZ7JGuJdCtYKhMaW"
    "OgbmkfDRk2xIY5r7cp9ktF3YcId32gbv0r9ZlWh8HfePjDr5HXZag8eTOgNd+quM4oyLXFz4X1r5NMPSY6bA8LeEX59lJFjtPYy+"
    "nkrA40quKfWA+r1cYjAqjw+sMQfWWANr4tRZgrKhjGXwGp4wskTF/Iwg4JVbA2sTAmvjA2unqKM0QTJ/Ly4pVL7CqPlJ6vuk+ggc"
    "WcJK3a+U80DiBISGk+bFiD2I+EDgFPv+lBD/aXkLyqVALfyuTsdeP0zNsKiA0dNe7tMeYNIJfnfoVLqAfDYVXow8/dDqORyWmVv1"
    "PMNum3e5LTWncLoL3QwtqXaFAQ/xQCLMyn2HGfBXv+p3Zj0uiaN2nJNIDsOJIiuCzJc3gM36zzrmB36nih8P4vAceLzVsOI2IG3p"
    "zDE/Jt9XrHp0GtX8HZgM8nlfqXRTsQqvCB1gHYs1TGP1OxTHSLuGSADohO/ZBRjnersx6bGMx+TI6nyzDtDo1ZvjyYdBjqP8m6QY"
    "mM4baUEVTx2NEhvIhyGxPssT6x/J1vht0ERao3LMcCTWIJYxsWMUYxRPzC8Ho6aezB8ATmy3LhN4LFxQ0gQ8bCyhMt30HPxaV5m7"
    "GDAa2gg4UOC1Qxg81HnkqepdUAFizu+dq2cXuY1wmFKVKk09ttgve8pMjZUmE3lqsvMML2peOKP5Ioyod5hcYXUYvssuNTsuo9yH"
    "pR6sK+tudlzSZSmEhIP6F1hjJBjTAtK3a+g4Y7+iFwA6g2xNA0IOxth2MUnzxwEOoneSw1xV2cE6uXbSyQURZ4rVU6hATrV3tOY0"
    "/yP16UeQUkOirZ110hZ1C1/bcQ0mO7voAYnE2ayX8wuJ/Lcdk1TAnzMDo5xYqM77M7+LJ1IeCew5VxgVU8Ritt83+mOU2eTWPcuz"
    "DDb+RnzZsOHkNdywxC7on90VoHmSbmGiaqaKtkpjilVgb1LJB84iK/CygHc+eTwAraYzy2yXItyPmoALGZhv3BStDK8LC+jJ+dSM"
    "sRm6N2I0LtW4nCOaAhFsQ6+0+0fC4QxlHcgzq69QI50VQDrwT9pyGo2yc57ZjjVVu/JPaZp7C1CW7yAOLn2E//Z6QwDM48ph9TEG"
    "8QTs2Ui1YRvuT7sN7DGHX5qtPkSpVSQhpQ+WCU90Ux95om8KG+CJTkOoUqtjXOFfGcOYn7lE+YeZnLz/TlbS3jzQELd6KrHEetkj"
    "A9KpASOHBzzf8kse+Q31HSj+0uVWzNTnbhM1WVTkYnXsQq7JVZW7eKb1AtUCWq+3mhgUAkMFmjyjmql+GOxw6wQQYKv6KV+hfU6h"
    "KzI4xJFwxwXqqvoPihdtNALM2p1aK+20J23BLiLzU7aq2wYlWT8oyYqrknRdM8kqS+1NRBPzL0vNWBzrR6YerHnfI7/jkbG4fbGu"
    "6DS8QABYPNdd+Q6moXssT36Gq/p9UxMzFm8cbtm7z7K7iiYE7jYLUjWiu22w7K1p3IUgV2Rjt7HUBvTqJy1P/CiSzJFr29/J0pFP"
    "r0eu4/Jt4IJGob/hK42kSd4+zOqkWfBZkW4HMIU0MTeXECoMltqZxI+ep5p8d4kTo2+KONH7JuKkOk+lKaNvpAgM8w3DSdXl2+RE"
    "8nWsPKps6SUH7waL93yEuL+rrMH3ZQQjeqxuGGbZewgKylaPo8HXGsEI4b4DESKF8YNSaLN4/8wptAV8/823tw28vc33Y75tvpRT"
    "dblcSqu6/DAgAi5vtNQ+GsG5JBRg3/dJxvawbJ1LIVZaBO3xLRYZs/ruEyeJvhyc1BsyZsg3VP1IP00ePpfFq4T4rYjMSOWouzkK"
    "WLRboCFBVCxFrbTURNDxIUtNH8bfjEfARkpH2VJzlo6bMC7RcTFUfUTiKz9JOMmW3fucVO0rT/NsqN5xulSCMqbVK7+jXkJ3zMAL"
    "VA9q9hFLuYhoQ4Rve7j4ft0rLU+vY6AHP83Nac5OG4Q0Hc4Ccn+uZM8l+P5cS+192CQE2EGLo47mAahqeGl7Orzcy87soQZL8EGO"
    "bRZvC2MntNGMwRcVxjNoNcUky1pp+h/WAiK1AEDuAO1YDn+VVmP4eBRtNYlPCC9yS83LBHLaB86PCtI/Ed70iRbHGzzpf4pIu1WU"
    "SToehIyW0Y71SiREGX6OIgekJ91ieWVer0CM8DrOYIQ47lQvz2dnIlL6toALnCbwMfXzeuscZ1ocxxna13EGz/QVkEk+aPyMtmZK"
    "6g7oV23vSbdQ4jqT5U3Si0nDmbw5mLcEcoBES6Fdlx2bRNad6hlgAZf6yHXR3b3G8vTjXPQSF/2Dlif9hFfU/T3LU8/T9KX7IQkd"
    "9A+kie7uR2DqHEYLHLUK+aIFvDSfyo+ALezKPaLOq3lraYSx1HxoYNFEKWoVgG9WgZYknABwIrQ39HkMXGXtSGoYb+arq2oPWjxz"
    "mTteKTG6W0y+1biQY6suf0+eh6/JBTML6sTNBrSa6so2Ak3efDtwqKuby/TUvz60i55dX3QazvovSsPwsh55m3LcD1YoFk7tpOID"
    "hHiVMq8XTPIM8y3XoQ4SlFLlUVxs8zqqCkFK04YdDvXNbcxSoVSq2HatPk3dhTQW1U0eRXcWQsVEUtuFVGlpVeXp78ljUE2C0SpF"
    "/zAUbbtdjqYCI4YZ1NRC37o+WsO1mViV8bL/Rre63lKz5gpXnZov+tgTD6auXJlfvkUXKnsrr2gPQqDe8bKxoNlxIKXOcbDFsZ+8"
    "9X1/QfiqrkadFdZHfbxB09mYKI3qbLRTrYmwvDmv12+karjdb0UgikIybIfG/31E41qKtx3bEgfO4+b1sVAQvK/r+ljLNFe0rYCP"
    "74Y5+SdEMVoZFfwuw90Pql3cBoMfSGmJboL344P7dd6/+xlhqi2QBwiFLREUA6hox3FQ+gJs/lMCE21McV9K95RtI3j6zQZD3st1"
    "sfn+d7y1dGdycw4/OozVpyekhUQpo7xXlZ4iZQWgC8470axPgSP1/FUIibDbbe/JHcmOE0e6/RO5zW4KtVl/5Hxgp0nhJPINRJCg"
    "u/Il4Er08Hpd3WWXJrPvZwTK9Hb/iF3iLNlvokk4ztD17OelSllDctnx5LL9+CJmGXYGrYCYhzOfOrOLJ90Beb9SSWGkx7u3i/Q1"
    "qglbdjgYZUtJoSsFcWqMEHZXvkH4W1JBbcPmPGBLUBf2SkQgb5vTFeGtPaNntLOtOc4ctdWh9RTyxHTHVsx85a30DC/JqF/AdNNd"
    "uU1XKjf6R7rz3glgQpd3wkkPOtBJal2MxxWcA4lykEgRSqeWgxdBPUOk6R//hHbQXtSVKmV76kF+XOc4jU+V96RSebS+1TcFZsXq"
    "95/+1laBbxLeY9CkBi1d8dI8SiiR980k0BlSdDBv4mvNWbob38rSZeBfwf9b+H8X/0aE9+If6/QVtE7f9Rtap0PbhxXY8FfEKt1l"
    "WI4R1ZZJy/TKEqULC+n+dXO2WKZLFqeasILeGOsdA2GwBOIqpmgLcm2prAaXyrSe/vLHA9bT8/zPfRt1aeVvaN9Pr778d96i0Q3E"
    "yOaVXmE2ayPEamMKWd10OqxVJS6rAk3rGcB+1pX1od0KhKcTy6UowNs1OwJW/zCt/dSVBWg4UG8za+QHQrf+tV3jRVCd6sVS4YCu"
    "Rb0vovbQ4F7rsMojuhxWnT1SJ4enO85Ixqq8QBX0fi7DA5P2JTcRGXiVNCtXujtXull908vcMrEB9TdexqXgFEEL88MssRB92kg9"
    "TgduwlRdnNgByJIHTWJccos0Hf9T8D8O/5hq2eU/QkOY12F5Bjs63f6xwM/2j4Jei6FDzEEFF+hfoMy1vqbDLGvSvlfJ3MfWuGWW"
    "lArN9p28GpMmZlL/AWdZyGfS8ATnhgD1kO2c1J04MdLJzTihJb1/fCYxGUiWTB1GemmlbR+Q7cUN3EbzrHso3doDDOYmjVBGbcL6"
    "qOv9SUXxNe9vInpD6u5uqM7rIFVUNS2uoeJVw4jApNvIXagUFt1NvedwjjX545A2gxT9prPRyszTOp1VfXo7z6w9EWDo+e6TwcJ1"
    "PEnthODt/bSaJLV+u4CKo1Gfuek7eFs1ca3GYyBPU2YozYJQgVhWgnQ4KcaqxL4ghWDck4S4oipYyep8+1EOGu8B9PJJ/8PtkHqS"
    "8I/2CFKEvECIFCEvYCrBZv52gr+PUFo1Vp3L4Urcf9L9paXQrlcd1NctDDMOFe/NDkuqSqyqy7tS9eCV3Dpo4mupuDsbqyw1f+H5"
    "gjVMWusKcx8O0GPqpaBWAsCjY9RUvEd1Gm3rSnmI7cD2DFu1uPS0ig7MqCvrVb/j0kwraKOgdyyUDI5uYoOfoc7doiUmNWF7bIZ6"
    "ezBx6W+djgAykIIMvErNojbPysphwkg5M6lRDo+qBEBWFHZXHNZJjbghO5MqgXRrps6Ow02ZpLrkqzBxhZVvJK6guRrf7OjT+2+g"
    "6qXX4B/kKISF+Q1o5tQMUccFECMyYfeQQnkXD4Ad1A5B6ppJDcpS8wrXc2qZG22NltoalmmHld3jj/JkLGxDrLvbuCEFCECW2lWs"
    "0Xb0pQYwN7hZT37ktYt4ZtAd6GMVNA/+BOfrCuPCqFnLO3XR+6SWQg5Yj4BJ+xCEumqpeQpdnMtAagpE9ZWLcYAiZJ73hUmrUT0s"
    "tX8kL/3K7nOvv6mTS+nNfSd0oXweESQblse/SwvrbqPlCWqw2vONwedbauYGWLOLwHNrOBDZwKMY18MX3scWeZMDULdk9uGH8DjU"
    "r35A1Vzv0YBzYLVFm8mZ9K5yQqErDCKz1/VnugGzJv4GWfyYJBHl347ioaxrPQayDRRHb3Ymv/StFf33E5yZoTu9sn3LJ6jkQ1FL"
    "JdWb7s7rq/psS4rpWhKktgCprrXhs8iqz7cMO5RWdqXOJN+IFmCSxl2zbZoSlSahnwaMFY17L/2S0J0ZSEwBj1EfMSY0y+PUjieo"
    "MJZ70oSB0Ts2Yc/W4i91W6D1SgeGM0lKx9LlBAn1PG7yFhQtg1VI+4CcPNA+kTZDof1dcInTwHRt4C45pmpIxoBU1Yd+SawJnchH"
    "unxSmoLJL94kkknXRAn0vz53UveoK57RcNvIDtM0yIBxHGtc43mvqIB2iIpVwxmyGDCTNu8x0M6q1idCxGb55kRSjtyuJ1WoFKN+"
    "8zhF0ZaX/wvsMGFuNnqXFYoqS00tG56YsNviiYVeFIm5285h40XTk0KGbFimqs6lmvpMMqvZS4OqsxjK2s8F/awMS80DM6GVIv2W"
    "SY+9pSpWypqUWd5cvScWqBPJ3fNtPZ584+bxJU6684tHuRZhZ8efJ9S0RGHxKDYFiUBnHBHojAZmlCisI+g3DUbuN0MKFWOiFEdN"
    "pkAt+kF/A5Um46n1eaY6k380RiogI5r4cVLocbDKxF6fKCW/KaivFIRG1vLnqSat2s4Gy8QdN1L9e+0Azjjf75m8zdZUYRK0cevG"
    "qs+EBMQUY3W62H9pHcSxF+TdAy7Bwlij+zO91OxU3/6xmJ4pkZ3ZEUDrvItw0xw/Zgu2UUkCFiZajGDAJ6PJwEkif0P/X8t4dTDP"
    "HN2fvSHowz7DKqqJEtX/pB8WcABeDXEfV2GeL+W7M4+Cw6sPuKWHsPu6gy5IwxixKgY2XmuKYRxZgMElz1SAnKWInH0PhDO4N0z+"
    "pN8KutXD6RUXu8IZlkpPHwB201PXslHANjIKiOHE8ZV3FnuL2hc5SRAMSVOEafVTq9hWnFGTGu4kU9+WcEqSp0Nf9GN50+7+RWlk"
    "eplVik2bAE0lMOrA6ruKsIWpW0D7IYtOeQF9y/b0xXHyRCECdu7dsQBBGQhdSIgkhwjl2rI7wqn6PtRU15W0oVv3IrO96zdPTs+z"
    "ViSmvp9ehh5j3yIUa0GxKwqa68Aoia0sIY185FltfMu6xLRlYKTDY5SqF3np+SBZLQgLUl8pfaZSN308oKXqBmaG6tlMNp3jJzWg"
    "AtNWO8xPBj0Nqjqyv3uNJ9bWEJfNx7x9Yg2xH8aqFx8LVhGB6wXSw2DtTVCPPTaY0/CPM7StZOwaXNVbW3ajv3K32XmDQCkyKfuI"
    "yerziavfn8I4j5oWVInwmgGpkWWczDDGMKHOSgqDurKhhCcTR7pt/5ac1T00B5fm4EgziJvpiEnDBDpiupBZNd9YpcR6Fw5Pqh9e"
    "9Xl11SGgofpvGRz6WNWhML9a9R3jFn9Mf0zVjVXuSmi4I3mW749mxCUd4H8NLbzZNHDX5KPqwbsmf5rOr+8avRjvHzMNu/IeE5UF"
    "7C29cwJLmoKUzyuTUJj12CsrVI43ttGOmcaTLI2qH0Ycx29Lh2sOSgUaebI/+niJ0tT4hbU4+rgy7E3iiVYala7Utw3thkvu8wGi"
    "jD6c2gzu5OrPiDVaTpjM5NEf0EEvm6pPsa3D/mXLl5Bt6JxeGF/PACzluZlfSLeAWfo0MTE3SaMQdAJBEQg66v/ZsuUiz3P6cB8O"
    "V8Shlw6FBNtLoILFJWjzCtnCTT9wiiiAYUFFDJo+ch/JyJT084rV80DeKwXam572vuWvXMZ5Jer6nwUNpzyZz+JG6W2RQJHfXqw2"
    "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"
    "xwGv/tJILG6EjqLMNobBZABuJlHUHop649j85vdsQj+/vBeYCawP5pfOiYOEHv4UhuZzsCyW36tM5MQCCHPma/MR9ENPUPZ75jxe"
    "g18xLlXseJ54FUros+ARgx3xEz1XF+SrsfaK2PdGfaoZn2pp89uAQdMLgJjX6cKRBIQP7l+/f/3+9fvX71+/f/3+9fuf8Rts9+XG"
    "d/hyk+BmwN0HlwT3xoe+3B64J+EegSuHWwu3DO4+uEg4ZSfiwc2CS4LbCFcNtwtuL1wr3Hm4Pjgl0BkmwN0NlwC3Cq4I7mG4n8L9"
    "Hu41uENwJ+E+gxuEUx325W6BuxtuLlwCXBpcHlw5XAPck3DPwu2DewOuE64HrhfOFwbdJ8BFwC2AS4FLg1sHVwhXDfdTuD1wB+A6"
    "4c7BfQ0XeMSXuxEuAm4eXArcOrhiuAa4p+HegDsB9xlcL9wwXBjq5vCHvqx+K1CXhR3S9ZPw2+E+hvsN3Gvyc/o9jWXePjj3LzY0"
    "nmuZGc8dyYrnzjbGc1WfxXP9f4n3vNeHYo8za+T+pq9Hrttf71pGPqWeTvc4RSe3+0ACFxISx/02OJ7TvpbArR0fz67Tix8qLtlS"
    "rDVtzTGVWgpKihFnNt5vld9X4/rf5OvDXtfh+xO4TlwvTVyfttigJ39ZukG/cjGWkrg2LF+mT4tfuZquE9NWp+opT3S9fOnS+DQ9"
    "u45fulTKc4VZKntMWDxXiuvuPyew61z5+i9V8dwq+fquCnxTvu7eFs8tkq+n4trHV6H08w9QjQsMUgeP14RcN+H60BtuvCns5ltu"
    "DZ84abL2ttunREy9487Iu+6OmhY9/Z4ZM2fFzJ4z9955sfN1Cxbed39cfELiIn1ScsriJQ8sNSxbnrpipTENjLNVqx9csxYq5xuy"
    "N+bkmvI25RcUPlS0ubik9EfmMgtfvmXrtod/XFFZtZ1bP30aR/anycSGDo7gDGllvRA3iSVm/dYCS6q5JMdUVsZxm8tySswm0/Tc"
    "oiIuPoeeacsLSoqyqQm00driEu3KtLTF2txsS/ZtVDcJ2bna3G3F2ZsLctbnZJdZ6GE3Vt8zvkzgCLjBx2tck00RwkHx9JfinJJc"
    "U2pJQbHFZMb9A/qVy/RLY2ZNXyS1wCLT6PdJRWVJyBv5RpMlI7uIZ9fJXtfxRUUlOf+ioNJPe8W/SM8/7T/wLwXM4L/1r+4q/0aH"
    "qPH65/MP/vOOX+v1z/cf/OeOq/1XB7hKm+b/v90DfEb+/aO/UT3AZ+Sf7z/4b6QH/J/++3vlp3+h+Od95/3O57/0Gxve97/4L4Qb"
    "+8SHkd/qmlprXf0jjzbYGoUd9sce3/mTn/5s1xNP/vypX/zbL3f/6tf//vQzzz73/Au/+e2e3/3+xb0vvfyHfX/8jz+98upr+w+8"
    "/sabb739zrtNzQdbDr3X2tbe0fn+4Q+OfNh19NjxE38+ear79Jmz5z76+JOeTz/7/Px/fvGl6PjKeeEvX3/Te/Hb7/r+2j8weOny"
    "90PANv8/ngCvPcH9QxPgf3f5/8fX/99bgFz7/T9F/aekzN+8eT6tbjguF79pWgN+WrrYhh9nMNyTm3sPLsjSDWSk4g1s7WHavJEt"
    "O7hlJeWe6+U5lhK6NGJV6n4Yz2/iyywct4QvYmks4YtN5MeXmguK4BuyzTlkpCjJtNHMZ5ulMNnF7BLfofQpXUqT0qJ0KA3E20Zp"
    "UHyKS3E4Y7aFN+dmszSSzAXsKi2fN5fJzzJNucUm+SaNl64MJcXsgZGX/WwLxaV4FJ7CURh6z/HFBRZTbnSZJdtiogqT7x8qKN6U"
    "W7IZ513mgmJ8NVd7hxYVkb2pBGHKSnhLfvRDWDdmy9fZeeaCnGzO/U7r9U7r9a6opDz7IY4r5U1mS0k0HpdgnR2dk19QzN6XmrWe"
    "6+KH4Uxboh82ZRdlF+dy+SXFm/DJ4k1kebmkiD3bhI9YtBvNBZbsAtovmIo3sec5D5tY/bsTc4fI3mxiWeHLyKGsyEvZlgLWUcq2"
    "mHILyvKj8wqKWRplpdnFdF9uKjY9zJuKKB33M96MDoCKdd9L5dGy8niemcw85xWnNNuczSKNeoZ1dPbIfTEyx0J5hdmMFbG52Ove"
    "tBWhij33qJdc3pxd5p0uUkBfzR6VZ1ORtiy7qDw7t8Q88iyHH3WPBi+gPBRrzaZSfmNRQc5I/JwSdBGt1JIjz4pKNm8syPb+Nuq8"
    "yOR1v7GkqKAcQdz32eZNpmKL1C6lJWYLatJUZoreaM5+uKCoILuYtX2JeYtpE26ii7fhuuyhUc82ljyEso0Kh2u0MEWPdrdngZmV"
    "ED0CPu43mcybvV6774v4rRjVJbx5k9ezgpx8i6m4zGJCn5GfZWPAm+lLeWZTcU7+SDry/ah05GeoyOxcrzgbTUVSZuVcRVM/HLn2"
    "ev7QyLVn/G0bGX/ud2PHl/s5jR33dSF6GL123xeYTZ5r9LaCjRtN2cVecalvua+R4YKHTSPvUAkj19JYYu2Vy1u8i8fGHTWqxYzy"
    "00YSzeV+VgbCko2GN3mFKyvYXFpUkFcA0uR5RuNdHu7uZ+TD5XOeiqWxLX+VNVC21IPcefNqfs8z7VWeuVfPW2sTOP2ydC5X9lNl"
    "fxHz47kF8JctxV6X3Sdy0+A/mJLCRTJ/MaeFn5hi5NTy88Ea6f58jfS+i92ncU01Ujp7a6T0n66R0t/J/KVcXY2UfinzYYaT+Yu5"
    "NOYv4VKY/yA3g/lGLpT5aZyK+cncULWUbq/s98BPWgnUOOYncm8xfym3l/lGbjf8Rfp4roH5iZyF+Uu5XOYbubRq6fuL4C9OM3Lz"
    "4C9bvpKLkP0Q5i/jBrcDRSMtgTsPX280cieYn8AdYv5Sbh/zl3O7mZ/IVTN/EVfK/CRuLfP1XArzk7nZzE/hIphv4EKZD7YS8xdz"
    "vVXkx3PnmP8gd5j5K7kDzE/n9jB/NbeL+RlcXRUBkyVxFVVSubZWSfVlqZLqqVT28+GnI90N8JMTVnKrqqjdlnGp5D+I/MnP58n+"
    "jCpqz0VcBPyUB5K5MLp/cCkXKvsqOf5QpeT3wk9duRiWNSg/D3Dd8B+MT+IOw38A9fmWfL9Pvt8NPy1tOcsvfW9HpeRXVEr5tMj5"
    "VatvUQeEzFWqVdFKhVIdEqKaqFqemMrFwy3z0M9lHppKPzMParzZpDWZzSVmbKGDgX6WtnS50Sg9oVvOuHhZstctt2i5IX7xspEn"
    "K+fOiJkdHBhfrM0uxUDOkZhH+dll2s3ZuSYtBl22BRNSqQUkTFtUAmJmyTdpE7XubxcVgPybt2kLwB8ym005lqJt0wNTi0zZZSZt"
    "TkmxJTvHwmJ4pX5nmbaML6UJRGsxZW/W5iHzm0FVkAYuN7Mw06XcSvmLCQ6M1saPZINH2gbj4qVaYjlp88wlm/GJgjJtdlkZCHnR"
    "Ni1mVZAqbTGSKjdJoUCJLQWgMQ+z5APTKHxBcS5lyYSY2o38Jtxrt2Ea8M7rdO1iixZBN2MKRVkfMiF1Ko7ZVMYXWbQledqc7KIi"
    "+hhqivKEiXVzKabRXG3kPTlF5ru0eXxxDqtTls/skUxhkjLzWKGatfjPXi4qKjJgrTPd3S6zqNzFJRbQvRJ+U74W83COiVUXGGfZ"
    "RaMqzLu+Zo6pL0/ZTVLjrUyT6tuSj0yXFOeYpv/j9eHO2wz6BqVE+Rv5QK78ftY8es8XZ29ENkdnId+UXSrllsLd+zfKuKWgZEy7"
    "jcSbe814ZZbcvxFvDsUr5VH68gKsYLKLRhqIWpIFpHCzr5n++pJirOMs96Ci4GktVERP+jNjR5e7pNRUzNq6BPe5pvKCHK+wch2Z"
    "tpZi3KDHUM14j1UKc++YMJvR7Qos+Vg951IveGhs+GvXixyJuMEIHiw1+dhBbzb9CGs6+hD1lJXyIEdBwNXFAhNl1hZQe1N354v5"
    "MqrALdn/F4c8yjAj9pplMBWj1UqKN2MZitAUdt41w2K1ylPAMk+6bDzlgYhZaMCWEq+aRSWyJvVc7P8KcswlZSV5Fm1GAStdYlSU"
    "px6WSsSOwgUi9PTp07kFpeaSTWYUCdsBE6qEnYTch+/JUfTUPLcFBqZKweYTp3OxZzAkYneDKioymlgXjC/ONZYWFCeWIDLCPYTd"
    "g6kIPHZi8NNaKqeMWTdKT0uKnif7M+cuZeci6csWJy5fpAevEPtCrgj/7mL0ILKYLyrCpT/9B4cphFP4c/6+IUq9Xu9HvzkzuFQW"
    "UDsvdVWAirt3xozMVOghabUqeqzakL8BPyywSrfip0IILoBTqVQkhKni6JbTJoLmFZnQN5ZvLERJtEtBnkDY7mTvikCWtSkFJjPt"
    "rLdpF5nKcswFpfJrTptA3UYKFG82Z2+7c/SzkeCYiLTghKZtKzWNSWQDI4da2gcX5Lj7OTZS5tw7uQ3YAWRvQn8uNzFam1NSum0U"
    "8cWW2SxndoMcpnyj1JWvHXIk7N9MTz5s0cqkItfkCUUdVErHHWaEQnrebjDla//RLHmF/ZsZH1sfXnkaXb4r6u0a6ZUWYcDROENS"
    "1AfWZGlzikrKQGGldMa+93q7oWRzcQEju2UFm6jd3SlQvwADgS7kti3PY3R2VDY8CY0Og3s69qJv61O4DXyuBVQNjJhiDHq8u6J2"
    "vPJzZX1fvV1Hwl21+ka1xTX7jzz9gHMxUkWbs0uv0g+v2t5/r/3+XruVocqyzVKVEzkcSUjul6a8bFriXL2qvL5/jfhS5kc93UD7"
    "cGqEK8asPFjpuQXjuyRPToP6BpV1o9yy9CzPc70O1LAC7g64BQsWcvfdt5Cbiut74KLhouDupjAVCAME+gqKQyo3RO5AExGcA6nm"
    "FlB8TkKUvQcu+r67OQTnouiaHP5E4eZu9o7jMKmzeqQ8Uh+9DfEXwtF56gIkdN99nr7M+jGzQrcei4Kigk3F2CivX2+maikAGxHX"
    "pRbz3NnwsVqk4rKweTidlW7Wr6elrfsaaxtPmNJseiylDZZ6ThF8qvPcSHq24ycJXB3cVrgiuA1waXApcHFws+Ei4fx+n8CV7sA7"
    "uDg4LZySfLwLo3hlCVwo/BA4NZwKTgnHwfXthAgn3AU4Ee48XA/cObhuuBNwXXCH4drhDsE1wb0FtxffPQD/Fbh9dA+3B+55uKfh"
    "dsM9BbcLbifcDrgGuDq4argKuFK4XLi1cKlw8+CmwYXBDT6OPMAdgHsKbitcGtw8uFC4vseQL7h9cE/D7YbbBVcHtwFuFdxSuAVw"
    "WjgOrtuO8HANcGvh4uDC4QZRX4fhnoar2yHVadqDjIcLVi04tmDcgn8LNi5xcxk/GSxicIrBMAbfGOxjcJHBTAZPGaxlcJiJ0Ywf"
    "Dsvls/5MLM1LthgtbKFEz9PLTGZpsl08soKKl+IsReeJz6FdRmpJKV/Knkn3UjKcASmCtieUbIXshlG/cuQUH4uE6upHqmsgbh+i"
    "eKT6kdrqUD8/rBTq6+sh/T5jRnUqLEepuMg756VmVmMdgMVCaiqBQmsjqxuYsUEsF/Lz81WqgK2lpVtKS0etExKXL1uenhbBpZIc"
    "yXVQmCDndZ0LeZDE2xLYtUQqsPKkXSdYSQXF5Rg+uVr5eWlJGeNOcYmR6EOIt+aOBCZTshFTv7ccCt1nk6CBVHWoezAzwZBazy6m"
    "x8bMwpjWL06jskfrEw2Sb5D8hPSkJPKRa7pfS9dJSxcbcWeOsnDRKYu4aCNzM1l446JZsh8j+7Nlf47sz5X9e5k/06hPJn9ZOqv+"
    "aKM+lZP9WbIfI/vxibI/K1HyY2Tf/X6W7CNCdCoYPfR86fJkt5+0WFonRifMmuP2Z8l+jOxTsVE+PQn/RGNBycJlxi9OmyX7dJ+8"
    "XMoj/OXLlq52XyemjDxzXzOhHq+wnvvlGay3RacuXsT8eKOUZqKRi6ZAiVJ9R7t9hK89/JPlT3xvLbWmWjdaN1nTrInW1bUdtR9Y"
    "K3FVYF1V+8FjW34q1r5X+2LtudrXay8GB0rreffaGcWTRFTMUj/HXrv29z9rq/3I/uvaT6QoiPxq7duRePPkrtoPauLth3Z1PfGw"
    "7eCutfjsRmtqzRprZm1v4+ZdSQh3yPZG7Z9qn73L/Z1EOs8wjf2K93cpJ7WHH7c1Xra9WfueNdlqq1lT+/tdL+18DcmdY5+2LsE3"
    "8q2N+LteyoP05BpfRbXaL+zca61lsRZbyaAKdaXHdwuPeT9E97ZarDbr8vlXuQdBqsGkiK4/Ooz3PcKgb4x+bxj9vgbwTTVVlFbK"
    "oqll04z4Q/+mURefCv44VVJgWpkRW0IwJswQTzKk6pOjZ2nTjDSmaVPoeZeBytLOnD5rLiI9Ufbz8tp2ax5Ks87+l8d31+6p/aL2"
    "aE18yqJ7MOrgZt1Dn6g9/MTvG+tqe+1ltc+iMvfXJMj8kMc21T77xPfztV6fXkPjPYu8RAPzDMzDINc+XvLzD1CsFKtgXU/PiABo"
    "y7Amp5uURfTXKP/dSh59mnyqdfIZcdAihTj0ShjLyNKWmXOmW8q02CpqWY608k96Xtsrd8GPxpZzx+e1hxFmfcoiBLuHrlDckctZ"
    "dBk4Or31lBs8/9kvkOwfGr5yF+TxzyOpM9H4cD+6q7aDeg7reFJduXM0X/uzIVYHcgkin3hm5y6voYXQd0nfpVrUaudrd534yabH"
    "v37iYm3vYznuBCNTl8avprr4eWltx7LFaTUb0pan1fbuWl57uPbt2k9YwENoypEUKb1EA6UHb2xygdL3DNJ7wzXeUwPivXcbIhBl"
    "fSQYhWONKocrwcCmskr0ZFToSIOcr5RFWko3ZZG7Vmp7KS4LB7LhSdcohTNeM1zkzJoNMbX7a0/VHrrLE2erFGfrNSNtrf2A4t3l"
    "aQnbQSlf1NyIS961c4ZwoLJbt07bunU+RcZN7WE3Gb2iDt2/SFYRH8ycu7Ng5y6iQtafWSuFL3Z216IfjM0HdX7kgzx3wkSB0NQf"
    "XTkgET7RyOop0fjE5Z/8vPa9mvifGNEZpJzvr3WgyInG2sNscAxJjx7/yv5o7Qe1f6z9ytNE7Ui2dVSed/4Jj19iqXhmAbmzur+7"
    "ldXDVu9vy8m9nZM/KgdSiWvf+1/tPQlcVNXXj4GMcAlNTTNtRFFIUMClHERmhkUIkREQDUFAZliSVUAhReFhyCKbbJa5KyqlYqmg"
    "oiICgTFKacrfLXIh0/SjLLWQ+M55y8ybYRjsX9/3+399vN/cue9u55577rn3nrudR5dZpcR0vTlIuLxflEY2UB0QpDZgwq044ZkJ"
    "5FcSV08TZhXINSDKEycxpprSTYZ0zxtXBHHTj+YeS/FPSQGEw1Iyc5vzLqVfyMmAalKPa/Un4k7+E3Hj7QRK/ltXnbyA6Vwgjgkt"
    "upgxkosZI7nQfAOjeny8JVSIlVn8ZLP4KWbxUwV8FjoOc2RDnhv0gw1Uz8VwVmEpsC/VS1LMW14cBlIAhQ2XF7iPyXpJ2llS7sJC"
    "MFXphwV8wIGU57lBNgBOESu3wIQVLQpjoN77G6imsSLlgNr97lMpeEWRZjIpX18JGdFDVSt5F9+ZsrQgGHIvzd4mlgJ0Joss0P4c"
    "eZ1lYy68KaQc+IQC1ph1lWxID8r7GJt3aeF58gF5GtrUdqbp0HTskpcqzbTnzMl3KikvXMxgigxOYXBTgUrGxYw4shRDIRaUcr03"
    "uZ1uwFT4YSVQ4AEQYRCmK5yTiQy0i8PxGYaMxtj4WCVLKUcqAzYNSpOYjm29isiNqpA4cCgoKl0SBwc7J7ps+M5KGGw+ZIOdE9lW"
    "GJt+muLLOk9Y1rUDgQ7qsQC4sQHbSWAIPSQZqPGgojeG/s/CIjBEYBUeGWFmYQVvsMi+VBbJwYGWnAV8RT/JSNCIF9pcHLD3yt6c"
    "cZHT30MOgGcdxiyuLGynKKPoOtXxYsrMZkHWqQ+THJwwgsBAcUqVj7MLxAnZLVmEpWcpJrFzJxshlGyzFFhYwA+Y7PvcecAClYpB"
    "Ne1eYQFwog9USzBZy8Urqyb3CJQmDfhjHxga81JyK5S3kaxdn5V2gSMAc/EBERvxUZO027KDgZPYbNPbcj4uts9tNTXJ35/1Y7aU"
    "6jaqgQ9qSLkrbqlYQVqykYMPCM+zUz5ISYbuLzh7bk6doh1QM6fnyY8pzPbCPTB2HYdCXCOvcdoxNfP6s3AK3st4lhwH8VBItppo"
    "YZVWn7UqeZk6PUBG6gEwSlFpxZs4A7RmqNyOFABimuQ4eDFDKuDf5ORlZF3+gezN0BViBsBzhS4gy2LN3VUKjIAXzEKxngrPZ5Sv"
    "y0w/C1yQleJGtqW3Fp0lG7h8bBILG7lhsLYBndhVwK6FbEwWgdx4kjwsXRoZtR7qTqUP5/PZqsw7kbNv3f2scoZv9kLSwyA0ULKA"
    "os9hZsPdYFKX4gO95AKlBDwxLDJ4kh+LErqU2Kq2K8Qdg+UmRtS8TAHCyIx9pwVNM9i9CICdaljJWJeTW6BGZ75qZnIN5DBVKz+f"
    "j7gX+mSXkHIsH9YIeQTkIK7chTP4hWbhMbJAX6gGFiN2AkINowfJwykOKY7gD7JhXmL+M5U+QTVPBAQiYvpPZGP+FwgBBRQqDbAA"
    "C4XupFTE6pz64lLgFrmlBcMX1AoDg5iAn1eZsgyrA+aWSTBDh3mMkz1OkygcD3MGNbk6vmo0odHPvlxEkm30qJO/HGpNtfvH/HHF"
    "QzlvYOc97BSiqNJMOXfEHrjwSPZHGdfIG6ZkqdXUqTCDgMzT6nNATiHrufzAjr1KmEVFBY8hf5zFKsjKbV/KfEh5/oGiSsWoJs+5"
    "lZMHMi2VCnvDrjCB2w+iQKzCj7UqUBqwV0XuIUuxrLmtlM92ci/bt0K/e5LtXYEusAJEjYlIH2za2MSVGZNt8+C8IY6DdZhWQQoa"
    "JAiOjiAQzdHAP/QkGSr6XM5V5SCfkgFtLljhrmXHL5TFOXmmP4PqY6TyjNCCher9AFcWaCuOSrvAkf+ZlSWQ/6mfGczJlRJE9uas"
    "HEa2ZRm1pzmAGixaglDCA8b/U/BMQIhMT0lGES1ZxCwPNOIMKGdtwUVggbWFMdCoaxXzZVq2XhdBSyqUjWOvnBqXHahxuUHZz9A9"
    "It1w6JkSDoTsTJGmEn2OCLbIA6gDLHAkAI8vmBjHmPIXAkK+GMk4xoBQ9E+4vgZdFLUHwaxh+jFrmpQN64Z+dh7GUnTDipBUYx40"
    "KD88vOyHSy0mFDI+syODcWfcPjRmCWLggy98d9zZFSfAEZVJMfQauQ+zQs5pPKY+zm5dYhqHSQkzpLOlh4DiB0ALX4ylrmBcCEQO"
    "R020gbZ84xi+q3gSbZnyIbWxMa5nUReV+sOClpY4FC1ni2AhiH7MjOFsAQjmfl7O9g5uZhbwwOkLD5gX+eGtRjPLt+EQg8Mce2oh"
    "0cRYSm3cmwMi5gEUyYDmE0GQBVpT/4gfnYlxTH+VfjkqVGpjEW9sMSXeDBbO4VCtjfHbztOmwNF5HDZtjCfTDiVT2BjTPotxZxDq"
    "hXYzbepvggYoGhnHGJnRgawXQb0weGOt2wAVXcRdwdFtQ1sMmgbA7zBDNTMztrCSCrh/k6Vs1lTMxQl2cOoJjlXYRUYEhQbzbfjG"
    "Uv7iBI8APMYaEQx3FqOdI6SyeCoAEmA7yn5QeJYsxUabd4maWZ3AROYz4R+qS1OW1HSRwJkCXTs6FVQ9SgXQUnNb80u7R5OiDR0P"
    "y6OlOMqyQ3xEs0fAbLznBYzxoTPBNFnlhaV8KgQZlDo/hN7Yv4EHLJ6ApE/Zl6AhxAg0QMdGDOk8Pfyg37SiFrChFdBdMoLhI7U0"
    "J6RT4vnG54+bvQVRBzJSDNwjWxB2IRiA90Pg9BjjMNFUs0iXrt4ElQ2sd/eUkYHmTpa/0DiG6l81hC+HQ0LQKyqiAB0cJLMoOmgl"
    "NZHnlv4Tu9ZgLC1cXLS9aDMMz7AAy6SHYXcBzHIWpyxjBymGzsxk/t+Gzy4GaIYPtZLxTnaEVl6FODnOxUefi0+RE3sEyMR7XqAs"
    "03PTs0/5yNN6EdbkS/8aZ9f/2jK9V5YsqX31M9fU116QzBpV8UB/3MttDUaXLmVMCvjSZYJ0Y7+pF1LllgZbs2ecOOH2dtTVgbO/"
    "qGtyGtWS77C3w1306b4hfiPKLi6sLir2isv0cq+fNvy91ROaI0r6bwwcaOgdPFg4MmGH77XE91dsiZIHLYptOTJmw/xPbn6cnbUt"
    "b3quf+GMqvGZmddbc9zbd5F3WqWpCxZOOPlfjveOTfPfW56cGPL5GvNJ+yZbPNx7b+i+nb59w7bmhltdHB/1qOkPr7Lrzi7R/5o9"
    "YtoX7X2enDHiHzpXaBN31iRJ8POWTe2PHY9XtP9UktD5y+OZ39nd77zzkbzyrnlT4o/Lo1KnVIXPshjuomez36t2+id9yPGvj7Ab"
    "U2tDTFzKP/3m+U3Zg+KT3IZuK+k3Yuhx+Ruv3M/Q2fnY5YXEJn39s/KGfi9+UhxfdsRrZWjukOgbWRfjrl7PXxJW5R55uHXgYl57"
    "U9Apxy2L9Bcu8v4qceT8IP9rHoEWG10vmns79+873P7Y0GZhcd2uT/lXpXt+6xi/a05L6zaXsm2nnu3zP26cOebI+qKbn02asC9j"
    "w7SwbJHhpJTH/R+ufeS790N7YcimTUETct9cca/g+5GHWiQEqIgeN+2HmdZPHlgvKXu0bln0k3kSq99vuj76w6+tsu7ug8Rqyy9n"
    "nk+91PllSmrFN1M2Jnz14ITgmvfW9uaHLf1C3+2QhyddzfZ/q85NalWk//4HmQ2rfPZlxNwvc1nu1V/P7TvDWpe3p6U65kyYJc5Y"
    "QfjYBJ1ecFtIzvPwtZu72Xqksem4a6PbiC1ms0YuMhG7Dp/2q6TZymzZRtuNS7ytx10aopv35cUXnR4UG3S2eQ34fetAQ9cTTYML"
    "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"
    "9HwyGWgxjJnnYf+2WmWix1MCrX9B+f67vuJd+HE/xbvkzMuK97G/DGLfk4o2DGXf+ZUnh9PveqcaRmRPwfdtDxrPjai+MEfIb9t8"
    "OGrCnn21m0KFTb4dxndey3Ybfj9FGF10udBuwAtZpgc2C387tdX+QfKgnGTyqPDUjG9Kznc6vxFffUEYWdey7oekhlnH8veIKj9Y"
    "Mm/89KwnUS0rxZXXs2/8tqn9/qrSuXbbWpfdavzZdNKa5HH2Joavlj7db3irtuZ3+/u7Lz56cv+7d94vPO8ga/wib0DJ/q3Db+1w"
    "7C97tV9ccmrcsgYn1wXi27vzp1tPrfjsgYfr7ju+NrW+1pmb13t3+pa0beNXee5a91bAVx2Z3pnNxr7pv10NLi18+mj8qe31vteT"
    "ImY3bCzmZ/Dc/WuMqW++yBvlzJfL222jbQwu74jCv6e23lLrb92yiiMGpfxqe+aCmWz4zQWvln/1k23Ty2PWzBox69Pa3Q9thSVH"
    "QsMOvHDirdT7tpNtKsXv3/mm4NSl722rOzrOBawZuLzxk9u2k2Yv/M615mRBYWuD7foaD+s4e/ngkx8dsL0RfKxgusO+UQfPF9iO"
    "HVN3s/KYtWVA5vu2AfPePb3qoMfKQcf9bC8/nJTV5+T6D4a029uOtd31w/Rd4++t3vOmbeKn225XSlc6Nl2fNzNwRZ/GMZ7LUzrz"
    "km3yfhcMfz/Q2M6y6tMZo9O/epucVVxBdFy2vpa2QH/Ewbu3Ukt0revWOIhfPPJh3FtXJwomR7/+9ZirVg+dc72nl6w9WTX/yi6y"
    "ZPthq5shnw3c7b7F/t1yQ7gOddt82hQ3j/3nlhjnvKu3s+pGdWL73bpRm79P856fN+OUJMVo2BwX2eKOlJwDfQoSB942v7Hl3Nf1"
    "etdLmtnVhyRDe8VcKomw+M+a7/U+vU/v0/v0Pr1P79P79D7P9+gxK/fD6H2+JHV/6hyrBn/cy8A7rAuqBhNeYN9mFlFmKD7mFB8e"
    "FhFjYwQfcBDEBIbAtxFjzMPZj7Tg15YEATHhE5dZGsHHEyJCg+DQBnNOyMbIcqKF0cz+BjMmsbBmSkQSkb09fBJrwQLmpdfd6+51"
    "97p73b3uXnevu9fd6+5197p73b3uXnfP7v8GvQY0Wg=="
)


if __name__ == "__main__":
    _proc_id_result = set_taskbar_identity()
    app = App()
    # 窓ができてから、窓にもIDを付ける(タスクバーのまとまり対策)。うまくいかなかった時だけ、ログに残す

    def _apply_window_identity():
        results = [_proc_id_result, set_window_taskbar_identity(app)]
        if any(("失敗" in r or "例外" in r) for r in results):
            app._append_log("[タスクバー] " + " / ".join(results))

    app.after(500, _apply_window_identity)
    app.mainloop()
