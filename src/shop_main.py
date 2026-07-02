"""Stage 5: 発見→取得→保存（店舗PoC 小ロット本ラン）

seed URL / 許可パス発見（shop.tiktok.com/jp・/tag）から店舗を取得し、
1件取れるたびに output/result_shop.{json,csv} と output/shops.jsonl を逐次保存する。

Usage:
  uv run python -m src.shop_main --max 20
  uv run python -m src.shop_main --max 10 --out-dir output --debug
"""
import argparse
import asyncio
import csv
import json
from pathlib import Path

from dotenv import load_dotenv

from src.shop_scraper import TikTokShopScraper
from src.utils import setup_logging

load_dotenv()


def _flush(results: list[dict], json_path: Path, csv_path: Path, jsonl_path: Path) -> None:
    """1件取れるたびに JSON/CSV/JSONL を書き直す（長時間ジョブのクラッシュ耐性）。"""
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if results:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


async def run(args) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "result_shop.json"
    csv_path = out_dir / "result_shop.csv"
    jsonl_path = out_dir / "shops.jsonl"

    results: list[dict] = []
    _flush(results, json_path, csv_path, jsonl_path)  # 前回結果を上書き

    async with TikTokShopScraper() as s:
        async for shop in s.scrape(max_total=args.max):
            results.append(shop.to_dict())
            print(
                f"  ✓ [{len(results)}] {shop.shop_name or shop.store_slug} "
                f"followers={shop.follower_count:,} sold={shop.total_sold:,} "
                f"(shop_id={shop.shop_id})"
            )
            _flush(results, json_path, csv_path, jsonl_path)

    print(f"\n取得完了: {len(results)} 件")
    print(f"  JSON : {json_path}")
    print(f"  JSONL: {jsonl_path}")
    if results:
        print(f"  CSV  : {csv_path}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=20, help="最大取得件数（PoCは小さく）")
    parser.add_argument("--out-dir", default="output")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    setup_logging(args.debug)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
