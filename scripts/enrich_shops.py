"""店舗リストに連絡先エンリッチメントをかける（PoC）

TikTok Shop スクレイプ結果（output/shops.jsonl か result_shop.json）を読み、
各店舗名から Web 検索で 電話・メール・会社名・住所 を best-effort で拾って
output/leads.jsonl / leads.csv に保存する。

Usage:
  uv run python -m scripts.enrich_shops                      # shops.jsonl を一括エンリッチ
  uv run python -m scripts.enrich_shops "Classical Elf【公式】"   # 店名1件だけ試す（動作確認）
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.enrich import ContactEnricher
from src.utils import setup_logging, env_bool

load_dotenv()


def _load_shops() -> list[dict]:
    out = Path("output")
    jsonl = out / "shops.jsonl"
    if jsonl.exists():
        return [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    js = out / "result_shop.json"
    if js.exists():
        return json.loads(js.read_text(encoding="utf-8"))
    return []


def _flush(rows: list[dict], jsonl_path: Path, csv_path: Path) -> None:
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if rows:
        keys = list(rows[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)


async def run_single(name: str) -> int:
    setup_logging(debug=True)
    async with ContactEnricher(headless=env_bool("HEADLESS", True)) as e:
        c = await e.enrich(name)
    print(json.dumps(c.to_dict(), ensure_ascii=False, indent=2))
    print("found" if c.found else "not found",
          "→ email:", c.emails, "phone:", c.phones)
    return 0


async def run_all() -> int:
    setup_logging(debug=True)
    shops = _load_shops()
    if not shops:
        print("FAIL: output/shops.jsonl も result_shop.json も無い。先に make shop-run を実行")
        return 1
    out = Path("output")
    jsonl_path, csv_path = out / "leads.jsonl", out / "leads.csv"
    rows: list[dict] = []
    hit = 0
    async with ContactEnricher(headless=env_bool("HEADLESS", True)) as e:
        for i, shop in enumerate(shops, 1):
            name = shop.get("shop_name") or shop.get("store_slug") or ""
            c = await e.enrich(name, shop_id=str(shop.get("shop_id", "")))
            merged = {
                "shop_id": shop.get("shop_id"),
                "shop_name": name,
                "follower_count": shop.get("follower_count"),
                "total_sold": shop.get("total_sold"),
                "product_count": shop.get("product_count"),
                "store_url": shop.get("store_url"),
                "contact_found": c.found,
                "emails": "; ".join(c.emails),
                "phones": "; ".join(c.phones),
                "company": c.company or "",
                "address": c.address or "",
                "source_urls": "; ".join(c.source_urls),
            }
            rows.append(merged)
            if c.found:
                hit += 1
            mark = "✓" if c.found else "·"
            print(f"  {mark} [{i}/{len(shops)}] {name}  email={c.emails} phone={c.phones}")
            _flush(rows, jsonl_path, csv_path)  # 逐次保存
    print(f"\n完了: {hit}/{len(rows)} 件で連絡先/会社情報を取得 → {csv_path}")
    return 0


def main():
    if len(sys.argv) > 1:
        sys.exit(asyncio.run(run_single(sys.argv[1])))
    sys.exit(asyncio.run(run_all()))


if __name__ == "__main__":
    main()
