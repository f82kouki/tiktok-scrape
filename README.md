# TikTok Scraper (PoC)

TikTok を対象にした2つの練習用スクレイパー：

1. **🛒 TikTok Shop 店舗抽出** — `shop.tiktok.com` の店舗（seller）情報（店名・フォロワー・販売数・評価等）を横断収集。**本ドキュメントの主対象**。
2. **👤 TikTok インフルエンサー抽出** — ハッシュタグから投稿者を発見し、各プロフィールのフォロワー数・bio・SNS リンクを取得（最初に作った機能）。

> **Status**: PoC. 学習目的・少量・低頻度の取得用。
> Shop の詳細は [TIKTOK_SHOP_POC.md](TIKTOK_SHOP_POC.md)（作業ログ）/ [TIKTOK_SHOP_POC_RESULTS.md](TIKTOK_SHOP_POC_RESULTS.md)（できた/できなかった）、インフルエンサーの本番化は [PRODUCTION_HANDOFF.md](PRODUCTION_HANDOFF.md) を参照。

### クイックナビ
| やりたいこと | コマンド |
|---|---|
| 店舗を集める（本命） | `make shop-run SHOP_MAX=20` |
| 店舗発見の疎通確認 | `make shop-discover` |
| 1店舗の構造ダンプ | `make shop-dump SHOP_URL="https://shop.tiktok.com/jp/pdp/<id>"` |
| インフルエンサーを集める | `make step2 HASHTAG=コスメ` |

---

# 🛒 TikTok Shop 店舗抽出

## 何ができるか

- `shop.tiktok.com/jp`（日本マーケット入口）→ カテゴリ `/jp/c/...` → 商品 `/jp/pdp/...` と辿り、各店舗の情報を取得
- **店名・フォロワー数・総販売数・商品数・動画数・評価・レビュー数・seller_id・地域・ロゴ・説明**を抽出
- `seller_id` で重複排除、JSON / CSV / JSONL に逐次保存（途中 Ctrl+C しても安全）
- **seed 不要・全自動**（入口からカテゴリを自動発見）
- （補助機能）説明文の公開URL抽出 / 店名→Web検索による連絡先エンリッチ

### 取得できる項目（[`TiktokShop`](src/models.py)）

```json
{
  "shop_id": "7494382431354651702",
  "store_slug": "everyday-muse",
  "store_url": "https://shop.tiktok.com/jp/pdp/....../1734949803800822838",
  "shop_name": "Everyday Muse",
  "follower_count": 458,
  "total_sold": 7254,
  "product_count": 395,
  "video_count": 449,
  "rating": null,
  "rating_count": 283,
  "avatar_url": "https://p16-oec-sg.ibyteimg.com/...",
  "region": "JP",
  "description": "Shop Everyday Muse on TikTok Shop! 7.2K+ sold, 400+ followers.  Join the trend!",
  "is_official": false,
  "source_type": "pdp",
  "source_value": "https://shop.tiktok.com/jp/pdp/...",
  "scraped_at": "2026-07-02T08:10:41.793566+00:00"
}
```
> `rating` は店舗によって `shop_rating` が無く `null` になる（新規/レビュー少）。`store_url` は独立店舗ページが公開GETで開けないため、**確実に開ける取得元PDP URL**を入れている。

## クイックスタート

```bash
make install                 # 依存と patchright/Chromium（初回のみ）
make login                   # cookie を ./.tiktok_profile に保存（下記「ログイン要否」参照）
make shop-run SHOP_MAX=3     # まず小さく：3店舗を取得して動作確認
make shop-run SHOP_MAX=20    # 問題なければ本番相当
```
結果は `output/result_shop.json` / `result_shop.csv` / `shops.jsonl` に出力。

## コマンド一覧（Shop）

| コマンド | 用途 | ネット |
|---|---|---|
| `make shop-run SHOP_MAX=20` | 発見→取得→保存（**本命**） | 要 |
| `make shop-discover` | 入口→カテゴリ→PDP の発見テスト | 要 |
| `make shop-dump SHOP_URL="..."` | 1商品/店舗ページの構造ダンプ＆パース確認 | 要 |
| `make shop-recon` | `shop.tiktok.com/jp` の手動リコン（ブラウザ表示） | 要 |
| `make shop-links [TEXT="..."]` | 説明文からセラー公開URL/SNSを抽出 | 不要（オフライン） |
| `make shop-enrich [NAME="店名"]` | 店名→Web検索→特商法/会社概要から連絡先 | 要 |

### 上書き可能な変数 / `.env`

```bash
make shop-run SHOP_MAX=30
make shop-dump SHOP_URL="https://shop.tiktok.com/jp/pdp/1734949803800822838"
```
| 変数（.env） | 意味 |
|---|---|
| `TIKTOK_SHOP_ENTRY_URL` | 発見の入口（既定 `https://shop.tiktok.com/jp`） |
| `TIKTOK_SHOP_CATEGORY_URLS` | 巡回カテゴリを明示指定（カンマ区切り。指定すると入口発見をスキップ） |
| `TIKTOK_SHOP_SEED_URLS` | 直接投入する PDP / 店舗URL（カンマ区切り） |
| `TIKTOK_SHOP_MAX` | 取得上限 |

> 特定ジャンルを狙うなら `TIKTOK_SHOP_CATEGORY_URLS` にカテゴリURLを指定（例：コスメ `https://shop.tiktok.com/jp/c/beauty-personal-care/601450`）。無指定だと入口の先頭カテゴリ（アパレル寄り）から発見する。

## 仕組み・判明した重要事実

- **`shop.tiktok.com` は本体 `www.tiktok.com` とは別アプリ**。埋め込みJSONは `__UNIVERSAL_DATA_FOR_REHYDRATION__` ではなく **`__MODERN_ROUTER_DATA__`**。店舗情報はその `...components_map[N].component_data.shop_info` に入る。
- **商品(PDP)1枚に店舗情報が全部入っている**ので、店舗ページを別途開く必要なし。
- **独立した店舗ページURLは公開GETで開けない**（`shop.tiktok.com/jp/store/...`＝404、`www.tiktok.com/shop/store/...`＝`/404`へ遷移）。→ `store_url` はPDPを採用。
- **連絡先（電話/メール）はTikTokに無い**。アプリの「このショップについて」（特商法：商号/電話/住所/代表）は**ネイティブアプリ専用**でweb取得不可。連絡先が要る場合は `shop-enrich`（外部サイトから）で部分的に補完。
- **login-wall ではないが、cookie 必須級**：cookie無しゲストだと数リクエストで Security Check が発動し取りこぼす（実測 **ゲスト 1/5 vs cookie有り 5/5**）。`make login` の信頼プロファイルを使うこと。
- **robots**：`shop.tiktok.com` の `/jp/c/`・`/jp/pdp/` は Disallow なし。`www` 側の `/search*`・`/shop/view/product/` は Disallow のため使わない。

## 出力ファイル / 実装

```
output/
├── result_shop.json / result_shop.csv / shops.jsonl   # 店舗データ（shop-run）
├── shop_links.csv / shop_links.jsonl                  # 公開リンク（shop-links）
├── leads.csv / leads.jsonl                            # 連絡先付きリード（shop-enrich）
└── store_page.html / store_page.json                  # ダンプ（shop-dump）
```
| ファイル | 役割 |
|---|---|
| [src/shop_scraper.py](src/shop_scraper.py) | `TikTokShopScraper`（発見→取得→重複排除） |
| [src/shop_parser.py](src/shop_parser.py) | `__MODERN_ROUTER_DATA__` → `shop_info` → `TiktokShop` |
| [src/shop_main.py](src/shop_main.py) | `make shop-run` の CLI・逐次保存 |
| [src/enrich.py](src/enrich.py) | 連絡先エンリッチ（検索→抽出＋店名照合） |
| `scripts/{dump_store_page,diagnose_shop,check_shop_discovery,enrich_shops,extract_links}.py` | 各診断/補助 |

> **本番統合（Vimmy Tools）**の作戦書：`vimmy-tools/docs/tiktok-shop-scraper-integration-plan.md`（確定コード・fixture・受け入れ基準を同梱）。

---

# 👤 TikTok インフルエンサー抽出

> 以下は最初に作った、ハッシュタグ→プロフィール抽出の機能。

## 何ができるか

- ハッシュタグ (例: `#コスメ`) から動画投稿者を発見し、各プロフィールを訪問
- フォロワー数・動画数・いいね数・bio・Instagram/YouTube/X リンクを抽出
- フォロワー数で絞り込み (例: 1万人以上だけ)
- JSON / CSV に逐次保存（途中 Ctrl+C しても安全）

### 取得できる項目（[`TiktokUser`](src/models.py)）

```json
{
  "tiktok_user_id": "MS4wLjABAAAA...",
  "unique_id": "xxxxxxxxxxxx",
  "nickname": "（表示名）",
  "signature": "（bioテキスト）",
  "avatar_url": "https://...",
  "follower_count": 146900,
  "following_count": 312,
  "video_count": 184,
  "total_likes": 1240000,
  "is_verified": false,
  "instagram_username": "xxxxxxxxxxxx",
  "youtube_url": null,
  "twitter_username": null,
  "source_hashtag": "コスメ",
  "source_keyword": null,
  "scraped_at": "2026-05-12T..."
}
```

---

## クイックスタート

### 1. セットアップ（初回のみ）

```bash
make install     # 依存と patchright/Chromium をインストール
```

### 2. TikTok に手動ログイン（**捨てアカウントを使うこと**）

```bash
make login       # Chromium ウィンドウが開く → 手動ログイン → Enter
```

cookie が `./.tiktok_profile/` に永続化される。以降のリクエストは自動でこの cookie を再利用。

> ⚠️ **本アカウントは絶対に使わない**。bot 検出で警告/ban のリスクがあるため、捨てアカウントで運用する。

### 3. 動作確認（順に通す）

```bash
make step0       # ブラウザ起動の疎通確認 (5秒)
make step1       # @tiktok のプロフィール取得 (30秒〜1分)
make step2       # ハッシュタグ「コスメ」から 20 件取得 (3〜8分)
```

すべて通れば、`output/result.json` と `output/result.csv` に結果が出ます。

---

## 実行例

`make step2` (ハッシュタグ「コスメ」、最大 20 件取得) のターミナル出力例:

```
$ make step2
uv run python -m src.main --hashtag "コスメ" --min-followers 100 --max-users-per-query 30 --max 20 --debug
2026-05-12 16:07:21,712 [INFO] src.scraper: using persistent profile: ./.tiktok_profile
[2026-05-12 16:07:32] INFO: Fetched (200) <GET https://www.tiktok.com/tag/%E3%82%B3%E3%82%B9%E3%83%A1>
2026-05-12 16:07:32,140 [DEBUG] src.scraper: fetched https://www.tiktok.com/tag/コスメ: status=200 body=730,776 chars
2026-05-12 16:07:32,151 [INFO] src.parser:   video-tile regex found 114 matches (タイル投稿者のみ、サイドバー除外)
2026-05-12 16:07:32,151 [INFO] src.scraper: hashtag=コスメ: discovered 30 usernames
[2026-05-12 16:07:54] INFO: Fetched (200) <GET https://www.tiktok.com/@xxxxxxxxxxxx>
  ✓ @xxxxxxxxxxxx (3,179 followers)  [1件目を保存]
[2026-05-12 16:08:07] INFO: Fetched (200) <GET https://www.tiktok.com/@yyyyyyyyyyyy>
  ✓ @yyyyyyyyyyyy (104,500 followers)  [2件目を保存]
[2026-05-12 16:08:28] INFO: Fetched (200) <GET https://www.tiktok.com/@zzzzzzzzzzzz>
  ✓ @zzzzzzzzzzzz (1,103 followers)  [3件目を保存]
[2026-05-12 16:08:48] INFO: Fetched (200) <GET https://www.tiktok.com/@aaaaaaaaaaaa>
  ✓ @aaaaaaaaaaaa (132,500 followers)  [4件目を保存]
... (省略) ...
  ✓ @bbbbbbbbbbbb (532,300 followers)  [19件目を保存]
  ✓ @cccccccccccc (21,800 followers)  [20件目を保存]

取得完了: 20 件
  JSON: output/result.json
  CSV : output/result.csv
```

### ログの読み方

| ログ行 | 意味 |
|---|---|
| `using persistent profile: ./.tiktok_profile` | `make login` で保存した cookie を読み込み |
| `Fetched (200) <GET .../tag/...>` | ハッシュタグページの取得成功 |
| `body=730,776 chars` | 受け取った HTML サイズ（login-wall 時は ~400KB に縮む） |
| `video-tile regex found 114 matches` | 動画タイルから投稿者リンクを抽出（サイドバーのおすすめは除外） |
| `discovered 30 usernames` | ユニーク化 + max-users-per-query で打ち切り |
| `✓ @xxx (NNN followers) [N件目を保存]` | 取得成功 → result.json に逐次保存 |
| `skip @xxx: followers N < 100` | min_followers でフィルタ除外（debug ログ） |

### 取得結果ファイル

```
output/
├── result.json          # JSON 形式（全 20 件）
├── result.csv           # CSV 形式（Excel/Numbers で開ける）
└── hashtag_コスメ_*.html # SAVE_HASHTAG_HTML=true のとき、取得元 HTML を保存
```

#### `output/result.json` のサンプル (1 件分)

```json
[
  {
    "tiktok_user_id": "MS4wLjABAAAA...",
    "unique_id": "xxxxxxxxxxxx",
    "nickname": "（表示名）",
    "signature": "（bioテキスト）",
    "avatar_url": "https://p16-common-sign.tiktokcdn.com/...",
    "follower_count": 146900,
    "following_count": 312,
    "video_count": 184,
    "total_likes": 2400000,
    "is_verified": false,
    "instagram_username": "xxxxxxxxxxxx_ig",
    "youtube_url": null,
    "twitter_username": null,
    "source_hashtag": "コスメ",
    "source_keyword": null,
    "scraped_at": "2026-05-12T07:09:55.246123+00:00"
  },
  ...
]
```

#### `output/result.csv` のサンプル

```csv
tiktok_user_id,unique_id,nickname,signature,avatar_url,follower_count,following_count,video_count,total_likes,is_verified,instagram_username,youtube_url,twitter_username,source_hashtag,source_keyword,scraped_at
MS4wLjABAAAA...,xxxxxxxxxxxx,（表示名）,（bio）,https://...,146900,312,184,2400000,False,xxxxxxxxxxxx_ig,,,コスメ,,2026-05-12T07:09:55+00:00
MS4wLjABAAAA...,yyyyyyyyyyyy,（表示名）,（bio）,https://...,3179,180,42,124000,False,,,,,コスメ,,2026-05-12T07:07:54+00:00
...
```

### 実行時間の目安

| コマンド | 件数 | 所要時間 |
|---|---|---|
| `make step1` | 1 件 (@tiktok) | 30 秒〜1 分 |
| `make step2` (デフォルト) | 20 件 | 3〜8 分 |
| `make step2 MAX=50 MAX_USERS_PER_QUERY=50` | 50 件 | 10〜20 分 |
| `make scale` (5 タグ × 50 件) | 最大 50 件 | 30 分〜1 時間 |

> 1 件あたり「ジッタースリープ 4〜8 秒 + プロフィールロード 5〜15 秒」≒ 10〜25 秒。bot 検出回避のため意図的にゆっくり。
> 途中で `Ctrl+C` しても、それまで取得した分は `output/result.json` に逐次保存されているので失われません。

---

## コマンド一覧

```bash
make help
```

| コマンド | 用途 |
|---|---|
| `make install` | 依存・Chromium のインストール |
| `make login` | TikTok に手動ログイン (cookie 保存) |
| `make step0` | ブラウザ疎通テスト (example.com) |
| `make step1` | プロフィール疎通テスト (@tiktok) |
| `make step2` | ハッシュタグ経由で取得 |
| `make scale` | 5 ハッシュタグ × 50 件で本番近い規模ラン |
| `make diag` | ハッシュタグページの診断 (HTML/PNG 保存) |
| `make test` | parser のユニットテスト |
| `make clean` | `output/` の result ファイル削除 |
| `make step3` | ⛔ 無効化済 (TikTok robots.txt が `/search/user?q=` を Disallow) |

### 上書き可能な変数

```bash
make step2 HASHTAG=メイク MAX=50 MIN_FOLLOWERS=1000

# Scale ラン
make scale SCALE_HASHTAGS="コスメ メイク スキンケア" SCALE_MAX=100
```

| 変数 | 既定値 | 意味 |
|---|---|---|
| `HASHTAG` | `コスメ` | step2 で使うハッシュタグ |
| `MIN_FOLLOWERS` | `100` | フォロワー数の最低ライン |
| `MAX` | `20` | 最終取得件数の上限 |
| `MAX_USERS_PER_QUERY` | `30` | 1 タグから発見する username 上限 |
| `SCALE_HASHTAGS` | `コスメ メイク スキンケア アイメイク リップ` | scale で使うタグ |
| `SCALE_MAX` | `50` | scale の合計取得上限 |

---

## ディレクトリ構成

```
tiktok-scraping/
├── src/
│   ├── main.py         # 【インフルエンサー】CLI エントリーポイント
│   ├── scraper.py      # TikTokScraper (ブラウザ起動、取得、リトライ)
│   ├── parser.py       # HTML/JSON → TiktokUser の変換 (pure function)
│   ├── shop_main.py    # 【Shop】CLI エントリーポイント（make shop-run）
│   ├── shop_scraper.py # 【Shop】TikTokShopScraper（発見→取得→重複排除）
│   ├── shop_parser.py  # 【Shop】__MODERN_ROUTER_DATA__ → shop_info → TiktokShop
│   ├── enrich.py       # 【Shop】連絡先エンリッチ（検索→抽出＋店名照合）
│   ├── models.py       # TiktokUser / TiktokShop dataclass
│   └── utils.py        # logging, sleep, env
├── scripts/
│   ├── login.py                # 手動ログイン用 (patchright 直接利用)
│   ├── diagnose_hashtag.py     # 【インフルエンサー】ハッシュタグ診断
│   ├── check_browser.py        # ブラウザ疎通テスト
│   ├── check_profile.py        # プロフィール疎通テスト
│   ├── dump_store_page.py      # 【Shop】PDP/店舗ページの構造ダンプ
│   ├── diagnose_shop.py        # 【Shop】入口の手動リコン
│   ├── check_shop_discovery.py # 【Shop】発見テスト
│   ├── enrich_shops.py         # 【Shop】連絡先エンリッチ実行
│   └── extract_links.py        # 【Shop】説明文の公開リンク抽出
├── tests/
│   ├── fixtures/           # サンプル HTML を置く場所
│   ├── test_parser.py      # 【インフルエンサー】parser の単体テスト
│   ├── test_shop_parser.py # 【Shop】parse_shop / URL抽出 の単体テスト
│   └── test_enrich.py      # 【Shop】連絡先抽出・照合ゲートの単体テスト
├── output/            # 結果出力 (gitignore)
├── .tiktok_profile/   # cookie 永続化先 (gitignore)
├── .env               # 設定 (gitignore)
├── .env.example       # 設定テンプレ
├── pyproject.toml
├── Makefile
├── README.md                        # このファイル
├── TIKTOK_SHOP_POC.md               # 【Shop】作業ログ（詳細）
├── TIKTOK_SHOP_POC_RESULTS.md       # 【Shop】できたこと/できなかったこと
└── PRODUCTION_HANDOFF.md            # 【インフルエンサー】本番統合用の詳細作戦書
```

---

## アーキテクチャ概要

```
make step2
   ↓
src/main.py (CLI)
   ↓
src/scraper.py (TikTokScraper)
   ↓
scrapling.AsyncStealthySession  ← 薄いラッパー
   ↓
patchright (playwright のステルス改造版)
   ↓
Chromium (~/Library/Caches/ms-playwright/)
   ↓
TikTok Web (https://www.tiktok.com)
```

### 2 種類の抽出パターン

| ページ | データ取得方法 |
|---|---|
| プロフィール `/@user` | `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` の中の JSON を regex 切り出し → `json.loads` |
| ハッシュタグ `/tag/コスメ` | 動画タイル `[data-e2e="challenge-item"]` が DOM に出現するまで待機 → レンダリング後の `<a href>` を regex で抽出 |

詳細: [PRODUCTION_HANDOFF.md §3](PRODUCTION_HANDOFF.md)

---

## 設定 (.env)

`.env.example` をコピーして使う:

```bash
cp .env.example .env
```

| 変数 | 既定値 | 意味 |
|---|---|---|
| `HTTP_PROXY` | (空) | プロキシ。本番は residential proxy 推奨 |
| `REQUEST_INTERVAL_MIN` | `4.0` | リクエスト間隔の最小秒数 |
| `REQUEST_INTERVAL_MAX` | `8.0` | リクエスト間隔の最大秒数 |
| `HEADLESS` | `true` | ブラウザを headless で起動 (false で画面表示) |
| `TIKTOK_USER_DATA_DIR` | `./.tiktok_profile` | cookie 永続化先 |
| `DEBUG` | `true` | DEBUG ログを出す |
| `SAVE_HASHTAG_HTML` | (false) | step2 で取得した HTML を `output/hashtag_*.html` に保存 |

---

## トラブルシューティング

### `make step1` で `None` が返る

cookie が無効か、TikTok が login-wall を返している:

```bash
# .env で HEADLESS=false にして実機の挙動を見る
make login          # 再ログイン
make step1
```

### `make step2` で「discovered 0 usernames」

cookie 期限切れの可能性:

```bash
make diag           # ハッシュタグページを目視確認 (Chromium 開く)
make login          # cookie 再生成
make step2
```

### scrapling のエンジンエラー (TypeError)

scrapling v0.3.13 で API 破壊的変更あり。`pyproject.toml` で `scrapling[fetchers]>=0.3.13` を確認:

```bash
uv sync
uv run scrapling install
```

### TikTok にアカウント警告メールが来た

すぐに停止し 24 時間以上空ける。`.env` でジッターを長めに:

```bash
REQUEST_INTERVAL_MIN=10.0
REQUEST_INTERVAL_MAX=30.0
```

詳細: [PRODUCTION_HANDOFF.md §9 運用上の注意](PRODUCTION_HANDOFF.md)

---

## 注意事項

### 法的・規約的

- TikTok の利用規約はスクレイピング全般を禁止する条項を含む
- 本プロジェクトは **学習目的・少量・低頻度の PoC** として実装
- 商用化・大量取得・データ配布の前に**必ず法務確認**
- robots.txt の Disallow パス (`/search/user?q=` 等) は使わない (`make step3` は無効化済)
- 詳細: [PRODUCTION_HANDOFF.md §9.5 ToS 準拠](PRODUCTION_HANDOFF.md)

### 運用上

- **本番アカウントを絶対使わない** (捨てアカウント運用)
- 1 日 100〜300 件以内が安全圏 (それ以上はレート制限・CAPTCHA リスク高)
- `Empty body` / `Timeout` 連発したら即停止 → 24時間以上空ける
- `make scale` 実行中は `caffeinate -di make scale` でスリープ抑止推奨

---

## 本番統合

このプロジェクトは Vimmy Tools 等への移植を前提とした PoC です。本番統合する際の詳細手順・ハマりポイント・移植マッピングは:

➡ **[PRODUCTION_HANDOFF.md](PRODUCTION_HANDOFF.md)** を参照

主な内容:
- §3 抽出パターン (プロフィール SSR / ハッシュタグ遅延ロード)
- §7 Vimmy Tools 移植プラン (ファイル配置、Dockerfile、Cloud Run 設定)
- §8 ハマりポイント 8 個 (PoC で踏んだ地雷集)
- §11 移植時のチェックリスト

**Shop 店舗抽出の本番統合**は、Vimmy Tools リポジトリ内の作戦書
`vimmy-tools/docs/tiktok-shop-scraper-integration-plan.md`（確定コード・テスト用fixture・各Phaseの受け入れ基準を同梱）を参照。

---

## 開発

### 依存

- Python 3.11+
- uv
- macOS / Linux (Windows は WSL 推奨)
- 数 GB のディスク空き (Chromium ~500MB)

### テスト

```bash
make test    # parser のユニットテスト (fixture 必要)
```

`tests/fixtures/profile_sample.html` にプロフィールページの HTML を保存しておくと、parser のリグレッションが検出できる。

### Lint

```bash
uv run ruff check src/ scripts/ tests/
```

---

## License

PoC のため未定。本番統合時に整理する。
