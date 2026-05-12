"""TikTokプロフィールページのパース処理

抽出は生HTMLからのregex抽出を主軸とする。
parse_profile() は新形式(UNIVERSAL)→旧形式(SIGI)の順で試すフォールバック付き。
"""
import json
import re
import logging
from typing import Optional
from src.models import TiktokUser

logger = logging.getLogger(__name__)


# ---------- JSON抽出 ----------

def extract_universal_json_from_html(html: str) -> Optional[dict]:
    """生HTMLから __UNIVERSAL_DATA_FOR_REHYDRATION__ を抽出"""
    match = re.search(
        r'<script[^>]+\bid="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse __UNIVERSAL_DATA_FOR_REHYDRATION__: {e}")
        return None


def extract_sigi_state_from_html(html: str) -> Optional[dict]:
    """生HTMLから SIGI_STATE を抽出（旧形式フォールバック）"""
    match = re.search(
        r'<script[^>]+\bid="SIGI_STATE"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


# ---------- ユーザーパース ----------

def parse_user_from_universal(
    data: dict,
    source_hashtag: Optional[str] = None,
    source_keyword: Optional[str] = None,
) -> Optional[TiktokUser]:
    """新形式 __UNIVERSAL_DATA_FOR_REHYDRATION__ → TiktokUser

    構造（2024年以降）:
    {
      "__DEFAULT_SCOPE__": {
        "webapp.user-detail": {
          "userInfo": {
            "user":  { "id", "secUid", "uniqueId", "nickname", "signature",
                       "avatarLarger", "verified", "bioLink": {"link": "..."} },
            "stats": { "followerCount", "followingCount", "heartCount", "videoCount" }
          }
        }
      }
    }
    """
    try:
        user_info = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
        user = user_info["user"]
        stats = user_info["stats"]
    except (KeyError, TypeError):
        return None

    bio_link = (user.get("bioLink") or {}).get("link", "")
    signature = user.get("signature", "")

    return TiktokUser(
        tiktok_user_id=user.get("secUid", ""),
        unique_id=user.get("uniqueId", ""),
        nickname=user.get("nickname", ""),
        signature=signature,
        avatar_url=user.get("avatarLarger") or user.get("avatarMedium", ""),
        follower_count=int(stats.get("followerCount", 0) or 0),
        following_count=int(stats.get("followingCount", 0) or 0),
        video_count=int(stats.get("videoCount", 0) or 0),
        total_likes=int(stats.get("heartCount", 0) or 0),
        is_verified=bool(user.get("verified", False)),
        instagram_username=_extract_instagram(bio_link) or _extract_instagram(signature),
        youtube_url=_extract_youtube(bio_link) or _extract_youtube(signature),
        twitter_username=_extract_twitter(bio_link) or _extract_twitter(signature),
        source_hashtag=source_hashtag,
        source_keyword=source_keyword,
    )


def parse_user_from_sigi(
    data: dict,
    username: str,
    source_hashtag: Optional[str] = None,
    source_keyword: Optional[str] = None,
) -> Optional[TiktokUser]:
    """旧形式 SIGI_STATE → TiktokUser（フォールバック）"""
    try:
        users = data.get("UserModule", {}).get("users", {})
        stats = data.get("UserModule", {}).get("stats", {})
        user = users.get(username) or next(iter(users.values()), None)
        if not user:
            return None
        st = stats.get(user.get("uniqueId", ""), {}) if isinstance(stats, dict) else {}
    except (KeyError, TypeError, AttributeError):
        return None

    signature = user.get("signature", "")
    return TiktokUser(
        tiktok_user_id=user.get("secUid", ""),
        unique_id=user.get("uniqueId", ""),
        nickname=user.get("nickname", ""),
        signature=signature,
        avatar_url=user.get("avatarLarger") or user.get("avatarMedium", ""),
        follower_count=int(st.get("followerCount", 0) or 0),
        following_count=int(st.get("followingCount", 0) or 0),
        video_count=int(st.get("videoCount", 0) or 0),
        total_likes=int(st.get("heartCount", 0) or 0),
        is_verified=bool(user.get("verified", False)),
        instagram_username=_extract_instagram(signature),
        youtube_url=_extract_youtube(signature),
        twitter_username=_extract_twitter(signature),
        source_hashtag=source_hashtag,
        source_keyword=source_keyword,
    )


def parse_profile(
    html: str,
    username: str = "",
    source_hashtag: Optional[str] = None,
    source_keyword: Optional[str] = None,
) -> Optional[TiktokUser]:
    """新形式 → 旧形式の順で試行"""
    data = extract_universal_json_from_html(html)
    if data:
        user = parse_user_from_universal(data, source_hashtag, source_keyword)
        if user and user.unique_id:
            return user

    sigi = extract_sigi_state_from_html(html)
    if sigi:
        user = parse_user_from_sigi(sigi, username, source_hashtag, source_keyword)
        if user and user.unique_id:
            return user

    logger.warning("Failed to parse profile (both UNIVERSAL and SIGI_STATE missing or empty)")
    return None


# ---------- ハッシュタグページからのusername抽出 ----------

def extract_usernames_from_hashtag_html(html: str, max_users: int = 30) -> list[str]:
    """
    ハッシュタグ/検索ページから投稿者の uniqueId を集める。
    1. __UNIVERSAL_DATA_FOR_REHYDRATION__ の itemList から author.uniqueId を取る
    2. それでダメなら href="/@username" の正規表現フォールバック
    """
    usernames: list[str] = []
    seen: set[str] = set()

    # login-wall 検出（HTMLの中身を判定）
    lower = html.lower()
    login_keywords = [kw for kw in ("log in", "login to", "sign up", "ログイン") if kw in lower]
    if login_keywords:
        logger.info(f"hashtag HTML contains login keywords: {login_keywords} (login-wall の可能性)")

    data = extract_universal_json_from_html(html)
    if data is None:
        logger.warning("__UNIVERSAL_DATA_FOR_REHYDRATION__ が HTML に存在しない")
    else:
        scope = data.get("__DEFAULT_SCOPE__", {})
        logger.info(f"__DEFAULT_SCOPE__ keys ({len(scope)}): {sorted(scope.keys())}")
        try:
            for key in ("webapp.challenge-detail", "webapp.video-list", "webapp.search"):
                if key not in scope:
                    logger.info(f"  scope[{key}] not present")
                    continue
                section = scope.get(key)
                if not isinstance(section, dict):
                    continue
                items = (
                    section.get("itemList")
                    or section.get("items")
                    or section.get("data", [])
                )
                if not isinstance(items, list):
                    logger.info(
                        f"  scope[{key}] present but no itemList/items/data list "
                        f"(keys={list(section.keys())[:10]})"
                    )
                    continue
                logger.info(f"  scope[{key}] has {len(items)} items")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    author = item.get("author")
                    if isinstance(author, dict):
                        uid = author.get("uniqueId")
                        if uid and uid not in seen:
                            seen.add(uid)
                            usernames.append(uid)
                            if len(usernames) >= max_users:
                                return usernames
        except Exception as e:
            logger.warning(f"hashtag JSON parse failed: {e}")

    # フォールバック1: 動画タイルの href のみ（最優先）
    # 動画タイルは <a href="https://www.tiktok.com/@user/video/N"> の絶対URL形式。
    # この形だけを拾うことで、サイドバー「おすすめ」やフッターのノイズを完全に除外する。
    video_tile_matches = re.findall(
        r'href="https?://www\.tiktok\.com/@([A-Za-z0-9._]+)/video/\d+"',
        html,
    )
    if video_tile_matches:
        logger.info(
            f"  video-tile regex found {len(video_tile_matches)} matches "
            f"(タイル投稿者のみ、サイドバー除外)"
        )
        for u in video_tile_matches:
            if u not in seen:
                seen.add(u)
                usernames.append(u)
                if len(usernames) >= max_users:
                    return usernames

    # フォールバック2: タイルが取れなかった時のみ広い regex
    # （タグページが login-wall 等で動画タイル無しの場合の最終手段）
    if len(usernames) < max_users:
        broad_matches = re.findall(
            r'href="(?:https?://www\.tiktok\.com)?/@([A-Za-z0-9._]+)(?:/|")',
            html,
        )
        if broad_matches:
            logger.info(
                f"  broad fallback regex found {len(broad_matches)} matches "
                f"(タイル取れず、サイドバー含む)"
            )
        for u in broad_matches:
            if u not in seen:
                seen.add(u)
                usernames.append(u)
                if len(usernames) >= max_users:
                    break

    return usernames


# ---------- bio内のSNSリンク抽出 ----------

def _extract_instagram(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", text)
    return m.group(1) if m else None


def _extract_youtube(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(youtube\.com/[^\s)]+|youtu\.be/[^\s)]+)", text)
    return m.group(1) if m else None


def _extract_twitter(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)", text)
    return m.group(1) if m else None
