"""shop_parser.py の単体テスト

使い方:
1. make shop-dump URL="<店舗URL>" で output/store_page.html を保存
2. それを tests/fixtures/store_sample.html にコピー
3. src/shop_parser.py parse_store() のフィールドパスを実構造に合わせて確定
4. uv run pytest tests/test_shop_parser.py -v

fixture が無い間は skip される（Stage 2 前でも壊れない）。
"""
from pathlib import Path

from src.shop_parser import (
    parse_store,
    extract_store_urls_from_html,
    _parse_ids_from_url,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_URL = "https://www.tiktok.com/shop/store/example-store/7495794203056835079"


def test_parse_ids_from_url():
    slug, sid = _parse_ids_from_url(SAMPLE_URL)
    assert slug == "example-store"
    assert sid == "7495794203056835079"


def test_extract_store_urls_from_plain_html():
    html = (
        '<a href="/shop/store/goli/7495794203056835079">x</a>'
        '<a href="/shop/view/product/123">product(除外対象)</a>'
        '<a href="https://www.tiktok.com/shop/store/foo-bar/1234567890123456789">y</a>'
    )
    urls = extract_store_urls_from_html(html, max_urls=10)
    assert "https://www.tiktok.com/shop/store/goli/7495794203056835079" in urls
    assert "https://www.tiktok.com/shop/store/foo-bar/1234567890123456789" in urls
    # /shop/view/product/ は robots Disallow のため拾わない
    assert all("view/product" not in u for u in urls)


def test_parse_store_from_fixture():
    fixture = FIXTURE_DIR / "store_sample.html"
    if not fixture.exists():
        import pytest
        pytest.skip("fixture not prepared")
    html = fixture.read_text(encoding="utf-8")
    shop = parse_store(html, SAMPLE_URL, source_type="seed", source_value="seed")
    assert shop is not None, "parse_store returned None"
    assert shop.shop_id != "", "shop_id (seller-id) is empty"
    assert shop.store_url == SAMPLE_URL
    # ↓ Stage 2 で parse_store() 確定後は、以下も有効化して回帰テストにする:
    # assert shop.shop_name != ""
    # assert shop.follower_count >= 0
