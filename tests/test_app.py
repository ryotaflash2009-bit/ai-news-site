"""正確さのルールが壊れていないかを確かめる自動テスト。

ネットにはつながず、用意した偽のフィード・公式ページで確かめる(いつ実行しても同じ結果になる)。
公開の前(GitHub Actions・Vercel のビルド)に毎回実行し、1つでも失敗したら公開しない。

手元で実行するとき: .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import json
import logging
import os
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

app.log.setLevel(logging.ERROR)
NOW = datetime.now(timezone.utc)


def ago(**kw):
    return NOW - timedelta(**kw)


def rss(items):
    """偽のRSS。items は (タイトル, リンク, 日時, 概要, 掲載元) のリスト。"""
    body = ""
    for title, link, when, summary, publisher in items:
        site = "https://example.com"
        if isinstance(publisher, tuple):
            publisher, site = publisher
        source = f"<source url='{site}'>{publisher}</source>" if publisher else ""
        date = f"<pubDate>{format_datetime(when)}</pubDate>" if when else ""
        body += (f"<item><title>{title}</title><link>{link}</link>{date}"
                 f"<description>{summary}</description>{source}</item>")
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>{body}</channel></rss>".encode()


def anthropic_page(articles):
    """anthropic.com のように、記事データを self.__next_f.push(...) で埋め込んだページ。
    記事の中に、チーム名の "title" が記事名より先に出てくる(実際のページと同じ並び)。"""
    posts = []
    for slug, title, date, kind in articles:
        posts.append({"_id": slug + "-id", "_type": "article", "articleType": kind,
                      "cardTeams": [{"slug": "team", "title": "Frontier Red Team"}],
                      "linkedUrl": None, "publishedOn": date, "slug": {"_type": "slug", "current": slug},
                      "summary": "summary of " + title, "title": title})
    payload = "1:" + json.dumps({"posts": posts}, separators=(",", ":"))  # 実際のページと同じく空白なし
    return f"<html><script>self.__next_f.push([1,{json.dumps(payload)}])</script></html>".encode()


def xai_page(articles):
    cards = ""
    for slug, title, when, summary in articles:
        cards += (f'<a class="card" href="/news/{slug}"><div><h3 class="t">{title}</h3>'
                  f'<p class="s">{summary}</p></div><div class="d">{when:%b} {when.day}, {when.year}</div></a>')
    return f"<html><body>{cards}</body></html>".encode()


def deepseek_page(articles):
    links = "".join(f'<a class="menu" href="/news/news{n}">{title} {when:%Y/%m/%d}</a>'
                    for n, title, when in articles)
    return f"<html><nav>{links}</nav></html>".encode()


def item(title, days=1, source="TechCrunch", priority=1, link=None):
    return {"title": title, "core": app.core_title(title), "link": link or "https://example.com/" + title,
            "summary": "", "published": ago(days=days), "date_only": False, "source": source, "priority": priority}


class FakeNetwork:
    """URL ごとに返す中身(または起こすエラー)を決めた、偽の download。"""

    def __init__(self, pages):
        self.pages = pages

    def __call__(self, url):
        for key, value in self.pages.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise urllib.error.URLError("no fake page for " + url)


class TestCase(unittest.TestCase):
    def setUp(self):
        app._cache.clear()
        app._raw_cache.clear()
        patcher = mock.patch.object(app, "load_snapshot", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestDates(TestCase):
    def test_future_and_missing_dates_are_rejected(self):
        self.assertIsNone(app.entry_datetime({}))
        self.assertIsNone(app.entry_datetime({"published_parsed": (ago(hours=-3)).timetuple()}))
        self.assertIsNone(app.entry_datetime({"published_parsed": (1999, 1, 1, 0, 0, 0)}))
        self.assertIsNotNone(app.entry_datetime({"published_parsed": ago(hours=2).timetuple()}))

    def test_feed_is_sorted_before_limit_and_old_items_dropped(self):
        # 関連度順のフィード(Googleニュースなど)でも、新しい記事から上位を使う
        feed = {"name": "TechCrunch", "url": "https://feed.test/a", "limit": 2}
        data = rss([("Claude old", "https://e.com/1", ago(days=5), "", None),
                    ("Claude older", "https://e.com/2", ago(days=9), "", None),
                    ("Claude newest", "https://e.com/3", ago(hours=1), "", None),
                    ("Claude ancient", "https://e.com/4", ago(days=400), "", None),
                    ("Claude no date", "https://e.com/5", None, "", None)])
        with mock.patch.object(app, "download", FakeNetwork({"feed.test": data})):
            items, dropped = app.fetch_feed(feed, app.SERVICES["claude"])
        self.assertEqual([i["title"] for i in items], ["Claude newest", "Claude old"])
        self.assertEqual(dropped["古い"], 1)
        self.assertEqual(dropped["日付なし・不正"], 1)


class TestRelevance(TestCase):
    def fetch(self, service, titles, **feed_options):
        feed = {"name": "Media", "url": "https://feed.test/r", "limit": 50, **feed_options}
        data = rss([(t, f"https://e.com/{n}", ago(hours=n + 1), s, p) for n, (t, s, p) in enumerate(titles)])
        with mock.patch.object(app, "download", FakeNetwork({"feed.test": data})):
            return [i["title"] for i in app.fetch_feed(feed, app.SERVICES[service])[0]]

    def test_same_name_different_things_are_excluded(self):
        self.assertEqual(self.fetch("grok", [("説明可能なAI(XAI)とは?", "", None),
                                             ("xAI releases Grok 5", "", None)]), ["xAI releases Grok 5"])
        self.assertEqual(self.fetch("gemini", [("Gemini horoscope for today", "", None),
                                               ("Winklevoss Gemini exchange news", "", None),
                                               ("Google Gemini 4 launches", "", None)]), ["Google Gemini 4 launches"])

    def test_title_only_sources_ignore_names_in_the_summary(self):
        titles = [("Big AI week recap", "OpenAI and Anthropic shipped Claude updates", None),
                  ("Claude gets new feature", "", None)]
        self.assertEqual(self.fetch("claude", titles, title_only=True), ["Claude gets new feature"])
        self.assertEqual(len(self.fetch("claude", titles)), 2)  # 通常の取得先は概要の冒頭も見る

    def test_unreliable_publishers_and_bad_links_are_dropped(self):
        feed = {"name": "Googleニュース", "url": "https://feed.test/g", "limit": 50}
        data = rss([("Claude spam", "https://e.com/1", ago(hours=1), "", "Kütahya İl Millî Eğitim Müdürlüğü"),
                    ("Claude blog", "https://e.com/2", ago(hours=1), "", "note"),
                    ("Claude script", "javascript:alert(1)", ago(hours=1), "", "ITmedia"),
                    ("Claude buzz", "https://e.com/5", ago(hours=1), "", ("shiritomo", "https://hashout.jp")),
                    ("Claude translated", "https://e.com/6", ago(hours=1), "", ("Vietnam.vn", "https://www.vietnam.vn")),
                    ("Claude similar domain", "https://e.com/7", ago(hours=1), "", ("Foo", "https://nothashout.jp")),
                    ("Claude real news", "https://e.com/4", ago(hours=1), "", "ITmedia")])
        with mock.patch.object(app, "download", FakeNetwork({"feed.test": data})):
            items, dropped = app.fetch_feed(feed, app.SERVICES["claude"])
        self.assertEqual(sorted(i["title"] for i in items), ["Claude real news", "Claude similar domain"])
        self.assertEqual(dropped["信頼できない掲載元"], 4)
        self.assertEqual(dropped["リンク不正"], 1)


    def test_evergreen_explainers_are_dropped(self):
        feed = {"name": "Googleニュース", "url": "https://feed.test/g", "limit": 50}
        titles = ["Grok 4.5とは？性能・料金・使い方を解説 - AIsmiley",
                  "Grokで画像編集する方法｜X・アプリ別の使い方 - AIsmiley",
                  "Grok Imagineとは？特徴・料金まで徹底解説【2026年最新】 - AIsmiley",
                  "Grokの新機能、気を付けるべきことは？ - ITmedia",
                  "xAI、Grok 5を発表 料金は据え置き - ITmedia"]
        data = rss([(t, "https://e.com/" + str(n), ago(hours=1), "", t.rsplit(" - ", 1)[1])
                    for n, t in enumerate(titles)])
        with mock.patch.object(app, "download", FakeNetwork({"feed.test": data})):
            items, dropped = app.fetch_feed(feed, app.SERVICES["grok"])
        self.assertEqual(sorted(i["title"] for i in items), sorted(titles[3:]))
        self.assertEqual(dropped["解説記事"], 3)

    def test_more_explainers_event_ads_and_posts_are_dropped(self):
        feed = {"name": "Googleニュース", "url": "https://feed.test/g", "limit": 50}
        rows = [("Grokは無料でどこまで使える？有料プランや他AIとの違いを解説", "AIsmiley"),
                ("Copilot活用講座、第1回無料招待枠を1,500名に拡大", "PR TIMES"),
                ("Copilotを比べる無料ウェブセミナーを11月12日に開催", "ニコニコニュース"),
                ("ねえ @grok、ビットコインは上がる？", ("Moomoo", "https://www.moomoo.com")),
                ("Grok搭載エージェント、通信攻撃で対策ソフトを回避", ("Howl.Link", "https://t.co")),
                ("「Grok 5」の用途は？ モデルの選び方、xAIが基本を解説", "ITmedia"),
                ("xAI、Grok開発者向け勉強会の内容を公開", "ITmedia")]
        data = rss([(t, "https://e.com/%d" % n, ago(hours=1), "", p) for n, (t, p) in enumerate(rows)])
        with mock.patch.object(app, "download", FakeNetwork({"feed.test": data})):
            items, dropped = app.fetch_feed(feed, app.SERVICES["grok"])
        self.assertEqual(sorted(i["title"] for i in items), sorted(t for t, _ in rows[5:]))
        self.assertEqual((dropped["解説記事"], dropped["宣伝・催し"], dropped["信頼できない掲載元"]), (1, 2, 2))

    def test_line_breaks_in_titles_become_spaces(self):
        feed = {"name": "ITmedia AI+", "url": "https://feed.test/i", "limit": 50}
        data = rss([("xAI、Grok 5を公開\n　料金は据え置き", "https://e.com/1", ago(hours=1), "", None)])
        with mock.patch.object(app, "download", FakeNetwork({"feed.test": data})):
            items, _ = app.fetch_feed(feed, app.SERVICES["grok"])
        self.assertEqual(items[0]["title"], "xAI、Grok 5を公開 料金は据え置き")


class TestDuplicates(TestCase):
    def test_publisher_suffix_versions_are_merged(self):
        a = item("職場のCopilotがメールを学習 - Forbes JAPAN", source="Googleニュース", priority=2)
        a["core"] = app.core_title(a["title"], "Forbes JAPAN")
        b = item("職場のCopilotがメールを学習 - Yahoo!ニュース", source="Googleニュース", priority=2)
        b["core"] = app.core_title(b["title"], "Yahoo!ニュース")
        self.assertEqual(len(app.dedupe([a, b])[0]), 1)

    def test_different_versions_and_months_are_kept(self):
        for x, y in [("Introducing Claude Haiku 5.5", "Introducing Claude Sonnet 5.5"),
                     ("Microsoft 365 Copilot の新機能 2026年5月", "Microsoft 365 Copilot の新機能 2026年2月"),
                     ("DeepSeek-V4.1-Flash-1017 Release", "DeepSeek-V4.1-Flash Release")]:
            self.assertEqual(len(app.dedupe([item(x), item(y)])[0]), 2, (x, y))

    def test_official_copy_is_kept(self):
        official = item("Introducing Grok Voice 3.0", source="xAI公式", priority=0, link="https://x.ai/news/v3")
        media = item("Introducing Grok Voice 3.0", source="TechCrunch", priority=1, link="https://x.ai/news/v3/")
        kept = app.dedupe([media, official])[0]
        self.assertEqual([i["source"] for i in kept], ["xAI公式"])


class TestOfficialPages(TestCase):
    def test_anthropic_uses_article_title_not_team_name(self):
        page = anthropic_page([("provable-inference", "Progress on provable inference", "2026-11-02", "research"),
                               ("gsa", "Expanding our partnership with GSA", "2026-10-27", "news")])
        entries = app.parse_anthropic(page.decode(), "https://www.anthropic.com/research")
        by_title = {e["title"]: e for e in entries}
        self.assertEqual(set(by_title), {"Progress on provable inference", "Expanding our partnership with GSA"})
        self.assertEqual(by_title["Progress on provable inference"]["link"],
                         "https://www.anthropic.com/research/provable-inference")
        self.assertEqual(by_title["Expanding our partnership with GSA"]["link"], "https://www.anthropic.com/news/gsa")
        self.assertEqual(by_title["Progress on provable inference"]["published_parsed"], (2026, 11, 2, 0, 0, 0))

    def test_xai_skips_date_only_paragraph(self):
        when = ago(days=2)
        page = xai_page([("grok-voice-3", "Introducing Grok Voice 3.0", when, f"{when:%b} {when.day}, {when.year}"),
                         ("team-bots", "Team Bots", when, "Shared AI teammates")])
        entries = {e["title"]: e for e in app.parse_xai(page.decode(), "https://x.ai/news")}
        self.assertEqual(entries["Introducing Grok Voice 3.0"]["summary"], "")
        self.assertEqual(entries["Team Bots"]["summary"], "Shared AI teammates")
        self.assertEqual(entries["Team Bots"]["link"], "https://x.ai/news/team-bots")

    def test_deepseek_release_list(self):
        page = deepseek_page([(261017, "DeepSeek-V4.1-Flash-1017 Release", datetime(2026, 10, 17))])
        entries = app.parse_deepseek(page.decode(), "https://api-docs.deepseek.com/news/news261017")
        self.assertEqual(entries[0]["title"], "DeepSeek-V4.1-Flash-1017 Release")
        self.assertEqual(entries[0]["published_parsed"], (2026, 10, 17, 0, 0, 0))

    def test_deepseek_follows_news_link_from_top_page(self):
        top = b'<html><a class="navbar" href="/news/news261017">News</a></html>'
        news = deepseek_page([(261017, "DeepSeek-V4.1-Flash-1017 Release", datetime(2026, 10, 17))])
        with mock.patch.object(app, "download", FakeNetwork({"/news/news261017": news})):
            entries = app.parse_deepseek(top.decode(), "https://api-docs.deepseek.com/")
        self.assertEqual([e["link"] for e in entries], ["https://api-docs.deepseek.com/news/news261017"])

    def test_changed_page_and_stale_feed_are_failures(self):
        changed = {"name": "Anthropic公式", "url": "https://www.anthropic.com/news", "limit": 20, "parser": "anthropic"}
        with mock.patch.object(app, "download", FakeNetwork({"anthropic.com": b"<html>redesigned</html>"})):
            with self.assertRaisesRegex(app.FeedError, "ページの形式が変わり"):
                app.read_entries(changed)
        stale = {"name": "ミラー", "url": "https://feed.test/m", "limit": 20, "max_silence_days": 14}
        data = rss([("Claude", "https://e.com/1", ago(days=20), "", None)])
        with mock.patch.object(app, "download", FakeNetwork({"feed.test": data})):
            with self.assertRaisesRegex(app.FeedError, "更新停止の可能性"):
                app.read_entries(stale)


class TestFailures(TestCase):
    SERVICE = {"label": "Claude", "company": "Anthropic", "color": "#e0835f", "color_strong": "#ec9677",
               "match": app.SERVICES["claude"]["match"],
               "feeds": [{"name": "A", "url": "https://a.test/feed", "limit": 20},
                         {"name": "B", "url": "https://b.test/feed", "limit": 20}]}

    def get(self, pages):
        with mock.patch.dict(app.SERVICES, {"test": self.SERVICE}), \
                mock.patch.object(app, "download", FakeNetwork(pages)):
            return app.get_news("test")

    def test_partial_failure_is_reported(self):
        news = self.get({"a.test": rss([("Claude news", "https://e.com/1", ago(hours=1), "", None)]),
                         "b.test": urllib.error.HTTPError("u", 503, "x", None, None)})
        self.assertFalse(news["stale"])
        self.assertEqual(len(news["items"]), 1)
        self.assertEqual(news["errors"], ["B（HTTP 503）"])

    def test_total_failure_keeps_previous_items_marked_stale(self):
        first = self.get({"a.test": rss([("Claude news", "https://e.com/1", ago(hours=1), "", None)]),
                          "b.test": rss([("Claude more", "https://e.com/2", ago(hours=2), "", None)])})
        app._cache["test"]["time"] -= 3600
        app._raw_cache.clear()
        down = urllib.error.URLError("down")
        second = self.get({"a.test": down, "b.test": down})
        self.assertTrue(second["stale"])
        self.assertEqual(len(second["items"]), 2)
        self.assertEqual(second["last_success"], first["last_success"])

    def test_total_failure_without_previous_uses_saved_snapshot(self):
        saved = {"items": [item("Claude saved")], "last_success": NOW.timestamp() - 7200}
        down = urllib.error.URLError("down")
        with mock.patch.object(app, "load_snapshot", return_value=saved):
            news = self.get({"a.test": down, "b.test": down})
        self.assertTrue(news["stale"])
        self.assertEqual([i["title"] for i in news["items"]], ["Claude saved"])

    def test_transient_error_is_retried_once(self):
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"ok"

        def urlopen(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError("u", 503, "busy", None, None)
            return Response()

        with mock.patch.object(app.urllib.request, "urlopen", urlopen), mock.patch.object(app.time, "sleep"):
            self.assertEqual(app.download("https://retry.test/feed"), b"ok")
        # 頼んでいないのに gzip 圧縮で届いた中身も読める
        self.assertEqual(app.decompress(__import__("gzip").compress(b"<rss/>")), b"<rss/>")
        self.assertEqual(app.decompress(b"<rss/>"), b"<rss/>")
        self.assertEqual(len(calls), 2)
        with mock.patch.object(app.urllib.request, "urlopen",
                               side_effect=urllib.error.HTTPError("u", 404, "nf", None, None)) as m:
            with self.assertRaises(urllib.error.HTTPError):
                app.download("https://missing.test/feed")
            self.assertEqual(m.call_count, 1)  # 404 などは取り直さない


def fake_internet():
    """実際の SERVICES のすべての取得先に、それらしい中身を返す偽のネット。"""
    names = ["Claude", "ChatGPT", "Gemini", "Grok", "DeepSeek", "Copilot"]
    generic = rss([(f"{n} update {k}", f"https://media.test/{n}/{k}", ago(hours=k * 3 + 1), "", None)
                   for k in range(3) for n in names])
    news = rss([(f"{n} ニュース {k} - ITmedia", f"https://news.google.test/{n}/{k}", ago(hours=k * 5 + 2), "", "ITmedia")
                for k in range(3) for n in names])
    days = [ago(days=d) for d in (1, 3, 6)]
    return FakeNetwork({
        "anthropic.com": anthropic_page([(f"a{k}", f"Anthropic post {k}", f"{d:%Y-%m-%d}", "news")
                                         for k, d in enumerate(days)]),
        "x.ai": xai_page([(f"x{k}", f"Grok post {k}", d, "summary") for k, d in enumerate(days)]),
        "deepseek.com": deepseek_page([(100 + k, f"DeepSeek-V{k} Release", d) for k, d in enumerate(days)]),
        "news.google.com": news,
        "": generic,
    })


class TestPages(TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(app, "download", fake_internet())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app.app.test_client()

    def test_every_tab_renders_newest_first(self):
        for key in app.SERVICES:
            for url in [f"/{app.page_file(key)}", f"/?tab={key}"] + (["/"] if key == app.DEFAULT_SERVICE else []):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200, url)
                html = res.get_data(as_text=True)
                self.assertIn(f'<span class="accent">{app.SERVICES[key]["label"]}</span>', html, url)
                stamps = [datetime.fromisoformat(s) for s in
                          __import__("re").findall(r'class="ago" data-ts="([^"]+)"', html)]
                self.assertGreater(len(stamps), 0, url)
                self.assertEqual(stamps, sorted(stamps, reverse=True), url)
                self.assertNotIn('class="notice" role="alert"', html, url)  # 全部成功ならお知らせは出ない

    def test_tab_links_use_page_files(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="chatgpt.html"', html)
        self.assertIn('href="index.html"', html)
        self.assertEqual(self.client.get("/unknown.html").status_code, 404)

    def test_canonical_url_points_to_official_site(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(f'<link rel="canonical" href="{app.SITE_URL}">', html)
        html = self.client.get("/grok.html").get_data(as_text=True)
        self.assertIn(f'<link rel="canonical" href="{app.SITE_URL}grok.html">', html)
        self.assertIn('<meta property="og:title" content="Grok ニュース | AI News Hub">', html)


if __name__ == "__main__":
    unittest.main()
