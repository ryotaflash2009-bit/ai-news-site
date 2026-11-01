"""AIニュースまとめサイト Phase 2: 主要AIサービスごとのニュースをタブで切り替えて表示する。

起動: start.bat をダブルクリック → ブラウザで http://127.0.0.1:5000 を開く
"""

import difflib
import html
import logging
import re
import socket
import time
import unicodedata
import urllib.error
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


def word(pattern):
    """英字の単語として一致させる(\\b は日本語の文字も単語の一部とみなすため、英字の前後だけを見る)。"""
    return rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"


# ---- 設定 -------------------------------------------------------------
# サービスごとの取得先リスト。ここに書いた順にタブが並ぶ(先頭が最初に開くタブ)。
# サービスを増やすときは、同じ形で1つ追加するだけでよい。
# "match"   : 記事のタイトルか概要の冒頭に、これが含まれる記事だけを載せる(本文の奥で名前が出るだけの記事を除くため)
# "exclude" : これを含む記事は、同じ名前の別物(人名・星座・暗号資産など)とみなして載せない
# "official": True の取得先(そのサービスの会社自身の公式ニュース)は、すべてそのサービスの話題なので "match" で絞らない
#             (Google・Microsoft の公式ブログは会社全体の話題が流れてくるので、"match" で絞る)
SERVICES = {
    "claude": {
        "label": "Claude",
        "company": "Anthropic",
        "color": "#e0835f",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#ec9677",   # 文字色・ホバー用の少し明るい色
        "match": re.compile(rf"anthropic|{word('claude')}|クロード|アンソロピック|アンスロピック", re.I),
        "exclude": re.compile(r"monet|debussy|van damme|makelele|モネ|ドビュッシー|ヴァン・?ダム|ジャン[=＝・]クロード", re.I),
        "feeds": [
            {
                # anthropic.com は公式RSSを出していないため、公式ニュースページをRSS化した公開ミラーを使用
                "name": "Anthropic公式",
                "url": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
                "limit": 20,
                "official": True,
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
        "match": re.compile(rf"openai|chatgpt|{word('gpt')}|gpt-?\d|{word('sora')}|{word('codex')}|altman|"
                            r"オープンAI|アルトマン", re.I),
        "feeds": [
            {"name": "OpenAI公式", "url": "https://openai.com/news/rss.xml", "limit": 20, "official": True},
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
        "match": re.compile(r"gemini|ジェミニ", re.I),
        # 暗号資産取引所の Gemini、星座(ふたご座)、NASAのジェミニ計画などは別物
        "exclude": re.compile(r"winklevoss|ウィンクルボス|crypto|bitcoin|暗号資産|仮想通貨|"
                              r"gemini (exchange|trust|earn|dollar|space)|"
                              r"horoscope|zodiac|双子座|ふたご座|星座|占い|nasa", re.I),
        "feeds": [
            {"name": "Google公式ブログ", "url": "https://blog.google/technology/ai/rss/", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/gemini/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/google/index.xml", "limit": 20},
            {"name": "Googleニュース", "url": google_news('"Gemini" Google AI'), "limit": 30},
        ],
    },
    "grok": {
        "label": "Grok",
        "company": "xAI",
        "color": "#d5d9df",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#f2f4f6",   # 文字色・ホバー用の少し明るい色
        # 「xAI」は大文字小文字まで一致させる(説明可能なAIの略語「XAI」と区別するため)
        "match": re.compile(rf"(?i:grok|グロック|spacex ?ai|spacex ?si|スペースX ?AI|スペースX ?SI)|{word('xAI')}"),
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
        "match": re.compile(r"deepseek|ディープシーク|深度求索", re.I),
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
        "match": re.compile(r"copilot|コパイロット", re.I),
        "feeds": [
            {"name": "Microsoft公式ブログ", "url": "https://blogs.microsoft.com/feed/", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/microsoft-copilot/feed/", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/copilot/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/microsoft/index.xml", "limit": 20},
            {"name": "Googleニュース", "url": google_news('"Copilot" Microsoft'), "limit": 30},
        ],
    },
}
DEFAULT_SERVICE = "claude"

SUMMARY_MAX_CHARS = 140    # 要約(抜粋)の最大文字数。全文転載しないよう短く切る
MATCH_TEXT_CHARS = 300     # 関連性の判定に使う概要の文字数(タイトル + 概要の冒頭)
MAX_ITEMS = 80             # ページに表示する最大件数
MAX_AGE_DAYS = 180         # これより古い記事は「最新ニュース」として載せない
FUTURE_TOLERANCE = timedelta(hours=1)  # 公開日時が今より1時間以上先の記事は、日時が壊れているとみなす
CACHE_SECONDS = 300        # 取得結果をサービスごとに5分だけ使い回す(短時間の連続更新で相手サイトに負担をかけないため)
RETRY_SECONDS = 60         # 取得に失敗した取得先があったときは、1分たてば取り直す
TIMEOUT_SECONDS = 10
USER_AGENT = "Mozilla/5.0 (ai-news-site; RSS reader)"
# 取得先ごとの優先度(重複した記事はこの順で残す): 公式 > 専門メディア > Googleニュース
SOURCE_PRIORITY = {"official": 0, "media": 1, "google": 2}
# ---------------------------------------------------------------------

app = Flask(__name__)
log = logging.getLogger("ai-news")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)

# サービスごとのキャッシュ: {"claude": {"time": ..., "items": [...], "errors": [...], "last_success": ...}, ...}
_cache = {}


class FeedError(Exception):
    """取得はできたが、中身がRSSとして使えなかったとき。"""


def clean_text(raw):
    """HTMLタグを取り除いた文字列にする。"""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def clean_summary(raw):
    """HTMLタグを取り除き、冒頭だけを短く切り出す。"""
    text = clean_text(raw)
    if len(text) > SUMMARY_MAX_CHARS:
        text = text[:SUMMARY_MAX_CHARS].rstrip() + "…"
    return text


def core_title(title, publisher=None):
    """比較用のタイトル。全角半角をそろえ、末尾の「 - 媒体名」「（媒体名）」を取り除く。"""
    t = unicodedata.normalize("NFKC", title).strip()
    if publisher:
        publisher = unicodedata.normalize("NFKC", publisher).strip()
        if t.endswith(" - " + publisher):
            t = t[: -len(publisher) - 3]
    t = re.sub(r"\s*\([^()]{1,30}\)\s*$", "", t)  # 末尾の (ケータイ Watch) など
    t = re.sub(r"\s*\{[^{}]{1,20}\}\s*$", "", t)  # 末尾の {VFT01A} など(同じ記事の掲載違いに付く記号)
    return t.strip()


def entry_datetime(entry):
    """記事の公開日時(UTC)。取れない・壊れている(未来の日時など)ときは None。"""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        dt = datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    if dt > datetime.now(timezone.utc) + FUTURE_TOLERANCE or dt.year < 2000:
        return None
    return dt


def normalize_url(url):
    """同じ記事のURLを同じ文字列にそろえる(大文字小文字・末尾の/・追跡用パラメータの違いを無視)。"""
    parts = urllib.parse.urlsplit(url.strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query)
             if not k.lower().startswith("utm_") and k.lower() not in ("ref", "fbclid", "gclid")]
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                                    parts.path.rstrip("/"), urllib.parse.urlencode(query), ""))


def source_type(feed):
    if feed.get("official") or "公式" in feed["name"]:
        return "official"
    if feed["name"].startswith("Google"):
        return "google"
    return "media"


def fetch_feed(feed, service):
    """1つのフィードを取得して、(表示用の辞書のリスト, 除外した件数) を返す。"""
    req = urllib.request.Request(feed["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
        data = res.read()
    parsed = feedparser.parse(data)
    if not parsed.entries:
        # エラーページ(HTML)が返ってきた場合なども、成功扱いにせず失敗として記録する
        raise FeedError("記事を読み取れませんでした" + ("(RSSの形式が不正)" if parsed.bozo else "(0件)"))

    kind = source_type(feed)
    dropped = {"日付なし・不正": 0, "古い": 0, "無関係": 0}
    oldest = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    items = []
    for entry in parsed.entries:
        title = html.unescape(entry.get("title", "")).strip()
        link = entry.get("link", "")
        if not title or not link:
            continue
        published = entry_datetime(entry)
        if published is None:
            dropped["日付なし・不正"] += 1
            continue
        if published < oldest:
            dropped["古い"] += 1
            continue
        publisher = (entry.get("source") or {}).get("title")
        core = core_title(title, publisher)
        text = clean_text(entry.get("summary", ""))
        if not feed.get("official"):
            haystack = core + " " + unicodedata.normalize("NFKC", text[:MATCH_TEXT_CHARS])
            excluded = service.get("exclude") and service["exclude"].search(haystack)
            if excluded or not service["match"].search(haystack):
                dropped["無関係"] += 1
                continue
        summary = clean_summary(text)
        # Googleニュースの説明欄はタイトルの繰り返しなので表示しない
        if summary and summary.startswith(title[:20]):
            summary = ""
        items.append({
            "title": title,
            "core": core,
            "link": link,
            "summary": summary,
            "published": published,
            # 公式ミラーなど、日付だけで時刻がない(00:00:00 になっている)記事
            "date_only": (published.hour, published.minute, published.second) == (0, 0, 0),
            "source": feed["name"],
            "priority": SOURCE_PRIORITY[kind],
        })
    # フィードの並び順は新しい順とは限らない(Googleニュースは関連度順)ので、日時で並べてから上位を使う
    items.sort(key=lambda i: i["published"], reverse=True)
    return items[: feed["limit"]], dropped


def error_reason(e):
    """エラーを短い日本語の理由にする(画面表示用)。"""
    if isinstance(e, FeedError):
        return str(e)
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e):
        return "時間切れ"
    if isinstance(e, urllib.error.URLError):
        return "接続できませんでした"
    return "取得エラー"


def title_key(text):
    return re.sub(r"\W", "", text.lower())


def is_same_story(a, b):
    """2つの記事が同じニュース(媒体違いの同じ記事)かどうか。"""
    ka, kb = title_key(a["core"]), title_key(b["core"])
    if ka == kb:
        return True
    if min(len(ka), len(kb)) < 12 or abs(a["published"] - b["published"]) > timedelta(days=3):
        return False
    # 数字(バージョン・日付・金額)が違えば別の記事(例: 「新機能 5月」と「新機能 2月」)
    if re.findall(r"\d+(?:\.\d+)?", a["core"]) != re.findall(r"\d+(?:\.\d+)?", b["core"]):
        return False
    # 英単語(製品名など)が食い違えば別の記事(例: 「Claude Haiku」と「Claude Sonnet」)
    wa = set(re.findall(r"[a-z]+", a["core"].lower()))
    wb = set(re.findall(r"[a-z]+", b["core"].lower()))
    if not (wa <= wb or wb <= wa):
        return False
    return difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.8


def dedupe(items):
    """同じ記事を1つにまとめる。URLが同じか、タイトルがほぼ同じなら同じ記事とみなし、
    公式 > 専門メディア > Googleニュース の順で優先して残す。"""
    kept, urls, merged = [], set(), 0
    for item in sorted(items, key=lambda i: (i["priority"], -i["published"].timestamp())):
        url = normalize_url(item["link"])
        if url in urls or any(is_same_story(item, k) for k in kept):
            merged += 1
            continue
        urls.add(url)
        kept.append(item)
    return kept, merged


def get_news(service_key):
    """指定したサービスのニュースを取得する(表示中のタブのぶんだけ取りに行く)。

    戻り値の辞書:
      items        表示する記事
      errors       取得に失敗した取得先(画面表示用の文字列)
      fetched_at   今回取得を試みた時刻
      last_success 最後にニュースを取得できた時刻(1つも取得できなかった回は更新しない)
      stale        True なら、今回は1件も取得できず、前回取得できた内容を表示している
    """
    cached = _cache.get(service_key)
    if cached and time.time() - cached["time"] < (RETRY_SECONDS if cached["errors"] else CACHE_SECONDS):
        return cached

    service = SERVICES[service_key]
    feeds = service["feeds"]
    items, errors, ok = [], [], 0
    dropped = {}
    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        futures = [(pool.submit(fetch_feed, f, service), f) for f in feeds]
        for future, feed in futures:
            try:
                feed_items, feed_dropped = future.result()
            except Exception as e:  # 1つのフィードが失敗しても、ほかは表示する
                reason = error_reason(e)
                errors.append(f"{feed['name']}（{reason}）")
                log.warning("[%s] 取得失敗: %s %s → %r", service_key, feed["name"], feed["url"], e)
                continue
            ok += 1
            items.extend(feed_items)
            for k, v in feed_dropped.items():
                dropped[k] = dropped.get(k, 0) + v

    now = time.time()
    unique, merged = dedupe(items)
    unique.sort(key=lambda i: i["published"], reverse=True)
    unique = unique[:MAX_ITEMS]

    if ok:
        result = {"items": unique, "last_success": now, "stale": False}
    elif cached and cached.get("items"):
        # 1つも取得できなかった: 前回の内容を残すが、「最新ではない」ことを画面に出す
        result = {"items": cached["items"], "last_success": cached["last_success"], "stale": True}
    else:
        result = {"items": [], "last_success": None, "stale": True}
    result.update(time=now, errors=errors)
    _cache[service_key] = result

    log.info("[%s] 取得先 成功 %d/%d・表示 %d件・重複まとめ %d件・除外 %s%s",
             service_key, ok, len(feeds), len(result["items"]), merged,
             "、".join(f"{k} {v}件" for k, v in dropped.items()),
             "・前回の内容を表示中" if result["stale"] and result["items"] else "")
    return result


@app.template_filter("jst")
def to_jst(dt):
    """日付を日本時間の 'YYYY/MM/DD HH:MM' 形式で表示する。"""
    if not dt:
        return "日付不明"
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y/%m/%d %H:%M")


@app.template_filter("jst_date")
def to_jst_date(dt):
    """時刻が分からない記事用。発表元の日付をそのまま 'YYYY/MM/DD' で表示する。"""
    return dt.strftime("%Y/%m/%d") if dt else "日付不明"


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


def utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def render_page(current, tab_url):
    """1つのタブのページのHTMLを作る。tab_url はタブのキーからリンク先URLを作る関数。
    (ローカルのサーバーと、公開用の静的ページ作成(build.py)の両方で使う)"""
    news = get_news(current)
    sources = list(dict.fromkeys(f["name"] for f in SERVICES[current]["feeds"]))
    return render_template("index.html", items=news["items"], errors=news["errors"], stale=news["stale"],
                           sources=sources, services=SERVICES, current=current, service=SERVICES[current],
                           tab_url=tab_url, fetched_at=utc(news["time"]),
                           last_success=utc(news["last_success"]), year=datetime.now().year)


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
