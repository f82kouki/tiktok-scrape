"""TikTok への手動ログイン → 永続プロファイルに cookie を保存

patchright (playwright のステルス改造版) を直接使ってブラウザを開きっぱなしにし、
人間がログインを完了するまで待つ。完了後 Enter で context を閉じると、
TIKTOK_USER_DATA_DIR に cookie が永続化される。

以降 src/scraper.py が同じ user_data_dir を使ってその cookie を再利用するため、
make step2 / step3 でハッシュタグ検索の login-wall を抜けられるようになる（はず）。

Usage:
  make login
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from patchright.async_api import async_playwright

load_dotenv()

PROFILE_DIR = os.getenv("TIKTOK_USER_DATA_DIR", "./.tiktok_profile")


async def main() -> int:
    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    profile_abs = str(Path(PROFILE_DIR).resolve())

    print("=" * 60)
    print("TikTok 手動ログインセッション")
    print("=" * 60)
    print(f"プロファイル保存先: {profile_abs}")
    print()
    print("手順:")
    print("  1. 開いた Chromium で TikTok にログインしてください")
    print("     （Google / Apple / メール / 電話、好きな方法でOK）")
    print("  2. ログイン完了し、トップページが普通に閲覧できる状態になったら")
    print("  3. このターミナルに戻って Enter を押すと cookie を保存して終了します")
    print()
    print("注意: 開いた Chromium ウィンドウは自分で閉じないでください")
    print("      （Enter を押すまで開いたまま）")
    print()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_abs,
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        try:
            await page.goto(
                "https://www.tiktok.com/login",
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except Exception as e:
            print(f"  注意: ナビゲーション中にエラー（無視可）: {e}")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, input, "ログインが終わったら Enter を押してください > "
        )

        await context.close()

    print()
    print(f"完了: cookie は {profile_abs} に保存されました")
    print("次の手順:")
    print("  - .env で HEADLESS=true に戻されていることを確認")
    print("  - make step2 を実行")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
