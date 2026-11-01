# Vercel 公開 作業ログ

最終更新：2026/11/01

## 結論（まずここだけ読めばOK）

- **Vercel でも公開できました。URL に GitHub のユーザー名は入っていません。**
  - **新しいURL：https://ai-news-hub-app.vercel.app/**
  - 第一候補の `ai-news-hub.vercel.app` は、すでに他の人が使っていて取れませんでした。そのため、第二候補の `ai-news-hub-app` にしました。
- GitHub Pages 版（https://ryotaflash2009-bit.github.io/ai-news-site/ ）も、そのまま残っています。両方とも公開中です。
- 有料プランへの登録・課金・パスワードやカード情報の入力は、していません（Vercel の無料プランの範囲です）。
- **Vercel 版も30分ごとに自動更新されます。あなたがやるべき残り作業はありません。**（下の(3)を参照）

---

## (1) 新しい URL

| 用途 | URL |
|---|---|
| **人に教える・公開用のURL（これを使ってください）** | **https://ai-news-hub-app.vercel.app/** |
| 自動で付いた予備のURL（同じ内容） | https://ai-news-hub-gules.vercel.app/ |

※ Vercel は、`ai-news-hub-ryotaflash2009-bit.vercel.app` のような「ユーザー名入りの管理用URL」も自動で作ります。これは Vercel の仕組み上、消すことができません。人に教えるのは、上の表の **ai-news-hub-app** のURLだけにしてください。サイトの画面には、ユーザー名やGitHubへのリンクは表示されません。

---

## (2) 確認結果（https://ai-news-hub-app.vercel.app/ で確認）

| タブ | 記事数 | 選択中タブ・見出しの色 | 表示 |
|---|---|---|---|
| Claude | 80件 | オレンジ | OK |
| ChatGPT | 80件 | ティールグリーン | OK |
| Gemini | 56件 | ブルー | OK |
| Grok | 64件 | シルバー | OK |
| DeepSeek | 49件 | 青紫 | OK |
| Copilot | 67件 | シアン | OK |

- 6タブすべてで、次のものが GitHub Pages 版と同じに表示されることを確認しました。
  - タブ・見出し・「元記事を読む →」ボタンのイメージカラー
  - 相対時間（「13分前」など）
  - フッターの権利表記
- 機能・デザイン・著作権まわり（全文を転載しないなど）は、一切変えていません。

---

## (3) 残り作業：なし（30分ごとの自動更新は有効化済み）

### 経緯
- Vercel 版を作り直すには、「Vercel に作り直しを頼む専用のURL（デプロイフック）」を GitHub に秘密情報として登録する必要があります。
- 最初の作業では、この登録が作業中の Claude の安全チェックで止められました。そのため、あなたの操作として残していました。
- その後、あなたから「Claudeに実行させる」と指示をもらったので、Claude が次の順に実行しました。
  1. デプロイフックの作成
  2. GitHub の Secrets（`VERCEL_DEPLOY_HOOK`）への登録
- 1回目は、URLの後ろに余分な記号（`",`）が付いたまま登録されてしまい、Vercel への依頼が失敗しました。正しいURLだけを登録し直して解決しました。`setup_vercel_hook.bat` の同じ不具合も直してあります。

### 確認結果
- GitHub Actions を手動で実行し、ログに「Vercel の再公開を依頼しました」と出ることを確認しました。
- Vercel 側で新しい公開（Ready）ができたことを確認しました。
- 公開URLの「取得」時刻が、その実行時刻（2026/11/01 15:36）に更新されたことも確認しました。
- これで、30分ごとの定期実行のたびに、GitHub Pages 版と Vercel 版の両方が最新ニュースで更新されます。

### 自分で確認したいとき
- https://github.com/ryotaflash2009-bit/ai-news-site/actions を開く
- 一番上の「Update news and publish」→「deploy」→「Refresh Vercel site」を開く
- 「Vercel の再公開を依頼しました」と出ていれば正常です
- `setup_vercel_hook.bat` は、もう実行する必要はありません。実行するとデプロイフックがもう1つ作られます（害はありません）。

---

## やったこと

1. **構成を確認した**
   - 公開用の静的HTML（6タブ分）は、GitHub に保存されているのではなく、GitHub Actions がその都度作っていました。
   - そこで Vercel 側でも、同じ `build.py` を動かして静的HTMLを作り、そのまま配信する形にしました。Flask を常時動かす方式ではありません。
2. **`vercel.json` を追加した**
   - Vercel に「Python の部品を入れて → build.py を実行して → dist フォルダを公開する」と伝える設定ファイルです。
   - 1回目は、Vercel のビルド環境の Python に直接部品を入れられずに失敗しました（「externally-managed-environment」というエラー）。専用の作業用環境（venv）に入れる形に直したところ、2回目で成功しました。
3. **Vercel プロジェクト `ai-news-hub` を作成した**
   - Vercel はすでにログイン済みでした。
   - この GitHub リポジトリを接続しました。その結果、**GitHub にコードを push すると、Vercel が自動で作り直して公開**します。
4. **`ai-news-hub-app.vercel.app` をプロジェクトのURLとして追加した**
5. **GitHub Actions の設定を変えた**（`.github/workflows/publish.yml`）
   - 30分ごとの定期実行のたびに、Vercel にも作り直しを頼むステップを追加しました。
   - デプロイフックが未登録の場合、このステップは何もせずスキップされます。エラーにはなりません。
6. **`setup_vercel_hook.bat` を追加した**（デプロイフックを作り直したいときのためのファイル）
7. **デプロイフックを作成し、GitHub の Secrets に登録した**（あなたの指示を受けて実行）
8. `.gitignore` に `.vercel/` などを追加しました。Vercel の接続情報や一時的な認証情報が、GitHub に上がらないようにするためです。

### 無料枠について
- Vercel 無料プラン（Hobby）の作り直し回数の上限は、1日100回です。30分ごとで1日48回なので、範囲内です。

---

## 困ったとき

| 症状 | 対処 |
|---|---|
| setup_vercel_hook.bat で「vercel」「login」系のエラー | 黒い画面（PowerShell）で `npx vercel login` を実行し、表示に従ってブラウザで Vercel にログインしてから、もう一度実行 |
| setup_vercel_hook.bat で「gh」「authentication」系のエラー | `gh auth login` を実行し、GitHub にログインしてから、もう一度実行 |
| Vercel 版のニュースが古いまま | Vercel のダッシュボード（https://vercel.com/dashboard ）→ ai-news-hub →「Deployments」で、最新の行が「Ready」になっているか確認。赤い「Error」なら、Claude に「Vercel のデプロイが失敗している」と伝えてください |
| 同じデプロイフックが2つできてしまった | 問題ありません。気になる場合は Vercel の ai-news-hub →「Settings」→「Git」→「Deploy Hooks」で古い方を削除 |
