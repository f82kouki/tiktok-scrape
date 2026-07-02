"""連絡先エンリッチメント（PoC）

TikTok Shop からは出品者の電話/メールが取れない（実測）。そこで別工程として、
取得済みの「店舗名」を手がかりに Web を検索し、その店の公式サイト等の
「特定商取引法に基づく表記 / 会社概要 / お問い合わせ」から 電話・メール・会社名・住所
を best-effort で拾う。

流れ:
  店名 → 検索(DuckDuckGo HTML) → 候補URL（特商法/会社概要/問い合わせを優先）
       → 各ページ取得 → 正規表現で email/phone/会社名/住所 を抽出

⚠️ 注意:
- ヒットするのは「自社サイトを持つブランド」中心。TikTok専業・汎用名の小規模店は取れない
  （＝部分的カバレッジ。空振りは正常）。
- 検索スクレイピングは不安定（ブロック/レート）。本番は検索API(SerpAPI/Bing/Google CSE)推奨。
- 取得した連絡先での営業は 特定電子メール法（メール）等の順守が前提。公開の特商法情報の
  範囲で、B2B 目的に限定して使うこと。
"""
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from scrapling.fetchers import AsyncStealthySession

from src.utils import jittered_sleep

logger = logging.getLogger(__name__)

# ---- 抽出用パターン ----
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 日本の固定/携帯（ハイフン区切りの表記を主対象＝特商法ページはこの形が多い）
PHONE_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}")

# メールの誤検出を弾く（画像/ライブラリ/計測/CDN 等）
EMAIL_DENY = (
    "example.", "sentry.", "wixpress.", "@2x", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".svg", "googleapis", "gstatic", "jsdelivr", "cloudflare", "schema.org",
    "w3.org", "godaddy", "your-email", "email@", "@sentry", "shopify", "myshopify",
)

# 連絡先が載っていそうなページを優先するためのヒント語（URL/タイトル）
CONTACT_HINTS = (
    "特定商取引", "特商", "tokushoho", "/law", "会社概要", "company", "about",
    "corporate", "お問い合わせ", "問い合わせ", "contact", "shopinfo", "/info", "運営",
)
# 連絡先ソースになりにくい（SNS/動画等）ドメインは候補から除外
SKIP_DOMAINS = (
    "tiktok.com", "instagram.com", "facebook.com", "youtube.com", "youtu.be",
    "twitter.com", "x.com", "pinterest.", "line.me", "lin.ee", "note.com",
    "ameblo.jp", "wikipedia.org",
)


@dataclass
class ShopContact:
    shop_id: str = ""
    shop_name: str = ""
    found: bool = False
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    company: Optional[str] = None
    address: Optional[str] = None
    source_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # CSV 化しやすいよう配列は "; " 連結の文字列列も併記
        d["emails_str"] = "; ".join(self.emails)
        d["phones_str"] = "; ".join(self.phones)
        d["source_urls_str"] = "; ".join(self.source_urls)
        return d


def _clean_emails(text: str) -> list[str]:
    out, seen = [], set()
    for m in EMAIL_RE.findall(text):
        e = m.strip(".").lower()
        if any(bad in e for bad in EMAIL_DENY):
            continue
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _clean_phones(text: str) -> list[str]:
    out, seen = [], set()
    for m in PHONE_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


# 値の終端（次のラベル/空白連続/行末など）で切る
_LABEL_STOP = (
    r"(?:電話|TEL|Tel|所在地|住所|代表|責任者|メール|mail|E-?mail|営業|定休|受付|"
    r"URL|FAX|\s{2,}|　|＜|<|\||｜|$)"
)


def _label_value(text: str, labels: tuple[str, ...]) -> Optional[str]:
    """「会社名：株式会社○○」のようなラベル直後の値を拾う（best-effort）。
    次のラベルや空白連続・行末で値を打ち切る。"""
    for label in labels:
        m = re.search(rf"{label}[\s：:　]*(.+?)\s*{_LABEL_STOP}", text)
        if m:
            val = m.group(1).strip(" 　:：\t")
            if 2 <= len(val) <= 60:
                return val
    return None


_GENERIC_TOKENS = {
    "shop", "store", "official", "japan", "tokyo", "inc", "co", "ltd", "the",
    "room", "clothing", "gal", "gear", "gears", "good", "only", "custom",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _name_tokens(name: str) -> list[str]:
    base = re.sub(r"【[^】]*】|（[^）]*）|\([^)]*\)|\[[^\]]*\]|公式|official",
                  " ", name, flags=re.IGNORECASE)
    toks = re.findall(r"[A-Za-z]{3,}|[ぁ-んァ-ヴー一-龥]{2,}", base)
    return [t.lower() for t in toks if t.lower() not in _GENERIC_TOKENS]


def _page_matches_shop(haystack: str, shop_name: str) -> bool:
    """ページ(本文+URL)が本当にこの店舗のものか判定（誤検出＝別サイトの連絡先を除外）。"""
    nh = _norm(haystack)
    base = re.sub(r"【[^】]*】|（[^）]*）|\([^)]*\)|公式|official", " ",
                  shop_name, flags=re.IGNORECASE)
    nb = _norm(base)
    if len(nb) >= 4 and nb in nh:            # 店名（空白除去）まるごと一致
        return True
    toks = _name_tokens(shop_name)
    hit = [t for t in toks if t in nh]
    if any(len(t) >= 5 for t in hit):        # 長め(>=5)の識別トークンが一致
        return True
    if len(toks) >= 2 and len(hit) >= 2:     # 識別トークンが2つ以上一致
        return True
    return False


def _score_candidate(url: str, title: str = "") -> int:
    s = 0
    hay = (url + " " + title).lower()
    for h in CONTACT_HINTS:
        if h.lower() in hay:
            s += 2
    return s


class ContactEnricher:
    """店名から連絡先を best-effort で拾う。TikTok cookie は使わない独立セッション。"""

    DDG_HTML = "https://html.duckduckgo.com/html/"

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[AsyncStealthySession] = None

    async def __aenter__(self):
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        self._session = await self._stack.enter_async_context(
            AsyncStealthySession(
                headless=self.headless,
                network_idle=True,
                block_webrtc=True,
                hide_canvas=True,
                timeout=60000,
                locale="ja-JP",
            )
        )
        return self

    async def __aexit__(self, *exc):
        if self._stack:
            await self._stack.__aexit__(*exc)
            self._stack = self._session = None

    async def _fetch(self, url: str) -> Optional[str]:
        try:
            page = await self._session.fetch(url)
            if page and page.body and (getattr(page, "status", 200) or 200) < 400:
                return page.body.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"fetch失敗 {url}: {e}")
        return None

    async def search(self, query: str, max_results: int = 8) -> list[str]:
        """DuckDuckGo HTML から候補URLを取得（リダイレクトリンクは復号）。"""
        html = await self._fetch(f"{self.DDG_HTML}?q={quote(query)}")
        if not html:
            return []
        urls: list[str] = []
        seen: set[str] = set()
        for m in re.finditer(r'href="(//duckduckgo\.com/l/\?[^"]*|https?://[^"]+)"', html):
            raw = m.group(1)
            # DDG のリダイレクト形式 //duckduckgo.com/l/?uddg=<encoded>
            if "duckduckgo.com/l/" in raw:
                q = parse_qs(urlparse("https:" + raw if raw.startswith("//") else raw).query)
                target = (q.get("uddg") or [""])[0]
                url = unquote(target)
            else:
                url = raw
            if not url.startswith("http"):
                continue
            host = urlparse(url).netloc.lower()
            if any(sd in host for sd in SKIP_DOMAINS) or "duckduckgo.com" in host:
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= max_results:
                break
        return urls

    async def _extract_from(
        self, url: str, shop_name: str
    ) -> tuple[list[str], list[str], Optional[str], Optional[str]]:
        html = await self._fetch(url)
        if not html:
            return [], [], None, None
        # タグを潰してテキスト寄りにしてからラベル抽出（雑だがPoCには十分）
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;", " ", text)
        # 誤検出防止: このページが本当にその店舗のものか（本文+URLに店名）を照合
        if not _page_matches_shop(text + " " + url, shop_name):
            logger.info(f"  店名不一致でスキップ（別サイトの連絡先を除外）: {url}")
            return [], [], None, None
        emails = _clean_emails(html)
        phones = _clean_phones(text)
        company = _label_value(text, ("販売業者", "会社名", "商号", "運営会社", "運営者", "販売事業者"))
        address = _label_value(text, ("所在地", "住所", "本社所在地"))
        return emails, phones, company, address

    async def enrich(self, shop_name: str, shop_id: str = "") -> ShopContact:
        result = ShopContact(shop_id=shop_id, shop_name=shop_name)
        # 検索クエリ: 店名 + 特商法/問い合わせ で連絡先ページに寄せる
        queries = [
            f"{shop_name} 特定商取引法に基づく表記",
            f"{shop_name} 会社概要 お問い合わせ",
        ]
        candidates: list[str] = []
        for q in queries:
            candidates += await self.search(q, max_results=6)
            await jittered_sleep(2, 4)
        # 重複排除 + 連絡先ページらしさでソート
        uniq, seen = [], set()
        for u in candidates:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        uniq.sort(key=lambda u: _score_candidate(u), reverse=True)

        for url in uniq[:5]:
            emails, phones, company, address = await self._extract_from(url, shop_name)
            if emails or phones or company:
                result.source_urls.append(url)
                for e in emails:
                    if e not in result.emails:
                        result.emails.append(e)
                for p in phones:
                    if p not in result.phones:
                        result.phones.append(p)
                result.company = result.company or company
                result.address = result.address or address
            # メールか電話が取れたら十分（ページを叩きすぎない）
            if result.emails or result.phones:
                break
            await jittered_sleep(2, 4)

        result.found = bool(result.emails or result.phones or result.company)
        return result
