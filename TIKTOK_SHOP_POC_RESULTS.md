# TikTok Shop PoC 成果まとめ（できたこと / できなかったこと）

> 作成日: 2026-07-02　ブランチ: `202607/02_shop-store-scraper-poc`
> 目的: TikTok Shop の店舗を横断収集し、営業リード（店舗指標＋連絡先）を作る PoC の結果整理。
> 技術詳細は [TIKTOK_SHOP_POC.md](TIKTOK_SHOP_POC.md) を参照。本書は「何ができて・何ができなかったか」に絞った振り返り。

---

## 0. ひとことで

- **店舗データの抽出は成立**（実証済み）。店名・フォロワー・販売数・商品数・評価などを全自動で取得できる。
- **壁は「連絡先」だけ**。TikTok は出品者の電話/メールを web に出しておらず、事業者情報（特商法）は**アプリ専用**。連絡先は TikTok の外（自社サイト）から**部分的に**しか補完できない。

---

## 1. これまでやったこと（工程）

1. 既存インフルエンサースクレイパーの土台調査 → 店舗向けに並置する設計
2. robots.txt 実測でコンプライアンス境界を確定
3. 店舗ページの構造をリコン → `shop.tiktok.com` の埋め込みJSON（`__MODERN_ROUTER_DATA__`）を特定
4. 発見導線（入口→カテゴリ→商品→店舗）を実装・オフライン検証
5. 小ロット実行で実データ取得（CSV/JSONL）
6. `store_url` が 404 になる問題を切り分け→対処
7. 連絡先が TikTok に無いと判明 → 外部エンリッチ（検索→特商法/会社概要）を試作・検証
8. 説明文(desc)からの公開リンク抽出を別コマンドで実装
9. アプリの「このショップについて」（特商法）の web 取得可否をネットワーク傍受でリコン → **アプリ専用**と確定

---

## 2. できたこと ✅

### 店舗データ抽出（主成果）
- `shop.tiktok.com/jp` → カテゴリ → 商品(PDP) と辿り、商品ページ埋め込みの `shop_info` から下記を取得：
  **店名・フォロワー数・総販売数・商品数・動画数・評価・レビュー数・seller_id・地域・ロゴ・説明文**
- **seed 不要・全自動・robots クリーン**な発見。`seller_id` で重複排除。
- 実データで実証（例）：
  - Classical Elf【公式】: フォロワー149,990 / 販売90,466 / 商品1,223 / 評価4.3
  - Perfect Diary Japan: フォロワー6,135 / 販売21,246 / 商品86 / 動画284 / 評価4.6
- 1件ごとに `output/result_shop.{json,csv}` と `shops.jsonl` へ逐次保存（クラッシュ耐性）。

### 連絡先エンリッチ（外部・部分的だが成立）
- 店名を Web 検索 → 「特定商取引法に基づく表記 / 会社概要」から **会社名・メール・電話・住所**を抽出。
- **誤検出防止ゲート**（ページに店名が含まれるか照合）で別サイトの連絡先混入を防止。
- 実証：Classical Elf → 株式会社クラシカルエルフ / `elf@silk.ocn.ne.jp` を自動取得。

### 公開リンク整理（無料・一瞬）
- 店舗説明文(desc)から、セラーが自分で貼った 自社サイト/Instagram/YouTube/X/LINE を抽出（既存プロフィール用パーサを流用）。オフライン・追加取得ゼロ。

### 品質・保守
- 既存コードは**一切削除せず追加のみ**。
- `make test` が元々壊れていた問題（pytest の import パス欠如）を修正。
- テスト **13 passed / 3 skipped**、`ruff` clean。

---

## 3. できなかったこと ❌

| できなかったこと | 理由（実測） |
|---|---|
| **独立した店舗ページを開けるURL化** | `shop.tiktok.com/jp/store/…` は 404、`www.tiktok.com/shop/store/…` は `/404` へリダイレクト（大手でも）。店舗は SPA/アプリ内でしか開けない → `store_url` は開ける PDP URL で代替 |
| **TikTok から連絡先（電話/メール）を直接取得** | TikTok Shop のページに出品者の電話/メールが存在しない（連絡は本来アプリ内メッセージ） |
| **特商法「このショップについて」（商号/電話/住所/代表）の web 取得** | デスクトップwebにUIが無い。モバイルwebにも無く**アプリDLへ誘導**＝**ネイティブアプリ専用**と確定 |
| **検索ベースの店舗発見** | `/search*` は robots.txt で Disallow のため不採用 |
| **TikTok専業・自社サイト無し店の連絡先** | web 上のどこにも公開されていないため取得不能 |

---

## 4. 部分的にできた 🟡

| 項目 | 状況 |
|---|---|
| 連絡先エンリッチ | 自社サイトを持つブランドは取れる（Classical Elf ✅）／TikTok専業・汎用名店は取れない（Kola Kola・Only Good Clothing ❌）。加えて**速度が遅い**（ブラウザ検索＋直列） |
| 公開リンク抽出 | 説明欄にURLを貼る店のみ。今回サンプルは **0/20**（desc がテンプレ文だったため。挙動としては正常） |

---

## 5. 判明した重要な事実（技術メモ）

- `shop.tiktok.com` は本体 `www.tiktok.com` とは**別アプリ**（`tiktok_shop_web_mono`）。`__UNIVERSAL_DATA_FOR_REHYDRATION__` は無く、**`__MODERN_ROUTER_DATA__`** に `shop_info` が入る。
- robots.txt：`shop.tiktok.com` の `/jp/c/`・`/jp/pdp/`・`/jp/store/` は Disallow なし。`www` 側は `/tag` Allow・`/search*` と `/shop/view/product/` は Disallow。
- **モバイルwebは「幅を狭くする（レスポンシブ）」では出ない**。**UA をスマホに変える**と別アプリ（`/api/shop/pdp_h5/page_data`）が配信される。ただしそれでも「このショップについて」は無い。
- 特商法情報は「このショップについて」を開いた時だけ呼ばれる **on-demand API**。web にトリガーが無いため、取得には**ネイティブアプリの通信傍受**（mitmproxy等）が必要＝重い・脆い・BAN/ToSリスク高で **PoC範囲外**。

---

## 6. 成果物

### コマンド
```bash
make shop-run SHOP_MAX=20   # 店舗収集 → shops.jsonl, result_shop.csv
make shop-links             # 公開リンク整理（無料・一瞬）→ shop_links.csv
make shop-enrich            # 連絡先エンリッチ（遅い・部分的）→ leads.csv
# 診断: make shop-discover / shop-dump SHOP_URL=... / shop-recon
```

### 実装ファイル（すべて追加）
`src/shop_parser.py` / `src/shop_scraper.py` / `src/shop_main.py` / `src/enrich.py` /
`src/models.py`(TiktokShop追記) / `scripts/{dump_store_page,diagnose_shop,check_shop_discovery,enrich_shops,extract_links}.py` /
`tests/{test_shop_parser,test_enrich}.py` / `Makefile`・`.env.example`・`pyproject.toml`(追記)

### 出力ファイル（`output/`）
`shops.jsonl`・`result_shop.{json,csv}`（店舗データ）／`shop_links.{csv,jsonl}`（公開リンク）／`leads.{csv,jsonl}`（連絡先付き）

---

## 7. 結論と割り切り

- **「有望な TikTok Shop 店を機械的にリスト化＋序列化」＝ できる（実用レベル）。** ここが本 PoC の確かな成果。
- **「全店の電話/メールを自動で揃える」＝ できない。** TikTok専業で自社サイトも無い店の連絡先は web 上に存在しないため。
- 用途が「**営業先リストを作り、連絡先は取れる範囲で付け、残りは人が確認**」なら成立する。
- 有望店（フォロワー・販売数が多い店）ほど自社サイトを持ちがちで連絡先が取れる傾向 → 実運用では回る。

---

## 8. 未着手 / 次の選択肢

1. **エンリッチの高速化**：検索API（Brave / Google CSE）＋素HTTP＋並列で 10〜100倍。
2. **有料 B2B 企業DB**（Musubu / FUMA 等）：店名→企業が引ければ連絡先を安定取得（コスト要）。
3. **特商法アプリAPI**：ネイティブアプリ傍受でのみ可能だが重い・リスク高（非推奨）。
4. **運用でカバー**：上位N件は人手でエンリッチ。
