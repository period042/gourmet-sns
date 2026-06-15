"""
X (Twitter) への自動投稿スクリプト

GitHub Actions から呼び出される:
  python scripts/post_x.py

queue/ の中で platform=x かつ status=approved のものを1件投稿し posted/ に移動。
"""
import os
import json
import time
import requests
import tempfile
from pathlib import Path
from datetime import datetime

import tweepy

QUEUE_DIR = Path(__file__).parent.parent / "queue"
POSTED_DIR = Path(__file__).parent.parent / "posted"

# X API v2 認証
def get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN_GOURMET"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET_GOURMET"],
    )

# v1.1 API (メディアアップロード用)
def get_auth() -> tweepy.OAuth1UserHandler:
    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN_GOURMET"],
        os.environ["X_ACCESS_TOKEN_SECRET_GOURMET"],
    )
    return auth


def upload_media(auth: tweepy.OAuth1UserHandler, url: str) -> str | None:
    """画像URLをダウンロードしてX v1.1 media/uploadへ送信、media_idを返す。"""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(resp.content)
            tmp = f.name
        api = tweepy.API(auth)
        media = api.media_upload(filename=tmp)
        Path(tmp).unlink(missing_ok=True)
        return str(media.media_id)
    except Exception as e:
        print(f"  [warn] media upload failed: {e}")
        return None


def pick_queue() -> Path | None:
    files = sorted(QUEUE_DIR.glob("*_x.json"))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("platform") == "x" and data.get("status") == "approved":
                return f
        except Exception:
            pass
    return None


def fix_caption(text: str) -> str:
    """X 403 を避けるための最低限のサニタイズ (x-affiliate の知見より)"""
    import re
    text = re.sub(r"\d{3,4}万円", "高収入", text)
    text = text.replace("LinkedIn", "SNS").replace("GitHub", "コード管理")
    return text


def main():
    POSTED_DIR.mkdir(exist_ok=True)
    qfile = pick_queue()
    if not qfile:
        print("投稿キューが空です。")
        return

    data = json.loads(qfile.read_text(encoding="utf-8"))
    caption = fix_caption(data.get("caption", ""))
    photo_urls = data.get("photo_urls", [])

    print(f"投稿: {data['restaurant_name']} ({data['area']})")

    auth = get_auth()
    media_ids = []
    for url in photo_urls[:4]:
        mid = upload_media(auth, url)
        if mid:
            media_ids.append(mid)
        time.sleep(1)

    # 画像付き投稿なのに全枚失敗した場合はスキップ（テキストのみ投稿は意図しない）
    if photo_urls and not media_ids:
        print("❌ メディアアップロード全失敗。投稿をスキップします。")
        data["status"] = "failed"
        data["error"] = "all media uploads failed"
        posted_path = POSTED_DIR / qfile.name
        posted_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        qfile.unlink()
        print(f"移動: {posted_path}")
        return

    client = get_client()
    kwargs = {"text": caption}
    if media_ids:
        kwargs["media_ids"] = media_ids

    try:
        res = client.create_tweet(**kwargs)
        tweet_id = res.data["id"]
        print(f"✅ 投稿完了: https://x.com/i/web/status/{tweet_id}")
        data["status"] = "posted"
        data["tweet_id"] = tweet_id
        data["posted_at"] = datetime.now().isoformat()
    except tweepy.errors.Forbidden as e:
        print(f"❌ 403 Forbidden: {e}")
        data["status"] = "failed"
        data["error"] = str(e)

    posted_path = POSTED_DIR / qfile.name
    posted_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    qfile.unlink()
    print(f"移動: {posted_path}")


if __name__ == "__main__":
    main()
