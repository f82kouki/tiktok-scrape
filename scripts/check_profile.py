"""Step 1: 単一プロフィール取得の疎通確認

Usage:
  uv run python -m scripts.check_profile             # @tiktok を取りに行く
  uv run python -m scripts.check_profile cosmetics   # 任意ユーザー
"""
import asyncio
import sys

from src.scraper import TikTokScraper
from src.utils import setup_logging


async def main(username: str) -> int:
    setup_logging(debug=True)
    async with TikTokScraper() as s:
        user = await s.fetch_user(username)
    if user is None:
        print(f"FAIL: fetch_user('{username}') returned None")
        print("ヒント: .env で HEADLESS=false にして実機確認 / 住宅プロキシを設定 / インターバル延長")
        return 1
    print(user)
    print()
    print(f"OK: @{user.unique_id} followers={user.follower_count:,}")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "tiktok"
    sys.exit(asyncio.run(main(target)))
