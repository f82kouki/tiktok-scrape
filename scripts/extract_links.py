"""セラーが公開したリンクを整理する（別コマンド・オフライン・追加取得ゼロ）

TikTok Shop スクレイプ結果（output/shops.jsonl か result_shop.json）の説明文(description)から、
セラー本人が公開した 自社サイト/Instagram/YouTube/X/LINE のURLを抽出し、
output/shop_links.csv / shop_links.jsonl に保存する。

「隠れた連絡先を推定・回収」ではなく「本人が公開したリンクを整理」する処理。
その先の窓口確認は、人が各サイトを見て行う想定。

Usage:
  uv run python -m scripts.extract_links                      # shops.jsonl を一括処理
  uv run python -m scripts.extract_links "https://example.com で販売中！IG @foo"   # 文字列1つを試す
"""
import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.shop_parser import extract_public_links
from src.utils import setup_logging

load_dotenv()


def _load_shops() -> list[dict]:
    out = Path("output")
    jsonl = out / "shops.jsonl"
    if jsonl.exists():
        return [json.loads(x) for x in jsonl.read_text(encoding="utf-8").splitlines() if x.strip()]
    js = out / "result_shop.json"
    if js.exists():
        return json.loads(js.read_text(encoding="utf-8"))
    return []


def _run_single(text: str) -> int:
    print(json.dumps(extract_public_links(text), ensure_ascii=False, indent=2))
    return 0


def _run_all() -> int:
    setup_logging(debug=False)
    shops = _load_shops()
    if not shops:
        print("FAIL: output/shops.jsonl も result_shop.json も無い。先に make shop-run を実行")
        return 1

    out = Path("output")
    rows: list[dict] = []
    hit = 0
    for shop in shops:
        links = extract_public_links(shop.get("description", ""))
        has_any = bool(
            links["website"] or links["instagram"] or links["youtube"]
            or links["twitter"] or links["line"]
        )
        rows.append({
            "shop_id": shop.get("shop_id"),
            "shop_name": shop.get("shop_name"),
            "follower_count": shop.get("follower_count"),
            "total_sold": shop.get("total_sold"),
            "store_url": shop.get("store_url"),
            "website": links["website"] or "",
            "instagram": links["instagram"] or "",
            "youtube": links["youtube"] or "",
            "twitter": links["twitter"] or "",
            "line": links["line"] or "",
            "all_urls": "; ".join(links["all_urls"]),
            "has_public_link": has_any,
        })
        if has_any:
            hit += 1
            print(f"  ✓ {shop.get('shop_name')}  website={links['website']} ig={links['instagram']}")

    jsonl_path, csv_path = out / "shop_links.jsonl", out / "shop_links.csv"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n完了: {hit}/{len(rows)} 件でセラー公開リンクを検出 → {csv_path}")
    if hit == 0:
        print("（0件は正常: desc がテンプレ文でURL無しの店が多いため。URLを貼る店だけ拾える）")
    return 0


def main():
    if len(sys.argv) > 1:
        sys.exit(_run_single(sys.argv[1]))
    sys.exit(_run_all())


if __name__ == "__main__":
    main()
