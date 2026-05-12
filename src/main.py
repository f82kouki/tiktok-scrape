"""CLIエントリーポイント

Usage:
  uv run python -m src.main --hashtag コスメ --hashtag メイク --min-followers 10000 --max 20
  uv run python -m src.main --keyword 美容ブロガー --max 10
"""
import argparse
import asyncio
import csv
import json
from pathlib import Path

from dotenv import load_dotenv

from src.scraper import TikTokScraper
from src.utils import setup_logging

load_dotenv()


def _flush(results: list[dict], json_path: Path, csv_path: Path) -> None:
    """1件取れるたびに JSON/CSV を書き直す。長時間ジョブ中のクラッシュ耐性のため。"""
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if results:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)


async def run(args):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "result.json"
    csv_path = out_dir / "result.csv"

    results: list[dict] = []
    # 開始時に空ファイルを作っておく（既存の前回結果を上書き）
    _flush(results, json_path, csv_path)

    async with TikTokScraper() as scraper:
        async for user in scraper.scrape(
            hashtags=args.hashtag,
            keywords=args.keyword,
            min_followers=args.min_followers,
            max_users_per_query=args.max_users_per_query,
            max_total=args.max,
        ):
            results.append(user.to_dict())
            print(f"  ✓ @{user.unique_id} ({user.follower_count:,} followers)  [{len(results)}件目を保存]")
            _flush(results, json_path, csv_path)

    print(f"\n取得完了: {len(results)} 件")
    print(f"  JSON: {json_path}")
    if results:
        print(f"  CSV : {csv_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hashtag", action="append", default=[], help="検索ハッシュタグ（複数指定可）")
    parser.add_argument("--keyword", action="append", default=[], help="検索キーワード（複数指定可）")
    parser.add_argument("--min-followers", type=int, default=1000)
    parser.add_argument("--max-users-per-query", type=int, default=30)
    parser.add_argument("--max", type=int, default=100, help="最大取得件数")
    parser.add_argument("--out-dir", default="output")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    setup_logging(args.debug)

    if not args.hashtag and not args.keyword:
        parser.error("--hashtag または --keyword を最低1つ指定してください")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
