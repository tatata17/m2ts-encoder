# m2ts-encoder

TV録画(.m2ts / .rpls)の一覧表示・エンコードキュー・チャンネル別仕分けを行う、Windows用の小さなツールです。
Python(tkinter)で動く `m2ts_encoder.pyw` 1つだけで動作します。

## 使い方
1. `m2ts_encoder.pyw` をダウンロードして、録画ファイルのあるフォルダ(または好きなフォルダ)に置く
2. `rplsinfo.exe` と `ffmpeg` / `ffprobe` を用意する
3. `m2ts_encoder.pyw` をダブルクリックして起動する

## アップデート
アプリのメニュー「ヘルプ」→「アップデートを確認」を押すと、最新版を自動でダウンロードして置き換え、再起動します。
置き換え前の版は `%LOCALAPPDATA%\m2ts_encoder\backup\` に自動でバックアップされます(最新5個)。

## ファイル
- `m2ts_encoder.pyw` : 本体
- `version.json` : 最新版の番号と更新内容(アプリが参照します)
