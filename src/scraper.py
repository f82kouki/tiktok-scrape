"""Scrapling AsyncStealthySession を使ったTikTokスクレイパー

設計ポイント:
- StealthyFetcher.fetch() は1リクエストごとにブラウザ起動・終了するため非効率。
  AsyncStealthySession で1セッション維持して複数リクエスト共有する。
- TikTok は Cloudflare ではなく独自WAFなので solve_cloudflare=True は使わない。
- async_fetch がネイティブ非同期なので asyncio.to_thread は不要。
- Scrapling v0.3.13+ で StealthyFetcher のエンジンは patchright(Chromium) に変更され、
  humanize, os_randomize, geoip, addons, disable_ads, block_images 等の引数は削除済み。
  本実装は新APIに準拠する。
"""
import logging
import os
from contextlib import AsyncExitStack
from typing import AsyncGenerator, Optional

from scrapling.fetchers import AsyncStealthySession

from src.models import TiktokUser
from src.parser import parse_profile, extract_usernames_from_hashtag_html
from src.utils import jittered_sleep, env_bool

logger = logging.getLogger(__name__)


class TikTokScraper:
    BASE_URL = "https://www.tiktok.com"

    def __init__(self):
        self.interval_min = float(os.getenv("REQUEST_INTERVAL_MIN", "4.0"))
        self.interval_max = float(os.getenv("REQUEST_INTERVAL_MAX", "8.0"))
        self.proxy = os.getenv("HTTP_PROXY") or None
        self.headless = env_bool("HEADLESS", True)
        # 永続プロファイル（手動ログイン後の cookie を再利用）
        self.user_data_dir = os.getenv("TIKTOK_USER_DATA_DIR") or None
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[AsyncStealthySession] = None

    async def __aenter__(self):
        # AsyncExitStack で AsyncStealthySession のライフサイクルを安全に管理
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        session_kwargs = dict(
            headless=self.headless,
            network_idle=True,       # ネットワーク静止待ち（JS実行完了の目安）
            google_search=True,      # referer を Google にして自然に
            block_webrtc=True,       # WebRTCリーク防止（プロキシ使用時必須級）
            hide_canvas=True,        # canvas fingerprinting対策
            timeout=60000,           # 60秒（TikTokのレンダリングは重い）
            proxy=self.proxy,
        )
        if self.user_data_dir:
            session_kwargs["user_data_dir"] = self.user_data_dir
            logger.info(f"using persistent profile: {self.user_data_dir}")
        self._session = await self._stack.enter_async_context(
            AsyncStealthySession(**session_kwargs)
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc, tb)
            self._stack = None
            self._session = None

    async def _fetch(self, url: str, wait_selector: Optional[str] = None):
        if self._session is None:
            raise RuntimeError("TikTokScraper must be used as async context manager")
        kwargs = {}
        if wait_selector:
            kwargs["wait_selector"] = wait_selector
        return await self._session.fetch(url, **kwargs)

    async def fetch_html(
        self,
        url: str,
        retries: int = 3,
        wait_selector: Optional[str] = None,
    ) -> Optional[str]:
        for attempt in range(retries):
            try:
                page = await self._fetch(url, wait_selector=wait_selector)
                if page is None:
                    logger.warning(f"None page at {url} (attempt {attempt + 1})")
                elif getattr(page, "status", None) and page.status >= 400:
                    logger.warning(
                        f"HTTP {page.status} at {url} (attempt {attempt + 1})"
                    )
                elif not page.body:
                    logger.warning(f"Empty body at {url} (attempt {attempt + 1})")
                else:
                    body = page.body.decode("utf-8", errors="replace")
                    logger.debug(
                        f"fetched {url}: status={getattr(page, 'status', '?')} "
                        f"body={len(body):,} chars"
                    )
                    return body
            except Exception as e:
                logger.error(f"Fetch failed {url} attempt {attempt + 1}: {e}")
            # 5秒+5*attempt+ジッターで待つ（指数より緩めに）
            await jittered_sleep(5 + 5 * attempt, 10 + 5 * attempt)
        return None

    async def discover_usernames_by_hashtag(
        self, hashtag: str, max_users: int = 30
    ) -> list[str]:
        """ハッシュタグページから投稿者usernameを発見

        動画タイルは XHR で遅延ロードされるため、 challenge-item セレクタを待つ。
        """
        url = f"{self.BASE_URL}/tag/{hashtag}"
        html = await self.fetch_html(
            url, wait_selector='[data-e2e="challenge-item"]'
        )
        if not html:
            return []

        # SAVE_HASHTAG_HTML=true なら、スクレイパーが実際に見た HTML を
        # output/hashtag_{hashtag}_{timestamp}.html に保存（証明用）
        if env_bool("SAVE_HASHTAG_HTML", False):
            from datetime import datetime
            from pathlib import Path
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = Path("output") / f"hashtag_{hashtag}_{ts}.html"
            out_path.parent.mkdir(exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
            logger.info(f"  saved hashtag HTML: {out_path} ({len(html):,} chars)")

        usernames = extract_usernames_from_hashtag_html(html, max_users=max_users)
        logger.info(f"hashtag={hashtag}: discovered {len(usernames)} usernames")
        return usernames

    async def discover_usernames_by_keyword(
        self, keyword: str, max_users: int = 30
    ) -> list[str]:
        """ユーザー検索ページから投稿者usernameを発見

        注意: /search/user?q=... は2024年以降ログイン要求が増えており、
        未ログインで叩くと空 or リダイレクトされる可能性が高い。
        練習PoCでは「動かなくても落胆しない」想定で実装している。
        """
        from urllib.parse import quote
        url = f"{self.BASE_URL}/search/user?q={quote(keyword)}"
        html = await self.fetch_html(
            url, wait_selector="script#__UNIVERSAL_DATA_FOR_REHYDRATION__"
        )
        if not html:
            logger.warning(
                f"keyword search returned no HTML (login wall の可能性高): {keyword}"
            )
            return []
        usernames = extract_usernames_from_hashtag_html(html, max_users=max_users)
        logger.info(f"keyword={keyword}: discovered {len(usernames)} usernames")
        return usernames

    async def fetch_user(
        self,
        username: str,
        source_hashtag: Optional[str] = None,
        source_keyword: Optional[str] = None,
    ) -> Optional[TiktokUser]:
        url = f"{self.BASE_URL}/@{username}"
        html = await self.fetch_html(
            url, wait_selector="script#__UNIVERSAL_DATA_FOR_REHYDRATION__"
        )
        if not html:
            return None
        return parse_profile(
            html,
            username=username,
            source_hashtag=source_hashtag,
            source_keyword=source_keyword,
        )

    async def scrape(
        self,
        hashtags: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        min_followers: int = 1000,
        max_users_per_query: int = 30,
        max_total: int = 100,
    ) -> AsyncGenerator[TiktokUser, None]:
        """ハッシュタグ・キーワードを順に処理し、条件に合うユーザーをyield"""
        seen_user_ids: set[str] = set()
        total_yielded = 0

        async def process_username_list(
            usernames: list[str],
            source_hashtag: Optional[str] = None,
            source_keyword: Optional[str] = None,
        ):
            nonlocal total_yielded
            for username in usernames:
                if total_yielded >= max_total:
                    return
                await jittered_sleep(self.interval_min, self.interval_max)
                user = await self.fetch_user(
                    username,
                    source_hashtag=source_hashtag,
                    source_keyword=source_keyword,
                )
                if not user or not user.tiktok_user_id:
                    continue
                if user.tiktok_user_id in seen_user_ids:
                    continue
                if user.follower_count < min_followers:
                    logger.debug(
                        f"skip @{user.unique_id}: followers {user.follower_count} < {min_followers}"
                    )
                    continue
                seen_user_ids.add(user.tiktok_user_id)
                total_yielded += 1
                yield user

        for hashtag in (hashtags or []):
            usernames = await self.discover_usernames_by_hashtag(hashtag, max_users_per_query)
            async for u in process_username_list(usernames, source_hashtag=hashtag):
                yield u
            if total_yielded >= max_total:
                return

        for keyword in (keywords or []):
            usernames = await self.discover_usernames_by_keyword(keyword, max_users_per_query)
            async for u in process_username_list(usernames, source_keyword=keyword):
                yield u
            if total_yielded >= max_total:
                return
