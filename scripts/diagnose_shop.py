"""Stage 4a: shop.tiktok.com/jp（発見の主起点）の手動リコン

patchright を直接使い、永続プロファイル（make login で作った cookie）で
TikTok Shop Japan 入口を開く。目視 + DevTools Network で以下を確認する:
  - カテゴリ/商品/店舗へ遷移したときの URL パターン
  - 店舗/商品データが埋め込みJSONか XHR 後読みか（内部APIの有無）
  - __UNIVERSAL_DATA_FOR_REHYDRATION__ / SIGI_STATE の有無
HTML/スクリーンショットも output/diag_shop.{html,png} に保存する。

Usage:
  uv run python -m scripts.diagnose_shop
  uv run python -m scripts.diagnose_shop "https://shop.tiktok.com/jp"
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from patchright.async_api import async_playwright

from src.shop_parser import (
    extract_category_urls_from_html,
    extract_pdp_urls_from_html,
    extract_modern_router_data,
    find_shop_info,
)
from src.utils import setup_logging

load_dotenv()

PROFILE_DIR = os.getenv("TIKTOK_USER_DATA_DIR", "./.tiktok_profile")
DEFAULT_ENTRY = os.getenv("TIKTOK_SHOP_ENTRY_URL", "https://shop.tiktok.com/jp")


async def main(entry_url: str) -> int:
    setup_logging(debug=False)
    out = Path("output")
    out.mkdir(exist_ok=True)
    profile_abs = str(Path(PROFILE_DIR).resolve())

    print(f"profile dir: {profile_abs}")
    print(f"entry URL  : {entry_url}")
    print()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_abs,
            headless=False,            # 目視 + DevTools 用
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"GET {entry_url}")
        try:
            await page.goto(entry_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  注意: ナビゲーション中にエラー（無視可）: {e}")

        print("ページロード。手動で カテゴリ→商品(PDP)→店舗 と遷移し URL パターンを控えてください。")
        print("PDP/店舗ページ では __MODERN_ROUTER_DATA__ に shop_info が埋め込まれます。")

        # 軽くスクロールして遅延ロード誘発
        for _ in range(3):
            try:
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
            except Exception:
                break
            await asyncio.sleep(1.5)

        screenshot_path = out / "diag_shop.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"\nsaved screenshot: {screenshot_path}")

        html = await page.content()
        html_path = out / "diag_shop.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"saved HTML:       {html_path}  ({len(html):,} chars)")

        # 埋め込みJSON（shop.tiktok.com は __MODERN_ROUTER_DATA__）の有無
        router = extract_modern_router_data(html)
        if router:
            has_shop = find_shop_info(router) is not None
            print(f"\n__MODERN_ROUTER_DATA__ : あり（shop_info={'あり' if has_shop else 'なし'}）")
        else:
            print("\n__MODERN_ROUTER_DATA__ : なし（入口/カテゴリは持たないことがある）")

        # 発見リンクが拾えるか
        cats = extract_category_urls_from_html(html, max_urls=30)
        pdps = extract_pdp_urls_from_html(html, max_urls=30)
        print(f"\nカテゴリ /jp/c/ リンク: {len(cats)} 件 / 商品 /jp/pdp/ リンク: {len(pdps)} 件")
        for u in (cats[:8] + pdps[:8]):
            print(f"  - {u}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, input, "\n画面/DevTools 確認後、Enter で閉じます > "
        )
        await context.close()

    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ENTRY
    sys.exit(asyncio.run(main(target)))
