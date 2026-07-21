"""
Instagram への自動投稿スクリプト (Instagram Graph API)

前提:
  - Instagram Creator/Business アカウント
  - Facebook Page に接続済み
  - Meta Developer App で graph API 有効化
  - 環境変数: IG_ACCESS_TOKEN, IG_BUSINESS_ACCOUNT_ID

queue/ の中で platform=instagram かつ status=approved のものを1件投稿。
*_instagram.json および *_reel.json の両方を対象とする。
"""
import os
import re
import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

JST = timezone(timedelta(hours=9))

load_dotenv(Path(__file__).parent.parent / ".env")

QUEUE_DIR       = Path(__file__).parent.parent / "queue"
POSTED_DIR      = Path(__file__).parent.parent / "posted"
RESTAURANTS_JSON= Path(__file__).parent.parent / "data" / "restaurants.json"
GRAPH_URL       = "https://graph.facebook.com/v22.0"

_restaurants_cache: list[dict] | None = None


def get_creds() -> tuple[str, str]:
    token = os.environ["IG_ACCESS_TOKEN"]
    account_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]
    return token, account_id


def get_location_id(restaurant_id: str) -> str | None:
    """restaurants.json から facebook_place_id を取得。"""
    global _restaurants_cache
    if _restaurants_cache is None:
        try:
            raw = json.loads(RESTAURANTS_JSON.read_text(encoding="utf-8"))
            _restaurants_cache = raw["restaurants"] if isinstance(raw, dict) else raw
        except Exception:
            _restaurants_cache = []
    for r in _restaurants_cache:
        if r.get("id") == restaurant_id:
            return r.get("facebook_place_id")
    return None


def create_media_container(
    token: str, account_id: str, image_url: str,
    caption: str = "", is_carousel_item: bool = False,
    location_id: str | None = None,
) -> str:
    """単一画像またはカルーセルアイテムのコンテナIDを作成。"""
    url = f"{GRAPH_URL}/{account_id}/media"
    params: dict = {"access_token": token, "image_url": image_url}
    if is_carousel_item:
        params["is_carousel_item"] = "true"
    else:
        params["caption"] = caption
        if location_id:
            params["location_id"] = location_id
    resp = requests.post(url, params=params, timeout=30)
    if not resp.ok:
        print(f"[API error] {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return resp.json()["id"]


def create_carousel_container(
    token: str, account_id: str, children_ids: list[str], caption: str,
    location_id: str | None = None,
) -> str:
    """カルーセル投稿のコンテナIDを作成。"""
    url = f"{GRAPH_URL}/{account_id}/media"
    params = {
        "access_token": token,
        "media_type": "CAROUSEL",
        "children": ",".join(children_ids),
        "caption": caption,
    }
    if location_id:
        params["location_id"] = location_id
    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def create_reel_container(
    token: str, account_id: str, video_url: str, caption: str,
) -> str:
    """Reels コンテナIDを作成。"""
    url = f"{GRAPH_URL}/{account_id}/media"
    params = {
        "access_token": token,
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
    }
    resp = requests.post(url, params=params, timeout=30)
    if not resp.ok:
        print(f"[API error] {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    return resp.json()["id"]


def publish_container(token: str, account_id: str, container_id: str) -> str:
    """コンテナを公開し、投稿IDを返す。"""
    url = f"{GRAPH_URL}/{account_id}/media_publish"
    params = {"access_token": token, "creation_id": container_id}
    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def wait_for_container(token: str, container_id: str, max_wait: int = 120) -> bool:
    """コンテナの処理完了を待つ。Reels は処理が長いため max_wait を長めに。"""
    url = f"{GRAPH_URL}/{container_id}"
    for _ in range(max_wait // 5):
        r = requests.get(url, params={"fields": "status_code", "access_token": token}, timeout=10)
        status = r.json().get("status_code", "")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            return False
        time.sleep(5)
    return False


def normalize_url(url: str, crop: bool = False) -> str:
    """Cloudinary URL を Instagram 向けに変換。
    - HEIC: Cloudinary の f_jpg transform + 拡張子変更（単純拡張子変更だけでは実体がJPGにならない）
    - 2枚目以降: 4:5 クロップ
    """
    if "res.cloudinary.com" not in url or "/upload/" not in url:
        return url

    transforms = []
    is_heic = url.lower().endswith(".heic")
    if is_heic:
        transforms.append("f_jpg")
    if crop:
        transforms.append("c_fill,ar_1:1,g_auto")

    if transforms:
        url = url.replace("/upload/", f"/upload/{','.join(transforms)}/", 1)
    if is_heic:
        url = re.sub(r'\.(heic|HEIC)$', '.jpg', url)
    return url


def _build_posted_rid_set() -> set[str]:
    """posted/ の投稿済みファイルから "rid:photo" / "rid:reel" のセットを返す。"""
    rids: set[str] = set()
    if not POSTED_DIR.exists():
        return rids
    for p in POSTED_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            if d.get("status") != "posted":
                continue
            rid = d.get("restaurant_id", "")
            if not rid or rid == "summary":
                continue
            ftype = "reel" if p.name.endswith("_reel.json") else "photo"
            rids.add(f"{rid}:{ftype}")
        except Exception:
            pass
    return rids


def pick_queue() -> Path | None:
    now = datetime.now(JST)
    posted_rids = _build_posted_rid_set()
    # *_instagram.json と *_reel.json の両方を対象にアルファベット順でソート
    files = sorted([
        *QUEUE_DIR.glob("*_instagram.json"),
        *QUEUE_DIR.glob("*_reel.json"),
    ])
    for f in files:
        try:
            # 冪等性チェック1: posted/ に同名ファイルがあればスキップ
            posted_file = POSTED_DIR / f.name
            if posted_file.exists():
                posted_data = json.loads(posted_file.read_text(encoding="utf-8-sig"))
                if posted_data.get("status") == "posted":
                    print(f"[SKIP] 投稿済み(同名ファイル): {f.name}")
                    f.unlink()
                    continue

            data = json.loads(f.read_text(encoding="utf-8-sig"))
            if data.get("platform") != "instagram" or data.get("status") != "approved":
                continue

            # 冪等性チェック2: 同一 restaurant_id で同一種別が投稿済みならスキップ
            rid = data.get("restaurant_id", "")
            if rid and rid != "summary":
                ftype = "reel" if f.name.endswith("_reel.json") else "photo"
                if f"{rid}:{ftype}" in posted_rids:
                    print(f"[SKIP] RID投稿済み(重複防止): {rid} ({f.name})")
                    f.unlink()
                    continue

            sched = data.get("scheduled_at")
            if sched:
                sched_dt = datetime.fromisoformat(sched)
                if sched_dt.tzinfo is None:
                    sched_dt = sched_dt.replace(tzinfo=JST)
                if sched_dt > now + timedelta(minutes=15):
                    continue
            return f
        except Exception as e:
            print(f"[WARN] queue file skip ({f.name}): {e}")
    return None


def main():
    POSTED_DIR.mkdir(exist_ok=True)
    qfile = pick_queue()
    if not qfile:
        print("Instagramキューが空です。")
        return

    data        = json.loads(qfile.read_text(encoding="utf-8-sig"))
    caption     = data.get("caption", "")
    media_type  = data.get("media_type", "IMAGE")
    rid         = data.get("restaurant_id", "")
    location_id = data.get("location_id") or get_location_id(rid)

    print(f"Instagram投稿: {data['restaurant_name']} ({data.get('area','')})  type={media_type}")
    if location_id:
        print(f"  位置情報: {location_id}")

    token, account_id = get_creds()

    try:
        if media_type == "REELS":
            video_url = data.get("video_url")
            if not video_url:
                raise ValueError("Reels queue に video_url がありません。create_reel.py を再実行してください。")
            print(f"  Reels video_url: {video_url[:60]}...")
            container_id = create_reel_container(token, account_id, video_url, caption)
            ok = wait_for_container(token, container_id, max_wait=120)
            if not ok:
                raise RuntimeError("Reels コンテナの処理がタイムアウトまたは失敗しました")
            post_id = publish_container(token, account_id, container_id)

        else:
            photo_urls = [normalize_url(u, crop=(i > 0)) for i, u in enumerate(data.get("photo_urls", []))]
            if len(photo_urls) == 1:
                container_id = create_media_container(
                    token, account_id, photo_urls[0], caption, location_id=location_id
                )
                wait_for_container(token, container_id)
                post_id = publish_container(token, account_id, container_id)
            else:
                children = []
                for url in photo_urls[:10]:
                    cid = create_media_container(token, account_id, url, is_carousel_item=True)
                    wait_for_container(token, cid, max_wait=30)
                    children.append(cid)
                    time.sleep(1)
                carousel_id = create_carousel_container(
                    token, account_id, children, caption, location_id=location_id
                )
                wait_for_container(token, carousel_id)
                post_id = publish_container(token, account_id, carousel_id)

        print(f"[OK] Instagram post_id={post_id}")
        data["status"]    = "posted"
        data["ig_post_id"]= post_id
        data["posted_at"] = datetime.now().isoformat()

    except Exception as e:
        print(f"[FAIL] Instagram: {e}")
        data["status"] = "failed"
        data["error"]  = str(e)

    posted_path = POSTED_DIR / qfile.name
    posted_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    qfile.unlink()
    print(f"移動: {posted_path}")


if __name__ == "__main__":
    main()
