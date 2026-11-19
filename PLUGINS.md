# プラグインの作りかた(m2ts-encoder)

くわしい説明は、[プラグインのページ](https://tatata17.github.io/m2ts-encoder/plugins.html)にあります。このファイルは、その要点です。

手元で足す拡張機能を、本体(`m2ts_encoder.pyw`)とは別のファイルとして置けます。
本体は自動更新で入れ替わりますが、プラグインは別のフォルダにあるので消えません。

- 置き場所: 「ツール」→「プラグインフォルダを開く」で開くフォルダ(アプリのデータフォルダの `plugins`)
- 読み込み: 起動時に、フォルダの中の `*.py` をファイル名の順に読み込みます(置いたあとは、アプリを起動しなおします。メニュー「ファイル」→「再起動」が使えます)
- プラグインが1つも無ければ、本体の動きは何も変わりません
- プラグインは、アプリと同じ権限で動く普通の Python プログラムです。中身の分かるものだけを置いてください
- このリポジトリには、プラグインの実物は入れません

## ファイルに書くもの

```python
PLUGIN_API_VERSION = 1        # 本体の PLUGIN_API_VERSION と同じ数。違うと読み込まれません

def register(host):           # 起動時に1回呼ばれます
    host.log("[sample] プラグインを読み込みました")
    host.add_tool_menu_item("サンプルプラグインの挨拶", lambda: host.log("[sample] こんにちは"))
    host.register_scan_extension(".sample", default=True)
    host.register_program_info_provider(
        lambda path: {"program_name": "サンプル番組", "channel": "サンプルch", "broadcast_date": "2026/01/01"}
        if path.lower().endswith(".sample") else None
    )
```

読み込みの途中でエラーになったプラグインは、そのプラグインだけ無効になり、理由がログ欄に出ます
(途中まで登録したメニューなども取り消されます)。本体とほかのプラグインは、そのまま動きます。

## host で使えるもの

| 名前 | 内容 |
|---|---|
| `host.api_version` | 本体の API の版(整数) |
| `host.app` | 本体のウインドウ(`App`) |
| `host.settings` | 本体と共有の設定(dict)。自分用の値は、ほかと重ならないキー名で入れます |
| `host.save_settings()` | 設定をファイルに保存します |
| `host.log(msg)` | 本体のログ欄に1行出します(どのスレッドから呼んでもかまいません) |
| `host.add_tool_menu_item(label, command)` | 「ツール」メニューに項目を足します。`command` は引数なしで呼べるもの |
| `host.register_scan_extension(ext, default=True)` | スキャンの対象にする拡張子を足し、検索対象の並びにチェックボックスを出します |
| `host.register_program_info_provider(fn)` | 番組情報を返す関数を登録します |
| `host.register_output_name_fallback(fn)` | エンコード後の出力名を決める関数を登録します |

### `register_scan_extension(ext, default=True)`

- この拡張子のファイルは、番組情報をまず `register_program_info_provider` に聞きます。そこで取れなかったときだけ、ファイルそのものを rplsinfo で読んでみます(中身が放送の TS なら、拡張子が `.m2ts` でなくても読めます)
- 対になる rpls は探しません
- チェックの状態は設定に覚えます(`default` は、まだ覚えていないときの初期値)
- `.m2ts` と `.rpls` は本体のものなので、登録できません
- 足した拡張子のファイルは、`.m2ts` と同じように、録画そのもののファイルとして扱われます。「変換済みm2tsを削除」とノイズ検査の対象にもなります

### `register_program_info_provider(fn)`

- `fn(path)` は、`{"program_name": str, "channel": str, "broadcast_date": str}` の dict か `None` を返します
- スキャンのとき、rpls から番組名が取れなかったファイルについて、登録した順に呼ばれます。最初に dict を返したものが使われます
- `broadcast_date` は `2026/01/01` の形です。空の項目は、本体の値のままになります
- 画面とは別のスレッドで呼ばれます。関数の中で、画面の部品を触らないでください

### `register_output_name_fallback(fn)`

- `fn(row, output_path)` は、新しい出力パスか `None` を返します。`row` はその行の情報(dict の写し。`path` / `program_name` / `channel` / `broadcast_date` など)です
- エンコードのあと、rplsinfo から名前が取れなかったときに、本体のふだんの処理より前に、登録した順に呼ばれます
- 関数の中で名前を変えて、そのパスを返してもかまいません。付けたい名前のパスだけを返した場合は、本体が名前を変えます(同じ名前のファイルがすでにあるときは変えません)
- 画面とは別のスレッドで呼ばれます
