# TikTok Shop 店舗抽出＋営業リード PoC 作業ログ

> 作成日: 2026-07-02
> ブランチ: `202607/02_shop-store-scraper-poc`
> 目的: TikTok Shop の店舗情報を横断収集し、営業リード（店舗指標＋連絡先）を作る PoC。
> このドキュメントは、ここまでの実装・実測で判明した事実・設計判断・未解決点を1枚にまとめた作業ログ（引き継ぎ用）。

---

## 0. TL;DR（何ができて、何が壁か）

- ✅ **店舗データ収集は成立**：`shop.tiktok.com/jp` → カテゴリ → 商品(PDP) と辿り、商品ページ埋め込みの `shop_info` から **店名・フォロワー・販売数・商品数・動画数・評価・レビュー数** を安定取得（seller_id で重複排除）。
- ✅ **公開リンク整理**：店舗説明文(desc)からセラーが自分で貼った 自社サイト/Instagram 等を抽出（オフライン・無料）。
- 🟡 **連絡先エンリッチ**：店名を Web 検索し「特定商取引法に基づく表記」等から 会社名・メール・電話 を抽出。**自社サイトを持つブランドは取れる／TikTok専業・汎用名の店は取れない**（部分的）。**速度が遅い**のが難点。
- ❌ **店舗ページの独立URLは公開GET不可**（`store_url` は開ける PDP URL で代替）。
- 🔍 **アプリの「このショップについて」（＝特商法：商号/電話/住所/代表）**はバックエンドに存在するが、**専用の on-demand API** でしか出ず、web(特にデスクトップ)には UI が無い。自動取得には追加のリバースエンジニアリングが必要（未達）。

---

## 1. 前提（既存プロジェクトとの関係）

このリポジトリは元々 **TikTok インフルエンサー（プロフィール）スクレイパー**（`scrapling` + `patchright` + cookie）。今回の店舗スクレイパーは**既存を壊さず並置**し、セッション/fetch などの共通部分を継承・再利用している。

| 再利用元（既存） | 使い方 |
|---|---|
| `src/scraper.py` `TikTokScraper`（セッション/`fetch_html`/retry/stealth） | 店舗スクレイパーが**サブクラス**して継承 |
| `src/parser.py` `_extract_instagram/_extract_youtube/_extract_twitter` | 公開リンク抽出でそのまま再利用 |
| `src/utils.py` `jittered_sleep/env_bool/setup_logging` | そのまま |
| `scripts/login.py` / `probe_qr.py`（cookie 取得） | ログインは既存を使用（`.tiktok_profile`） |

---

## 2. 実装したファイル一覧（すべて追加 / 既存は削除していない）

### 収集・パース
| ファイル | 役割 |
|---|---|
| `src/models.py`（追記） | `TiktokShop` dataclass（shop_info 実キーに対応） |
| `src/shop_parser.py`（新規） | `extract_modern_router_data` / `find_shop_info` / `parse_shop` / カテゴリ・PDP URL抽出 / `parse_store_ids` / `extract_public_links` |
| `src/shop_scraper.py`（新規） | `TikTokShopScraper(TikTokScraper)`：`fetch_shop` / `discover_category_urls` / `discover_pdp_urls` / `scrape`（seller_id 重複排除） |
| `src/shop_main.py`（新規） | 小ロット実行CLI。`output/result_shop.{json,csv}` と `shops.jsonl` に逐次保存 |

### 連絡先・リンク
| ファイル | 役割 |
|---|---|
| `src/enrich.py`（新規） | `ContactEnricher`：店名→検索(DuckDuckGo)→特商法/会社概要ページ→email/電話/会社名/住所抽出。**誤検出防止ゲート**（ページに店名が含まれるか照合）付き |
| `scripts/enrich_shops.py`（新規） | `shops.jsonl` を一括エンリッチ→`output/leads.{csv,jsonl}` |
| `scripts/extract_links.py`（新規） | desc からセラー公開URL/SNSを抽出→`output/shop_links.{csv,jsonl}`（オフライン） |

### 診断スクリプト
| ファイル | 役割 |
|---|---|
| `scripts/dump_store_page.py`（新規） | PDP/店舗ページの構造ダンプ＆`parse_shop`結果確認 |
| `scripts/diagnose_shop.py`（新規） | `shop.tiktok.com/jp` の手動リコン（patchright非ヘッドレス） |
| `scripts/check_shop_discovery.py`（新規） | 入口→カテゴリ→PDP の自動発見テスト |

### テスト・設定
| ファイル | 役割 |
|---|---|
| `tests/test_shop_parser.py`（新規） | パース・URL抽出・公開リンク抽出の単体 |
| `tests/test_enrich.py`（新規） | 抽出・誤検出防止ゲートの単体 |
| `pyproject.toml`（追記） | `[tool.pytest.ini_options] pythonpath=["."]`（`make test` が元々壊れていた問題の修正） |
| `Makefile`（追記） | `shop-dump / shop-recon / shop-discover / shop-run / shop-enrich / shop-links` |
| `.env.example`（追記） | `TIKTOK_SHOP_ENTRY_URL` 等 |

**検証状況**：`uv run pytest` → **13 passed / 3 skipped**、`ruff check` → clean。

---

## 3. 使い方（コマンド）

```bash
# 準備（初回）
make install
make login                         # cookie を ./.tiktok_profile に保存

# 本番フロー（営業リスト）
make shop-run SHOP_MAX=20          # ①店舗収集 → output/shops.jsonl, result_shop.csv
make shop-links                    # ②公開リンク整理（無料・一瞬）→ shop_links.csv
make shop-enrich                   # ③連絡先エンリッチ（遅い・部分的）→ leads.csv

# 単体お試し
make shop-dump  SHOP_URL="https://shop.tiktok.com/jp/pdp/<id>"
make shop-enrich NAME="Classical Elf【公式】"
make shop-links  TEXT="公式 https://... IG instagram.com/xxx"

# 診断
make shop-discover     # 発見が機能するか
make shop-recon        # 入口の構造を目視
```

---

## 4. 実測で判明した重要事実

### 4-1. robots.txt（コンプライアンス）
`www.tiktok.com/robots.txt`（User-agent: *）実測：

| パス | 判定 | 扱い |
|---|---|---|
| `/shop/store/{slug}/{id}` | Disallow なし | 取得可 |
| `/shop/view/product/` | **Disallow** | 使わない |
| `/search?` `/search/user?q=` `/search/video?` | **Disallow** | 使わない（検索発見は不採用） |
| `/tag` | **Allow** | 既存ハッシュタグ法はクリーン |

`shop.tiktok.com/robots.txt` は Allow列挙のみで catch-all Disallow 無し → `/jp/c/`・`/jp/pdp/`・`/jp/store/` は Disallow されていない（robots 上は取得可）。

> 補足：ユーザー確認事項だった「ハッシュタグ抽出も Disallow では？」は誤認。封印されていたのは `/search/user?q=`（キーワード検索）で、`/tag/` は Allow。

### 4-2. 店舗ページの構造（★元作戦書からのズレ）
`shop.tiktok.com` は本体 `www.tiktok.com` とは**別アプリ**（`tiktok_shop_web_mono`）。

| 項目 | 元作戦書の想定 | 実測 |
|---|---|---|
| 対象ページ | `www.tiktok.com/shop/store/{slug}/{id}` | `shop.tiktok.com/jp/pdp/{商品ID}` から店舗情報が取れる |
| 埋め込みJSON | `__UNIVERSAL_DATA_FOR_REHYDRATION__` | **`__MODERN_ROUTER_DATA__`**（別物。`SIGI_STATE` も無し） |
| 発見単位 | 店舗ページ直 | **商品(PDP)経由で店舗**（seller_id 重複排除） |

**`shop_info` の格納パス（確定）**：
```
__MODERN_ROUTER_DATA__
  .loaderData.{<region>/pdp/...}.page_config.components_map[N].component_data.shop_info
```
`shop_info` の主なキー：
`seller_id, shop_name, shop_logo{url_list}, creator_name, desc, sold_count, on_sell_product_count, review_count, followers_count, video_count, shop_rating, shop_link, region`

**発見の導線（robots クリーン・全自動・seed不要）**：
```
shop.tiktok.com/jp → /jp/c/{slug}/{id}（カテゴリ）→ /jp/pdp/{id}（商品）→ shop_info
```

**実データ検証（Perfect Diary Japan）**：seller_id=`7496204608949095270` / followers=**6,135** / sold=**21,246** / products=**86** / videos=**284** / rating=**4.6** / review=**1,502** を正確に抽出（保存HTMLでオフライン検証済み）。

### 4-3. store_url が 404 になる問題（対処済み）
- `shop_info.shop_link`（`shop.tiktok.com/jp/store/{slug}/{id}`）→ **404**
- `www.tiktok.com/shop/store/{slug}/{id}` → **`/404` へリダイレクト**（大手 Perfect Diary でも。スラッグは飾りで seller_id で特定されるが、結局どちらも開けない）
- **結論**：JPでは独立した店舗ページの公開GET-URLが存在しない（店舗はSPA/アプリ内でのみ開く）。
- **対処**：`store_url` には「確実に開ける」取得元の **PDP URL** を入れる（`parse_shop` で `source_url` を採用）。

### 4-4. 連絡先（電話・メール）
- **TikTok Shop のページは出品者の電話/メールを持っていない**（PDP実測で 電話/メール/特商法 は 0 件）。連絡は本来「アプリ内メッセージ」導線。
- → 連絡先は **TikTokの外**（店名→検索→自社サイトの特商法/会社概要）で取る＝`enrich.py`。

### 4-5. アプリの「このショップについて」（特商法）の所在
アプリでは店舗の「このショップについて」に **商号・電話番号・住所・代表者**（特定商取引法の表示）が出る（ユーザー提供スクショで確認：例 株式会社マクアケ / +810367582205 / 東京都目黒区… / 中山 亮太郎）。

ネットワーク傍受リコン（patchright + cookie）の結果：
| 調査 | 特商法データ |
|---|---|
| PDP 初期HTML / レンダリング後DOM | 無し |
| デスクトップweb | 「このショップについて」UI 自体が無い |
| モバイルweb 内部API `/api/shop/pdp_h5/page_data`（145KB）の `seller_info` | 店名・ロゴのみ（特商法無し） |

→ **特商法は「このショップについて」モーダルを開いた時だけ呼ばれる別の on-demand API**。ヘッドレス自動化ではそのモーダル到達＝APIの発火ができず未捕捉。加えて TikTok API は**署名トークン必須**のため直叩きも困難。

---

## 5. 各アプローチと結果まとめ

| アプローチ | 実装 | 速さ | コスト | 取れるもの / 歩留まり |
|---|---|---|---|---|
| **①店舗データ収集** | `shop_scraper.py` | 中 | 要リクエスト | 店名・指標（ほぼ確実）＝**主成果** |
| **②公開リンク整理** | `extract_links.py` | ◎一瞬 | 無料 | descにURLを貼る店のみ（今回サンプルは0/20＝desc がテンプレ文） |
| **③連絡先エンリッチ** | `enrich.py` | △遅い | 無料枠 | 会社名・メール・電話。自社サイトあり店のみ（例: Classical Elf ✅ / Kola Kola・Only Good ❌） |
| **④特商法API（アプリ相当）** | 未実装 | - | - | 商号・電話・住所・代表。**TikTok専業店も埋められる可能性**だが取得の壁が高い |

### エンリッチのライブ検証（③）
- **Classical Elf【公式】** → HIT：株式会社クラシカルエルフ / `elf@silk.ocn.ne.jp` / `classicalelf_official@classicalelf.jp`（特商法ページ `classicalelf.shop/pages/law`）
- **Kola Kola あったかROOM / Only Good Clothing** → MISS（独自サイト無し）
- 初期版は無関係な法律解説記事の電話を誤検出 → **店名照合ゲート**追加で解消

---

## 6. データモデル `TiktokShop`（`src/models.py`）

| フィールド | 由来 |
|---|---|
| `shop_id` | shop_info.seller_id（一意キー） |
| `store_slug` | shop_link 中のスラッグ |
| `store_url` | 確実に開ける取得元URL（＝PDP。独立店舗ページは公開GET不可） |
| `shop_name` | shop_info.shop_name |
| `follower_count` | shop_info.followers_count |
| `total_sold` | shop_info.sold_count |
| `product_count` | shop_info.on_sell_product_count |
| `video_count` | shop_info.video_count |
| `rating` / `rating_count` | shop_info.shop_rating / review_count |
| `avatar_url` | shop_info.shop_logo.url_list[0] |
| `region` / `description` | shop_info.region / desc |
| `source_type` / `source_value` | 発見種別 / 取得元URL |

---

## 7. 出力ファイル（`output/`、gitignore対象）

| ファイル | 内容 |
|---|---|
| `shops.jsonl` / `result_shop.{json,csv}` | 店舗データ（①） |
| `shop_links.{csv,jsonl}` | セラー公開リンク（②） |
| `leads.{csv,jsonl}` | 連絡先付きリード（③） |
| `store_page.{html,json}` | ダンプ（診断） |
| `diag_*.html` / `netcap*/` | リコンの生データ |

---

## 8. 制約・リスク・注意

- **residential proxy or 自宅回線**で。データセンターIPは弾かれやすい。
- リクエスト間隔 **10〜30秒**、1日は控えめ（既存方針で 100〜300件/日 が安全圏）。cookie は捨てアカ。
- 発見系（カテゴリ巡回・検索エンリッチ）は特にレート/BANリスク。件数・頻度を絞る。
- エンリッチの検索スクレイピング（DuckDuckGo）は不安定。本番は検索API（Brave / Google CSE 等）に置換推奨。
- 取得連絡先での営業は 特定電子メール法 等の順守前提。公開の特商法情報の範囲で B2B 目的に限定。

---

## 9. 未解決 / 次の一手

1. **特商法API（このショップについて）の取得可否**（最有力の残課題）
   - 案A：**ガイド付きキャプチャ**＝非ヘッドレスで開き、人が「このショップについて」を1回タップ→専用APIのエンドポイント/レスポンスを捕捉→そこから実装可否判断。
   - 案B：webのJSバンドルからエンドポイント文字列を探索（署名の壁は残る）。
   - 案C：モバイルアプリのAPIを実機傍受（最重・BANリスク高、PoC非推奨）。
   - 価値：**エンリッチで取れないTikTok専業店の連絡先を埋められる**唯一の源。
2. **エンリッチの高速化**：検索API化＋素HTTP取得＋並列で 10〜100倍（現状は browser+直列で遅い）。
3. **公開リンク抽出の対象拡大**：desc だけでなく、店舗→クリエイター垢(@)紐付けが取れれば既存 profile parser の bioLink 抽出を流用可能。

---

## 10. パイプライン全体像

```
① shop-run   TikTok Shop 収集   → 店名・フォロワー・販売数・評価（有望店の抽出/優先度付け）
② shop-links 公開リンク整理      → 自社サイト/SNS（本人公開分のみ・無料）
③ shop-enrich 連絡先エンリッチ   → 会社名・メール・電話（自社サイトあり店）
（未）④ 特商法API                → 商号・電話・住所・代表（TikTok専業店も。要リバースエンジニアリング）
        ↓
   output/result_shop.csv + shop_links.csv + leads.csv = 営業リスト
```

**運用の現実解**：`shop-run` で母集団 → `shop-links`（無料）で取れる分回収 → 有望店だけ `shop-enrich` or 人手で連絡先確認 → 最後は人が窓口を確認して営業。
