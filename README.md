# AI News Hub

主要なAIサービス（Claude / ChatGPT / Gemini / Grok / DeepSeek / Copilot）の最新ニュースを、サービスごとのタブで見られるまとめサイトです。

各ニュースは、各配信元がRSSや公式のニュース一覧ページで公開している情報から、タイトル・短い抜粋（140字以内）・元記事へのリンクのみを掲載しています。記事の権利は各配信元に帰属します。

## しくみ

- `app.py` … 取得先の設定（`SERVICES`）、ニュースの取得、ページ表示。手元で動かすローカルサーバーも兼ねる
- `api/index.py` … Vercel 版の入り口。ページが見られたときにその場でニュースを取得し、Vercel の配信網に5分ほど保存して使い回す（いつ見ても最大十数分前までの内容）
- `build.py` … 全タブ分のニュースを取得し、`dist/` に静的なHTMLとして保存する（GitHub Pages 版）。Vercel では、取得が全部失敗したときの予備データ（`data/タブ名.json`）だけを作る
- `.github/workflows/publish.yml` … GitHub Actions が定期的に（予定は30分ごと。GitHub側の混雑で数時間あくことがある）テストと `build.py` を実行し、GitHub Pages に公開する
- `tests/` … 正確さのルール（新しい順・重複・関連性・取得失敗の表示など）の自動テスト。公開の前に毎回実行し、失敗したら公開しない

## テストを手元で実行する

- `.venv\Scripts\python.exe -m unittest discover -s tests -v`

## 手元で動かす

- `start.bat` をダブルクリック → ブラウザで http://127.0.0.1:5000 を開く
