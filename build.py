"""公開用の静的ページを作る。

ニュースを全サービス分取得して、dist フォルダに HTML として保存する。
公開サイトでは、GitHub Actions がこのスクリプトを定期的に(30分ごと)実行し、
できた dist フォルダを GitHub Pages に公開する。見る人は保存済みのページを読むだけなので速く安定する。

手元で試すとき: .venv\\Scripts\\python.exe build.py  → dist\\index.html をブラウザで開く
"""

import shutil
import sys
from pathlib import Path

from app import DEFAULT_SERVICE, SERVICES, app, get_news, render_page

DIST = Path(__file__).parent / "dist"


def page_file(key):
    """タブごとのファイル名。最初に開くタブ(Claude)は index.html にする。"""
    return "index.html" if key == DEFAULT_SERVICE else f"{key}.html"


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    empty = []
    with app.app_context():
        for key in SERVICES:
            items, errors = get_news(key)
            for e in errors:
                print(f"[警告] {key}: {e}")
            if not items:
                empty.append(key)
            html = render_page(key, page_file)
            (DIST / page_file(key)).write_text(html, encoding="utf-8")
            print(f"{page_file(key)}: {len(items)}件")

    # GitHub Pages に「そのまま公開する」ことを伝える空ファイル
    (DIST / ".nojekyll").write_text("", encoding="utf-8")

    if empty:
        # 1件も取れなかったタブがあるときは失敗扱いにして、前回の公開内容をそのまま残す
        print(f"[エラー] ニュースを1件も取得できなかったタブ: {', '.join(empty)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
