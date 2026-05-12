# TikTok Scraper (PoC)

TikTok のハッシュタグから投稿者を発見し、各プロフィールのフォロワー数・bio・SNS リンク等を取得する練習用スクレイパー。

> **Status**: PoC. 学習目的・少量・低頻度の取得用。本番化前に [PRODUCTION_HANDOFF.md](PRODUCTION_HANDOFF.md) を参照。

---

## 何ができるか

- ハッシュタグ (例: `#コスメ`) から動画投稿者を発見し、各プロフィールを訪問
- フォロワー数・動画数・いいね数・bio・Instagram/YouTube/X リンクを抽出
- フォロワー数で絞り込み (例: 1万人以上だけ)
- JSON / CSV に逐次保存（途中 Ctrl+C しても安全）

### 取得できる項目（[`TiktokUser`](src/models.py)）

```json
{
  "tiktok_user_id": "MS4wLjABAAAA...",
  "unique_id": "tantei_cosme",
  "nickname": "コスメ探偵",
  "signature": "bioテキスト ...",
  "avatar_url": "https://...",
  "follower_count": 146900,
  "following_count": 312,
  "video_count": 184,
  "total_likes": 1240000,
  "is_verified": false,
  "instagram_username": "ig_handle",
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
│   ├── main.py        # CLI エントリーポイント
│   ├── scraper.py     # TikTokScraper (ブラウザ起動、取得、リトライ)
│   ├── parser.py      # HTML/JSON → TiktokUser の変換 (pure function)
│   ├── models.py      # TiktokUser dataclass
│   └── utils.py       # logging, sleep, env
├── scripts/
│   ├── login.py            # 手動ログイン用 (patchright 直接利用)
│   ├── diagnose_hashtag.py # ハッシュタグページの診断
│   ├── check_browser.py    # ブラウザ疎通テスト
│   └── check_profile.py    # プロフィール疎通テスト
├── tests/
│   ├── fixtures/      # サンプル HTML を置く場所
│   └── test_parser.py # parser の単体テスト
├── output/            # 結果出力 (gitignore)
├── .tiktok_profile/   # cookie 永続化先 (gitignore)
├── .env               # 設定 (gitignore)
├── .env.example       # 設定テンプレ
├── pyproject.toml
├── Makefile
├── README.md          # このファイル
└── PRODUCTION_HANDOFF.md  # 本番統合用の詳細作戦書
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
