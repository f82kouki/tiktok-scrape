"""parser.py の単体テスト

使い方:
1. ブラウザで https://www.tiktok.com/@<some_user> を開きソース表示
2. 全選択コピーして tests/fixtures/profile_sample.html に保存
3. uv run pytest -v
"""
from pathlib import Path
from src.parser import parse_profile, extract_universal_json_from_html


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_parse_profile_from_universal_data():
    fixture = FIXTURE_DIR / "profile_sample.html"
    if not fixture.exists():
        import pytest
        pytest.skip("fixture not prepared")
    html = fixture.read_text(encoding="utf-8")
    user = parse_profile(html, username="test", source_keyword="test")
    assert user is not None, "parse_profile returned None"
    assert user.unique_id != "", "unique_id is empty"
    assert user.follower_count >= 0
    assert user.tiktok_user_id != "", "tiktok_user_id (secUid) is empty"


def test_extract_universal_json_returns_dict():
    fixture = FIXTURE_DIR / "profile_sample.html"
    if not fixture.exists():
        import pytest
        pytest.skip("fixture not prepared")
    html = fixture.read_text(encoding="utf-8")
    data = extract_universal_json_from_html(html)
    assert data is not None
    assert "__DEFAULT_SCOPE__" in data
