"""enrich.py の純関数テスト（ネット不要）

抽出（email/phone/label）と、誤検出防止の店名照合ゲートを検証する。
検索/取得を伴う ContactEnricher.enrich() はライブ確認（make shop-enrich NAME=...）で行う。
"""
from src.enrich import (
    _clean_emails,
    _clean_phones,
    _label_value,
    _page_matches_shop,
    _score_candidate,
)


def test_clean_emails_filters_noise():
    html = "問い合わせ elf@silk.ocn.ne.jp ロゴ logo@2x.png cdn@googleapis.com a@example.com"
    emails = _clean_emails(html)
    assert "elf@silk.ocn.ne.jp" in emails
    assert all("2x.png" not in e and "googleapis" not in e and "example." not in e for e in emails)


def test_clean_phones_jp():
    text = "電話番号：048-242-3146 / 03-1234-5678 だけど 12345 は無視"
    phones = _clean_phones(text)
    assert "048-242-3146" in phones
    assert "03-1234-5678" in phones


def test_label_value_stops_at_next_field():
    text = "会社名：株式会社クラシカルエルフ 電話番号：048-242-3146 所在地：埼玉県戸田市上戸田3-2-8　定休日：土日"
    assert _label_value(text, ("会社名", "販売業者")) == "株式会社クラシカルエルフ"
    assert _label_value(text, ("所在地", "住所")) == "埼玉県戸田市上戸田3-2-8"


def test_page_matches_shop_true_for_real_site():
    assert _page_matches_shop(
        "… クラシカルエルフ 会社概要 … https://classicalelf.shop/pages/law",
        "Classical Elf【公式】",
    )
    assert _page_matches_shop("Classical Elf official store", "Classical Elf【公式】")


def test_page_matches_shop_rejects_unrelated_page():
    # 店名を含まない別サイト（特商法の解説記事など）は弾く＝誤検出防止
    assert not _page_matches_shop(
        "特定商取引法違反とは 弁護士法人 0120-929-739 https://law-bright.com/",
        "Kola Kola あったかROOM",
    )


def test_score_candidate_prefers_contact_pages():
    assert _score_candidate("https://x.jp/pages/law", "特定商取引法に基づく表記") >= 4
    assert _score_candidate("https://x.jp/news/123", "新着情報") == 0
