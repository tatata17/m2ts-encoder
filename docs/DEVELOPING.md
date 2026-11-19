# 開発メモ

## ファイルの役割
- `m2ts_encoder.pyw` … 本体。`APP_VERSION` が版番号。
- `version.json` … 最新の版番号・変更内容と、本体の SHA-256(アプリの更新が読みに来る)。手で書かない。
- `CHANGELOG.md` … 更新履歴。
- `tools/release.py` … 公開前の確認と、`version.json` の書き出し。
- `PLUGINS.md` … プラグイン(手元で足す拡張機能)の作りかた。プラグインの実物は、このリポジトリに入れない。
- `docs/index.html` … 使い方のページ(GitHub Pages で公開)。
- `docs/plugins.html` … プラグインの説明のページ。デザイン(`<style>`)と共通スクリプトは、使い方のページと同じ内容にそろえる。プラグインのしくみを変えたら、このページと `PLUGINS.md` も直す。
- `docs/sitemap.xml` … 検索エンジン向けのサイトマップ。

## 公開の手順
1. `m2ts_encoder.pyw` を直し、`APP_VERSION` を上げる
2. 起動して確かめる
3. `python tools/release.py "更新内容のひとこと"` … 確認して `version.json` を書く
   - 構文エラーがある・版番号が上がっていない・本体が小さすぎるときは、何も書かずに止まります
   - 本体を変えたら、同じ版のままでも必ずもう一度実行します
4. `CHANGELOG.md` と使い方のページの「更新履歴」に追記する
5. commit して `main` に push する

## SHA-256 について
- `version.json` の `sha256` は、改行を LF にそろえた本体の SHA-256 です。
- アプリは更新のとき、ダウンロードした本体を LF にそろえてから照合します(`download_update_source`)。公開側とアプリ側の計算を、片方だけ変えないでください。
- `*.pyw` と `*.py` は `.gitattributes` で LF に固定しています。

## 使い方ページ
m2ts-encoder / avs-maker / syncdub の3つの使い方ページは、同じデザイン・同じ書き方でそろえています。どれか1つを変えるときは、他の2つと食い違わないようにしてください。
