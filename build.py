"""公開用の静的ページを作る。

ニュースを全サービス分取得して、dist フォルダに HTML として保存する。
GitHub Pages 版では、GitHub Actions がこのスクリプトを定期的に実行し、
できた dist フォルダを公開する。見る人は保存済みのページを読むだけなので速く安定する。

Vercel 版では、ページは見られたときにその場で作る(api/index.py)。ここでは、取得がすべて失敗したときの
予備として使う「前回の取得結果」(data/タブ名.json)だけを作る。

あるタブの取得先がすべて失敗したときは、公開中のサイトに保存してある前回の取得結果を読み込み、
「最後に取得できた時点の内容で、最新ではない」ことを画面に出す(app.get_news を参照)。

手元で試すとき: .venv\\Scripts\\python.exe build.py  → dist\\index.html をブラウザで開く
"""

import json
import os
import shutil
import sys
from pathlib import Path

import app
from app import SERVICES, get_news, page_file, render_page

DIST = Path(__file__).parent / "dist"
# Vercel のビルド中は環境変数 VERCEL が "1" になる。そのときはページを作らず、予備のデータだけを作る
ON_VERCEL = bool(os.environ.get("VERCEL"))


def save_snapshot(key, news):
    """次回のために、今回表示した内容を data/タブ名.json に保存する(タイトル・短い抜粋・リンクのみ)。"""
    items = [{**i, "published": i["published"].isoformat()} for i in news["items"]]
    data = {"last_success": news["last_success"], "stale": news["stale"], "errors": news["errors"], "items": items}
    (DIST / "data" / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "data").mkdir(parents=True)

    fresh = 0
    with app.app.app_context():
        for key in SERVICES:
            news = get_news(key)
            for e in news["errors"]:
                print(f"[警告] {key}: 取得失敗 {e}")
            if news["stale"]:
                when = app.to_jst(app.utc(news["last_success"]))
                print(f"[警告] {key}: 取得先がすべて失敗。前回 ({when}) の内容 {len(news['items'])}件を「最新ではない」と表示")
            else:
                fresh += 1
            if not ON_VERCEL:
                (DIST / page_file(key)).write_text(render_page(key, page_file), encoding="utf-8")
            save_snapshot(key, news)
            print(f"{page_file(key)}: {len(news['items'])}件")

    # GitHub Pages に「そのまま公開する」ことを伝える空ファイル
    (DIST / ".nojekyll").write_text("", encoding="utf-8")

    if not fresh:
        # どのタブも1件も取れなかった(ネットワーク障害など)ときは失敗扱いにして、前回の公開内容をそのまま残す
        # (その場合も、ページ側で「何時間前に取得した内容か」を表示する)
        print("[エラー] すべてのタブでニュースを取得できませんでした")
        sys.exit(1)


if __name__ == "__main__":
    main()
