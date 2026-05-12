"""ハッシュタグページの診断（ログイン後の状態を確認）

patchright を直接使い、永続プロファイル（make login で作った cookie）で
ハッシュタグページを開く。動画タイルが描画されるか、login-wallが出るかを
ブラウザで目視確認しつつ、HTML/スクリーンショットも保存する。

Usage:
  uv run python -m scripts.diagnose_hashtag コスメ
"""
import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from patchright.async_api import async_playwright

from src.parser import extract_universal_json_from_html
from src.utils import setup_logging

load_dotenv()

PROFILE_DIR = os.getenv("TIKTOK_USER_DATA_DIR", "./.tiktok_profile")

# TikTok 各ページで動画タイルに割り当てられている可能性のある data-e2e 属性
TILE_SELECTORS = [
    '[data-e2e="challenge-item"]',
    '[data-e2e="challenge-item-list"]',
    '[data-e2e="user-post-item"]',
    'div[class*="DivItemContainer"]',
    'a[href*="/video/"]',
]


async def main(hashtag: str) -> int:
    setup_logging(debug=False)
    out = Path("output")
    out.mkdir(exist_ok=True)
    profile_abs = str(Path(PROFILE_DIR).resolve())

    print(f"profile dir: {profile_abs}")
    print(f"hashtag    : {hashtag}")
    print()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_abs,
            headless=False,            # 目視できるように
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        url = f"https://www.tiktok.com/tag/{hashtag}"
        print(f"GET {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        print("ページロード完了。動画タイルが現れるか各セレクタを最大15秒ずつ待ちます...")
        for sel in TILE_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=15000, state="attached")
                count = await page.locator(sel).count()
                print(f"  ✓ {sel}: {count} 件マッチ")
            except Exception:
                print(f"  ✗ {sel}: タイムアウト or 未出現")

        # 軽くスクロールして遅延ロードを誘発
        print("スクロールして遅延ロード誘発（3回）...")
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(1.5)

        # スクリーンショット & HTML保存
        screenshot_path = out / "diag_hashtag.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"\nsaved screenshot: {screenshot_path}")

        html = await page.content()
        html_path = out / "diag_hashtag.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"saved HTML:       {html_path}  ({len(html):,} chars)")

        # JSON 解析
        data = extract_universal_json_from_html(html)
        if data:
            scope_keys = sorted(data.get("__DEFAULT_SCOPE__", {}).keys())
            print(f"\n__DEFAULT_SCOPE__ keys: {scope_keys}")
        else:
            print("\n__UNIVERSAL_DATA_FOR_REHYDRATION__ が無い")

        # /@username を全部拾う
        usernames = sorted(set(re.findall(r'href="/@([A-Za-z0-9._]+)"', html)))
        print(f"\n/@username links found in rendered HTML: {len(usernames)}")
        for u in usernames[:30]:
            print(f"  - {u}")

        # /video/ リンク（動画タイルが描画されている証拠）
        videos = re.findall(r'href="(/@[A-Za-z0-9._]+/video/\d+)"', html)
        print(f"\n/video/ links: {len(videos)}")
        for v in videos[:5]:
            print(f"  - {v}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, input, "\n画面確認後、Enter で閉じます > "
        )
        await context.close()

    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "コスメ"
    sys.exit(asyncio.run(main(target)))
