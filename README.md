# PyBot Live Lab — ルールベースAIをライブ解剖する

Hugging Face の [PyBot](https://github.com/huggingface/pybot) を **そのまま動かし**、候補回答・優先度・選択されたモジュール・対応コード・ルールの実行行を調べる、データサイエンス勉強会用のローカルWebアプリです。

- Mac: `start_mac.command` をダブルクリック
- Windows: `start_windows.bat` をダブルクリック
- 共通: Python 3.8+ で `python launch.py`
- 詳細な操作説明: `docs/MANUAL.html`

初回に公開済みPyBotを固定コミットからダウンロードします（初回のみネット接続が必要）。外部API、LLM、GPU、pipライブラリは不要です。PyBot自身もルールベースです。開いたブラウザとローカルPCの間だけで処理します。

**元のPyBotの著作権・ライセンスは Hugging Face contributors / Apache-2.0 に従います。** 本アプリは元コードを修正・再配布せず、初回取得後に `.runtime/` に保持します。

> 実行追跡は同じ会話を再実行して取得します。乱数や内部状態により差異が生じた場合は画面に明示します。候補の採用理由は「観測事実」と「コードからの推察」を分けて考察してください。

## 運用

最初にユーザーとAIの会話を試し、右パネルで候補の優先度と採択結果を観察し、候補を選んでソースコードを確認します。「実行行を追跡」は、選んだモジュールとarbiterの通過行を観測します。初心者向けのシナリオと上級者向けの議論問いを用意しています。

開発方針は `AGENTS.md`、検証は `python -m unittest discover -s tests -v` を参照してください。

## 音声入力とプライバシー
質問欄横の「音声」でブラウザの音声認識を開始し、文字起こしを確認してから「送信」します。日本語と英語を切り替えられます。Web Speech API非対応のブラウザでは、macOSの音声入力またはWindowsの `Win+H` を使ってください。

**重要**: 音声認識はブラウザの実装に依存し、ブラウザ提供元のサービスへ音声データが送信される場合があります。音声入力が完全オフラインであるとは保証できません。PyBot本体の応答は従来どおりローカルのルールのみで生成し、音声ファイルはアプリに保存しません。

## 資料とオフライン配布
- `docs/MANUAL.html` : 一枚だけを保存してもスタイルと画像が崩れない自己完結HTML
- `docs/RESEARCH.html` : PyBot原典、評価、関連文献と議論ポイント
- `docs/MANUAL.source.html` + `docs/manual.css` : 手動編集用ソース。 `python tools/build_manual.py` で配布版を生成
