"""公開用の静的ページを作る。

ニュースを全サービス分取得して、dist フォルダに HTML として保存する。
GitHub Pages 版では、GitHub Actions がこのスクリプトを定期的に実行し、
できた dist フォルダを公開する。見る人は保存済みのページを読むだけなので速く安定する。

Vercel 版も同じように、ビルドのときに作ったページをそのまま配る(見られたときに計算しないので、無料枠の
計算時間を使わない)。GitHub Actions が定期実行のたびに Vercel の作り直しを依頼する。

あるタブの取得先がすべて失敗したときは、公開中のサイトに保存してある前回の取得結果を読み込み、
「最後に取得できた時点の内容で、最新ではない」ことを画面に出す(app.get_news を参照)。

手元で試すとき: .venv\\Scripts\\python.exe build.py  → dist\\index.html をブラウザで開く
"""

import json
import shutil
import sys
from pathlib import Path

import app
from app import SERVICES, get_news, page_file, render_page

DIST = Path(__file__).parent / "dist"


def save_snapshot(key, news):
    """次回のために、今回表示した内容を data/タブ名.json に保存する(タイトル・短い抜粋・リンクのみ)。"""
    items = [{**i, "published": i["published"].isoformat()} for i in news["items"]]
    data = {"last_success": news["last_success"], "stale": news["stale"], "errors": news["errors"], "items": items}
    (DIST / "data" / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write_sitemap():
    """検索エンジン向けに、正式なURLのページ一覧(sitemap.xml)と robots.txt を作る。"""
    urls = "".join(f"<url><loc>{app.canonical_url(key)}</loc><changefreq>hourly</changefreq></url>"
                   for key in SERVICES)
    (DIST / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n', encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {app.SITE_URL}sitemap.xml\n",
                                     encoding="utf-8")


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
            (DIST / page_file(key)).write_text(render_page(key, page_file), encoding="utf-8")
            save_snapshot(key, news)
            print(f"{page_file(key)}: {len(news['items'])}件")

    # GitHub Pages に「そのまま公開する」ことを伝える空ファイル
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    write_sitemap()

    if not fresh:
        # どのタブも1件も取れなかった(ネットワーク障害など)ときは失敗扱いにして、前回の公開内容をそのまま残す
        # (その場合も、ページ側で「何時間前に取得した内容か」を表示する)
        print("[エラー] すべてのタブでニュースを取得できませんでした")
        sys.exit(1)


if __name__ == "__main__":
    main()
