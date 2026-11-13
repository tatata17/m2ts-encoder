#!/usr/bin/env python3
"""公開前の確認と、version.json の書き出し。

  python tools/release.py                      … 更新内容のひとことは空(同じ版の書き直しなら、今の文を残す)
  python tools/release.py "更新内容のひとこと"   … アップデートの案内に出す文を付ける

本体(m2ts_encoder.pyw)の APP_VERSION を読み、version.json(version / file / sha256 / notes)を書く。
SHA-256 は、改行を LF にそろえた中身で計算する(アプリが更新のときに、同じ計算で照合する)。
構文エラーがある・版番号が上がっていない・本体が小さすぎる、のどれかなら、何も書かずに止まる。
同じ本体でもう一度実行すると、同じ version.json になる。
"""
import hashlib
import json
import os
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_FILE = "m2ts_encoder.pyw"
MIN_SIZE = 100_000   # アプリ側は、これより小さいファイルを「壊れている」として受け付けない


def vkey(version):
    return tuple(int(x) for x in re.findall(r"\d+", str(version)))


def main():
    args = sys.argv[1:]
    if len(args) > 1 or (args and args[0] in ("-h", "--help")):
        sys.exit(__doc__)
    src = ROOT / APP_FILE
    raw = src.read_bytes().replace(b"\r\n", b"\n")      # リポジトリの中身(LF)と同じにして計算する
    code = raw.decode("utf-8")
    try:
        py_compile.compile(str(src), doraise=True)
    except py_compile.PyCompileError as e:
        sys.exit(f"{APP_FILE}: 構文エラーがあります(何も変えていません)\n{e.msg}")
    if len(raw) < MIN_SIZE:
        sys.exit(f"{APP_FILE}: 小さすぎます ({len(raw)} バイト)。アプリ側の確認に通りません")
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', code, re.M)   # アプリ側の確認と同じ読み方
    if not m or not vkey(m.group(1)):
        sys.exit(f"{APP_FILE}: APP_VERSION が見つかりません")
    ver = m.group(1)
    sha = hashlib.sha256(raw).hexdigest()

    out = ROOT / "version.json"
    old = {}
    if out.exists():
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
            if not isinstance(old, dict):
                old = {}
        except ValueError:
            print("注意: 今の version.json が読めません(空か、壊れています)。新しく書き直します")
    same_version = vkey(old.get("version", "")) == vkey(ver)
    if old.get("version"):
        # 版が下がる・同じ版なのに中身が違う、は止める(sha256 の無い古い version.json に、初めて付けるときは通す)
        if vkey(ver) < vkey(old["version"]) or (same_version and old.get("sha256") and sha != old["sha256"]):
            sys.exit(f"版番号が上がっていません (今 {old['version']})。APP_VERSION を上げてください")
    notes = args[0] if args else (str(old.get("notes", "")) if same_version else "")
    info = {"version": ver, "file": APP_FILE, "sha256": sha, "notes": notes}

    # 空のファイルが残らないように、別名に書ききって、読み直して確かめてから入れ替える
    text = json.dumps(info, ensure_ascii=False, indent=2) + "\n"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    if json.loads(tmp.read_text(encoding="utf-8")) != info:
        tmp.unlink()
        sys.exit("version.json の書き出しを確かめられませんでした(何も変えていません)")
    os.replace(tmp, out)
    print(f"version.json を書きました: v{ver}  sha256 {sha[:12]}…")
    print("忘れずに: CHANGELOG.md と docs/index.html の更新履歴に書く")


if __name__ == "__main__":
    main()
