"""TikTokユーザーのデータモデル"""
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class TiktokUser:
    tiktok_user_id: str          # secUid（TikTok内部の不変ID）
    unique_id: str               # @username
    nickname: str                # 表示名
    signature: str               # bio
    avatar_url: str
    follower_count: int
    following_count: int
    video_count: int
    total_likes: int             # heartCount
    is_verified: bool = False
    instagram_username: Optional[str] = None
    youtube_url: Optional[str] = None
    twitter_username: Optional[str] = None
    source_hashtag: Optional[str] = None
    source_keyword: Optional[str] = None
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TiktokShop:
    """TikTok Shop 店舗（seller）のデータモデル

    一意キーは shop_id（= 店舗URL末尾の seller-id）。本番では doc id 候補になる。
    フィールドは店舗ページの埋め込みJSONに合わせて Stage 2 で確定する想定。
    """
    shop_id: str                        # seller-id（URL末尾の数値）= 一意キー
    store_slug: str                     # store-slug（URL中間のスラッグ）
    store_url: str                      # 取得元の完全URL
    shop_name: str = ""
    follower_count: int = 0
    total_sold: int = 0                 # 総販売数
    product_count: int = 0              # 販売中商品数
    rating: Optional[float] = None      # 店舗評価
    rating_count: int = 0
    avatar_url: Optional[str] = None
    tiktok_username: Optional[str] = None  # 紐づく @アカウント（あれば）
    is_official: bool = False
    source_type: Optional[str] = None   # "entry" | "hashtag" | "seed"
    source_value: Optional[str] = None  # 発見元（entry URL / hashtag 語 / "seed"）
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)
