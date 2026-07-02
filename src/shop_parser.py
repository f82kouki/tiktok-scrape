"""TikTok Shop（shop.tiktok.com）店舗ページ / 商品(PDP)ページのパース処理

実測で確定した構造（2026-07 時点）:
- shop.tiktok.com は TikTok 本体（www.tiktok.com）とは別アプリ（tiktok_shop_web_mono）で、
  __UNIVERSAL_DATA_FOR_REHYDRATION__ / SIGI_STATE は **無い**。
- 代わりに <script id="__MODERN_ROUTER_DATA__"> に SSR データが JSON で埋め込まれ、
  商品(PDP)ページ / 店舗ページの両方で、店舗情報 shop_info が次の場所に入る:

    __MODERN_ROUTER_DATA__
      .loaderData.{<region>/pdp/... または <region>/store/...}
        .page_config.components_map[N].component_data.shop_info

  shop_info の主なキー:
    seller_id, shop_name, shop_logo{url_list}, creator_name, desc,
    sold_count, on_sell_product_count, review_count,
    followers_count, video_count, shop_rating, shop_link, region ...

発見用URLパターン（すべて shop.tiktok.com、robots で Disallow されていない）:
    カテゴリ: https://shop.tiktok.com/jp/c/{slug}/{category_id}
    商品    : https://shop.tiktok.com/jp/pdp/{product_id}      （/pdp/{slug}/{id} 形もある）
    店舗    : https://shop.tiktok.com/jp/store/{slug}/{seller_id}
"""
import json
import logging
import re
from typing import Optional

from src.models import TiktokShop

logger = logging.getLogger(__name__)

SHOP_BASE = "https://shop.tiktok.com"
# 注（実測）: JP では独立した店舗ページのURLは公開の直GETでは開けない。
#   - shop_info.shop_link（shop.tiktok.com/jp/store/{slug}/{id}） → 404
#   - www.tiktok.com/shop/store/{slug}/{id}                        → /404 へリダイレクト
# 店舗は TikTok Shop のSPA内でしか開けないため、確実に開けるのは取得元の
# PDP(商品) URL（shop.tiktok.com/jp/pdp/{id}）。store_url にはそれ（source_url）を入れる。

# 店舗URL: .../store/{slug}/{seller_id}
_STORE_ID_RE = re.compile(r"/store/([^/?#]+)/(\d+)")
# 商品URL: .../pdp/{id} または .../pdp/{slug}/{id}
_PDP_RE = re.compile(r"/jp/pdp/(?:[^/\"?#]+/)?(\d+)")
# カテゴリURL: .../jp/c/{slug}/{id}
_CATEGORY_RE = re.compile(r"/jp/c/([a-z0-9-]+)/(\d+)")


# ---------- 埋め込みJSON抽出 ----------

def extract_modern_router_data(html: str) -> Optional[dict]:
    """<script id="__MODERN_ROUTER_DATA__"> の JSON を取り出す"""
    m = re.search(
        r'<script[^>]+\bid="__MODERN_ROUTER_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning(f"__MODERN_ROUTER_DATA__ parse失敗: {e}")
        return None


def find_shop_info(router_data: dict) -> Optional[dict]:
    """__MODERN_ROUTER_DATA__ から shop_info dict を探して返す。

    loaderData 配下の各ルートの page_config.components_map を走査し、
    component_data.shop_info を持つ要素を拾う（PDP/店舗どちらの構造でも動く）。
    """
    loader = router_data.get("loaderData")
    if not isinstance(loader, dict):
        return None
    for route_val in loader.values():
        if not isinstance(route_val, dict):
            continue
        page_config = route_val.get("page_config")
        if not isinstance(page_config, dict):
            continue
        cmap = page_config.get("components_map")
        if not isinstance(cmap, list):
            continue
        for comp in cmap:
            if not isinstance(comp, dict):
                continue
            cdata = comp.get("component_data")
            if isinstance(cdata, dict) and isinstance(cdata.get("shop_info"), dict):
                return cdata["shop_info"]
    return None


# ---------- 変換ヘルパ ----------

def _to_int(v) -> int:
    """'6135' や 21246 を int に。'6.1K+' 等の整形済み文字列は入力に使わない。"""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"-?\d+", str(v))
    return int(m.group()) if m else 0


def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None and str(v) != "" else None
    except (TypeError, ValueError):
        return None


def _logo_url(shop_info: dict) -> Optional[str]:
    logo = shop_info.get("shop_logo")
    if isinstance(logo, dict):
        urls = logo.get("url_list")
        if isinstance(urls, list) and urls:
            return urls[0]
    return None


def _slug_from_shop_link(shop_link: str, seller_id: str) -> str:
    if shop_link:
        m = _STORE_ID_RE.search(shop_link)
        if m:
            return m.group(1)
    return ""


# ---------- 店舗パース ----------

def parse_shop(
    html: str,
    source_url: str,
    source_type: Optional[str] = None,
    source_value: Optional[str] = None,
) -> Optional[TiktokShop]:
    """shop.tiktok.com の PDP / 店舗ページ HTML → TiktokShop

    shop_info（__MODERN_ROUTER_DATA__ 内）から店舗情報を組み立てる。
    """
    router = extract_modern_router_data(html)
    if router is None:
        logger.warning(
            "__MODERN_ROUTER_DATA__ が無い（shop.tiktok.com 以外 or 構造変化）: %s",
            source_url,
        )
        return None

    shop_info = find_shop_info(router)
    if not shop_info:
        logger.warning("shop_info が components_map に見つからない: %s", source_url)
        return None

    seller_id = str(shop_info.get("seller_id") or shop_info.get("global_seller_id") or "")
    if not seller_id:
        logger.warning("shop_info に seller_id が無い: %s", source_url)
        return None

    shop_link = shop_info.get("shop_link") or ""
    slug = _slug_from_shop_link(shop_link, seller_id)
    # store_url には「確実に開ける」取得元URL（通常はPDP）を入れる。
    # 独立した店舗ページURLは公開GETで開けないため使わない（上の注を参照）。

    return TiktokShop(
        shop_id=seller_id,
        store_slug=slug,
        store_url=source_url,
        shop_name=shop_info.get("shop_name") or shop_info.get("creator_name") or "",
        follower_count=_to_int(shop_info.get("followers_count")),
        total_sold=_to_int(shop_info.get("sold_count")),
        product_count=_to_int(shop_info.get("on_sell_product_count")),
        video_count=_to_int(shop_info.get("video_count")),
        rating=_to_float(shop_info.get("shop_rating")),
        rating_count=_to_int(shop_info.get("review_count")),
        avatar_url=_logo_url(shop_info),
        region=shop_info.get("region"),
        description=shop_info.get("desc"),
        source_type=source_type,
        source_value=source_value or source_url,
    )


# ---------- 発見（URL抽出） ----------

def extract_category_urls_from_html(html: str, max_urls: int = 50) -> list[str]:
    """HTML から カテゴリURL /jp/c/{slug}/{id} を収集（重複排除）"""
    urls: list[str] = []
    seen: set[str] = set()
    for slug, cid in _CATEGORY_RE.findall(html):
        key = f"{slug}/{cid}"
        if key in seen:
            continue
        seen.add(key)
        urls.append(f"{SHOP_BASE}/jp/c/{slug}/{cid}")
        if len(urls) >= max_urls:
            break
    return urls


def extract_pdp_urls_from_html(html: str, max_urls: int = 50) -> list[str]:
    """HTML から 商品(PDP)URL /jp/pdp/{id} を収集（slug は落として id で正規化）"""
    urls: list[str] = []
    seen: set[str] = set()
    for pid in _PDP_RE.findall(html):
        if pid in seen:
            continue
        seen.add(pid)
        urls.append(f"{SHOP_BASE}/jp/pdp/{pid}")
        if len(urls) >= max_urls:
            break
    return urls


def parse_store_ids(url: str) -> tuple[str, str]:
    """店舗URL .../store/{slug}/{seller_id} から (slug, seller_id) を取り出す"""
    m = _STORE_ID_RE.search(url)
    return (m.group(1), m.group(2)) if m else ("", "")
