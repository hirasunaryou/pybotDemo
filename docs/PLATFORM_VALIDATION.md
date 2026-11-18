# PyBot Live Lab — 対応OS・表示品質の検証

この文書は「何を自動確認できたか／実機で何を見ればよいか」を明確にするためのものです。MacやWindowsのデスクトップ操作を、人間が確認したと誤解させないようにします。

## 実装方針

- オリジナルの `huggingface/pybot` を固定リビジョンで取り込み、内部コードは変更しません。
- 本体・WebサーバーはPython標準ライブラリのみで動きます。モデル重み・GPU・追加pipパッケージは不要です。
- Windows: `start_windows.bat`、macOS: `start_mac.command`、共通: `python launch.py`。
- HTMLとJavaScriptはUTF-8に統一し、`<meta charset="utf-8">` を使用します。
- UIはOSテーマに連動してライト／ダークを初期選択し、ボタンでも切り替えられます。表示設定のみブラウザに保存します。
- 日本語のブラウザ画像はNoto Sans CJK JPなど日本語字形を持つフォントがある撮影環境で作成します。
- HTMLマニュアルはCSSと実画面PNGを内蔵し、単体で読める形式です。

## 自動テスト

| 対象 | 自動検証の内容 | まだ実機確認が必要な点 |
| --- | --- | --- |
| Windows | Python 3.11・ユニット／HTTPテスト、Windowsバッチの起動から実PyBotソースとWeb APIを確認 | SmartScreen・既定ブラウザ・権限・マイク入力 |
| macOS | Python 3.11・ユニット／HTTPテスト、bashスクリプトから実PyBotソースとWeb APIを確認 | Gatekeeper・ZIP展開後の実行許可・既定ブラウザ・マイク入力 |
| Linux（CI） | 実PyBotに質問し、回答候補・行トレースの整合を確認 | 適宜OS実機 |
| デスクトップUI | Chromiumでダーク／ライトを切替、代表的な背景と文字色のコントラスト比4.5:1以上を検査し、両方の実スクリーンショットを取得 | 実モニタ・多様なフォント設定 |
| 日本語表示 | UTF-8読込の厳密チェック、日本語フォント導入、Canvasで異なる漢字が異なる字形に描画されるか検査 | 各OS上の実ブラウザ描画 |
| モバイル幅 | Chromiumの幅390pxで意図しない横スクロールがないか検査 | iPhone・Android実機 |
| HTML資料 | CSS・画像埋込とファイル直接表示をChromiumで確認 | 配布後の個別環境 |
| 音声入力 | モック音声認識で文字起こし後に自動送信しないこと／非対応ブラウザの案内を確認 | 実マイク・音声認識サービス・ブラウザごとの認識精度 |

最新のCI結果は [GitHub Actions](https://github.com/hirasunaryou/pybotDemo/actions) で確認できます。記載の試験項目は「設定済みの検証」であり、未実行／失敗時はGitHub Actions上の結果を優先してください。

## 手元で起動と点検を行うとき

1. 最新版を取得し、利用するOSの起動ファイルを実行します。まず画面で日本語が四角い記号になっていないか確認します。
2. **ライト／ダーク**を切り替えます。文字、入力欄、回答候補、選択状態がそれぞれ読みやすいかを確認します。
3. 「名前と記憶」から2回質問し、候補が表示されること、コード画面に移動できることを確かめます。
4. マイクを使う場合は声を認識できるか確認します。認識文字は送信前に修正可能です。
5. `docs/MANUAL.html` をファイル単体で開き、レイアウトと実画面スクリーンショットが表示されることを確認します。

アプリ起動後、別の診断を行いたい場合は、アプリを終了して次のコマンドを実行します。

```bash
python launch.py --self-check
python -m unittest discover -s tests -v
```

`--self-check` は実PyBotをセットアップし、ローカルWeb API・ソースコード・HTMLマニュアルを確認した後に終了します。ブラウザは開きません。

## スクリーンショットの扱い

- `docs/images/overview.png`: 実PyBotのダーク画面
- `docs/images/overview-light.png`: 同じ会話のライト画面
- `docs/images/code-trace.png`: 実PyBotのコード追跡画面
- `docs/images/manual-preview.png`: HTMLマニュアルのプレビュー
- `docs/images/research-preview.png`: 研究資料ページのプレビュー

画像はモックではなく、実アプリをChromium上で動かして撮影します。画像の更新は `tools/capture_manual.py` と `.github/workflows/screenshots.yml` が担当します。技術説明中の概念図は、実行ログとは別物として明記します。

## 表示・音声に関する制約

- Web Speech APIはブラウザ依存で、一部の実装では音声を外部サービスへ送る可能性があります。音声の完全オフライン動作は保証しません。
- 解析用の実行行トレースは会話の**再実行**に基づきます。回答が一致しないときは元のターンの確定経路として扱えません。
- MacとWindowsのOS権限ダイアログやマイクを伴う操作は、今後の実機確認が必要です。
