"""TikTok Shop 店舗スクレイパー（PoC / shop.tiktok.com 経路）

実測で判明した robots クリーンな全自動導線:
    shop.tiktok.com/jp                （入口。カテゴリリンク /jp/c/{slug}/{id} を持つ）
      → /jp/c/{slug}/{id}             （カテゴリ。商品リンク /jp/pdp/{id} を持つ）
        → /jp/pdp/{id}               （商品。__MODERN_ROUTER_DATA__ に shop_info 埋め込み）
          → shop_info（seller_id / shop_name / followers / sold / products / rating / shop_link）

- 店舗の一意キーは seller_id。PDP 1枚から店舗情報が全部取れる（追加 fetch 不要）。
- shop.tiktok.com の robots は /jp/c/・/jp/pdp/・/jp/store/ を Disallow していない（catch-all なし）。
- セッション/ステルス設定/retry は src/scraper.py の TikTokScraper をそのまま継承。
"""
import logging
import os
from typing import AsyncGenerator, Optional

from src.scraper import TikTokScraper
from src.models import TiktokShop
from src.shop_parser import (
    parse_shop,
    extract_category_urls_from_html,
    extract_pdp_urls_from_html,
)
from src.utils import jittered_sleep

logger = logging.getLogger(__name__)

DEFAULT_ENTRY_URL = "https://shop.tiktok.com/jp"


def _kind(url: str) -> str:
    return "store" if "/store/" in url else "pdp"


class TikTokShopScraper(TikTokScraper):
    """TikTokScraper を継承。セッション/fetch はそのまま流用し店舗用メソッドを追加。"""

    async def fetch_shop(
        self,
        url: str,
        source_type: Optional[str] = None,
        source_value: Optional[str] = None,
    ) -> Optional[TiktokShop]:
        """PDP または店舗URLを取得し TiktokShop を返す。"""
        html = await self.fetch_html(url)
        if not html:
            return None
        return parse_shop(html, url, source_type or _kind(url), source_value or url)

    async def discover_category_urls(self, max_categories: int = 6) -> list[str]:
        """入口 shop.tiktok.com/jp からカテゴリURLを発見（明示指定があれば優先）。"""
        explicit = [
            u.strip()
            for u in os.getenv("TIKTOK_SHOP_CATEGORY_URLS", "").split(",")
            if u.strip()
        ]
        if explicit:
            logger.info(f"カテゴリURLは明示指定を使用: {len(explicit)} 件")
            return explicit[:max_categories]

        entry = os.getenv("TIKTOK_SHOP_ENTRY_URL") or DEFAULT_ENTRY_URL
        html = await self.fetch_html(entry)
        if not html:
            logger.warning(f"入口 HTML が取れない: {entry}")
            return []
        cats = extract_category_urls_from_html(html, max_urls=max_categories * 3)
        logger.info(f"入口 {entry}: カテゴリ {len(cats)} 件発見")
        return cats[:max_categories]

    async def discover_pdp_urls(
        self, max_urls: int = 40, max_categories: int = 6
    ) -> list[str]:
        """カテゴリページを巡回して商品(PDP)URLを収集。"""
        cats = await self.discover_category_urls(max_categories=max_categories)
        pdps: list[str] = []
        seen: set[str] = set()
        for c in cats:
            if len(pdps) >= max_urls:
                break
            await jittered_sleep(self.interval_min, self.interval_max)
            html = await self.fetch_html(c)
            if not html:
                logger.warning(f"カテゴリ HTML が取れない: {c}")
                continue
            n0 = len(pdps)
            for u in extract_pdp_urls_from_html(html, max_urls=max_urls):
                if u not in seen:
                    seen.add(u)
                    pdps.append(u)
                    if len(pdps) >= max_urls:
                        break
            logger.info(f"  [{c}] PDP +{len(pdps) - n0}（累計 {len(pdps)}）")
        return pdps

    async def scrape(self, max_total: int = 20) -> AsyncGenerator[TiktokShop, None]:
        """seed URL → 発見PDP の順に取得し、seller_id で重複排除して店舗を yield。

        人気店舗は複数 PDP に跨るため、目標 max_total に対し PDP は多めに集める。
        """
        seen_sellers: set[str] = set()
        total = 0

        seeds = [
            s.strip()
            for s in os.getenv("TIKTOK_SHOP_SEED_URLS", "").split(",")
            if s.strip()
        ]
        # 重複排除で目減りする分、候補PDPは目標の3倍程度集める
        pdps = await self.discover_pdp_urls(max_urls=max(max_total * 3, 12))

        work: list[tuple[str, str]] = (
            [(u, "seed") for u in seeds] + [(u, _kind(u)) for u in pdps]
        )
        logger.info(
            f"取得対象: seed {len(seeds)} + 発見PDP {len(pdps)} = {len(work)} URL "
            f"（目標 {max_total} 店舗）"
        )

        for url, src in work:
            if total >= max_total:
                return
            await jittered_sleep(self.interval_min, self.interval_max)
            shop = await self.fetch_shop(url, source_type=src, source_value=url)
            if not shop or not shop.shop_id:
                continue
            if shop.shop_id in seen_sellers:
                logger.debug(f"skip 重複 seller {shop.shop_id} ({shop.shop_name})")
                continue
            seen_sellers.add(shop.shop_id)
            total += 1
            yield shop
