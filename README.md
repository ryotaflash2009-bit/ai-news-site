# AI News Hub

主要なAIサービス（Claude / ChatGPT / Gemini / Grok / DeepSeek / Copilot）の最新ニュースを、サービスごとのタブで見られるまとめサイトです。

各ニュースは、各配信元がRSSや公式のニュース一覧ページで公開している情報から、タイトル・短い抜粋（140字以内）・元記事へのリンクのみを掲載しています。記事の権利は各配信元に帰属します。

## しくみ

- `app.py` … 取得先の設定（`SERVICES`）、ニュースの取得、ページ表示。手元で動かすローカルサーバーも兼ねる
- `build.py` … 全タブ分のニュースを取得し、`dist/` に静的なHTMLとして保存する
- `.github/workflows/publish.yml` … GitHub Actions が30分ごとに `build.py` を実行し、GitHub Pages に公開する

## 手元で動かす

- `start.bat` をダブルクリック → ブラウザで http://127.0.0.1:5000 を開く
