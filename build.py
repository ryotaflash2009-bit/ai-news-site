"""公開用の静的ページを作る。

ニュースを全サービス分取得して、dist フォルダに HTML として保存する。
公開サイトでは、GitHub Actions がこのスクリプトを定期的に(30分ごと)実行し、
できた dist フォルダを GitHub Pages に公開する。見る人は保存済みのページを読むだけなので速く安定する。

あるタブの取得先がすべて失敗したときは、公開中のサイトに保存してある前回の取得結果(data/タブ名.json)を
読み込み、「最後に取得できた時点の内容で、最新ではない」ことを画面に出して公開する。

手元で試すとき: .venv\\Scripts\\python.exe build.py  → dist\\index.html をブラウザで開く
"""

import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import app
from app import DEFAULT_SERVICE, SERVICES, USER_AGENT, get_news, render_page

DIST = Path(__file__).parent / "dist"
# 前回の取得結果を読みに行く場所(公開中のサイト)。環境変数 NEWS_SNAPSHOT_URL で変えられる
SNAPSHOT_URL = os.environ.get("NEWS_SNAPSHOT_URL", "https://ai-news-hub-app.vercel.app/data/")


def page_file(key):
    """タブごとのファイル名。最初に開くタブ(Claude)は index.html にする。"""
    return "index.html" if key == DEFAULT_SERVICE else f"{key}.html"


def load_snapshot(key):
    """公開中のサイトから、前回取得できたニュースを読み込む(読めなければ None)。"""
    try:
        req = urllib.request.Request(SNAPSHOT_URL + f"{key}.json", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.load(res)
        for item in data["items"]:
            item["published"] = datetime.fromisoformat(item["published"])
        return {"time": 0, "items": data["items"], "errors": [], "last_success": data["last_success"]}
    except Exception as e:
        print(f"[情報] {key}: 前回の取得結果を読み込めませんでした ({e!r})")
        return None


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
            snapshot = load_snapshot(key)
            if snapshot:
                app._cache[key] = snapshot  # time=0 なので必ず取り直す。全部失敗したときだけ使われる
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

    if not fresh:
        # どのタブも1件も取れなかった(ネットワーク障害など)ときは失敗扱いにして、前回の公開内容をそのまま残す
        # (その場合も、ページ側で「何時間前に取得した内容か」を表示する)
        print("[エラー] すべてのタブでニュースを取得できませんでした")
        sys.exit(1)


if __name__ == "__main__":
    main()
