# TikTok スクレイパー 本番統合作戦書（PoC からの引き継ぎ）

> **読者**: 本番プロジェクト（Vimmy Tools 等）に組み込む実装担当者・AI エージェント
> **書き手**: PoC を実装し動作確認まで完了した AI エージェント
> **対象 PoC**: `/Users/yazawakoki/practice/tiktok-scrape/tiktok-scraping/`
> **作成日**: 2026-05-12
> **検証済み**: ハッシュタグ「コスメ」から 5 件のフォロワー 8 万〜200 万のインフルエンサーを取得成功

---

## 0. このドキュメントの目的

PoC で「動くこと」を確認した TikTok スクレイパーを、本番プロジェクトに移植する際に、
**PoC で得た知見・ハマりポイント・現在動いている技術選択をすべて引き継ぐ**ためのドキュメント。

PoC のコードを丸ごと移植するのではなく、
- なぜそうなっているか（Why）
- 何が壊れやすいか（Brittleness）
- どこが本番で書き換え対象か（Migration target）

を明記する。これを読めば、本番側の AI/実装者は **PoC が辿った試行錯誤を追体験せず、結論だけを使って実装を進められる**。

---

## 1. PoC の達成事項（事実関係）

### 動作した範囲

| 機能 | 状態 | 備考 |
|---|---|---|
| patchright/Chromium 起動 | ✅ | `~/Library/Caches/ms-playwright/chromium-1217/` |
| プロフィール取得 (@tiktok 等) | ✅ | フォロワー、動画数、いいね、bio、SNS リンク全部取れる |
| ハッシュタグ経由ユーザー発見 | ✅ | ログイン必須。cookie 永続化で抜けた |
| 出力 (JSON / CSV、逐次保存) | ✅ | `output/result.{json,csv}` |
| 重複排除 | ✅ (ラン内のみ) | secUid ベース。**1 回の `scrape()` 呼び出し内で dedup**。ラン間 dedup は未実装（result.json は毎回上書き）。本番 (Firestore) 側で secUid を doc ID にして dedup する想定 |
| フォロワー数フィルタ | ✅ | `--min-followers` 引数 |

### 動作しなかった / 試していない範囲

| 機能 | 状態 | 理由 |
|---|---|---|
| 未ログインでのハッシュタグ取得 | ❌ | TikTok が login-wall を返す（PoC で確認済） |
| **キーワード検索 (`/search/user?q=`)** | **❌ 永久封印** | **PoC で実機検証 → 機能せず + robots.txt Disallow → `make step3` 無効化済（§8.8 参照）** |
| 大規模ラン（5タグ × 50件 = 250件） | ❓ | コードは準備済 (`make scale`)、ユーザー側でまだ未実行 |
| Cloud Run 上での動作 | ❓ | 未検証。本ドキュメントで手順だけ提示 |

### 検証済みの定量データ

- HTML サイズ: プロフィール ~600KB、ハッシュタグ ~700-870KB（ログイン後）
- 1ユーザー取得時間: 約 5〜15秒（ページレンダリング込み）
- ジッタースリープ: 4〜8秒推奨だが scale ラン用に 10〜30秒に拡大済
- 取れたサンプル: 5 件（フォロワー数 8 万〜200 万のコスメ系投稿者。username は伏せる）

---

## 2. アーキテクチャ全体像

```
┌──────────────────────────────────────────────────────────────┐
│ Python 業務ロジック (src/main.py, src/scraper.py)            │
│   - フィルタ (min_followers, dedup)                          │
│   - 逐次保存 (1件ごとに result.json 上書き)                  │
│   - async generator でストリーミング yield                   │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ scrapling (薄いラッパー、AsyncStealthySession のみ使用)      │
│   - bot 検出対策のデフォルト束を 1 行で適用                  │
│   - patchright/playwright の定型コードを吸収                 │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ patchright (playwright のステルス改造フォーク)               │
│   - navigator.webdriver 偽装                                 │
│   - WebGL/canvas/permissions API 偽装                        │
│   - scripts/login.py / diagnose_hashtag.py から直接利用      │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Chromium (~/Library/Caches/ms-playwright/chromium-1217/)     │
│   - patchright が落としてきた専用 Chromium                   │
│   - ユーザーの Google Chrome とは完全に別物                  │
│   - persistent context: ./.tiktok_profile/                   │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
                   TikTok Web (https://www.tiktok.com)
```

**重要**: 本プロジェクトは「ブラウザ自動化方式」であり、TikTok の内部 API を直接叩いていない。
理由は §10 「将来の選択肢」参照。

---

## 3. 2 種類の抽出パターン（最重要）

TikTok のページは 2 種類のレンダリング方式が混在しており、それぞれ別の取り方をしている。
**本番移植時はこの違いを必ず保持すること**。

### パターン A: プロフィールページ → SSR 埋め込み JSON

URL: `https://www.tiktok.com/@{username}`

**特徴**: サーバーサイドで JSON が HTML に埋め込まれた状態で返ってくる（SSR）。
ブラウザの JS 実行を待つ必要があるが、データは初期 HTML に既にある。

**HTML 内の場所**:
```html
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
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
</script>
```

**取り方**: [src/parser.py:48-94](src/parser.py#L48) `parse_user_from_universal()` を参照。
1. 正規表現で `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` の中身を切り出す
2. `json.loads()`
3. `data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]` を辿る
4. `TiktokUser` dataclass にマッピング

**待機セレクタ**: `script#__UNIVERSAL_DATA_FOR_REHYDRATION__`

**フォールバック**: 旧形式 `SIGI_STATE` も [src/parser.py:97-131](src/parser.py#L97) で実装済（現状未使用）。

### パターン B: ハッシュタグページ → 遅延ロード後の DOM スクレイピング

URL: `https://www.tiktok.com/tag/{hashtag}`

**特徴**: 初期 HTML には骨組みだけ。動画リストは JS が後から XHR で取りに行って差し込む。
**`__UNIVERSAL_DATA_FOR_REHYDRATION__` には `webapp.challenge-detail` キーが存在しない**。
（PoC 序盤に「JSON 取れない」と詰まった原因）

**HTML 内の動画タイル形式**（XHR 完了後）:
```html
<div data-e2e="challenge-item" ...>
  <a href="https://www.tiktok.com/@xxxxxxxxxxxx/video/7630045352166477064">
    ...
  </a>
</div>
```

**取り方**: [src/parser.py:138-202](src/parser.py#L138) `extract_usernames_from_hashtag_html()` を参照。
1. `wait_selector='[data-e2e="challenge-item"]'` でタイルが描画されるのを待つ
2. レンダリング後の HTML 全体を取得
3. 正規表現で **`href="(https?://www.tiktok.com)?/@username/..."`** をすべて抽出
4. set で重複除去

**重要な regex**:
```python
re.findall(
    r'href="(?:https?://www\.tiktok\.com)?/@([A-Za-z0-9._]+)(?:/|")',
    html
)
```
**動画タイルは絶対 URL** (`https://www.tiktok.com/@user/video/...`) を使う。
**サイドバー/フッターは相対パス** (`/@user`)。両対応が必須。

**ノイズ**: 1 ページで 200+ の `/@xxx` リンクがマッチする。サイドバー「おすすめアカウント」、
フッター、コメント欄等の username も拾う。実害は少ないがフィルタを強化する余地あり。

### パターン A/B の使い分けまとめ

| ページ種別 | データ位置 | 待機セレクタ | パース方法 |
|---|---|---|---|
| プロフィール `/@user` | `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` 内 JSON | `script#__UNIVERSAL_DATA_FOR_REHYDRATION__` | regex で script 切り出し → `json.loads` → 辞書アクセス |
| ハッシュタグ `/tag/コスメ` | レンダリング後の DOM (`<a href>`) | `[data-e2e="challenge-item"]` | レンダリング後 HTML に regex で href 抽出 |

---

## 4. 認証 (Cookie 永続化)

### 必要性

TikTok のハッシュタグページ・キーワード検索ページは、**ログイン無しだと完全な login-wall** を返す。
具体的には `__DEFAULT_SCOPE__` に `webapp.app-context` `webapp.i18n-translation` 等の骨組みしか含まれず、
肝心の `webapp.challenge-detail` が無い。プロフィールページは（少なくとも 2026-05 時点で）ログイン無しでも取れる。

### 実装方式

**`scrapling.AsyncStealthySession` の `user_data_dir` 引数を使う**。
これは playwright の `launch_persistent_context(user_data_dir=...)` と同じで、
Chromium のユーザープロファイルディレクトリを永続化する。

```python
# src/scraper.py:43-47
session_kwargs = dict(
    headless=self.headless,
    network_idle=True,
    google_search=True,
    block_webrtc=True,
    hide_canvas=True,
    timeout=60000,
    proxy=self.proxy,
)
if self.user_data_dir:
    session_kwargs["user_data_dir"] = self.user_data_dir
```

`.env` で `TIKTOK_USER_DATA_DIR=./.tiktok_profile` を指定するとここが効く。

### 初回ログイン手順 (`scripts/login.py`)

scrapling の `AsyncStealthySession.fetch()` は **1 回 fetch するとページを閉じる**ため、
人間が手動でログイン操作する用途には使えない。なので **`scripts/login.py` は patchright を直接呼んでいる**:

```python
# scripts/login.py
async with async_playwright() as p:
    context = await p.chromium.launch_persistent_context(
        user_data_dir=profile_abs,
        headless=False,                  # 人間が見える必要がある
        viewport={"width": 1280, "height": 800},
        locale="ja-JP",
    )
    page = context.pages[0]
    await page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
    # asyncio loop を止めずに input を待つ
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "ログインしたら Enter > ")
    await context.close()
```

`context.close()` のタイミングで cookie が `user_data_dir` に永続化される。

### `.tiktok_profile/` の中身

Chromium のフルプロファイル。サイズは 50〜200MB 程度。重要なファイル:
- `Default/Cookies` (SQLite): TikTok のセッション cookie (`sessionid`, `tt_csrf_token`, `ms_token` 等)
- `Default/Local Storage/`: localStorage
- `Default/IndexedDB/`: TikTok の SPA が使う IndexedDB
- 他: キャッシュ、設定ファイル等

### Cookie の有効期限

実測してないが、TikTok 一般論として:
- `sessionid`: 数週間〜数ヶ月
- `ms_token`: 数日〜数週間（ログイン状態とは別に頻繁に更新される）

**期限切れの兆候**:
- step2 で再び `webapp.challenge-detail` が取れなくなる
- `'log in' / 'sign up'` キーワードが HTML に再出現
- 取得結果が 0 件になる

**対処**: `make login` を再実行 → 新しい `.tiktok_profile/` が上書きされる

---

## 5. ファイル別の役割と再利用可能性

| ファイル | 役割 | 本番移植時の扱い |
|---|---|---|
| [src/scraper.py](src/scraper.py) | ブラウザ起動、ページ取得、リトライ、ジッター、フィルタ、async generator | **そのまま移植可**。Vimmy Tools の services 配下に配置。`AsyncExitStack` パターンも維持 |
| [src/parser.py](src/parser.py) | HTML/JSON → TiktokUser 変換。**ネットワーク I/O 無しの pure function** | **そのまま移植可**。テスト容易性のため I/O を分離してある設計を維持 |
| [src/models.py](src/models.py) | `TiktokUser` dataclass | Firestore 直接保存なら不要。dict 変換用に残しても OK |
| [src/main.py](src/main.py) | CLI、引数解釈、逐次保存 | **本番では捨てる**。Cloud Run Job のエントリーポイントに置き換え |
| [src/utils.py](src/utils.py) | logging, sleep, env_bool | 流用可。本番のログフレームワークに合わせて差し替え |
| [scripts/login.py](scripts/login.py) | 手動ログイン → cookie 永続化 | **そのまま流用**。手元 Mac で月 1 程度実行する運用ツール |
| [scripts/diagnose_hashtag.py](scripts/diagnose_hashtag.py) | ハッシュタグページの診断（HTML/PNG 保存） | デバッグ専用。本番には不要、手元に残す |
| [scripts/check_browser.py](scripts/check_browser.py) | example.com 疎通確認 | 本番疎通テストに転用可 |
| [scripts/check_profile.py](scripts/check_profile.py) | @tiktok の取得テスト | 本番疎通テストに転用可 |
| [tests/test_parser.py](tests/test_parser.py) | parser のサンプル HTML テスト | **そのまま移植**。fixture も持っていく |
| [Makefile](Makefile) | step0/step1/step2/scale/login/diag コマンド (**step3 は無効化済**、§8.8 参照) | 本番では `gcloud` / `docker` コマンドに置き換え |

---

## 6. 環境設定 (.env)

```bash
# プロキシ（本番では residential proxy 必須級）
HTTP_PROXY=

# リクエスト間隔（推奨: 10〜30秒、軽め: 4〜8秒）
REQUEST_INTERVAL_MIN=10.0
REQUEST_INTERVAL_MAX=30.0

DEBUG=true

# 通常 true。make login 時のみ false
HEADLESS=true

# 永続プロファイル（cookie 保存先）
TIKTOK_USER_DATA_DIR=./.tiktok_profile
```

---

## 7. 本番移植プラン (Vimmy Tools 想定)

### 7.1 ファイル配置マッピング

| PoC | Vimmy Tools |
|---|---|
| `src/scraper.py` の `TikTokScraper` クラス | `backend/api/services/tiktok_scraping_service.py` (Lemon8 service パターン準拠) |
| `src/parser.py` の関数群 | 同 service の private helper として吸収 |
| `src/models.py` の `TiktokUser` | 不要（Firestore dict で直接保存）or `backend/api/models/` に配置 |
| `src/main.py` の CLI | `backend/api/jobs/tiktok_scraping_job.py` (Cloud Run Job entrypoint) |
| `scripts/login.py` | `tools/tiktok_login.py` (手元実行スクリプト) |
| 出力先 `output/` | Firestore `env/{env}/tiktok_influencers` collection |
| 依存定義 | `backend/pyproject.toml` に `scrapling[fetchers]>=0.3.13` 追記 |

### 7.2 依存関係の追加

`backend/pyproject.toml` に追加:
```toml
dependencies = [
    # 既存依存...
    "scrapling[fetchers]>=0.3.13",
]
```

`scrapling[fetchers]` extras で patchright + playwright 等の必要パッケージが全部入る。

### 7.3 Dockerfile 追記（Cloud Run 用）

```dockerfile
# patchright/Chromium に必要なシステムライブラリ
# 簡易版: `playwright install-deps chromium` でも良いが、明示の方が CI キャッシュ管理しやすい
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
    libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libxss1 \
    libpango-1.0-0 libcairo2 \
    libasound2 \
    fonts-liberation fonts-noto-color-emoji fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# patchright/Chromium と関連ファイル（ステルスドライバ）の取得
RUN uv run scrapling install
```

`fonts-noto-cjk` は日本語表示用。これがないと headless で取った一部 DOM テキストが □ 化する。
JSON パースには影響しないが、デバッグ時に視認性が落ちる。

### 7.4 Cookie 移植戦略（最重要）

**運用フロー**:

```
[手元 Mac、月1〜2回]
  1. make login → ./.tiktok_profile/ に最新 cookie 保存
  2. tar -czf tiktok_profile.tar.gz ./.tiktok_profile/
  3. gsutil cp tiktok_profile.tar.gz gs://{bucket}/secrets/tiktok/

[Cloud Run Job 起動時]
  1. gsutil cp gs://{bucket}/secrets/tiktok/tiktok_profile.tar.gz /tmp/
  2. tar -xzf /tmp/tiktok_profile.tar.gz -C /workspace/
  3. 環境変数 TIKTOK_USER_DATA_DIR=/workspace/.tiktok_profile を設定
  4. python -m backend.api.jobs.tiktok_scraping_job 実行
```

**Cloud Storage に置く理由**:
- Container Image に焼き込むと cookie 更新のたびに再ビルドが要る
- Secret Manager は値を 64KB 制限があり、`.tiktok_profile/` (50MB+) は入らない
- Cloud Storage の private bucket + Workload Identity でアクセス制御

**期限切れ検出**:
Cloud Run Job が 0 件で終了した時、Slack 通知 → 手元で `make login` 再実行が必要、というアラートを仕込む。
具体的には `tiktok_scraping_service` 内で「ハッシュタグから 0 件発見」が連続したら例外を投げ、
`backend/api/jobs/tiktok_scraping_job.py` でそれをキャッチして Slack 通知する。

### 7.5 Cloud Run Job 設定の最低ライン

| 項目 | 値 |
|---|---|
| メモリ | **2 GB 以上** (patchright/Chromium が ~500MB 使う + Python ランタイム) |
| CPU | 2 vCPU |
| タイムアウト | 30 分以上 (5タグ × 50件 で 4〜6 時間想定なら job を分割するか、3600秒上限を意識) |
| 同時実行 | 1 (同じ cookie で並列実行すると bot 検出されやすい) |
| Service Account | Cloud Storage 読み取り権限、Firestore 書き込み権限 |
| 環境変数 | `HTTP_PROXY` (residential proxy 必須), `TIKTOK_USER_DATA_DIR`, `REQUEST_INTERVAL_MIN/MAX` |

### 7.6 residential proxy について

**自宅・モバイル回線では動いた**が、**Cloud Run の GCP IP からはほぼ確実に弾かれる**。
TikTok は datacenter IP レンジを bot として扱う傾向が強い。本番ではほぼ必須。

候補サービス（参考）:
- Bright Data (旧 Luminati): 高品質、月 $500〜
- Oxylabs: 同上
- Smartproxy: 月 $50〜、品質はミドル
- Webshare: 月 $10〜、データセンター IP も混じる注意

`HTTP_PROXY=http://user:pass@residential.proxy.example.com:8080` の形式で .env / Cloud Run 環境変数に設定するだけで scrapling が反映する。

---

## 8. ハマりポイントと False Start（PoC で踏んだ地雷）

本番側で同じことをやり直さないため。

### 8.1 Scrapling v0.3.13 の API 破壊的変更

旧バージョン（〜v0.3.12）では `humanize`, `os_randomize`, `geoip`, `block_images`, `addons`, `disable_ads` 引数が
`StealthyFetcher` / `AsyncStealthySession` に存在した。**v0.3.13 で全部削除**され、
TypeError になる。エンジンが Camoufox(Firefox) → patchright(Chromium) に変更されたため。

**対処**: 本作戦書のコードは新 API（`hide_canvas`, `block_webrtc`, `network_idle`, `google_search` のみ使用）に
準拠済。本番でも同じ引数だけ使う。`pyproject.toml` で `scrapling[fetchers]>=0.3.13` と明示固定すること。

### 8.2 ハッシュタグページの SSR JSON が空（PoC 序盤の最大の地雷）

「プロフィールページと同じく `__UNIVERSAL_DATA_FOR_REHYDRATION__` から `webapp.challenge-detail` を取れる」
と最初は想定していたが、**ハッシュタグページの challenge-detail は SSR されない**。
JS が後から XHR で取りに行く構造になっている。

**症状**:
```
__DEFAULT_SCOPE__ keys (5): ['seo.abtest', 'webapp.a-b', 'webapp.app-context',
                              'webapp.biz-context', 'webapp.i18n-translation']
scope[webapp.challenge-detail] not present
discovered 0 usernames
```

**対処**: `wait_selector='[data-e2e="challenge-item"]'` で動画タイルが描画されるのを待ち、
レンダリング後の DOM に対して regex で href を拾う。これが [src/parser.py:178-184](src/parser.py#L178)。

### 8.3 動画タイルの href が絶対 URL

最初は `href="/@user"` の相対パスだけ regex で拾っていたが、動画タイルは
`href="https://www.tiktok.com/@user/video/123..."` の絶対 URL を使う。58 タイルあるのに 11 件しか拾えなかった。

**対処**: regex を両対応に。
```python
r'href="(?:https?://www\.tiktok\.com)?/@([A-Za-z0-9._]+)(?:/|")'
```

### 8.4 `AsyncStealthySession.fetch()` は人間操作に向かない

login.py の最初の実装では scrapling の `AsyncStealthySession` で TikTok ログインページを
開いて `input()` で待たせようとした → **fetch() がページを閉じてしまうのでウィンドウが一瞬で消えた**。

**対処**: 手動操作系（login, diag）は patchright の `launch_persistent_context` を直接使う。
scrapling は短命ページ前提の API。

### 8.5 ハッシュタグページにログイン無しだと完全に詰む

cookie 無しで `/tag/コスメ` を叩くと 100% login-wall 。HEADLESS=true/false に関係なく同じ結果。
**プロフィールページは cookie 無しでも取れる**ので、「ハッシュタグから username 発見 → プロフィール詳細取得」
の前半が完全に詰むのが PoC 序盤の致命的問題だった。

**対処**: `make login` で手動ログイン → `user_data_dir` で cookie 永続化 → 以降のリクエストで再利用。

### 8.6 ヘッドレス検出と HEADLESS=false は同一結果

「ヘッドレス検出されてるから HEADLESS=false にすれば抜けられる」と試したが、
**HEADLESS=false でも login-wall のままだった**（HTML サイズも同じ 399KB）。

**結論**: ヘッドレス検出ではなく、cookie 無しが原因。HEADLESS=false にしても解決しない。
本番では HEADLESS=true で問題ない。

### 8.7 本番想定で「自分の Chrome を使う」誘惑に注意

`AsyncStealthySession(real_chrome=True)` でユーザーの実 Chrome を起動する選択肢があるが:
- patchright のステルスパッチが当たらないので bot 検出は弱くなる
- ユーザーの普段使い Chrome のプロファイルを汚染する
- OS 依存性が増える
- Cloud Run には Chrome がそもそも入ってない

**結論**: real_chrome は使わない。patchright の専用 Chromium で完結させる。

### 8.8 キーワード検索 (`/search/user?q=`) は使用禁止

PoC で `make step3` (キーワード検索) を実装・実機検証したが、**本番では使ってはいけない**。
Makefile の `step3` ターゲットは無効化済（実行すると警告メッセージ表示のみ）。

**理由 1: TikTok robots.txt で明示的に Disallow**

```
User-agent: *
...
Disallow: /search/user?q=
Disallow: /search/video?
Disallow: /search?
```

ハッシュタグ (`/tag/`) は Allow なので明確に区別すべき。robots.txt 自体に法的拘束力はないが、
TikTok の「クローラーに対して禁止意思を明示している」=「ToS 違反の証拠固めに使われやすい」状態。

**理由 2: PoC で実機検証 → 機能していない**

`/search/user?q=美容ブロガー` を叩いた結果（`make step3 KEYWORD=美容ブロガー`）:
- HTML サイズ: ~419KB（小さい）
- `__DEFAULT_SCOPE__` キー: `seo.abtest, webapp.a-b, webapp.app-context, webapp.biz-context, webapp.i18n-translation` のみ
- `webapp.search` scope は **存在しない** = 検索結果データが SSR にも DOM にも入ってこない
- 取れた "結果" は実は **ログインアカウントへのおすすめ表示の username**（サイドバー由来）
  - 別キーワード（コスメ／美容ブロガー）で叩いても **完全に同じ username 順序** で出てきた
- 取得結果として大企業の公式アカウント等が出てくるが、これは検索結果ではなく
  **TikTok がそのアカウントに対して個別に推薦しているだけ**

**結論**: キーワード検索は技術的・規約的・効果的に三重に NG。本番ロードマップに含めない。

**本番側 AI への指示**:
- `make step3` 相当のエンドポイント (`/search/user?q=`, `/search?`, `/search/video?`) を実装しないこと
- 既に PoC で `Makefile` の step3 ターゲットは `exit 1` で停止するよう無効化されている
- もし「ユーザーがキーワードで検索したい」という要件が来た場合は、
  「ハッシュタグ検索 + キーワードフィルタ（取得後 nickname/signature の文字列マッチ）」で代替する
- 例: `/tag/コスメ` → 30 名取得 → bio に "美容ブロガー" 含む人で絞り込み

---

## 9. 運用上の注意

### 9.1 アカウント運用

- **絶対に本番アカウントを使わない**。捨てアカウントで運用
- ban されても困らないアカウントを Cloud Run 用に専用で 1 つ作る
- 投稿/フォロー/いいねの自動化は絶対にしない（read-only に徹する）

### 9.2 リクエスト間隔

- PoC 既定: 4〜8 秒（小規模テスト用）
- 推奨（scale 用）: **10〜30 秒**
- それ以下にすると bot 検出されやすい

### 9.3 一日の取得上限

経験則として:
- **1 アカウントで 1 日 100〜300 件のプロフィール取得が安全圏**
- それ以上はレート制限・CAPTCHA リスク高
- 必要なら捨てアカウントを複数作って分散

### 9.4 失敗パターンの監視

ログに以下のいずれかが出たら即停止 → 24時間以上空ける:
- `Empty body` 連発
- `Locator.wait_for: Timeout` 連発
- `Failed to parse profile` 連発
- HTTP 429/403

### 9.5 TikTok ToS 準拠

TikTok の利用規約はスクレイピングを禁止する条項を含む。
本プロジェクトは「学習・少量・低頻度」前提の PoC として実装されている。
本番化前に必ず法務確認すること。商用化・大量取得は要相談。

---

## 10. 将来の選択肢（PoC を超えて）

### 10.1 ms_token + API 直叩き方式 (TikTokApi ライブラリ)

[davidteather/TikTokApi](https://github.com/davidteather/TikTokApi) を使う方式。
ブラウザを「署名生成のためだけ」に起動し、実データ取得は HTTP 直接。

**移行の検討タイミング**:
- 本プロジェクトの patchright 方式が遅すぎてコストが問題になった時
- メモリが Cloud Run の 2GB に収まらなくなった時

**やめる理由**:
- TikTok の署名アルゴリズム (X-Bogus) が頻繁に変わる → ライブラリのメンテ追従待ちで止まる
- ms_token も自分で取りに行く必要があり、結局 patchright が要る
- 現状 patchright 方式が動いている間は書き換えコストに見合わない

### 10.2 商用スクレイピング API

Apify, Bright Data Datasets, Scrapfly 等。月 $50〜$500 で「TikTok データを REST で返す」サービス。

**検討タイミング**: 自前メンテのコストが商用 API の月額を上回った時。

### 10.3 公式 TikTok Display API / Marketing API

developers.tiktok.com で公開されている公式 API。
**インフルエンサー検索 / ハッシュタグ動画一覧の用途には使えない**（範囲が狭すぎる）。
動画埋め込み、コメント取得、マーケティング解析等の限定機能のみ。

---

## 11. 移植時のチェックリスト

本番側 (Vimmy Tools) で実装する時の順番:

- [ ] `backend/pyproject.toml` に `scrapling[fetchers]>=0.3.13` 追加
- [ ] `backend/Dockerfile` に Chromium 用 apt パッケージと `scrapling install` 追加
- [ ] PoC の `src/scraper.py` を `backend/api/services/tiktok_scraping_service.py` に移植
- [ ] PoC の `src/parser.py` の関数を同 service のヘルパーとして吸収
- [ ] `tests/test_parser.py` と fixtures を `backend/tests/` に移植
- [ ] Cloud Storage バケット `gs://{bucket}/secrets/tiktok/` を作成
- [ ] 手元 Mac で `make login` → `tiktok_profile.tar.gz` を初回アップロード
- [ ] Cloud Run Job エントリーポイント `backend/api/jobs/tiktok_scraping_job.py` を実装
  - cookie tar 取得・展開
  - service 実行
  - Firestore 書き込み
  - Slack 通知
- [ ] residential proxy を契約・設定
- [ ] Cloud Run Job のメモリ 2GB、タイムアウト 30 分以上、Service Account 設定
- [ ] 0 件取得時の Slack アラート設定
- [ ] 月次の cookie 更新フロー（運用ドキュメント）

---

## 12. 引き継ぎ事項サマリ

**この PoC で確立されたこと**:
1. patchright/Chromium + scrapling 薄ラッパーで TikTok スクレイピングは可能
2. 認証は `user_data_dir` で cookie 永続化、初回手動ログインを `make login` で済ませる
3. プロフィールは SSR JSON、ハッシュタグは遅延ロード後の DOM、と 2 パターン使い分け
4. `wait_selector` の選定が成否を分ける（プロフィール: script タグ、ハッシュタグ: data-e2e）
5. 動画タイルの href は絶対 URL なので regex 両対応必須

**本番側で必ずやること**:
1. residential proxy の契約と設定
2. Cookie 移植の運用フロー確立（Cloud Storage 経由、月次更新）
3. メモリ 2GB 以上の Cloud Run Job
4. 0 件アラートの Slack 通知

**本番側でやるべきでないこと**:
1. 本番アカウントの使用（必ず捨てアカウント）
2. ジッター 4 秒未満（bot 検出されやすい）
3. 同時並列実行（1 cookie で 1 並列まで）
4. 投稿・フォロー・いいねの自動化（read-only に限定）
5. **キーワード検索 (`/search/user?q=` / `/search?` / `/search/video?`) の実装**（§8.8 参照、robots.txt Disallow + 機能していない）

**PoC で作った成果物の場所**:
- ソース: `/Users/yazawakoki/practice/tiktok-scrape/tiktok-scraping/`
- GitHub: https://github.com/f82kouki/tiktok-scrape
- 動作実績: `output/result.json`, `output/result.csv` に PoC 取得結果あり

---

以上。本ドキュメントに無い実装ディテールが必要な場合は、PoC リポジトリの該当ファイルを直接参照すること。
ファイル別の役割は §5、技術詳細は §3 (抽出パターン)、ハマりポイントは §8 を最初に読むのが効率的。
