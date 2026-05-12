"""共通ユーティリティ"""
import logging
import os
import random
import asyncio


def setup_logging(debug: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def jittered_sleep(min_sec: float, max_sec: float) -> None:
    """min〜max の乱数秒スリープ"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default
