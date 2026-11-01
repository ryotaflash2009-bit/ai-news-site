"""AIニュースまとめサイト Phase 2: 主要AIサービスごとのニュースをタブで切り替えて表示する。

起動: start.bat をダブルクリック → ブラウザで http://127.0.0.1:5000 を開く
"""

import html
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import feedparser
from flask import Flask, render_template, request


def google_news(query):
    """Googleニュース(日本語)の検索フィードのURLを作る。"""
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
            + "&hl=ja&gl=JP&ceid=JP:ja")


# ---- 設定 -------------------------------------------------------------
# サービスごとの取得先リスト。ここに書いた順にタブが並ぶ(先頭が最初に開くタブ)。
# サービスを増やすときは、同じ形で1つ追加するだけでよい。
# "keywords" を付けたフィードは、タイトルか概要にそのどれかを含む記事だけを使う
# (会社全体のニュースが流れてくるフィードから、そのサービスの記事だけを拾うため)。
SERVICES = {
    "claude": {
        "label": "Claude",
        "company": "Anthropic",
        "color": "#e0835f",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#ec9677",   # 文字色・ホバー用の少し明るい色
        "feeds": [
            {
                # anthropic.com は公式RSSを出していないため、公式ニュースページをRSS化した公開ミラーを使用
                "name": "Anthropic公式",
                "url": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
                "limit": 20,
            },
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/anthropic/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/anthropic/index.xml", "limit": 20},
            {"name": "Googleニュース", "url": google_news("Anthropic OR Claude AI"), "limit": 30},
        ],
    },
    "chatgpt": {
        "label": "ChatGPT",
        "company": "OpenAI",
        "color": "#2bbf97",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#5ad6b3",   # 文字色・ホバー用の少し明るい色
        "feeds": [
            {"name": "OpenAI公式", "url": "https://openai.com/news/rss.xml", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/openai/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/openai/index.xml", "limit": 20},
            {"name": "Googleニュース", "url": google_news("OpenAI OR ChatGPT"), "limit": 30},
        ],
    },
    "gemini": {
        "label": "Gemini",
        "company": "Google",
        "color": "#5b95f7",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#86b1ff",   # 文字色・ホバー用の少し明るい色
        "feeds": [
            {"name": "Google公式ブログ", "url": "https://blog.google/technology/ai/rss/", "limit": 20,
             "keywords": ["Gemini"]},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/gemini/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/google/index.xml", "limit": 20,
             "keywords": ["Gemini"]},
            {"name": "Googleニュース", "url": google_news('"Gemini" Google AI'), "limit": 30},
        ],
    },
    "grok": {
        "label": "Grok",
        "company": "xAI",
        "color": "#d5d9df",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#f2f4f6",   # 文字色・ホバー用の少し明るい色
        "feeds": [
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/xai/feed/", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/grok/feed/", "limit": 20},
            {"name": "Googleニュース", "url": google_news("xAI OR Grok"), "limit": 30},
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "company": "DeepSeek",
        "color": "#8e8cff",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#aeacff",   # 文字色・ホバー用の少し明るい色
        "feeds": [
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/deepseek/feed/", "limit": 20},
            {"name": "Googleニュース", "url": google_news("DeepSeek"), "limit": 30},
        ],
    },
    "copilot": {
        "label": "Copilot",
        "company": "Microsoft",
        "color": "#2ec4e6",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#67d8f1",   # 文字色・ホバー用の少し明るい色
        "feeds": [
            {"name": "Microsoft公式ブログ", "url": "https://blogs.microsoft.com/feed/", "limit": 20,
             "keywords": ["Copilot"]},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/microsoft-copilot/feed/", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/copilot/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/microsoft/index.xml", "limit": 20,
             "keywords": ["Copilot"]},
            {"name": "Googleニュース", "url": google_news('"Copilot" Microsoft'), "limit": 30},
        ],
    },
}
DEFAULT_SERVICE = "claude"

SUMMARY_MAX_CHARS = 140    # 要約(抜粋)の最大文字数。全文転載しないよう短く切る
MAX_ITEMS = 80             # ページに表示する最大件数
CACHE_SECONDS = 300        # 取得結果をサービスごとに5分だけ使い回す(短時間の連続更新で相手サイトに負担をかけないため)
TIMEOUT_SECONDS = 10
USER_AGENT = "Mozilla/5.0 (ai-news-site; RSS reader)"
# ---------------------------------------------------------------------

app = Flask(__name__)
# サービスごとのキャッシュ: {"claude": {"time": ..., "items": [...], "errors": [...]}, ...}
_cache = {}


def clean_summary(raw):
    """HTMLタグを取り除き、冒頭だけを短く切り出す。"""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[:SUMMARY_MAX_CHARS].rstrip() + "…"
    return text


def entry_datetime(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def fetch_feed(feed):
    """1つのフィードを取得して、表示用の辞書のリストを返す。"""
    req = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        data = res.read()
    parsed = feedparser.parse(data)

    keywords = [k.lower() for k in feed.get("keywords", [])]
    items = []
    for entry in parsed.entries[: feed["limit"]]:
        title = html.unescape(entry.get("title", "")).strip()
        link = entry.get("link", "")
        if not title or not link:
            continue
        if keywords:
            haystack = (title + " " + entry.get("summary", "")).lower()
            if not any(k in haystack for k in keywords):
                continue
        summary = clean_summary(entry.get("summary", ""))
        # Googleニュースの説明欄はタイトルの繰り返しなので表示しない
        if summary and summary.startswith(title[:20]):
            summary = ""
        items.append({
            "title": title,
            "link": link,
            "summary": summary,
            "published": entry_datetime(entry),
            "source": feed["name"],
        })
    return items


def get_news(service_key):
    """指定したサービスのニュースだけを取得する(表示中のタブのぶんだけ取りに行く)。"""
    cached = _cache.get(service_key)
    if cached and cached["items"] and time.time() - cached["time"] < CACHE_SECONDS:
        return cached["items"], cached["errors"]

    feeds = SERVICES[service_key]["feeds"]
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        futures = {pool.submit(fetch_feed, f): f for f in feeds}
        for future, feed in futures.items():
            try:
                items.extend(future.result())
            except Exception as e:  # 1つのフィードが失敗しても、ほかは表示する
                errors.append(f"{feed['name']}: {e}")

    # 同じタイトルの記事が複数のフィードにある場合は1つにまとめる
    seen, unique = set(), []
    for item in items:
        key = re.sub(r"\W", "", item["title"].lower())[:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    oldest = datetime.min.replace(tzinfo=timezone.utc)
    unique.sort(key=lambda i: i["published"] or oldest, reverse=True)
    unique = unique[:MAX_ITEMS]

    _cache[service_key] = {"time": time.time(), "items": unique, "errors": errors}
    return unique, errors


@app.template_filter("jst")
def to_jst(dt):
    """日付を日本時間の 'YYYY/MM/DD HH:MM' 形式で表示する。"""
    if not dt:
        return "日付不明"
    return (dt + timedelta(hours=9)).strftime("%Y/%m/%d %H:%M")


@app.template_filter("iso")
def to_iso(dt):
    """ブラウザ側で「何分前」を計算するためのISO形式の日時。"""
    return dt.isoformat() if dt else ""


@app.template_filter("source_kind")
def source_kind(name):
    """取得先バッジの色分け用の種類名を返す。"""
    if "公式" in name:
        return "official"
    if name == "TechCrunch":
        return "techcrunch"
    if name == "The Verge":
        return "verge"
    if name.startswith("Google"):
        return "google"
    return "other"


def render_page(current, tab_url):
    """1つのタブのページのHTMLを作る。tab_url はタブのキーからリンク先URLを作る関数。
    (ローカルのサーバーと、公開用の静的ページ作成(build.py)の両方で使う)"""
    items, errors = get_news(current)
    sources = list(dict.fromkeys(f["name"] for f in SERVICES[current]["feeds"]))
    fetched_at = datetime.fromtimestamp(_cache[current]["time"], tz=timezone.utc)
    return render_template("index.html", items=items, errors=errors, sources=sources,
                           services=SERVICES, current=current, service=SERVICES[current],
                           tab_url=tab_url, fetched_at=fetched_at, year=datetime.now().year)


@app.route("/")
def index():
    # URLの ?tab=chatgpt などで表示するサービスを決める。指定がなければ Claude
    current = request.args.get("tab", DEFAULT_SERVICE)
    if current not in SERVICES:
        current = DEFAULT_SERVICE
    return render_page(current, lambda key: f"/?tab={key}")


if __name__ == "__main__":
    print("サーバーを起動しました。ブラウザで http://127.0.0.1:5000 を開いてください。")
    print("終了するには、この画面で Ctrl + C を押してください。")
    app.run(host="127.0.0.1", port=5000, debug=False)
