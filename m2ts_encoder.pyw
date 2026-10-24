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
    登録バッチの一覧(m2ts_encoder_bats.json)やVLCのパスなどの設定は
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
    - ファイルの場所を開く: エクスプローラーでそのファイルを選択した状態で開く
    - VLCで再生: VLCで再生する(初回はvlc.exeの場所を聞かれるので選択してください。
      次回以降は自動的に使われます)
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
import subprocess
import tempfile
import time
import unicodedata
import urllib.request
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, scrolledtext
from typing import Dict, List, Optional, Tuple


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


def get_sort_root() -> str:
    return os.path.join(get_script_dir(), SORT_ROOT_NAME)


def list_sorted_dirs() -> List[str]:
    """仕分けフォルダ本体と、その直下のチャンネル別フォルダの一覧(存在するものだけ)"""
    root = get_sort_root()
    if not os.path.isdir(root):
        return []
    dirs = [root]
    try:
        for name in sorted(os.listdir(root)):
            sub = os.path.join(root, name)
            if os.path.isdir(sub):
                dirs.append(sub)
    except OSError:
        pass
    return dirs


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

    if program_name and not program_name.startswith("("):
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

_HEAD_SECONDS = 5.0            # 録画の先頭とみなす秒数(この範囲の映像/音声エラーは無視)
_TAIL_SECONDS = 20.0           # 録画の末尾とみなす秒数(終端の切れ目で出るエラーは無視)
_TRUNCATED_SECONDS = 60.0      # 出力の長さが元よりこの秒数以上短ければ「途中で終わった」と判断
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
    秒数を保持しておくことで、あとからVLCでその時刻から再生する、といった用途に使える。

    誤検知を減らすため、次のものはノイズ/失敗として扱わない:
      - 録画の先頭(_HEAD_SECONDS)・末尾(_TAIL_SECONDS)に出るデコード系エラー
        (録画の切れ目で必ず出る副作用のため)
      - 一定間隔で規則的に出続けるデコード系エラー(GOP周期の副作用)
      - 録画の末尾で出る「Conversion failed」(最後まで変換できていれば内容は無事)
      - 重複フレーム(dup)の増加(ほぼ全ファイルで出るため、他に問題がある時の参考情報としてのみ記録)
    """
    duration_seconds: Optional[float] = None
    current_time_seconds = 0.0
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
            saw_time = True

        dup_match = _DUP_RE.search(line)
        if dup_match:
            dup_val = int(dup_match.group(1))
            delta = dup_val - prev_dup
            if delta >= _DUP_JUMP_THRESHOLD:
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
        duration_seconds is not None and saw_time and (duration_seconds - current_time_seconds) <= _TAIL_SECONDS
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
        and (duration_seconds - current_time_seconds) > _TRUNCATED_SECONDS
    ):
        short_by = duration_seconds - current_time_seconds
        significant["出力が元の長さより短く終了"] = [
            (current_time_seconds, f"元{_seconds_to_hms(duration_seconds)}→出力{_seconds_to_hms(current_time_seconds)}、{short_by:.0f}秒不足")
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
    cmd = [ffprobe, "-v", "error", "-show_entries", "packet=stream_index,pts_time,dts_time",
           "-of", "compact=p=0", path]
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
    cmd = [ffprobe, "-v", "error", "-count_packets", "-show_entries",
           "stream=index,codec_type,codec_name,nb_read_packets,field_order,avg_frame_rate,"
           "width,height,channels,sample_rate", "-of", "json", path]
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
    for st in streams:
        if st["index"] in times:
            st["first_time"], st["last_time"], st["max_gap"] = times[st["index"]]
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
        if both_used and audio[1]["packets"] < audio[0]["packets"] * AUDIO_DESC_RATIO:
            o["audio_desc"] = True
            ratio = audio[1]["packets"] * 100 // audio[0]["packets"]
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
        if post:
            o["audio_ordinals"] = [k for k in selected if k not in post]
            o["audio_post_ordinals"] = post
            notes.append("→ 途切れる音声は、エンコード後に元のm2tsから合体します(同時に入れると長い番組で失敗するため)")

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
echo %NAME%
rename %1.csv "%NAME%".csv

set "error_log_prefix=ffmpeg_error_"


ffmpeg -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" -fflags +discardcorrupt -map 0 -c copy -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc -qp 32 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -c:s copy -aspect 16:9 -buffer_size 512k %1.mkv

REM -bsf:a aac_adtstoasc 2> %error_log_prefix%%~n1.log

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set NAME=%%A
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo %NAME%
rename %1.mkv "%NAME%.mkv"

REM del %1

if "%~2"=="" GOTO EXIT
shift
GOTO REPEAT
:EXIT
copy *.log matome.log
pause
""",
    "m2ts→mp4(モノラル二か国語)_CNCATV.bat": """echo on

:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set NAME=%%A
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo %NAME%
rename %1.csv "%NAME%".csv

chcp 65001

ffmpeg -i "%1" -fflags +discardcorrupt -dn -ignore_unknown -filter_complex channelsplit[FL][FR] -ss 0 -map 0:v -map [FL] -map [FR] -map 0:a -c:v hevc_nvenc -c:a:0 aac -c:a:1 aac -c:a:2 copy -bsf:a aac_adtstoasc -ac 1 -qp 32 -tag:v hvc1 -metadata:s:a:0 title=主音声 -metadata:s:a:1 title=副音声 -metadata:s:a:2 title=主/副 -aspect 16:9 %1.mp4
REM 2> %error_log_prefix%%~n1.log 

chcp 932


for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set NAME=%%A
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo %NAME%
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
echo %NAME%
rename %1.csv "%NAME%".csv

set "error_log_prefix=ffmpeg_error_"


ffmpeg -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" -fflags +discardcorrupt -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc -qp 32 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -aspect 16:9 -buffer_size 512k %1.mp4

REM -bsf:a aac_adtstoasc 2> %error_log_prefix%%~n1.log

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set NAME=%%A
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo %NAME%
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
echo %NAME%
rename %1.csv "%NAME%".csv

set "error_log_prefix=ffmpeg_error_"


ffmpeg -scan_all_pmts 1 -probesize 500M -analyzeduration 500M -i "%1" -fflags +discardcorrupt -map 0 -c copy -ss 0 -dn -ignore_unknown -max_interleave_delta 0 -c:v hevc_nvenc -vf bwdif=1 -qp 32 -c:a copy -bsf:a aac_adtstoasc -metadata:s:a:0 language=jpn -metadata:s:a:1 language=eng -c:s copy -aspect 16:9 -buffer_size 512k %1.mkv 

REM -bsf:a aac_adtstoasc 2> %error_log_prefix%%~n1.log

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b -d') do set NAME=%%A
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo %NAME%
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
echo %NAME%
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
    "m2ts→mp4(モノラル二か国語)_忘れずアスペクト比変えるlinsun.bat": """echo on

:REPEAT
if not "%RPLSINFO_SOURCE%"=="" (set "INFOSRC=%RPLSINFO_SOURCE%") else (set "INFOSRC=%1")
rplsinfo.exe "%INFOSRC%" %1.csv -T -f -b -d -t -c -i -e

for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set NAME=%%A
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo %NAME%
rename %1.csv "%NAME%".csv

chcp 65001

ffmpeg -i "%1" -fflags +discardcorrupt -dn -ignore_unknown -filter_complex channelsplit[FL][FR] -ss 0 -map 0:v -map [FL] -map [FR] -map 0:a -vf yadif=1 -c:v hevc_nvenc -c:a:0 aac -c:a:1 aac -c:a:2 copy -bsf:a aac_adtstoasc -ac 1 -qp 32 -tag:v hvc1 -metadata:s:a:0 title=主音声 -metadata:s:a:1 title=副音声 -metadata:s:a:2 title=主/副 -aspect 16:9 %1.mp4 
REM 2> %error_log_prefix%%~n1.log 

chcp 932


for /f "DELIMS=" %%A in ('call rplsinfo.exe "%INFOSRC%" -b') do set NAME=%%A
set "NAME=%NAME:/=%"
set "NAME=%NAME:\\=`%"
set "NAME=%NAME:?=$%"
set "NAME=%NAME::=;%"
echo %NAME%
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
    existing_names = {item["name"] for item in existing}
    updated = list(existing)
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
    ("mp4・モノラル二か国語(CNCATV)", {"container": "mp4", "audio": "mono", "hvc1": True}),
    ("mp4・モノラル二か国語・yadif(linsun)",
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


def build_ffmpeg_command(options: Optional[Dict[str, object]], input_expr: str = '"%1"') -> Tuple[str, str]:
    """
    設定からffmpegコマンド行(cmd.exe用の文字列)と出力拡張子(".mkv"/".mp4")を作る。
    入力は input_expr(バッチ内の "%1")、出力は %1.<拡張子>。
    """
    o = normalize_encode_options(options)
    ext = "." + str(o["container"])
    # 字幕を後から合体する設定の時は、エンコードの段階では字幕を入れない
    inline_subs = bool(o["subs"]) and not o["sub_postmux"]
    parts: List[str] = ["ffmpeg"]
    if o["cuda"]:
        parts += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    if o["catv"]:
        parts += ["-scan_all_pmts", "1", "-probesize", "500M", "-analyzeduration", "500M"]
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
    parts += ["-c:v", "hevc_nvenc"]

    filters: List[str] = []
    if o["cuda"]:
        filters += ["hwdownload", "format=nv12"]
    if o["deint"] == "yadif":
        filters.append("yadif=1")
    elif o["deint"] == "bwdif":
        filters.append("bwdif=1")
    if o["cuda"]:
        filters.append("format=yuv420p")
    if filters:
        vf = ",".join(filters)
        parts += ["-vf", f'"{vf}"' if ("," in vf) else vf]
    if o["cuda"]:
        parts += ["-color_primaries", "bt709", "-color_trc", "bt709",
                  "-colorspace", "bt709", "-color_range", "tv"]

    parts += ["-qp", str(o["qp"])]
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


APP_VERSION = "2026.10.25.2"
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


def fetch_update_info() -> Dict[str, object]:
    """GitHub上の version.json を取得する。失敗したら例外"""
    raw = _http_get(UPDATE_BASE_URL + UPDATE_INFO_FILE + f"?t={int(datetime.datetime.now().timestamp())}")
    info = json.loads(raw.decode("utf-8"))
    if not isinstance(info, dict) or not parse_version(info.get("version", "")) or not info.get("file"):
        raise ValueError("version.json の形式が正しくありません")
    return info


def is_newer_version(remote: str, local: Optional[str] = None) -> bool:
    r, l = parse_version(remote), parse_version(local if local is not None else APP_VERSION)
    return bool(r) and r > l


def download_update_source(info: Dict[str, object]) -> bytes:
    """新しい版のファイルを取得し、壊れていないか確認してから返す(確認に通らなければ例外)"""
    raw = _http_get(UPDATE_BASE_URL + str(info["file"]) + f"?t={int(datetime.datetime.now().timestamp())}", timeout=60.0)
    text = raw.decode("utf-8")
    if len(raw) < 100_000:
        raise ValueError("ダウンロードしたファイルが小さすぎます(壊れている可能性があります)")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m or m.group(1) != str(info["version"]):
        raise ValueError("ダウンロードしたファイルの版番号が version.json と一致しません(少し待ってからやり直してください)")
    compile(text, "m2ts_encoder_update", "exec")  # 構文エラーがないか確認
    return raw


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
    try:  # バックアップは新しい順に一定数だけ残す
        olds = sorted(
            (n for n in os.listdir(backup_dir) if n.startswith("m2ts_encoder_") and n.endswith(".pyw")), reverse=True
        )
        for n in olds[UPDATE_BACKUP_KEEP:]:
            os.remove(os.path.join(backup_dir, n))
    except OSError:
        pass
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


def open_run_log(m2ts_path: str):
    """エンコード1件分のログファイルを開く(失敗したらNone)。古いログは一定数を超えたら消す"""
    try:
        log_dir = get_run_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        stem = re.sub(r'[\\/:*?"<>|\r\n]', "_", os.path.splitext(os.path.basename(m2ts_path))[0])[:80]
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"m2ts エンコーダー v{APP_VERSION}(録画番組名ビューア/エンコードキュー)")
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

        # 設定(VLCのパスなど)
        self.settings: Dict[str, str] = load_settings()
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
        if self.settings.get("auto_update_check", "1") != "0":
            self.after(4000, lambda: self.check_for_update(manual=False))
        self._refresh_bat_combo()
        self.after(100, self.start_scan)

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
        tool_menu.add_command(label="チャンネル別に仕分け(mkv/mp4/csvを「仕分け」フォルダへ。m2tsが無いものも対象)",
                              command=self.sort_into_channel_folders)
        tool_menu.add_command(label="ファイル名の記号を全角に修正", command=self._fix_semicolon_filenames)
        tool_menu.add_separator()
        tool_menu.add_command(label="変換済みm2tsを削除...", command=self._delete_converted_m2ts)
        menubar.add_cascade(label="ツール", menu=tool_menu)
        self.sort_button = MenuEntryProxy(tool_menu, 0)
        self.fix_names_item = MenuEntryProxy(tool_menu, 1)
        self.delete_converted_button = MenuEntryProxy(tool_menu, 3)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="エンコード設定...", command=lambda: self.open_settings_editor("preset"))
        settings_menu.add_command(label="バッチファイル管理...", command=lambda: self.open_settings_editor("bat"))
        menubar.add_cascade(label="設定", menu=settings_menu)

        log_menu = tk.Menu(menubar, tearoff=0)
        log_menu.add_command(label="ログを保存...", command=self._save_log_as)
        log_menu.add_command(label="ログフォルダを開く", command=self._open_log_folder)
        log_menu.add_command(label="ログフォルダのtxtを1つにまとめる...", command=self._merge_log_files)
        log_menu.add_separator()
        log_menu.add_command(label="ログ(txt)を全削除...", command=self._delete_all_logs)
        log_menu.add_command(label="エンコード診断結果を表示(全件)", command=self.show_all_diagnostics)
        menubar.add_cascade(label="ログ", menu=log_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="アップデートを確認...", command=lambda: self.check_for_update(manual=True))
        self.auto_update_var = tk.BooleanVar(value=self.settings.get("auto_update_check", "1") != "0")
        help_menu.add_checkbutton(
            label="起動時に更新を確認する", variable=self.auto_update_var, command=self._on_auto_update_toggled
        )
        help_menu.add_separator()
        help_menu.add_command(label="バージョン情報", command=self._show_about)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)
        self._help_menu = help_menu

        self.configure(menu=menubar)

    # ------------------------------------------------------------------
    # スキャン処理
    # ------------------------------------------------------------------
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
                program_name = "(番組情報を取得できませんでした)"
                channel_name = "(不明)"
                broadcast_date = ""
            else:
                _, program_name, channel_name, broadcast_date = info
                if not program_name.strip():
                    program_name = "(番組情報を取得できませんでした)"
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
            if os.path.normcase(os.path.dirname(output_path)) == os.path.normcase(dest_dir):
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
            return

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
        known_channels |= {os.path.basename(d) for d in list_sorted_dirs()[1:]}

        entries: List[dict] = []
        for path in outside + inside:
            is_sorted = os.path.normcase(os.path.abspath(path)).startswith(
                os.path.normcase(os.path.abspath(root)) + os.sep)
            csv_path = os.path.splitext(path)[0] + ".csv"
            has_csv = os.path.isfile(csv_path)
            channel = ""
            program, date = "", ""
            if has_csv:
                channel = read_channel_from_sidecar_csv(csv_path, known_channels) or ""
                program, date = read_program_info_from_sidecar_csv(csv_path)
            if is_sorted:
                state, label = "sorted", "済"
                if not channel:
                    channel = os.path.basename(os.path.dirname(path))
            elif channel_folder_name(channel):
                state, label = "unsorted", "未"
            else:
                state, label = "unknown", "不明"
            where = os.path.relpath(os.path.dirname(path), self.folder)
            entries.append({
                "path": path, "channel": channel, "state": state, "label": label,
                "file": os.path.basename(path), "program": program, "date": date,
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
    # 右クリックメニュー (ファイルの場所を開く / VLCで再生 / rplsから情報再取得)
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
        menu.add_command(label="ファイルの場所を開く", command=lambda: self._open_containing_folder(iid))
        menu.add_command(label="VLCで再生", command=lambda: self._play_with_vlc(iid))
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
                # /select, を使うとエクスプローラーでファイルを選択した状態で開ける
                subprocess.Popen(["explorer", "/select,", path])
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

    def _get_vlc_path(self) -> Optional[str]:
        """
        VLCの実行ファイルパスを取得する。見つからなければファイル選択を促し、
        選択されたパスは設定に保存して次回以降自動で使う。
        """
        vlc_path = find_vlc(self.settings.get("vlc_path"))
        if vlc_path:
            return vlc_path

        messagebox.showinfo(
            "VLCが見つかりません",
            "VLCの実行ファイル(vlc.exe)を選択してください。\n"
            "一度選択すれば、次回からは自動で使われます。",
        )
        selected = filedialog.askopenfilename(
            title="vlc.exe を選択",
            filetypes=[("VLC実行ファイル", "vlc.exe"), ("すべてのファイル", "*.*")],
        )
        if not selected:
            return None
        self.settings["vlc_path"] = selected
        save_settings(self.settings)
        return selected

    def _launch_vlc(self, path: str, start_seconds: Optional[float] = None):
        vlc_path = self._get_vlc_path()
        if not vlc_path:
            return

        cmd = [vlc_path, path]
        if start_seconds is not None:
            cmd.append(f"--start-time={start_seconds:.2f}")

        try:
            subprocess.Popen(cmd)
        except Exception as e:
            messagebox.showerror("エラー", f"VLCを起動できませんでした:\n{e}")

    def _play_with_vlc(self, iid: str):
        data = self.row_data.get(iid)
        if not data:
            return
        self._launch_vlc(data["path"])

    def _play_with_vlc_at(self, path: Optional[str], seconds: float):
        if not path or not os.path.isfile(path):
            messagebox.showerror("エラー", f"ファイルが見つかりません:\n{path}")
            return
        self._launch_vlc(path, seconds)

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
    def _on_auto_update_toggled(self):
        self.settings["auto_update_check"] = "1" if self.auto_update_var.get() else "0"
        save_settings(self.settings)

    def _show_about(self):
        messagebox.showinfo(
            "バージョン情報",
            f"m2ts エンコーダー\nバージョン {APP_VERSION}\n\n配布元: https://github.com/tatata17/m2ts-encoder",
            parent=self,
        )

    def check_for_update(self, manual: bool = False):
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
            if kind == "err":
                if manual:
                    messagebox.showerror("アップデート", f"更新の確認に失敗しました。\nネットワークに接続できているか確認してください。\n\n{value}", parent=self)
                return
            info = value
            if not is_newer_version(str(info["version"])):
                if manual:
                    messagebox.showinfo("アップデート", f"最新の版です。(バージョン {APP_VERSION})", parent=self)
                return
            try:
                self._help_menu.entryconfig(0, label=f"アップデートを確認... (新しい版 {info['version']} があります)")
            except Exception:
                pass
            if not manual:
                self._append_log(f"[アップデート] 新しい版 {info['version']} があります。メニュー「ヘルプ」→「アップデートを確認」から更新できます。")
                return
            self._confirm_and_update(info)

        self.after(300, poll)

    def _confirm_and_update(self, info: Dict[str, object]):
        if self.encoding_running:
            messagebox.showinfo("アップデート", "エンコード中は更新できません。終わってからやり直してください。", parent=self)
            return
        notes = str(info.get("notes", "")).strip() or "(更新内容の記載なし)"
        if not messagebox.askyesno(
            "アップデート",
            f"新しい版があります。\n\n現在: {APP_VERSION}\n最新: {info['version']}\n\n【更新内容】\n{notes}\n\n"
            "更新して、アプリを再起動しますか?\n(今の版は自動でバックアップします)",
            parent=self,
        ):
            return
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
                return
            if self.encoding_running:
                messagebox.showinfo("アップデート", "エンコードが始まったため、更新を中止しました。", parent=self)
                return
            try:
                backup_path = install_update(value)
            except Exception as e:
                self.status_var.set("アップデートに失敗しました。")
                messagebox.showerror("アップデート", f"置き換えに失敗しました。今の版はそのままです。\n\n{e}", parent=self)
                return
            messagebox.showinfo(
                "アップデート", f"バージョン {info['version']} に更新しました。再起動します。\n\n(旧版のバックアップ: {backup_path})", parent=self
            )
            self._restart_app()

        self.after(300, poll)

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
        total = len(iids)
        for index, iid in enumerate(iids, start=1):
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

            try:
                returncode = self._run_bat(data["path"], data["bat_path"], iid)
                if self.stop_requested:
                    status = "中断"
                elif returncode == 0:
                    status = "完了"
                else:
                    status = f"エラー(code {returncode})"
            except Exception as e:
                status = "エラー"
                self.encode_queue.put(("log", f"[例外] {e}"))

            self.encode_queue.put(("status", iid, status, index, total))

        self.encode_queue.put(("all_done",))

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
                "時刻の項目は右クリックでVLC再生ができます)"
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
                    label="元のファイルをその時刻からVLCで再生",
                    command=lambda: self._play_with_vlc_at(source_path, seconds),
                )
                if output_path and os.path.isfile(output_path):
                    menu.add_command(
                        label="エンコード後のファイルをその時刻からVLCで再生",
                        command=lambda: self._play_with_vlc_at(output_path, seconds),
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


if __name__ == "__main__":
    app = App()
    app.mainloop()
