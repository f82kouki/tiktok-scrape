"""TikTok Shop 店舗スクレイパー（PoC）

設計:
- セッション/ステルス設定/retry/backoff は src/scraper.py の TikTokScraper を
  そのまま継承する（__aenter__ / __aexit__ / fetch_html は店舗ページにも汎用）。
- 本クラスは店舗固有の 3 メソッドだけ足す: fetch_store / discover_store_urls / scrape。

コンプライアンス（robots.txt 実測）:
- 取得対象 /shop/store/{slug}/{id} は Disallow なし → OK。
- 発見は robots 許可パスのみ:
    * shop.tiktok.com/jp（別ホスト・catch-all Disallow なし）
    * /tag/{カテゴリ語}（Allow: /tag、既存 step2 と同じ）
    * seed URL（手動投入）
- /search 系・/shop/view/product/ は Disallow のため叩かない。
"""
import logging
import os
from typing import AsyncGenerator, Optional
from urllib.parse import quote

from scrapling.fetchers import AsyncStealthySession  # noqa: F401 (親が使用)

from src.scraper import TikTokScraper
from src.models import TiktokShop
from src.shop_parser import parse_store, extract_store_urls_from_html
from src.utils import jittered_sleep

logger = logging.getLogger(__name__)

DEFAULT_ENTRY_URL = "https://shop.tiktok.com/jp"


class TikTokShopScraper(TikTokScraper):
    """TikTokScraper を継承。セッション/fetch はそのまま流用し店舗用メソッドを追加。"""

    async def fetch_store(
        self,
        store_url: str,
        source_type: Optional[str] = None,
        source_value: Optional[str] = None,
    ) -> Optional[TiktokShop]:
        # wait_selector は Stage 2 で店舗ページの安定要素を確認して調整する。
        html = await self.fetch_html(
            store_url,
            wait_selector="script#__UNIVERSAL_DATA_FOR_REHYDRATION__",
        )
        if not html:
            return None
        return parse_store(html, store_url, source_type, source_value)

    async def discover_store_urls(self, max_urls: int = 30) -> list[str]:
        """robots 許可パスのみから店舗URLを発見する。

        経路:
          1) TIKTOK_SHOP_ENTRY_URL（既定 https://shop.tiktok.com/jp）
          2) TIKTOK_SHOP_CATEGORIES の各語 → https://www.tiktok.com/tag/{語}
        いずれも埋め込みJSON/hrefから /shop/store/ リンクを拾う。
        """
        found: list[str] = []
        seen: set[str] = set()

        def _merge(urls: list[str], src: str) -> None:
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    found.append(u)
            logger.info(f"  [{src}] 累計 {len(found)} 店舗URL")

        # 1) shop.tiktok.com/jp エントリ
        entry_url = os.getenv("TIKTOK_SHOP_ENTRY_URL") or DEFAULT_ENTRY_URL
        if entry_url:
            html = await self.fetch_html(entry_url)
            if html:
                _merge(extract_store_urls_from_html(html, max_urls=max_urls), entry_url)
            else:
                logger.warning(f"entry URL の HTML が取れない: {entry_url}")

        # 2) /tag/{カテゴリ} から店舗リンクを補完（Allow: /tag）
        cats = [
            c.strip()
            for c in os.getenv("TIKTOK_SHOP_CATEGORIES", "").split(",")
            if c.strip()
        ]
        for cat in cats:
            if len(found) >= max_urls:
                break
            await jittered_sleep(self.interval_min, self.interval_max)
            tag_url = f"{self.BASE_URL}/tag/{quote(cat)}"
            html = await self.fetch_html(tag_url)
            if html:
                _merge(
                    extract_store_urls_from_html(html, max_urls=max_urls),
                    f"tag:{cat}",
                )
            else:
                logger.warning(f"tag ページの HTML が取れない: {tag_url}")

        return found[:max_urls]

    async def scrape(self, max_total: int = 20) -> AsyncGenerator[TiktokShop, None]:
        """seed URL → 自動発見 の順で店舗を取得し、条件に合う店舗を yield。"""
        seen_ids: set[str] = set()
        total = 0

        # 0) seed URL（TIKTOK_SHOP_SEED_URLS, カンマ区切り）
        seeds = [
            s.strip()
            for s in os.getenv("TIKTOK_SHOP_SEED_URLS", "").split(",")
            if s.strip()
        ]
        # 1) 自動発見
        discovered = await self.discover_store_urls(max_urls=max_total * 2)

        work: list[tuple[str, str]] = (
            [(u, "seed") for u in seeds] + [(u, "entry") for u in discovered]
        )
        logger.info(f"取得対象: seed {len(seeds)} + 発見 {len(discovered)} = {len(work)} URL")

        for store_url, src in work:
            if total >= max_total:
                return
            await jittered_sleep(self.interval_min, self.interval_max)
            shop = await self.fetch_store(
                store_url, source_type=src, source_value=src
            )
            if not shop or not shop.shop_id:
                continue
            if shop.shop_id in seen_ids:
                continue
            seen_ids.add(shop.shop_id)
            total += 1
            yield shop
