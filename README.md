# AI News Hub

主要なAIサービス（Claude / ChatGPT / Gemini / Grok / DeepSeek / Copilot）の最新ニュースを、サービスごとのタブで見られるまとめサイトです。

各ニュースは、各配信元がRSSや公式のニュース一覧ページで公開している情報から、タイトル・短い抜粋（140字以内）・元記事へのリンクのみを掲載しています。記事の権利は各配信元に帰属します。

## しくみ

- `app.py` … 取得先の設定（`SERVICES`）、ニュースの取得、ページ表示。手元で動かすローカルサーバーも兼ねる
- `build.py` … 全タブ分のニュースを取得し、`dist/` に静的なHTMLとして保存する（GitHub Pages 版・Vercel 版とも同じ。見られたときに計算しないので、Vercel の無料枠の計算時間を使わない）
- `.github/workflows/publish.yml` … GitHub Actions が約30分ごとに（公開後に次の実行を自分で予約する。GitHub の定期実行は混雑で数時間あくため、予約が途切れたときの再開役）テストと `build.py` を実行し、GitHub Pages に公開する
- `tests/` … 正確さのルール（新しい順・重複・関連性・取得失敗の表示など）の自動テスト。公開の前に毎回実行し、失敗したら公開しない

## テストを手元で実行する

- `.venv\Scripts\python.exe -m unittest discover -s tests -v`

## 手元で動かす

- `start.bat` をダブルクリック → ブラウザで http://127.0.0.1:5000 を開く
