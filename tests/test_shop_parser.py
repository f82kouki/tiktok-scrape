"""shop_parser.py の単体テスト（shop.tiktok.com 経路）

- URL抽出（カテゴリ/PDP/店舗ID）は純関数として inline HTML で検証。
- parse_shop は合成 __MODERN_ROUTER_DATA__ で決定論的に検証（fixture 不要）。
- 実HTML回帰は tests/fixtures/store_sample.html があれば追加検証（無ければ skip）。
  （make shop-dump で保存した output/store_page.html を置くと有効化）
"""
import json
from pathlib import Path

from src.shop_parser import (
    parse_shop,
    parse_store_ids,
    extract_category_urls_from_html,
    extract_pdp_urls_from_html,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_store_ids():
    slug, sid = parse_store_ids(
        "https://shop.tiktok.com/jp/store/perfect-diary-japan/7496204608949095270"
    )
    assert slug == "perfect-diary-japan"
    assert sid == "7496204608949095270"


def test_extract_category_urls():
    html = (
        '<a href="https://shop.tiktok.com/jp/c/beauty-personal-care/601450">x</a>'
        '<a href="/jp/c/makeup/848648">y</a>'
        '<a href="/jp/c/beauty-personal-care/601450">dup</a>'
    )
    urls = extract_category_urls_from_html(html)
    assert "https://shop.tiktok.com/jp/c/beauty-personal-care/601450" in urls
    assert "https://shop.tiktok.com/jp/c/makeup/848648" in urls
    assert len(urls) == 2  # 重複排除


def test_extract_pdp_urls():
    html = (
        '<a href="https://shop.tiktok.com/jp/pdp/1731687107318417254">a</a>'
        '<a href="/jp/pdp/some-slug/1732100037928060331">b</a>'   # slug 付き形
        '<a href="/jp/pdp/1731687107318417254">dup</a>'            # id 重複
    )
    urls = extract_pdp_urls_from_html(html)
    assert "https://shop.tiktok.com/jp/pdp/1731687107318417254" in urls
    assert "https://shop.tiktok.com/jp/pdp/1732100037928060331" in urls
    assert len(urls) == 2  # slug は落として id で正規化・重複排除


def _synthetic_pdp_html(shop_info: dict) -> str:
    router = {
        "loaderData": {
            "(region)/pdp/(product_name_slug$)/(product_id)/page": {
                "page_config": {
                    "components_map": [
                        {"component_data": {"foo": 1}},
                        {"component_data": {"shop_info": shop_info}},
                    ]
                }
            }
        },
        "errors": None,
    }
    return (
        '<html><body>'
        '<script id="__MODERN_ROUTER_DATA__" type="application/json">'
        + json.dumps(router, ensure_ascii=False)
        + "</script></body></html>"
    )


def test_parse_shop_from_synthetic_router_data():
    shop_info = {
        "seller_id": "7496204608949095270",
        "shop_name": "Perfect Diary Japan",
        "followers_count": "6135",
        "sold_count": 21246,
        "on_sell_product_count": 86,
        "video_count": "284",
        "review_count": 1502,
        "shop_rating": "4.6",
        "region": "JP",
        "desc": "Shop on TikTok Shop!",
        "shop_link": "https://shop.tiktok.com/jp/store/perfect-diary-japan/7496204608949095270",
        "shop_logo": {"url_list": ["https://example.com/logo.webp"]},
    }
    html = _synthetic_pdp_html(shop_info)
    shop = parse_shop(html, "https://shop.tiktok.com/jp/pdp/123", source_type="pdp")
    assert shop is not None
    assert shop.shop_id == "7496204608949095270"
    assert shop.store_slug == "perfect-diary-japan"
    # store_url は「確実に開ける」取得元URL（= 渡した source_url = PDP）。
    # 独立した店舗ページURL(shop_link / www の /shop/store/…)は公開GETで開けないため使わない。
    assert shop.store_url == "https://shop.tiktok.com/jp/pdp/123"
    assert shop.shop_name == "Perfect Diary Japan"
    assert shop.follower_count == 6135
    assert shop.total_sold == 21246
    assert shop.product_count == 86
    assert shop.video_count == 284
    assert shop.rating == 4.6
    assert shop.rating_count == 1502
    assert shop.avatar_url == "https://example.com/logo.webp"
    assert shop.region == "JP"


def test_parse_shop_missing_data_returns_none():
    assert parse_shop("<html>no router data</html>", "https://x/pdp/1") is None


def test_parse_shop_from_fixture():
    fixture = FIXTURE_DIR / "store_sample.html"
    if not fixture.exists():
        import pytest
        pytest.skip("fixture not prepared")
    html = fixture.read_text(encoding="utf-8")
    shop = parse_shop(html, "https://shop.tiktok.com/jp/pdp/fixture", source_type="pdp")
    assert shop is not None, "parse_shop returned None"
    assert shop.shop_id != "", "seller_id is empty"
    assert shop.follower_count >= 0
