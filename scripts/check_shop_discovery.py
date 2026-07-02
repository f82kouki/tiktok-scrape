"""Stage 4b: 自動発見の疎通確認（shop.tiktok.com 経路）

入口 → カテゴリ → 商品(PDP) の順に辿り、robots クリーンなパスから
PDP URL（＝店舗の入口）を自動収集できるかを確認する。件数を print するだけ。

Usage:
  uv run python -m scripts.check_shop_discovery          # 既定 上限
  uv run python -m scripts.check_shop_discovery 40       # PDP 上限を指定
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
        cats = await s.discover_category_urls(max_categories=6)
        print(f"\nカテゴリURL: {len(cats)} 件")
        for u in cats[:10]:
            print(f"  - {u}")
        pdps = await s.discover_pdp_urls(max_urls=max_urls, max_categories=6)

    print(f"\n発見した商品(PDP)URL: {len(pdps)} 件")
    for u in pdps[:15]:
        print(f"  - {u}")

    if not pdps:
        print("FAIL: PDP URLが0件（diagnose_shop で構造確認 / seed 方式へ退避）")
        return 1
    print(f"OK: {len(pdps)} 件の PDP を発見（各PDPから shop_info→店舗を取得できる）")
    return 0


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    sys.exit(asyncio.run(main(limit)))
