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

    一意キーは shop_id（= shop_info.seller_id）。本番では doc id 候補になる。
    フィールドは shop.tiktok.com の PDP/店舗ページに埋め込まれた
    __MODERN_ROUTER_DATA__ の shop_info（実測で確定）に対応する。
    """
    shop_id: str                        # seller_id = 一意キー
    store_slug: str                     # shop_link 中のスラッグ（表示・識別用）
    store_url: str                      # 確実に開けるURL（取得元PDP）。独立店舗ページは公開GET不可
    shop_name: str = ""
    follower_count: int = 0             # shop_info.followers_count
    total_sold: int = 0                 # shop_info.sold_count
    product_count: int = 0             # shop_info.on_sell_product_count
    video_count: int = 0               # shop_info.video_count
    rating: Optional[float] = None      # shop_info.shop_rating
    rating_count: int = 0              # shop_info.review_count
    avatar_url: Optional[str] = None    # shop_info.shop_logo.url_list[0]
    region: Optional[str] = None        # shop_info.region（例: "JP"）
    description: Optional[str] = None    # shop_info.desc
    is_official: bool = False
    source_type: Optional[str] = None   # "pdp" | "store" | "seed"
    source_value: Optional[str] = None  # 発見元URL（取得元の PDP/店舗URL）
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)
