.PHONY: help install step0 step1 step2 step3 run test clean

# 既定値（呼び出し時に上書き可能）
HASHTAG ?= コスメ
KEYWORD ?= 美容ブロガー
MIN_FOLLOWERS ?= 10000
MAX ?= 5

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

step0:  ## Step 0: ブラウザ起動の最低疎通（example.com）
	uv run python -m scripts.check_browser

step1:  ## Step 1: 単一プロフィール取得（@tiktok）
	uv run python -m scripts.check_profile

step2:  ## Step 2: ハッシュタグ経由（HASHTAG / MIN_FOLLOWERS / MAX で上書き可）
	uv run python -m src.main --hashtag "$(HASHTAG)" --min-followers $(MIN_FOLLOWERS) --max $(MAX) --debug

step3:  ## Step 3: キーワード経由（KEYWORD / MAX で上書き可。login-wallで取れない可能性あり）
	uv run python -m src.main --keyword "$(KEYWORD)" --max $(MAX) --debug

run: step2  ## step2 のエイリアス

test:  ## pytest 実行
	uv run pytest -v

clean:  ## output/ をクリア
	rm -rf output/*.json output/*.csv
	@echo "cleaned output/"
