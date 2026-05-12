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
