@echo off
chcp 65001 > nul
cd /d %~dp0
echo ============================================================
echo  AI News Hub をインターネットに公開します
echo  (GitHub に公開リポジトリ ai-news-site を作り、GitHub Pages で公開)
echo ============================================================
echo.

echo [1/3] GitHub に公開リポジトリを作成しています...
git remote get-url origin > nul 2>&1
if errorlevel 1 (
  gh repo create ai-news-site --public --description "AI News Hub - AI news digest" --source . --remote origin
  if errorlevel 1 goto fail
) else (
  echo     すでに作成済みなので、この手順は飛ばします。
)
echo.

echo [2/3] GitHub Pages を有効にしています...
gh api -X POST "repos/{owner}/{repo}/pages" -f build_type=workflow > nul 2>&1
if errorlevel 1 (
  gh api -X PUT "repos/{owner}/{repo}/pages" -f build_type=workflow > nul
  if errorlevel 1 goto fail
)
echo     OK
echo.

echo [3/3] コードをアップロードしています（アップロード後、自動でニュース取得と公開が始まります）...
git push -u origin main
if errorlevel 1 goto fail
echo.

for /f "delims=" %%u in ('gh api user --jq .login') do set GHUSER=%%u
echo ============================================================
echo  完了しました！
echo  2〜3分後に、次のURLでサイトが見られるようになります：
echo.
echo     https://%GHUSER%.github.io/ai-news-site/
echo.
echo  公開の進み具合は、次のページで確認できます（緑のチェックが付けば完了）：
echo     https://github.com/%GHUSER%/ai-news-site/actions
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ************************************************************
echo  途中でエラーが出ました。上に表示されたメッセージを確認してください。
echo  PHASE4_LOG.md の「困ったとき」も参考にしてください。
echo ************************************************************
pause
exit /b 1
