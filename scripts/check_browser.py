"""Step 0: patchright/Chromium が起動して example.com を取れるか確認"""
from scrapling.fetchers import StealthyFetcher

page = StealthyFetcher.fetch("https://example.com", headless=True)
print(f"status: {page.status}")
print(f"len:    {len(page.body)}")
assert page.status == 200, "expected status 200"
print("OK: browser launch succeeded")
