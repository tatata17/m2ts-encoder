#!/usr/bin/env python3
"""自動テストをまとめて実行する。

  python tests/run_tests.py            … 全部
  python tests/run_tests.py sort       … 名前に sort を含むテストファイルだけ(test_sort.py)
  python tests/run_tests.py -v         … 1項目ずつ表示

・録画データも、実機の GPU も、ffmpeg も使わない。画面も開かない。
・設定・ログ・出力は、テスト専用の一時フォルダに作り、終わったら消す(tests/support.py)。
・失敗したときは、どの項目が、なぜ失敗したかを最後にまとめて出し、終了コード 1 で終わる。
・tools/release.py は、公開の前にこれを実行する。失敗したら、version.json を書かずに止まる。
"""
import os
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
for stream in (sys.stdout, sys.stderr):                  # Windows のコンソールでも、日本語で落ちないように
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def repo_snapshot():
    """リポジトリの中のファイルの一覧(大きさと更新時刻)。テストが書きかえていないかを、あとで比べる"""
    found = {}
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            path = os.path.join(folder, name)
            try:
                info = os.stat(path)
            except OSError:
                continue
            found[os.path.relpath(path, ROOT)] = (info.st_size, info.st_mtime_ns)
    return found


def describe(test):
    """失敗した項目の説明: ファイル › クラス › 項目名 と、その項目の説明文(無ければ、クラスの説明文)の1行目"""
    if not isinstance(test, unittest.TestCase):          # ファイルごと読みこめなかった場合など
        return str(test), ""
    doc = (getattr(test, "_testMethodDoc", None) or type(test).__doc__ or "").strip().splitlines()
    return f"{type(test).__module__}.py › {type(test).__name__} › {test._testMethodName}", (doc[0].strip() if doc else "")


def reason_of(traceback_text):
    """トレースバックのうち、原因を書いた部分(「AssertionError: …」から数行)"""
    lines = traceback_text.rstrip().splitlines()
    for index, line in enumerate(lines):
        if line and not line.startswith(" ") and not line.startswith("Traceback"):
            return "\n".join(l for l in lines[index:index + 8] if l.strip())
    return traceback_text.strip()


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.problems = []                               # (種類, テスト, サブテストの条件, トレースバック)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.problems.append(("失敗", test, "", self.failures[-1][1]))

    def addError(self, test, err):
        super().addError(test, err)
        self.problems.append(("エラー", test, "", self.errors[-1][1]))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            kind = "失敗" if issubclass(err[0], test.failureException) else "エラー"
            store = self.failures if kind == "失敗" else self.errors
            self.problems.append((kind, test, subtest._subDescription(), store[-1][1]))

    def printErrors(self):                               # 既定の英語のまとめは出さない(下で、日本語でまとめる)
        pass


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv[1:]
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        return 0
    names = sorted(p.stem for p in HERE.glob("test_*.py") if not args or any(a in p.stem for a in args))
    if not names:
        print("実行するテストが見つかりません: " + " ".join(args))
        return 1

    before = repo_snapshot()
    started = time.time()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    counts = {}
    for name in names:
        tests = loader.loadTestsFromName(name)
        counts[name] = tests.countTestCases()
        suite.addTests(tests)
    runner = unittest.TextTestRunner(resultclass=Result, verbosity=2 if verbose else 1, stream=sys.stdout)
    result = runner.run(suite)
    changed = sorted(k for k in set(before) | set(repo_snapshot()) if before.get(k) != repo_snapshot().get(k))

    print()
    for name in names:
        bad = sum(1 for _kind, test, _sub, _tb in result.problems if type(test).__module__ == name)
        print(f"  {'×' if bad else '○'} {name}.py  {counts[name]}項目" + (f"(うち {bad} 件が失敗)" if bad else ""))
    print()
    if result.problems:
        print("=" * 70)
        print(f"失敗したテスト: {len(result.problems)} 件")
        print("=" * 70)
        for number, (kind, test, sub, traceback_text) in enumerate(result.problems, 1):
            where, doc = describe(test)
            print(f"\n[{number}] {kind}: {where}")
            if doc:
                print(f"    内容: {doc}")
            if sub:
                print(f"    条件: {sub}")
            print("    原因: " + reason_of(traceback_text).replace("\n", "\n          "))
            print("    ---- くわしい記録 ----")
            print("    " + traceback_text.rstrip().replace("\n", "\n    "))
    if changed:
        print("=" * 70)
        print("テストが、リポジトリの中のファイルを書きかえました(テストは、一時フォルダの外にさわってはいけません):")
        for name in changed:
            print("  " + name)
    ok = result.wasSuccessful() and not changed
    skipped = f"、とばした項目 {len(result.skipped)}" if result.skipped else ""
    print(f"\n{'テストは、すべて通りました' if ok else 'テストに失敗しました'}"
          f"({result.testsRun}項目{skipped}、{time.time() - started:.1f}秒)")
    for test, why in result.skipped:
        print(f"  とばした項目: {describe(test)[0]}  … {why}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
