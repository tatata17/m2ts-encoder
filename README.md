# m2ts-encoder

TV録画(`.m2ts` / `.rpls`)を **一覧表示 → 設定を割り当て → まとめてエンコード → チャンネル別に仕分け** できる、Windows用の小さなツールです。
Python(tkinter)で動く **`m2ts_encoder.pyw` 1つだけ** で動作します(インストール不要)。

**👉 [使い方・更新履歴のページ](https://tatata17.github.io/m2ts-encoder/)**

- 番組名・チャンネル・放送日を一覧表示(rplsinfo.exe で録画データから取得)
- 「おまかせ」で、ファイルごとに音声・字幕・インターレース・放送局を自動判定してエンコード(HEVC / NVENC)
- 複数ファイルを上から順に自動エンコード(キュー)。ログは自動保存
- エンコード結果の自動診断(ノイズ・破損・失敗の疑いを検出)と、デコードノイズ検査
- エンコード済みファイルをチャンネル別フォルダへ自動仕分け
- メニューからワンクリックで最新版へアップデート

## 必要なもの

| もの | 説明 |
|---|---|
| Windows 10/11 | |
| Python 3 | 3.9以上を推奨。[python.org](https://www.python.org/downloads/windows/) からインストールします。インストーラーで **「Add python.exe to PATH」** と **「py launcher」** にチェックを入れてください |
| ffmpeg / ffprobe | **「full」版**を使います(ARIB字幕に必要な部品は、full版にだけ入っています)。`m2ts_encoder.pyw` と同じフォルダに置くか、PATHを通します |
| rplsinfo.exe | 番組名・チャンネル・放送日の取得に使います。[rplsinfo152.zip(v1.5.2)](https://github.com/tsukumijima/rplsinfo/releases/download/v1.5.2/rplsinfo152.zip) を解凍して、中の `rplsinfo.exe` を同じフォルダに置くか、PATHを通します(配布元: [tsukumijima/rplsinfo](https://github.com/tsukumijima/rplsinfo/releases)) |
| NVIDIAのGPU(推奨) | 既定のエンコード設定は `hevc_nvenc` です。無くても、Intel(QSV)・AMD(AMF)・CPU(libx265)でエンコードできます |

TsSplitter.exe は用意不要です(アプリに埋め込んであります)。

**ffmpeg の入れかた:** Windows 10/11 なら、コマンドプロンプトで `winget install Gyan.FFmpeg` を実行すると、full版が入り、PATHも自動で設定されます。入れたあとは `ffmpeg -version` で確認して、m2ts-encoder を起動し直してください。アプリを起動できていれば、メニュー「ツール」→「環境セットアップ...」からも入れられます(full版の `ffmpeg.exe` と `ffprobe.exe` を、同じフォルダに置きます)。手動で入れる方法や、PATHが分からないときの手順は、[使い方のページ](https://tatata17.github.io/m2ts-encoder/)の「ffmpeg の入れかた」を見てください(同じフォルダに置くだけでも動きます)。

## 起動のしかた

1. `m2ts_encoder.pyw` をダウンロードして、好きなフォルダ(録画ファイルのあるフォルダでも可)に置きます
2. 同じフォルダに `rplsinfo.exe`(と、必要なら `ffmpeg.exe` `ffprobe.exe`)を置きます
3. `m2ts_encoder.pyw` を **ダブルクリック**します(コマンドプロンプトは開きません)
4. 画面上部の「対象フォルダ」が、そのフォルダになり、自動でスキャンが始まります

> 一覧に何も出ないときは、**「サブフォルダも検索する」にチェック**してください。ブルーレイレコーダー等の録画は、`〇〇/STREAM/00001.m2ts` のようにフォルダの奥に入っていることが多いためです。

使い方の流れ(対象を選ぶ → 設定を決める → 実行)や、エンコード設定・診断・仕分けの説明は、[使い方のページ](https://tatata17.github.io/m2ts-encoder/)にあります。

## 更新のしかた

メニュー「**ヘルプ**」→「**アップデートを確認...**」を押します。新しい版があれば、更新内容が表示され、「はい」でダウンロード → 置き換え → 自動で再起動します。置き換え前の版は、`%LOCALAPPDATA%\m2ts_encoder\backup\` に自動でバックアップされます(最新5個)。エンコード中は更新できません。

## 困ったとき

| 症状 | 対処 |
|---|---|
| 「rplsinfo.exe が見つかりません」 | `rplsinfo.exe` を `m2ts_encoder.pyw` と同じフォルダに置く |
| 一覧に何も出ない | 画面上部の「サブフォルダも検索する」にチェック。`.m2ts` にもチェックが入っているか確認 |
| 「おまかせ」の判定が出ない | `ffprobe.exe` を同じフォルダに置くか、PATHを通す |
| `.pyw` をダブルクリックしても開かない | Pythonをインストールし直し、`py launcher` と `.pyw` の関連付けにチェックを入れる |
| 診断が「要確認」 | 診断の詳細で時刻を確認し、プレーヤー(VLCなど)で元のm2tsと出力の両方を見て比べる |

ほかの症状は、[使い方のページ](https://tatata17.github.io/m2ts-encoder/)の「困ったとき」を見てください。

## 更新履歴

[CHANGELOG.md](CHANGELOG.md) か、[使い方のページ](https://tatata17.github.io/m2ts-encoder/)の「更新履歴」を見てください。

## 開発者向け

[docs/DEVELOPING.md](docs/DEVELOPING.md) を参照してください。
