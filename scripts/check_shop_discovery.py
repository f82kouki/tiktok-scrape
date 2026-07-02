"""Stage 4b: 自動発見の疎通確認

robots 許可パス（shop.tiktok.com/jp + /tag/{カテゴリ}）から /shop/store/... を
自動収集できるかを確認する薄いスクリプト。発見件数を print するだけ。

Usage:
  uv run python -m scripts.check_shop_discovery          # .env の TIKTOK_SHOP_CATEGORIES を使う
  uv run python -m scripts.check_shop_discovery 30       # 上限件数を指定
"""
import asyncio
import sys

from dotenv import load_dotenv

from src.shop_scraper import TikTokShopScraper
from src.utils import setup_logging

load_dotenv()


async def main(max_urls: int) -> int:
    setup_logging(debug=True)
    async with TikTokShopScraper() as s:
        urls = await s.discover_store_urls(max_urls=max_urls)

    print(f"\n発見した店舗URL: {len(urls)} 件")
    for u in urls:
        print(f"  - {u}")

    if not urls:
        print("FAIL: 店舗URLが0件（entry/tag の HTML 構造を diagnose_shop で確認、seed 方式へ退避）")
        return 1
    print(f"OK: {len(urls)} 件の店舗URLを許可パスから発見")
    return 0


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    sys.exit(asyncio.run(main(limit)))
