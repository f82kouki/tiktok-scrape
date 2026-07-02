"""Phase 0: TikTok QR ログインページの挙動検証スクリプト

目的:
1. tiktok.com/login/qrcode が patchright で開けるか
2. QR コードがどの DOM 要素に入っているか (canvas / img / svg)
3. QR スキャン後の URL 遷移パターン (ログイン完了の検知方法)
4. cookie が永続化されることの確認

成果物:
  - .tiktok_qr_probe/    Chromium プロファイル (cookie 含む)
  - output/qr_page.html  ページ HTML 全体
  - output/qr_page.png   スクリーンショット

Usage:
  make probe-qr
  または: uv run python -m scripts.probe_qr
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from patchright.async_api import async_playwright

load_dotenv()

PROBE_DIR = "./.tiktok_qr_probe"
QR_URL = "https://www.tiktok.com/login/qrcode"

# QR コード DOM 候補 (どれかにヒットすれば本実装で使う)
QR_CANDIDATE_SELECTORS = [
    "canvas",
    "img[src*='qr']",
    "img[src^='data:image']",
    "[class*='qr']",
    "[class*='QR']",
    "[class*='scan']",
]


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


async def main() -> int:
    Path(PROBE_DIR).mkdir(parents=True, exist_ok=True)
    Path("output").mkdir(exist_ok=True)
    profile_abs = str(Path(PROBE_DIR).resolve())

    section("Phase 0: TikTok QR ログイン挙動検証")
    print(f"プロファイル保存先: {profile_abs}")
    print(f"対象 URL          : {QR_URL}")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=profile_abs,
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Step 1: ページにアクセス
        section("Step 1: QR ログインページを開く")
        try:
            await page.goto(
                QR_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            print("✓ ページアクセス成功")
        except Exception as e:
            print(f"❌ ページが開けません: {e}")
            await ctx.close()
            return 1

        # JS が走り終わるのを少し待つ
        await asyncio.sleep(3)

        # Step 2: URL 確認 (リダイレクトされてないか)
        section("Step 2: 現在の URL")
        print(f"  {page.url}")
        if "qrcode" not in page.url:
            print("⚠️  QR ページからリダイレクトされました")

        # Step 3: QR コード DOM 候補のスキャン
        section("Step 3: QR コード DOM 候補を探索")
        any_hit = False
        for sel in QR_CANDIDATE_SELECTORS:
            try:
                els = await page.query_selector_all(sel)
                if not els:
                    print(f"  ✗ {sel:40s} 0 件")
                    continue
                any_hit = True
                print(f"  ✓ {sel:40s} {len(els)} 件")
                for i, el in enumerate(els[:3]):
                    try:
                        outer = await el.evaluate(
                            "e => e.outerHTML.slice(0, 200)"
                        )
                        print(f"     [{i}] {outer[:180]}")
                    except Exception as e:
                        print(f"     [{i}] (取得失敗: {e})")
            except Exception as e:
                print(f"  ✗ {sel:40s} エラー: {e}")
        if not any_hit:
            print("⚠️  どのセレクタもヒットしませんでした")
            print("    output/qr_page.html を解析してセレクタを再検討してください")

        # Step 4: HTML 全体を保存
        section("Step 4: HTML を保存")
        html = await page.content()
        out_html = Path("output/qr_page.html")
        out_html.write_text(html, encoding="utf-8")
        print(f"  saved: {out_html} ({len(html):,} chars)")

        # login-wall / CAPTCHA キーワード検出
        lower = html.lower()
        flags = []
        for kw in ("captcha", "verify", "log in", "sign up", "ログイン", "ロボット", "ブロック"):
            if kw in lower:
                flags.append(kw)
        if flags:
            print(f"⚠️  HTML に検出されたキーワード: {flags}")

        # Step 5: スクリーンショット保存
        section("Step 5: スクリーンショット保存")
        out_png = Path("output/qr_page.png")
        await page.screenshot(path=str(out_png), full_page=True)
        print(f"  saved: {out_png}")

        # Step 6: 人間操作待機
        section("Step 6: スマホで QR スキャン")
        print("  1. 画面に QR コードが表示されているか目視確認")
        print("  2. スマホ TikTok アプリでスキャン (※ 捨てアカ推奨)")
        print("  3. アプリ側で「ログインしますか?」→ 確認")
        print("  4. アプリでログイン押した後、このターミナルに戻って Enter")
        print()
        print("  ※ 重要: Chromium ウィンドウは何があっても閉じない/触らない")
        print()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, input, "ログイン押した後、Enter > "
        )

        # Step 6.5: ブラウザを最前面に持ってきて JS スロットル解除を促す
        section("Step 6.5: ブラウザにフォーカスを戻す + sessionid を最大 60 秒 polling")
        try:
            await page.bring_to_front()
        except Exception:
            pass

        sessionid_found = False
        for i in range(30):  # 2 秒 × 30 = 60 秒
            await asyncio.sleep(2)
            try:
                cookies_now = await ctx.cookies()
            except Exception:
                cookies_now = []
            has_session = any(c.get("name") == "sessionid" for c in cookies_now)
            current_url = page.url
            print(f"  [{(i+1)*2:>3}s] url={current_url[:60]}  sessionid={'✓' if has_session else '✗'}")
            if has_session:
                sessionid_found = True
                print(f"\n  ✓ sessionid を {(i+1)*2} 秒で検出")
                break

        if not sessionid_found:
            print("\n  ❌ 60 秒待っても sessionid が出ない")

        # Step 6.7: スキャン後のスクショと HTML を保存 (状態確認用)
        section("Step 6.7: スキャン後の状態を保存")
        try:
            await page.screenshot(path="output/qr_page_after.png", full_page=True)
            print("  saved: output/qr_page_after.png")
            html_after = await page.content()
            Path("output/qr_page_after.html").write_text(html_after, encoding="utf-8")
            print(f"  saved: output/qr_page_after.html ({len(html_after):,} chars)")
        except Exception as e:
            print(f"  保存失敗: {e}")

        # Step 7: 最終 URL
        section("Step 7: 最終 URL")
        print(f"  {page.url}")
        if "qrcode" in page.url:
            print("  ⚠️  まだ QR ページ (URL ベース完了検知は使えない可能性)")
        else:
            print("  ↑ これが完了検知のパターン (page.wait_for_url で使う)")

        # Step 8: cookie 確認
        section("Step 8: cookie 確認")
        try:
            cookies = await ctx.cookies()
        except Exception as e:
            print(f"❌ cookies 取得失敗: {e}")
            cookies = []

        sessionid = next(
            (c for c in cookies if c.get("name") == "sessionid"), None
        )
        if sessionid:
            value = sessionid.get("value", "")
            expires = sessionid.get("expires", -1)
            print(f"  ✓ sessionid 取得: {value[:20]}...")
            print(f"    expires: {expires} (-1 = session cookie)")
        else:
            print("  ❌ sessionid が cookie に無い (ログイン未完了の可能性)")

        # 他に重要そうな cookie も列挙
        important = ["sessionid", "tt_csrf_token", "ms_token", "tt-target-idc",
                     "passport_csrf_token"]
        print()
        print("  主要 cookie 確認:")
        for name in important:
            c = next((c for c in cookies if c.get("name") == name), None)
            mark = "✓" if c else "✗"
            print(f"    {mark} {name}")

        await ctx.close()

        # Step 9: SQLite に書き込まれたか
        section("Step 9: cookie SQLite 永続化確認")
        cookies_db = Path(profile_abs) / "Default" / "Cookies"
        if cookies_db.exists():
            size = cookies_db.stat().st_size
            print(f"  ✓ {cookies_db}")
            print(f"    サイズ: {size:,} bytes")
        else:
            print(f"  ❌ {cookies_db} が無い")

        # 完了サマリ
        section("✓ Phase 0 検証完了")
        print(f"  プロファイル: {profile_abs}")
        print(f"  HTML       : {out_html}")
        print(f"  スクショ   : {out_png}")
        print()
        print("次の確認: 既存 scraper でこの cookie が使えるか")
        print(f"  TIKTOK_USER_DATA_DIR={profile_abs} make step1")
        print()

        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
