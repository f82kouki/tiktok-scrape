.PHONY: help install login step0 step1 step2 step3 scale run test clean diag probe-qr shop-dump shop-recon shop-discover shop-run

# 既定値（呼び出し時に上書き可能）
HASHTAG ?= コスメ
KEYWORD ?= 美容ブロガー
MIN_FOLLOWERS ?= 100
MAX ?= 20
MAX_USERS_PER_QUERY ?= 30

help:  ## このヘルプを表示
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "変数の上書き例:"
	@echo "  make step2 HASHTAG=メイク MAX=10 MIN_FOLLOWERS=5000"
	@echo "  make step3 KEYWORD=ガジェット"

install:  ## 依存と patchright/Chromium をインストール（初回のみ）
	uv sync
	uv run scrapling install

login:  ## TikTok に手動ログイン（cookie を ./.tiktok_profile に保存）
	uv run python -m scripts.login

step0:  ## Step 0: ブラウザ起動の最低疎通（example.com）
	uv run python -m scripts.check_browser

step1:  ## Step 1: 単一プロフィール取得（@tiktok）
	uv run python -m scripts.check_profile

step2:  ## Step 2: ハッシュタグ経由（HASHTAG / MIN_FOLLOWERS / MAX / MAX_USERS_PER_QUERY で上書き可）
	uv run python -m src.main --hashtag "$(HASHTAG)" --min-followers $(MIN_FOLLOWERS) --max-users-per-query $(MAX_USERS_PER_QUERY) --max $(MAX) --debug

step3:  ## Step 3: キーワード検索（無効化済み: TikTok robots.txt が /search/user?q= を Disallow）
	@echo ""
	@echo "  ⛔  step3 (キーワード検索) は無効化されています"
	@echo ""
	@echo "  理由: TikTok の robots.txt が /search/user?q= を明示的に Disallow しています。"
	@echo "        ToS 違反リスクのため自動実行は禁止としました。"
	@echo ""
	@echo "  代替: make step2 (ハッシュタグ検索)"
	@echo "        ハッシュタグ /tag/ は robots.txt で Allow されています。"
	@echo ""
	@echo "  どうしても叩きたい場合は src/main.py を直接呼んでください："
	@echo "    uv run python -m src.main --keyword \"<word>\" --max <N>"
	@echo "    （ただし TikTok ToS 違反、アカウントbanリスクあり、自己責任）"
	@echo ""
	@exit 1

# 本番近い規模ラン: 5ハッシュタグ × 各50件、最大250件
# - 結果は1件ごとに output/result.json に逐次保存される（途中Ctrl+Cでも安全）
# - 所要時間: おおよそ 1〜2 時間（リクエスト間4〜8秒 × 50 + プロフィールロード時間）
# - HASHTAGS は他のタグに変えたい場合は make scale HASHTAGS="メンズコスメ ヘアアレンジ ..." で上書き
SCALE_HASHTAGS ?= コスメ メイク スキンケア アイメイク リップ
SCALE_MAX_PER_QUERY ?= 50
SCALE_MAX ?= 50

scale:  ## 本番近い規模: 5タグ×50件 (1〜2時間、逐次保存される)
	REQUEST_INTERVAL_MIN=10 REQUEST_INTERVAL_MAX=30 \
	uv run python -m src.main \
		$(foreach h,$(SCALE_HASHTAGS),--hashtag "$(h)") \
		--max-users-per-query $(SCALE_MAX_PER_QUERY) \
		--max $(SCALE_MAX) \
		--min-followers $(MIN_FOLLOWERS) \
		--debug

run: step2  ## step2 のエイリアス

diag:  ## ハッシュタグページの診断（HASHTAG で上書き可）
	uv run python -m scripts.diagnose_hashtag "$(HASHTAG)"

probe-qr:  ## Phase 0: TikTok QR ログインページ挙動検証
	uv run python -m scripts.probe_qr

# ---- TikTok Shop 店舗スクレイパー PoC ----
# 発見は robots 許可パス（shop.tiktok.com/jp + /tag/）と seed URL のみ。
# /search 系・/shop/view/product/ は Disallow のため使わない。
SHOP_URL ?= https://www.tiktok.com/shop/store/goli-nutrition/7495794203056835079
SHOP_MAX ?= 20

shop-dump:  ## Stage2【最重要】店舗ページ構造ダンプ（SHOP_URL="..." で上書き）
	uv run python -m scripts.dump_store_page "$(SHOP_URL)"

shop-recon:  ## Stage4a: shop.tiktok.com/jp 手動リコン（DevTools で XHR/URL 確認）
	uv run python -m scripts.diagnose_shop

shop-discover:  ## Stage4b: 許可パスからの自動発見テスト
	uv run python -m scripts.check_shop_discovery $(SHOP_MAX)

shop-run:  ## Stage5: 小ロット本ラン（seed+発見→取得、逐次保存 / SHOP_MAX で上書き）
	uv run python -m src.shop_main --max $(SHOP_MAX) --debug

test:  ## pytest 実行
	uv run pytest -v

clean:  ## output/ をクリア
	rm -rf output/*.json output/*.csv output/*.jsonl
	@echo "cleaned output/"
