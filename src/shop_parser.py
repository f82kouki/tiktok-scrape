"""TikTok Shop 店舗ページのパース処理

方針:
- 埋め込みJSON抽出は src/parser.py の実績関数を **そのまま流用** する
  （extract_universal_json_from_html / extract_sigi_state_from_html）。
- parse_store() は現時点では「スキャフォールド」。__DEFAULT_SCOPE__ の全キーと
  shop/store/seller を含む候補キーを logger.info で出す（parser.py の
  extract_usernames_from_hashtag_html と同じ流儀）。
  ★ Stage 2（scripts/dump_store_page.py）で store_page.json の実構造を見てから、
    正しい scope key / フィールドパスに直して確定させること。★
"""
import json
import logging
import re
from typing import Optional

from src.models import TiktokShop
from src.parser import (
    extract_universal_json_from_html,
    extract_sigi_state_from_html,
)

logger = logging.getLogger(__name__)


# 店舗URL: https://www.tiktok.com/shop/store/{slug}/{seller-id}
#   slug は英数.-_、seller-id は数値。/shop/view/product/ は robots Disallow のため拾わない。
_STORE_LINK_RE = re.compile(r"/shop/store/([A-Za-z0-9._-]+)/(\d+)")
_STORE_ID_RE = re.compile(r"/shop/store/([^/]+)/(\d+)")


def _parse_ids_from_url(url: str) -> tuple[str, str]:
    """店舗URLから (slug, seller-id) を取り出す。取れなければ ("", "")。"""
    m = _STORE_ID_RE.search(url)
    if m:
        return m.group(1), m.group(2)
    return "", ""


def _to_int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _to_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def parse_store(
    html: str,
    store_url: str,
    source_type: Optional[str] = None,
    source_value: Optional[str] = None,
) -> Optional[TiktokShop]:
    """店舗ページ HTML → TiktokShop

    ⚠️ 下の scope key / フィールドパスは「推定」。Stage 2 で実 __DEFAULT_SCOPE__ の
       キーとネスト構造を確認してから正しいパスに直すこと。
    """
    slug, shop_id = _parse_ids_from_url(store_url)

    data = extract_universal_json_from_html(html)
    if data is None:
        # フォールバック: 旧形式 SIGI_STATE
        data = extract_sigi_state_from_html(html)
        if data is None:
            logger.warning(
                "店舗ページに埋め込みJSON（UNIVERSAL/SIGI）が無い "
                "→ 店舗データが XHR 後読みの可能性。diagnose_shop / Network を確認"
            )
            return None

    scope = data.get("__DEFAULT_SCOPE__", data) if isinstance(data, dict) else {}
    all_keys = sorted(scope.keys()) if isinstance(scope, dict) else []
    candidate_keys = [
        k for k in all_keys
        if any(t in k.lower() for t in ("shop", "store", "seller"))
    ]
    logger.info(f"店舗ページ __DEFAULT_SCOPE__ keys ({len(all_keys)}): {all_keys}")
    logger.info(f"  店舗候補キー: {candidate_keys}")

    # ↓ 候補キー配下の dict を section とする（Stage 2 で正しいキーに固定する）
    section = None
    for k in candidate_keys:
        v = scope.get(k)
        if isinstance(v, dict):
            section = v
            break
    if section is None:
        logger.warning(
            "店舗データの scope が特定できない（Stage 2 の store_page.json を見てここを直す）"
        )
        # slug/id だけでも返しておくと発見→重複排除は回る（PoC 中間状態）
        if shop_id:
            return TiktokShop(
                shop_id=shop_id,
                store_slug=slug,
                store_url=store_url,
                source_type=source_type,
                source_value=source_value,
            )
        return None

    # ↓ フィールド名は推定。実 JSON を見て正しいパスにマッピングし直す。
    shop = (
        section.get("shopInfo")
        or section.get("shop")
        or section.get("sellerInfo")
        or section
    )
    if not isinstance(shop, dict):
        shop = section
    stats = shop.get("stats", {}) if isinstance(shop.get("stats"), dict) else {}

    return TiktokShop(
        shop_id=shop_id or str(shop.get("sellerId") or shop.get("shopId") or ""),
        store_slug=slug,
        store_url=store_url,
        shop_name=shop.get("shopName") or shop.get("name") or "",
        follower_count=_to_int(
            stats.get("followerCount", shop.get("followerCount", 0))
        ),
        total_sold=_to_int(stats.get("soldCount", shop.get("totalSold", 0))),
        product_count=_to_int(
            stats.get("productCount", shop.get("onSellProductCount", 0))
        ),
        rating=_to_float(shop.get("ratingScore") or shop.get("rating")),
        rating_count=_to_int(shop.get("ratingCount", 0)),
        avatar_url=shop.get("avatar") or shop.get("logoUrl"),
        tiktok_username=shop.get("uniqueId") or shop.get("username"),
        is_official=bool(shop.get("isOfficial", False)),
        source_type=source_type,
        source_value=source_value,
    )


def extract_store_urls_from_html(html: str, max_urls: int = 30) -> list[str]:
    """任意のHTML（shop.tiktok.com/jp・/tag ページ等）から店舗URLを収集する。

    JSON優先 → href 正規表現フォールバックの二段構え（parser.py の思想を踏襲）。
    /shop/view/product/ は robots Disallow のため対象外（_STORE_LINK_RE は store のみ一致）。
    """
    urls: list[str] = []
    seen: set[str] = set()

    def _add(slug: str, sid: str) -> bool:
        key = f"{slug}/{sid}"
        if key in seen:
            return True
        seen.add(key)
        urls.append(f"https://www.tiktok.com/shop/store/{slug}/{sid}")
        return len(urls) < max_urls

    # 1) 埋め込みJSON全体を走査（PoC では素朴に JSON 文字列を正規表現でスキャン）
    data = extract_universal_json_from_html(html)
    if data is not None:
        text = json.dumps(data, ensure_ascii=False)
        for slug, sid in _STORE_LINK_RE.findall(text):
            if not _add(slug, sid):
                return urls

    # 2) href / 生HTML の正規表現フォールバック
    for slug, sid in _STORE_LINK_RE.findall(html):
        if not _add(slug, sid):
            break

    return urls
