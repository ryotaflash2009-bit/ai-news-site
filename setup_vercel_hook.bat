@echo off
chcp 65001 > nul
cd /d %~dp0
echo ============================================================
echo  Vercel 版の「30分ごとの自動更新」を有効にします
echo  (Vercel に再公開用のURL=デプロイフックを作り、GitHub の Secrets に保存)
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$out = npx --yes vercel@65.9.0 deploy-hooks create github-actions-30min --ref main 2>&1 | Out-String;" ^
  "$m = [regex]::Match($out, 'https://api\.vercel\.com/[^\s,\x22]+');" ^
  "if (-not $m.Success) { Write-Host $out; Write-Host 'Failed to create deploy hook.'; exit 1 }" ^
  "$m.Value | gh secret set VERCEL_DEPLOY_HOOK; if ($LASTEXITCODE -ne 0) { exit 1 }" ^
  "Write-Host 'Saved VERCEL_DEPLOY_HOOK to GitHub Secrets.'"
if errorlevel 1 goto fail
echo.
echo 完了しました！次の定期実行（毎時17分・47分ごろ）から、Vercel 版も自動で更新されます。
pause
exit /b 0

:fail
echo.
echo 途中でエラーが出ました。VERCEL_LOG.md の「困ったとき」を見てください。
pause
exit /b 1
