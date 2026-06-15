# グルメ Instagram 自動投稿システム

Instagram 1日3件の自動投稿パイプライン。

```
[iCloudPhotos 7,600枚] → analyze_photos.py (Gemini無料)
                               ↓ 食べ物分類 + GPS店名取得
                        generate_posts.py (Gemini無料)
                               ↓ キャプション生成
                     [Flask ダッシュボード でレビュー]
                               ↓ 承認
                       [Cloudinaryアップロード]
                               ↓
                         [queue/*.json]
                               ↓ GitHub Actions
                      Instagram 3件/日 自動投稿
```

---

## 必要なAPIキー一覧

| API | 費用 | 用途 |
|---|---|---|
| **Gemini API** | **無料** | 写真分類・キャプション生成 |
| **Instagram Graph API** | **無料** | 自動投稿 |
| **Cloudinary** | **無料** | 写真ホスティング |
| Google Maps API | 任意・無料枠内 | GPS→店名自動取得 |

---

## ステップ0: パッケージインストール

```bash
pip install -r requirements.txt
```

---

## ステップ1: APIキーを取得する

### 1-A. Gemini API キー（無料）

1. https://aistudio.google.com にアクセス
2. 「Get API key」→「Create API key」
3. クレジットカード不要

**無料枠:** 1,500リクエスト/日、15リクエスト/分

### 1-B. Instagram Graph API

**事前準備:**
1. InstagramをCreatorアカウントに変更:
   設定 → アカウント → アカウントの種類を切り替え → Creatorアカウント
2. Facebookページを作成（無料）: https://www.facebook.com/pages/create
3. Instagram設定 → リンクされたアカウント → Facebook → 上記Pageを接続

**Meta Developer Appの作成:**
1. https://developers.facebook.com にアクセス
2. 「マイアプリ」→「アプリを作成」→「その他」→「ビジネス」
3. 「Instagram Graph API」を追加
4. 「ツール」→「Graph API エクスプローラー」:
   - 権限: `instagram_basic`, `instagram_content_publish`, `pages_show_list`
   - 「アクセストークンを生成」
5. 長期トークンに変換（60日有効）:
   ```
   GET https://graph.facebook.com/v22.0/oauth/access_token
       ?grant_type=fb_exchange_token
       &client_id={APP_ID}
       &client_secret={APP_SECRET}
       &fb_exchange_token={SHORT_LIVED_TOKEN}
   ```
6. Instagram Business Account ID を取得:
   ```
   GET https://graph.facebook.com/v22.0/me/accounts?access_token={TOKEN}
   → page_id を取得

   GET https://graph.facebook.com/v22.0/{page_id}?fields=instagram_business_account&access_token={TOKEN}
   → instagram_business_account.id が IG_BUSINESS_ACCOUNT_ID
   ```

### 1-C. Cloudinary（無料）

1. https://cloudinary.com/users/register/free で無料登録
2. ダッシュボードから取得: Cloud Name / API Key / API Secret

---

## ステップ2: 環境変数を設定する

### ローカル実行用（PowerShell）

```powershell
$env:GEMINI_API_KEY          = "AIza..."
$env:CLOUDINARY_CLOUD_NAME   = "your_cloud_name"
$env:CLOUDINARY_API_KEY      = "123456789"
$env:CLOUDINARY_API_SECRET   = "your_secret"
```

### GitHub Secrets（自動投稿用）

リポジトリ Settings → Secrets and variables → Actions で登録:

| Secret名 | 内容 |
|---|---|
| `IG_ACCESS_TOKEN` | Instagram 長期アクセストークン |
| `IG_BUSINESS_ACCOUNT_ID` | Instagram ビジネスアカウントID |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary Cloud Name |
| `CLOUDINARY_API_KEY` | Cloudinary API Key |
| `CLOUDINARY_API_SECRET` | Cloudinary API Secret |

---

## ステップ3: 写真を分析する（複数日に分けて実行）

```bash
python scripts/analyze_photos.py
```

- Gemini で全写真を食べ物/非食べ物に分類
- 撮影時刻で同一店舗をグルーピング（3時間以内 = 同一訪問）
- HEIC・JPG両対応、GPS情報を自動取得
- **1,500枚/日の制限あり → 7,600枚は約5日で完了**
- 中断・再開可能（処理済みはキャッシュに保存）

---

## ステップ4: キャプションを生成する

```bash
python scripts/generate_posts.py
```

---

## ステップ5: ダッシュボードでレビューする

```bash
python dashboard/app.py
```

http://localhost:5000 を開く。各店舗ごとに:
1. 食べ物写真を確認
2. 店名・エリアを入力（GPS自動取得 or 手動）
3. Instagramキャプションを編集
4. 「承認して投稿キューへ」をクリック

---

## ステップ6: GitHubリポジトリを作成して自動投稿を有効化する

```bash
git init
git add .
git commit -m "init: gourmet instagram automation"
```

GitHub で新リポジトリを作成してpush。
自動投稿スケジュール（Instagram）: 8:00 / 12:00 / 19:00 JST

---

## 投稿フォーマット（Instagram）

```
📍 店名 | エリア

料理の詳細感想（3〜4行）

English description.

━━━━━━━━━━━
🏠 店名
📍 エリア
━━━━━━━━━━━

#ジャンル #エリアグルメ #グルメ #foodie #japanesefood
```

※ 1枚目: 店名+エリアのテキストオーバーレイ
※ 2〜9枚目: 料理・内装など
※ ハッシュタグは5個まで（2026年Instagram仕様）

---

## ディレクトリ構成

```
gourmet-sns/
├── scripts/
│   ├── analyze_photos.py    # 写真分類・クラスタリング（Gemini）
│   ├── generate_posts.py    # キャプション生成（Gemini）
│   ├── create_overlay.py    # 1枚目テキスト合成
│   └── post_instagram.py    # Instagram自動投稿
├── dashboard/
│   ├── app.py               # Flaskダッシュボード
│   └── templates/
├── data/
│   ├── restaurants.json     # 全データ
│   └── classify_cache.json  # 分類キャッシュ（再実行時に再利用）
├── queue/                   # 承認済み投稿キュー
├── posted/                  # 投稿済みアーカイブ
├── overlaid/                # テキスト合成済み1枚目
└── .github/workflows/
    └── post_instagram.yml   # Instagram自動投稿（3件/日）
```
