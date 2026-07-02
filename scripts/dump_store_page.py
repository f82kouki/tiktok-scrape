"""Stage 2【最重要】店舗ページの埋め込みJSON構造をダンプする

既知の店舗URL（seed）を1件 fetch し、__DEFAULT_SCOPE__ のキー一覧と JSON 全体を
ファイルに吐き出して、parse_store() の正しい scope key / フィールドパスを
人間（or AI）が特定できるようにする。PoC で最初に走らせるスクリプト。

Usage:
  uv run python -m scripts.dump_store_page "https://www.tiktok.com/shop/store/<slug>/<id>"
"""
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.shop_scraper import TikTokShopScraper
from src.parser import extract_universal_json_from_html, extract_sigi_state_from_html
from src.utils import setup_logging

load_dotenv()

# 検証用の既知店舗URL（実在するものに差し替える / .env の TIKTOK_SHOP_SEED_URLS 先頭でも可）
DEFAULT_URL = "https://www.tiktok.com/shop/store/goli-nutrition/7495794203056835079"


async def main(url: str) -> int:
    setup_logging(debug=True)
    out = Path("output")
    out.mkdir(exist_ok=True)

    print(f"GET {url}")
    async with TikTokShopScraper() as s:
        html = await s.fetch_html(
            url, wait_selector="script#__UNIVERSAL_DATA_FOR_REHYDRATION__"
        )

    if not html:
        print("FAIL: HTML 取得できず（cookie / bot 検出 / 地域制限を疑う）")
        print("ヒント: .env で HEADLESS=false にして実機確認 / cookie 再取得 / proxy 地域変更")
        return 1

    html_path = out / "store_page.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"saved HTML: {html_path}  ({len(html):,} chars)")

    data = extract_universal_json_from_html(html) or extract_sigi_state_from_html(html)
    if not data:
        print("店舗ページに __UNIVERSAL_DATA_FOR_REHYDRATION__ / SIGI_STATE が無い")
        print("→ 店舗データが XHR で後読みされている可能性。")
        print("  make shop-recon（diagnose_shop）や DevTools Network で内部APIを確認すること。")
        return 2

    json_path = out / "store_page.json"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"saved JSON: {json_path}")

    scope = data.get("__DEFAULT_SCOPE__", data)
    print("\n=== __DEFAULT_SCOPE__ のキー一覧 ===")
    for k in sorted(scope.keys()):
        mark = " ★候補" if any(t in k.lower() for t in ("shop", "store", "seller")) else ""
        print(f" - {k}{mark}")

    print("\n→ output/store_page.json を開き、店舗名/フォロワー/販売数がどのキー配下にあるか特定し、")
    print("  src/shop_parser.py parse_store() のフィールドパスを修正すること（これが PoC の核）。")
    print("→ 特定後、この store_page.html を tests/fixtures/store_sample.html に置いて make test。")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    sys.exit(asyncio.run(main(target)))
