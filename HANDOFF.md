# Handoff Document — gourmet-sns 自動投稿システム
**最終更新**: 2026-09-26  
**引き継ぎ元**: Claude Sonnet 4.6 (Claude Code)  
**引き継ぎ先**: GitHub Copilot Agent または後続AIエージェント

---

## 1. システム概要

**リポジトリ**: `period042/gourmet-sns`（GitHub）  
**ローカルパス**: `C:\Users\hmorimot\Documents\01_ClaudeCode\gourmet-sns`

グルメ訪問記録を **Instagram に 1日1件・毎日12:05 JST** に自動投稿するシステム。  
Threads への同時投稿は停止中（Instagram 投稿は継続中）。

---

## 2. アーキテクチャ

### 投稿フロー（GitHub Actions）
```
queue/*.json
  ↓ Phase 0: 失敗ファイルを repair（scheduled_at に空きスロット割り当て）
  ↓ Phase 1: lock（in_progress/ に移動）
  ↓ Phase 2a: Instagram 投稿（graph.instagram.com/v22.0）
  ↓ Phase 2b: cleanup（posted/ に移動）
```

ワークフローは1日11回実行（10:35〜20:35 JST）されるが、`DAILY_POST_LIMIT = 1` により1日1件のみ投稿される。

### ファイル状態
| ディレクトリ | 意味 |
|---|---|
| `queue/` | 投稿待ち（`scheduled_at` ≤ now のものが次回実行で投稿） |
| `in_progress/` | 投稿処理中（ロック中） |
| `posted/` | 投稿済みアーカイブ |

### 主要ファイル
| ファイル | 役割 |
|---|---|
| `scripts/post_instagram.py` | メイン投稿スクリプト（Phase 0〜2b） |
| `scripts/create_overlay.py` | 1枚目写真にテキストオーバーレイを合成 |
| `.github/workflows/post_instagram.yml` | 毎日11回実行ワークフロー（10:35〜20:35 JST） |
| `.github/workflows/check_token_expiry.yml` | 毎日09:00 JST トークン期限チェック |
| `.github/workflows/refresh_ig_token.yml` | 手動トークン更新ワークフロー |
| `token_metadata.json` | トークン期限・user_id 管理 |
| `dashboard/app.py` | Flask ダッシュボード（ローカル: http://127.0.0.1:5000） |
| `data/restaurants.json` | 全レストランデータ（構造: `{"restaurants": [...], "generated_at": "..."}`） |
| `data/restaurant_overrides.json` | ステータス上書き（構造後述） |

---

## 3. Instagram API 設定

| 項目 | 値 |
|---|---|
| API 形式 | Instagram with Instagram Login（新形式） |
| エンドポイント | `https://graph.instagram.com/v22.0` |
| トークン形式 | `IGAAN...`（60日有効） |
| トークン期限 | 2026-10-11（`token_metadata.json` 参照） |
| User ID | `28190971523873170` |
| App ID | `1554579942959950` |

**GitHub Secrets**（`period042/gourmet-sns`）:
- `IG_ACCESS_TOKEN` — 現在有効な IGAAN トークン
- `IG_BUSINESS_ACCOUNT_ID` — `28190971523873170`
- `IG_APP_ID` — `1554579942959950`
- `IG_APP_SECRET` — （設定済み）
- `THREADS_ACCESS_TOKEN` — 期限 2026-10-11（現在投稿停止中）
- `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` — 画像ホスティング

---

## 4. このセッションで実施した変更（詳細）

### 4-1. Threads 投稿の停止
**ファイル**: `scripts/post_instagram.py` L625〜627  
`_post_to_threads()` の呼び出し3行をコメントアウト。Instagram 投稿は継続。  
```python
# Threads 投稿は停止中（Instagram のみ継続）
# th_id = _post_to_threads(data, ig_permalink)
# if th_id:
#     data["th_post_id"] = th_id
```

### 4-2. 1日投稿上限チェックの追加
**ファイル**: `scripts/post_instagram.py` L227〜257  
ワークフローが1日11回実行されても複数投稿されないよう `DAILY_POST_LIMIT = 1` を追加。  
`_count_posted_today()` が `posted/` フォルダを走査して当日 JST の投稿数をカウントし、上限に達していれば `pick_queue()` が `None` を返してスキップする。  
- 週次まとめ（`restaurant_id == "summary"`）はカウント対象外
- `utf-8-sig` で BOM 付きファイルも正しく読む

### 4-3. create_overlay.py — レイアウト切替（`layout` パラメータ）
**ファイル**: `scripts/create_overlay.py`  
`create_overlay()` に `layout: str = "top"` パラメータを追加。

| layout | フック（黄色バー）位置 | キャッチコピー位置 | エリアバッジ位置 | チェックリスト位置 |
|---|---|---|---|---|
| `"top"`（デフォルト） | 左上（y=16） | フック直下 | 右下 | コピー直下（H×61.5%以降） |
| `"bottom"` | コピー直上（下部） | 下部（ボトムマージン 40px） | 右上（y=16） | H×42%（中段） |

変更前はレイアウトが固定（前セッションで「bottom」に変更していたが、今セッションで `"top"` をデフォルトとし両対応に整理）。

### 4-4. create_overlay.py — EXIF 回転自動補正
**ファイル**: `scripts/create_overlay.py` L12, L258  
```python
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
# ...
img = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
```
縦撮り HEIC 写真がオーバーレイ生成時に 90 度回転していた問題を修正。`ImageOps.exif_transpose()` で EXIF の Orientation タグを反映してから処理する。

### 4-5. create_overlay.py — テキストシャドウ削除
**ファイル**: `scripts/create_overlay.py`  
`_shadow()` の呼び出しを全削除（キャッチコピー・チェックリスト・エリアバッジの3か所）。  
シャドウ（黒・半透明・ぼかし）が写真を不必要に暗くしていたため。  
`_shadow()` 関数の定義自体は残存（削除しても影響なし）。

### 4-6. create_overlay.py — 下部グラデーション削除
**ファイル**: `scripts/create_overlay.py` L271〜279（削除済み）  
写真の下 45%（H×0.45〜）にかかっていた黒グラデーション（最大不透明度 190/255）を完全削除。  
変更前:
```python
grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(grad)
gs = int(H * 0.45)
for i in range(H - gs):
    t = i / (H - gs)
    gd.rectangle([(0, gs + i), (W, gs + i + 1)], fill=(0, 0, 0, int(190 * (t ** 1.1))))
canvas = Image.alpha_composite(img.convert("RGBA"), grad)
```
変更後:
```python
canvas = img.convert("RGBA")
```

### 4-7. ダッシュボード — レイアウト切替 UI の追加
**ファイル**: `dashboard/templates/detail.html`、`dashboard/app.py`

`detail.html` の「フック」フィールド直下にラジオボタンを追加:
```html
<input type="radio" name="layout" value="top" checked onchange="schedulePreviewRefresh()">上
<input type="radio" name="layout" value="bottom" onchange="schedulePreviewRefresh()">下
```

JS の `generateOverlayPreview()` と `approve()` で `layout` を取得してリクエストに含める:
```javascript
const layout = document.querySelector('input[name="layout"]:checked')?.value || 'top';
```

`app.py` の2エンドポイントで `layout` を受け取り `create_overlay()` に渡す:
- `/api/restaurant/<rid>/overlay_preview`（GET）: `layout = request.args.get("layout", "top")`
- `/api/restaurant/<rid>/approve`（POST）: `layout = body.get("layout", "top")`

### 4-8. restaurant_overrides.json — 正しい entries 構造への修正
**ファイル**: `data/restaurant_overrides.json`

**問題**: Python スクリプトでオーバーレイを書き込む際、`entries` の外（トップレベル）にキーを追加していた。  
**原因**: `dashboard/app.py` の `_apply_overrides()` が `load_overrides().get("entries", {})` で読むため、トップレベルのキーは無視される。  
**正しい構造**:
```json
{
  "version": 1,
  "entries": {
    "IMG_2728.HEIC": { "status": "approved" },
    "IMG_2689.HEIC": { "status": "approved" }
  }
}
```
**修正方法**: トップレベルに書かれていたキーを `entries` 内に移動するスクリプトを実行。  
**影響**: これにより「承認済みなのにレビュー待ち」と表示されていた店舗が正しく表示されるようになった。

### 4-9. 承認済みキュー全件のオーバーレイ再生成
**対象**: `queue/*.json` のうち `status == "approved"` の全 32 件  
**理由**: グラデーション・シャドウ削除後の新ロジックで、既存の Cloudinary 画像を差し替える必要があった。

**処理内容**:
1. 各キューファイルの `overlay_source_path`（承認時に保存されるカバー写真の相対パス）からローカルファイルを特定
2. `restaurants.json` から `catchphrase`、`hook_text`、`yellow_word`、`bullets` を取得
3. `create_overlay()` で新しいオーバーレイを生成
4. Cloudinary に再アップロード
5. `photo_urls[0]` を新 URL に更新してキューファイルを上書き

**使用スクリプト**: `scratchpad/regen_overlays.py`（セッション固有パス）  
**結果**: 32件全て成功・0件失敗

### 4-10. キュー日付設定（複数回）
今セッションで追加された全キューファイルに `scheduled_at` を設定。  
設定形式: `"2026/10/31 12:05:00"`（スラッシュ区切り・12:05 JST 固定）

`scheduled_at` 設定と合わせて `restaurant_overrides.json` の `entries` に `{"status": "approved"}` を追加（ダッシュボードで「レビュー待ち」から消えるようにする）。

---

## 5. キューファイルの構造と重要フィールド

```json
{
  "id": "20260926_134734_r0411_instagram",
  "platform": "instagram",
  "restaurant_id": "r0411",
  "restaurant_name": "チャモロ",
  "area": "恵比寿駅",
  "photo_urls": ["https://res.cloudinary.com/..."],
  "caption": "...",
  "created_at": "2026-09-26T...",
  "status": "approved",
  "overlay_source_path": "photos/2024/..../IMG_3287.HEIC",
  "scheduled_at": "2026/10/01 12:05:00",
  "catchphrase": "",
  "hook_text": "",
  "yellow_word": "",
  "layout": ""
}
```

**重要**: `overlay_source_path` はダッシュボードの承認ボタン経由で作成した場合のみ存在する。直接 JSON を作成した場合は空になる。

---

## 6. 重要な設計上の注意点

### restaurant_overrides.json の構造
```json
{
  "version": 1,
  "entries": {
    "IMG_3295.HEIC": { "status": "approved", "catchphrase": "..." }
  }
}
```
- キーは **写真ファイル名**（HEIC/JPG のファイル名のみ・パスなし）
- `dashboard/app.py` の `_override_key(r)` が `postable_photos[0]["filename"]` を返す
- **`entries` の外（トップレベル）に書いても反映されない**
- Python で直接書く場合は必ず `overrides.setdefault("entries", {})[key] = {...}` を使うこと

### ダッシュボードの承認フロー
1. ダッシュボードの「承認」ボタン → `POST /api/restaurant/<rid>/approve`
2. `create_overlay()` でオーバーレイ生成 → Cloudinary アップロード
3. `queue/` に JSON 書き込み（`scheduled_at` は**空のまま**）
4. `restaurant_overrides.json` の `entries` に `{"status": "approved"}` を書き込む
5. **`scheduled_at` は別途 Claude Code に「日付入れて」と依頼する**

### ダッシュボードを経由せずキューを直接作成した場合
- `restaurant_overrides.json` が更新されないため、ダッシュボードが `pending` のまま
- → 手動で `entries` に `{"status": "approved"}` を追加する
- `overlay_source_path` も入らないため、オーバーレイ再生成時は `postable_photos[0]` で代替する

### restaurants.json の ID 断絶問題
過去に `restaurants.json` が複数回再生成されており、同じ ID が異なる店に再利用されている。  
`posted/` の `restaurant_id` はあくまで参考。名前照合が必要な場合がある。

### Threads 停止中
`scripts/post_instagram.py` L625〜627 がコメントアウト済み。再開する場合はコメントを外すこと。

### Instagram error 2207052 の自動修復
`post_instagram.py` の `_reupload_cloudinary()` が実装済み。  
Instagram が Cloudinary の URL からメディアを取得できない場合（error 2207052）、自動で再アップロードしてリトライする。

### git push rejected 問題
GitHub Actions が定期実行でコミットを積むため、ローカルからの push が頻繁に rejected になる。  
対処パターン:
```bash
git stash && git pull --rebase && git stash pop && git push
```

### ダッシュボード起動は 127.0.0.1
Windows 環境で `localhost` が IPv6（`::1`）に解決され、Flask の IPv4 リスナーに届かない。  
**必ず `http://127.0.0.1:5000` を使うこと**（`http://localhost:5000` は NG）。

---

## 7. 現在の投稿スケジュール（2026-09-26 時点）

| 日付 | 店名 |
|---|---|
| 9/26 | 新潟屋 |
| 9/27 | スタンドトトノイ |
| 9/28 | 九州産直 炉端かてて 八丁堀はなれ |
| 9/29 | 和牛焼串 とびうし 離宮 |
| 9/30 | 魚猫 大山店 |
| 10/1 | チャモロ |
| 10/2 | いっちゃん 本店 |
| 10/3 | 居魚屋 うおはん |
| 10/4 | おいしかよ |
| 10/5 | じねん |
| 10/6 | 丸吉食堂 |
| 10/7 | Il Cucchiaio di Angelo |
| 10/8 | 日本料理 秀たか |
| 10/9 | 焼鳥たなべ |
| 10/10 | なきざかな 新宿店はなれ |
| 10/11 | hide mode |
| 10/12 | べったこ |
| 10/13 | タイ イサーン |
| 10/14 | 立ち呑み処 魚しょう 天満 |
| 10/15 | のみくい なにわ |
| 10/16 | 地魚屋台 浜ちゃん 上野店 |
| 10/17 | リアン スイートホーム |
| 10/18 | 中華そば 半ざわ |
| 10/19 | Caline |
| 10/20 | 居酒茶屋 鑪 |
| 10/21 | たる鉄 |
| 10/22 | 酒ば すぎちゃんチ |
| 10/23 | ひでちゃん |
| 10/24 | 串駒 本店 |
| 10/25 | ニューみかん |
| 10/26 | 魚と肉の創作酒場 あどはだり |
| 10/27 | 焼肉29テラス 渋谷南口店 |
| 10/28 | 立呑みアーニー |
| 10/29 | 壱ノ宮 |
| 10/30 | OSTERIA CHOUZETSU TOKYO |
| 10/31 | うしごろ 貫 恵比寿本店 |

---

## 8. 未解決事項

### 8-1. IG_ACCESS_TOKEN の自動更新（要確認）
トークン期限: **2026-10-11**。  
`check_token_expiry.yml` が 14日前（2026-09-27頃）に自動更新を試みる予定。  
GitHub Actions のログで成否を確認すること。失敗した場合は Meta Developer Console から手動取得 → GitHub Secrets と `.env` を更新。

### 8-2. ダッシュボードの pending 表示（手動照合が必要）
「レビュー待ち」約 165 件の中に実際には投稿済みの店が混在している可能性あり。  
https://www.instagram.com/sake_to_meshi_3155/ と照合が必要。  
判明したら `restaurant_overrides.json` の `entries` に `{"status": "posted"}` を追加（キー=写真ファイル名）。

### 8-3. Threads トークン期限（2026-10-11）
Threads 投稿停止中だが、トークンが期限切れになる。再開する場合は更新が必要。

---

## 9. よく使う操作

### ダッシュボード起動
```powershell
Start-Process python -ArgumentList "dashboard/app.py" `
  -WorkingDirectory "C:\Users\hmorimot\Documents\01_ClaudeCode\gourmet-sns" `
  -WindowStyle Hidden
# → http://127.0.0.1:5000 を開く（localhost は IPv6 解決されて接続不可）
```

### 新規キューへの日付割り当て
「キュー追加したから日付入れて」と Claude Code に伝えれば自動処理される。  
手動で設定する場合の形式: `"2026/10/31 12:05:00"`（スラッシュ区切り）

### git push が rejected になった場合
```bash
git stash && git pull --rebase && git stash pop && git push
```

### 承認済みキューのオーバーレイを再生成する場合
```python
# 各キューファイルの overlay_source_path を使う
from scripts.create_overlay import create_overlay
overlay = create_overlay(
    src_path, area, catchphrase, out_dir,
    target_copy=hook_text, yellow_word=yellow_word,
    bullets=bullets, layout=layout  # "top" or "bottom"
)
# → Cloudinary に再アップロードして photo_urls[0] を差し替える
```

---

## 10. 重要な前提条件

| 原則 | 内容 |
|---|---|
| **APIキーはチャットで共有しない** | `.env` は gitignore 済み・コミット禁止 |
| **自分でやる** | ユーザーに操作手順を案内しない。できることは自分で実行 |
| **他サービスへの書き込み確認** | GitHub 以外のサービスへの書き込みは事前にユーザー確認 |
| **1日1件上限** | `DAILY_POST_LIMIT = 1`（`post_instagram.py` L227） |
| **Threads 停止中** | `post_instagram.py` L625〜627 をコメントアウト済み |
| **overrides キーは写真ファイル名** | ID や店名でキー検索すると効かない |
| **overrides は entries の中** | トップレベルに書いても `_apply_overrides()` に反映されない |
| **graph.instagram.com 使用** | 旧形式の `graph.facebook.com` ではトークンエラーになる |
| **ダッシュボードは 127.0.0.1** | `localhost` は Windows で IPv6 解決されて接続できない |

---

## 11. 関連リンク

- Instagram: https://www.instagram.com/sake_to_meshi_3155/
- GitHub Repository: https://github.com/period042/gourmet-sns
- Meta Developer Console: https://developers.facebook.com（App ID: 1554579942959950）
