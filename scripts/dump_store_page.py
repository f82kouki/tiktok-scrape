"""Stage 2: shop.tiktok.com の PDP/店舗ページ構造ダンプ & 店舗パース確認

商品(PDP) または 店舗ページのURLを1件 fetch し、
  - HTML を output/store_page.html に保存
  - __MODERN_ROUTER_DATA__ を output/store_page.json に保存
  - 抽出した shop_info と parse_shop() の結果（TiktokShop）を表示
する。parse_shop() が正しく店舗情報を埋められるかの検証用。

Usage:
  uv run python -m scripts.dump_store_page "https://shop.tiktok.com/jp/pdp/<product_id>"
  uv run python -m scripts.dump_store_page "https://shop.tiktok.com/jp/store/<slug>/<seller_id>"
"""
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.shop_scraper import TikTokShopScraper, _kind
from src.shop_parser import extract_modern_router_data, find_shop_info, parse_shop
from src.utils import setup_logging

load_dotenv()

# 検証用の既定URL（実在の PDP。必要に応じて差し替え / seed を渡す）
DEFAULT_URL = "https://shop.tiktok.com/jp/pdp/1731687107318417254"


async def main(url: str) -> int:
    setup_logging(debug=True)
    out = Path("output")
    out.mkdir(exist_ok=True)

    print(f"GET {url}")
    async with TikTokShopScraper() as s:
        html = await s.fetch_html(url)

    if not html:
        print("FAIL: HTML 取得できず（cookie / bot 検出 / 地域制限を疑う）")
        print("ヒント: HEADLESS=false で実機確認 / cookie 再取得 / proxy 地域変更")
        return 1

    (out / "store_page.html").write_text(html, encoding="utf-8")
    print(f"saved HTML: output/store_page.html  ({len(html):,} chars)")

    router = extract_modern_router_data(html)
    if not router:
        print("__MODERN_ROUTER_DATA__ が無い（shop.tiktok.com 以外 or 構造変化）")
        print("→ make shop-recon / DevTools で構造を確認すること")
        return 2
    (out / "store_page.json").write_text(
        json.dumps(router, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("saved JSON: output/store_page.json")

    shop_info = find_shop_info(router)
    if not shop_info:
        print("shop_info が見つからない（components_map の構造変化を確認）")
        return 3
    print(f"\n=== shop_info keys ({len(shop_info)}) ===")
    print(", ".join(sorted(shop_info.keys())))

    shop = parse_shop(html, url, source_type=_kind(url))
    print("\n=== parse_shop() → TiktokShop ===")
    print(json.dumps(shop.to_dict(), ensure_ascii=False, indent=2))
    print(
        f"\nOK: {shop.shop_name} (seller_id={shop.shop_id}) "
        f"followers={shop.follower_count:,} sold={shop.total_sold:,} "
        f"products={shop.product_count}"
    )
    print("→ この store_page.html を tests/fixtures/store_sample.html に置けば make test で回帰確認できる")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    sys.exit(asyncio.run(main(target)))
