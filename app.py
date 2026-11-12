"""AIニュースまとめサイト Phase 2: 主要AIサービスごとのニュースをタブで切り替えて表示する。

起動: start.bat をダブルクリック → ブラウザで http://127.0.0.1:5000 を開く
"""

import difflib
import gzip
import html
import json
import logging
import os
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
# "parser"  : RSSを出していない公式サイトは、ニュース一覧ページを直接読み取る(PAGE_PARSERS を参照)
# "max_silence_days": 最新の記事がこの日数より古ければ「更新が止まっている」として取得失敗扱いにする
# "title_only": True の取得先(AI全般を扱うメディア)は、タイトルにサービス名がある記事だけを載せる
#               (いろいろな会社の話題がまとめて流れてくるので、概要に名前が出るだけの記事は載せない)

# AI全般を扱う信頼できるメディア。すべてのタブで使い、タイトルにそのサービス名がある記事だけを拾う
AI_MEDIA = [
    {"name": "TechCrunch", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "limit": 20, "title_only": True},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "limit": 20, "title_only": True},
    {"name": "Ars Technica", "url": "https://arstechnica.com/ai/feed/", "limit": 20, "title_only": True},
    {"name": "WIRED", "url": "https://www.wired.com/feed/tag/ai/latest/rss", "limit": 20, "title_only": True},
    {"name": "The Decoder", "url": "https://the-decoder.com/feed/", "limit": 20, "title_only": True},
    {"name": "ITmedia AI+", "url": "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", "limit": 20, "title_only": True},
    {"name": "PC Watch", "url": "https://pc.watch.impress.co.jp/data/rss/1.0/pcw/feed.rdf", "limit": 20, "title_only": True},
]

SERVICES = {
    "claude": {
        "label": "Claude",
        "company": "Anthropic",
        "color": "#e0835f",          # タブ・見出し・ボタンのイメージカラー(暗い背景で見やすい明るさ)
        "color_strong": "#ec9677",   # 文字色・ホバー用の少し明るい色
        "match": re.compile(rf"anthropic|{word('claude')}|クロード|アンソロピック|アンスロピック", re.I),
        "exclude": re.compile(r"monet|debussy|van damme|makelele|モネ|ドビュッシー|ヴァン・?ダム|ジャン[=＝・]クロード", re.I),
        "feeds": [
            # anthropic.com は公式RSSを出していないため、公式のニュース・研究ページを直接読み取る
            {"name": "Anthropic公式", "url": "https://www.anthropic.com/news", "limit": 20, "official": True,
             "parser": "anthropic", "max_silence_days": 21},
            {"name": "Anthropic公式（研究）", "url": "https://www.anthropic.com/research", "limit": 20,
             "official": True, "parser": "anthropic"},
            {
                # 予備: 公式ニュースページをRSS化した有志の公開ミラー(公式ページの読み取りが壊れたときの保険)。
                # 更新が止まっても気づけるよう、最新記事が古すぎるときは取得失敗として表示する
                "name": "Anthropic公式（ミラー）",
                "url": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
                "limit": 20,
                "official": True,
                "max_silence_days": 14,
            },
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/anthropic/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/anthropic/index.xml", "limit": 20},
            *AI_MEDIA,
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
            {"name": "OpenAI公式", "url": "https://openai.com/news/rss.xml", "limit": 20, "official": True,
             "max_silence_days": 14},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/openai/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/openai/index.xml", "limit": 20},
            *AI_MEDIA,
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
            # Gemini 専用の公式ブログ(すべて Gemini の話題)
            {"name": "Gemini公式ブログ", "url": "https://blog.google/products/gemini/rss/", "limit": 20,
             "official": True, "max_silence_days": 30},
            {"name": "Google公式ブログ", "url": "https://blog.google/technology/ai/rss/", "limit": 20},
            {"name": "Google DeepMind公式ブログ", "url": "https://deepmind.google/blog/rss.xml", "limit": 20,
             "title_only": True},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/gemini/feed/", "limit": 20},
            {"name": "The Verge", "url": "https://www.theverge.com/rss/google/index.xml", "limit": 20},
            *AI_MEDIA,
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
            # x.ai は公式RSSを出していないため、公式ニュースページを直接読み取る
            {"name": "xAI公式", "url": "https://x.ai/news", "limit": 20, "official": True, "parser": "xai",
             "max_silence_days": 30},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/xai/feed/", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/grok/feed/", "limit": 20},
            *AI_MEDIA,
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
            # DeepSeek は公式RSSを出していないため、公式APIドキュメントの「News」一覧(リリース名と日付)を読み取る。
            # 発表の間隔が数か月あくこともあるので、更新停止の判定はしない
            {"name": "DeepSeek公式", "url": "https://api-docs.deepseek.com/", "limit": 20,
             "official": True, "parser": "deepseek"},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/deepseek/feed/", "limit": 20},
            *AI_MEDIA,
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
            # Copilot 専用の公式RSSはないため、Microsoft の各公式フィードから Copilot の記事を拾う
            {"name": "Microsoft公式ブログ", "url": "https://blogs.microsoft.com/feed/", "limit": 20},
            {"name": "Microsoft公式ニュース", "url": "https://news.microsoft.com/source/feed/", "limit": 20,
             "title_only": True},
            {"name": "Microsoft 365公式ブログ", "url": "https://www.microsoft.com/en-us/microsoft-365/blog/feed/", "limit": 20,
             "title_only": True},
            {"name": "Windows公式ブログ", "url": "https://blogs.windows.com/feed/", "limit": 20,
             "title_only": True},
            {"name": "GitHub公式チェンジログ", "url": "https://github.blog/changelog/feed/", "limit": 20,
             "title_only": True},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/microsoft-copilot/feed/", "limit": 20},
            {"name": "TechCrunch", "url": "https://techcrunch.com/tag/copilot/feed/", "limit": 20},
            # Microsoft 全般のタグなので、概要に「Copilot+ PC」(パソコンの名前)が出るだけの Xbox などの記事が混ざる。
            # タイトルに Copilot があるものだけにする
            {"name": "The Verge", "url": "https://www.theverge.com/rss/microsoft/index.xml", "limit": 20,
             "title_only": True},
            *AI_MEDIA,
            {"name": "Googleニュース", "url": google_news('"Copilot" Microsoft'), "limit": 30},
        ],
    },
}
DEFAULT_SERVICE = "claude"

SUMMARY_MAX_CHARS = 140    # 要約(抜粋)の最大文字数。全文転載しないよう短く切る
MATCH_TEXT_CHARS = 300     # 関連性の判定に使う概要の文字数(タイトル + 概要の冒頭)
MAX_ITEMS = 100            # ページに表示する最大件数
MAX_AGE_DAYS = 180         # これより古い記事は「最新ニュース」として載せない
FUTURE_TOLERANCE = timedelta(hours=1)  # 公開日時が今より1時間以上先の記事は、日時が壊れているとみなす
CACHE_SECONDS = 300        # 取得結果をサービスごとに5分だけ使い回す(短時間の連続更新で相手サイトに負担をかけないため)
RETRY_SECONDS = 60         # 取得に失敗した取得先があったときは、1分たてば取り直す
TIMEOUT_SECONDS = 10
USER_AGENT = "Mozilla/5.0 (ai-news-site; RSS reader)"
# サイトの正式なURL(人に教える・検索エンジンに伝えるURL)
SITE_URL = "https://ai-news-hub-app.vercel.app/"
# 前回の取得結果(data/タブ名.json)を読みに行く場所(公開中のサイト)。環境変数 NEWS_SNAPSHOT_URL で変えられる
SNAPSHOT_URL = os.environ.get("NEWS_SNAPSHOT_URL", "https://ai-news-hub-app.vercel.app/data/")
# 取得先ごとの優先度(重複した記事はこの順で残す): 公式 > 専門メディア > Googleニュース
SOURCE_PRIORITY = {"official": 0, "media": 1, "google": 2}
# Googleニュースに混ざる、報道機関ではない掲載元(個人ブログ・SNS・動画・自動生成の記事まとめ・宣伝ページ、
# 乗っ取られた公共機関サイトのスパムなど)。これらの記事は載せない
UNRELIABLE_PUBLISHERS = re.compile(
    r"^(YouTube|X|note|Pasquale Pillitteri|BigGo ファイナンス|mbp-japan\.com|ホリエモンAI学校|OrcaRouter|"
    r"TIKR\.com|Yellow\.com)$"
    r"|Müdürlüğü|Belediyesi|Valiliği|Üniversitesi")
# 掲載元のサイト(ドメイン)で除外するもの。名前は変わることがあるので、サイトの住所でも判定する
#   hashout.jp(shiritomo): X(旧Twitter)で話題の投稿をもとに記事を量産するまとめ系サイト
#   mezha.net / vietnam.vn / martincid.com / techflowpost.com / panewslab.com:
#       海外サイトの記事を自動翻訳した日本語ページ(元の英語報道は専門メディアの取得先で拾える)
#   ai-market.jp: 「〇〇とは？」の解説記事で、更新のたびに日付が新しくなり、ニュースの日付として正しくない
#   laodong.vn: 海外サイトの自動翻訳(上と同じ)
#   moomoo.com: 投資アプリの利用者投稿(「ねえ @grok、…」のような個人の書き込み)
#   t.co: X(旧Twitter)の投稿へのリンク
UNRELIABLE_DOMAINS = ("hashout.jp", "mezha.net", "vietnam.vn", "martincid.com", "techflowpost.com",
                      "panewslab.com", "ai-market.jp", "laodong.vn", "moomoo.com", "t.co")
# ニュースではない「〇〇とは？〜を解説」「〜する方法｜…」のような解説・使い方の記事。
# 内容を更新するたびに日付だけが新しくなるため、ニュースの日付として正しくない(例: 古いモデルの解説が今日の日付で並ぶ)
EVERGREEN_TITLE = re.compile(r"とは[？?].*(解説|紹介|違い|比較|まとめ)|方法[｜|]|徹底解説|(特徴|料金|使い方)[^。]*を解説"
                             r"|[？?][^？?]*(違い|設定|対策|方法|使い方|料金|ステップ)[^？?]*を解説")
# ニュースではない、セミナー・勉強会などの宣伝(参加者の募集)
EVENT_AD_TITLE = re.compile(r"(ウェビナー|セミナー|勉強会|講座|説明会|ハンズオン|ワークショップ)[^。]*"
                            r"(開催|参加無料|無料招待|申込|受付|募集)|(開催|参加無料)[^。]*(ウェビナー|セミナー|勉強会|講座)")
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


# ---- RSSを出していない公式サイトのニュース一覧ページを読み取る ----------------
# どれも「タイトル・URL・日付(・要約)」だけを取り出す。日付は発表元の日付のみ(時刻なし)なので 00:00 UTC として扱う

def _date_tuple(y, m, d):
    return (int(y), int(m), int(d), 0, 0, 0)


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


NEXT_DATA = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def parse_anthropic(page, url):
    """anthropic.com/news・/research: ページに埋め込まれた記事データ(タイトル・公開日・要約・URL)を読む。
    データはJSONとして正しく読み解く(記事の中にある分類名・チーム名の "title" を記事名と取り違えないため)。"""
    data = "".join(json.loads(s) for s in NEXT_DATA.findall(page))
    decoder = json.JSONDecoder()
    articles = {}
    for m in re.finditer(r'\{"_id":"[^"]+","_type":"article"', data):
        try:
            article, _ = decoder.raw_decode(data, m.start())
        except ValueError:
            continue
        slug = (article.get("slug") or {}).get("current")
        title = (article.get("title") or "").strip()
        date = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", article.get("publishedOn") or "")
        if not (title and slug and date) or slug in articles:
            continue
        linked = article.get("linkedUrl")
        path = linked if linked and linked.startswith(("/", "http")) else \
            ("/research/" if article.get("articleType") == "research" else "/news/") + slug
        articles[slug] = {"title": title, "link": urllib.parse.urljoin(url, path),
                          "summary": article.get("summary") or "", "published_parsed": _date_tuple(*date.groups())}
    return list(articles.values())


def parse_xai(page, url):
    """x.ai/news: 記事カード(<a href="/news/..."> の中の見出し・説明・日付)を読む。"""
    articles = {}
    for m in re.finditer(r'<a[^>]+href="(/news/[a-z0-9-]+)"[^>]*>(.*?)</a>', page, re.S):
        title = re.search(r"<h[1-4][^>]*>(.*?)</h[1-4]>", m[2], re.S)
        date = re.search(r">\s*([A-Z][a-z]{2})[a-z]* (\d{1,2}), (\d{4})\s*<", m[2])
        if not (title and date) or m[1] in articles or date[1].lower() not in MONTHS:
            continue
        # 説明文(日付だけが入った <p> は説明ではないので使わない)
        summaries = [clean_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", m[2], re.S)]
        summaries = [s for s in summaries if s and not re.fullmatch(r"[A-Z][a-z]+ \d{1,2}, \d{4}", s)]
        articles[m[1]] = {"title": clean_text(title[1]), "link": urllib.parse.urljoin(url, m[1]),
                          "summary": summaries[0] if summaries else "",
                          "published_parsed": _date_tuple(date[3], MONTHS[date[1].lower()], date[2])}
    return list(articles.values())


def parse_deepseek(page, url, follow=True):
    """api-docs.deepseek.com: 「News」一覧(「DeepSeek-V4 Preview Release 2026/04/24」の形)を読む。
    トップページには一覧がないので、メニューの「News」のリンク先(最新のお知らせのページ)をたどって読む
    (個々のお知らせのページは消えることがあるため、いつもあるトップページから入る)。"""
    articles = {}
    for m in re.finditer(r'<a[^>]+href="(/news/news\d+)"[^>]*>(.*?)</a>', page, re.S):
        text = clean_text(m[2])
        date = re.fullmatch(r"(.+?)\s+(\d{4})/(\d{2})/(\d{2})", text)
        if date and m[1] not in articles:
            articles[m[1]] = {"title": date[1], "link": urllib.parse.urljoin(url, m[1]), "summary": "",
                              "published_parsed": _date_tuple(*date.groups()[1:])}
    news_link = re.search(r'<a[^>]+href="(/news/news\d+/?)"', page)
    if not articles and follow and news_link:
        news_url = urllib.parse.urljoin(url, news_link[1])
        return parse_deepseek(download(news_url).decode("utf-8", "replace"), news_url, follow=False)
    return list(articles.values())


PAGE_PARSERS = {"anthropic": parse_anthropic, "xai": parse_xai, "deepseek": parse_deepseek}
MIN_PAGE_ARTICLES = 3   # ページから読み取れた記事がこれより少なければ、ページの形式が変わったとみなす

# 同じURLを短時間に何度も取りに行かない(すべてのタブで使うメディアのフィードを、タブの数だけ取得しないため)
RAW_CACHE_SECONDS = 120
_raw_cache = {}


RETRY_WAIT_SECONDS = 2


def is_transient(e):
    """一時的なエラー(時間切れ・接続失敗・相手サーバーの5xx)かどうか。1回だけ取り直す対象。"""
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500
    return isinstance(e, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError))


def decompress(data):
    """頼んでいなくても gzip 圧縮で送ってくるサーバー(Google DeepMind のブログなど)があるので、圧縮されていれば戻す。"""
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


def download(url):
    cached = _raw_cache.get(url)
    if cached and time.time() - cached[0] < RAW_CACHE_SECONDS:
        return cached[1]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
            data = res.read()
    except Exception as e:
        # 一時的な失敗なら少し待って1回だけ取り直す(それでもだめなら、これまで通り取得失敗として表示する)
        if not is_transient(e):
            raise
        log.info("一時的なエラーのため取り直します: %s → %r", url, e)
        time.sleep(RETRY_WAIT_SECONDS)
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
            data = res.read()
    data = decompress(data)
    _raw_cache[url] = (time.time(), data)
    return data


def read_entries(feed):
    """取得先から記事の一覧を読む。読めないとき・更新が止まっているときは FeedError。"""
    data = download(feed["url"])
    if feed.get("parser"):
        entries = PAGE_PARSERS[feed["parser"]](data.decode("utf-8", "replace"), feed["url"])
        if len(entries) < MIN_PAGE_ARTICLES:
            raise FeedError("ページの形式が変わり、記事を読み取れませんでした")
    else:
        parsed = feedparser.parse(data)
        entries = parsed.entries
        if not entries:
            # エラーページ(HTML)が返ってきた場合なども、成功扱いにせず失敗として記録する
            raise FeedError("記事を読み取れませんでした" + ("(RSSの形式が不正)" if parsed.bozo else "(0件)"))
    if feed.get("max_silence_days"):
        # 取得できても、最新の記事が古すぎるなら更新が止まっている(ミラーの停止など)とみなし、黙って古いままにしない
        dates = [d for d in map(entry_datetime, entries) if d]
        days = (datetime.now(timezone.utc) - max(dates)).days if dates else None
        if days is None or days > feed["max_silence_days"]:
            raise FeedError(f"最新の記事が{days}日前のまま更新されていません（更新停止の可能性）"
                            if days is not None else "日付のある記事がありません")
    return entries


def is_unreliable(publisher, site_url):
    """Googleニュースの掲載元が、報道機関ではない(載せない)ものかどうか。名前とサイトの住所の両方で判定する。"""
    if publisher and UNRELIABLE_PUBLISHERS.search(publisher.strip()):
        return True
    host = (urllib.parse.urlsplit(site_url or "").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in UNRELIABLE_DOMAINS)


def fetch_feed(feed, service):
    """1つのフィードを取得して、(表示用の辞書のリスト, 除外した件数) を返す。"""
    entries = read_entries(feed)
    kind = source_type(feed)
    dropped = {"日付なし・不正": 0, "古い": 0, "無関係": 0, "信頼できない掲載元": 0, "リンク不正": 0, "解説記事": 0, "宣伝・催し": 0}
    oldest = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    items = []
    for entry in entries:
        # タイトル途中の改行は空白1つにする(全角の空白など、記事の書式はそのまま残す)
        title = re.sub(r"\s*[\r\n]+\s*", " ", html.unescape(entry.get("title", ""))).strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue
        if not link.lower().startswith(("https://", "http://")):
            # javascript: など、普通のWebページ以外へのリンクは載せない(安全のため)
            dropped["リンク不正"] += 1
            continue
        published = entry_datetime(entry)
        if published is None:
            dropped["日付なし・不正"] += 1
            continue
        if published < oldest:
            dropped["古い"] += 1
            continue
        publisher = (entry.get("source") or {}).get("title")
        if is_unreliable(publisher, (entry.get("source") or {}).get("href")):
            dropped["信頼できない掲載元"] += 1
            continue
        core = core_title(title, publisher)
        text = clean_text(entry.get("summary", ""))
        if not feed.get("official"):
            if EVERGREEN_TITLE.search(core):
                dropped["解説記事"] += 1
                continue
            if EVENT_AD_TITLE.search(core):
                dropped["宣伝・催し"] += 1
                continue
            haystack = core + " " + unicodedata.normalize("NFKC", text[:MATCH_TEXT_CHARS])
            excluded = service.get("exclude") and service["exclude"].search(haystack)
            matched = service["match"].search(core if feed.get("title_only") else haystack)
            if excluded or not matched:
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


def load_snapshot(key):
    """公開中のサイトに保存してある、前回取得できたニュース(data/タブ名.json)を読む(読めなければ None)。"""
    try:
        data = json.loads(download(SNAPSHOT_URL + f"{key}.json"))
        for item in data["items"]:
            item["published"] = datetime.fromisoformat(item["published"])
        return {"items": data["items"], "last_success": data["last_success"]}
    except Exception as e:
        log.info("[%s] 前回の取得結果を読み込めませんでした (%r)", key, e)
        return None


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

    if not ok and not (cached and cached.get("items")):
        # 1つも取得できず、手元に前回の内容もない(起動直後など): 公開中のサイトに保存してある前回分を探す
        cached = load_snapshot(service_key)
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
                           tab_url=tab_url, canonical_url=canonical_url(current), fetched_at=utc(news["time"]),
                           last_success=utc(news["last_success"]), year=datetime.now().year)


def page_file(key):
    """タブごとのページのファイル名。最初に開くタブ(Claude)は index.html にする。
    (公開版・手元のサーバーとも、同じURL(/chatgpt.html など)で開けるようにする)"""
    return "index.html" if key == DEFAULT_SERVICE else f"{key}.html"


PAGE_KEYS = {page_file(k).removesuffix(".html"): k for k in SERVICES}


def canonical_url(key):
    """タブの正式なURL(Vercel 版)。最初のタブはサイトのトップ(/)にする。"""
    return SITE_URL if key == DEFAULT_SERVICE else SITE_URL + page_file(key)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    # /chatgpt.html などのURL(古い形の ?tab=chatgpt も可)で表示するサービスを決める。指定がなければ Claude
    name = path.rsplit("/", 1)[-1].removesuffix(".html")
    if path.startswith("api/") or not name:
        name = ""  # Vercel では /api/index に転送されてくる
    current = request.args.get("tab") or PAGE_KEYS.get(name or "index")
    if path and name and current is None:
        return "ページが見つかりません", 404
    if current not in SERVICES:
        current = DEFAULT_SERVICE
    return render_page(current, page_file)


@app.after_request
def cache_headers(response):
    """Vercel で動かすときは、取得結果を Vercel の配信網に数分だけ保存して使い回す
    (見る人が多くても取得先に負担をかけず、表示も速くする)。取得失敗があったページは短めにする。"""
    if os.environ.get("VERCEL") and response.status_code == 200:
        has_problem = b'class="notice" role="alert">' in response.get_data()
        cdn = "max-age=60, stale-while-revalidate=120" if has_problem else \
            f"max-age={CACHE_SECONDS}, stale-while-revalidate=600"
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
        response.headers["Vercel-CDN-Cache-Control"] = cdn
    return response


if __name__ == "__main__":
    print("サーバーを起動しました。ブラウザで http://127.0.0.1:5000 を開いてください。")
    print("終了するには、この画面で Ctrl + C を押してください。")
    app.run(host="127.0.0.1", port=5000, debug=False)
