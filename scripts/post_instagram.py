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

QUEUE_DIR          = Path(__file__).parent.parent / "queue"
IN_PROGRESS_DIR    = Path(__file__).parent.parent / "in_progress"
POSTED_DIR         = Path(__file__).parent.parent / "posted"
RESTAURANTS_JSON   = Path(__file__).parent.parent / "data" / "restaurants.json"
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


def _build_rid_set(directory: Path) -> set[str]:
    """指定ディレクトリの JSON ファイルから "rid:photo" / "rid:reel" のセットを返す。"""
    rids: set[str] = set()
    if not directory.exists():
        return rids
    for p in directory.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
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
    posted_rids     = _build_rid_set(POSTED_DIR)
    in_progress_rids = _build_rid_set(IN_PROGRESS_DIR)
    files = sorted([
        *QUEUE_DIR.glob("*_instagram.json"),
        *QUEUE_DIR.glob("*_reel.json"),
    ])
    for f in files:
        try:
            # チェック1: posted/ に同名ファイルがあればスキップ
            if (POSTED_DIR / f.name).exists():
                d = json.loads((POSTED_DIR / f.name).read_text(encoding="utf-8-sig"))
                if d.get("status") == "posted":
                    print(f"[SKIP] 投稿済み(同名): {f.name}")
                    f.unlink()
                    continue

            data = json.loads(f.read_text(encoding="utf-8-sig"))
            if data.get("platform") != "instagram" or data.get("status") != "approved":
                continue

            rid   = data.get("restaurant_id", "")
            ftype = "reel" if f.name.endswith("_reel.json") else "photo"
            key   = f"{rid}:{ftype}"

            # チェック2: 同一RIDが投稿済みならスキップ
            if rid and rid != "summary" and key in posted_rids:
                print(f"[SKIP] RID投稿済み: {rid} ({f.name})")
                f.unlink()
                continue

            # チェック3: 同一RIDが処理中(in_progress)ならスキップ
            if rid and rid != "summary" and key in in_progress_rids:
                print(f"[SKIP] RID処理中(in_progress): {rid} ({f.name})")
                continue  # 削除しない

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


def _call_instagram_api(data: dict) -> str:
    """Instagram API を呼び出して post_id を返す。失敗時は例外を raise。"""
    token, account_id = get_creds()
    caption     = data.get("caption", "")
    media_type  = data.get("media_type", "IMAGE")
    rid         = data.get("restaurant_id", "")
    location_id = data.get("location_id") or get_location_id(rid)

    print(f"Instagram投稿: {data['restaurant_name']} ({data.get('area','')})  type={media_type}")

    if media_type == "REELS":
        video_url = data.get("video_url")
        if not video_url:
            raise ValueError("Reels queue に video_url がありません。")
        container_id = create_reel_container(token, account_id, video_url, caption)
        if not wait_for_container(token, container_id, max_wait=120):
            raise RuntimeError("Reels コンテナの処理がタイムアウトしました")
        return publish_container(token, account_id, container_id)

    photo_urls = [normalize_url(u, crop=(i > 0)) for i, u in enumerate(data.get("photo_urls", []))]
    if len(photo_urls) == 1:
        cid = create_media_container(token, account_id, photo_urls[0], caption, location_id=location_id)
        wait_for_container(token, cid)
        return publish_container(token, account_id, cid)

    children = []
    for url in photo_urls[:10]:
        cid = create_media_container(token, account_id, url, is_carousel_item=True)
        wait_for_container(token, cid, max_wait=30)
        children.append(cid)
        time.sleep(1)
    carousel_id = create_carousel_container(token, account_id, children, caption, location_id=location_id)
    wait_for_container(token, carousel_id)
    return publish_container(token, account_id, carousel_id)


def phase1_lock() -> bool:
    """
    Phase 1: queue/ から1件選び in_progress/ に移動する。
    in_progress/ に ig_post_id 付きのファイルがあれば recovery モード（phase2b のみ必要）。
    戻り値: 処理対象があれば True、なければ False。
    """
    IN_PROGRESS_DIR.mkdir(exist_ok=True)
    POSTED_DIR.mkdir(exist_ok=True)

    # recovery チェック: in_progress に ig_post_id 付きファイルがあれば phase2b に任せる
    for p in IN_PROGRESS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            if d.get("ig_post_id"):
                print(f"[RECOVERY] ig_post_id あり。phase2b でクリーンアップ: {p.name}")
                return True  # phase1 はスキップ、ファイルはそのまま
        except Exception:
            pass

    qfile = pick_queue()
    if not qfile:
        print("キューが空です。")
        return False

    data = json.loads(qfile.read_text(encoding="utf-8-sig"))
    data["locked_at"] = datetime.now(JST).isoformat()
    ip_path = IN_PROGRESS_DIR / qfile.name
    ip_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    qfile.unlink()
    print(f"[Phase1] ロック: {ip_path.name}")
    return True


def phase2a_post():
    """
    Phase 2a: in_progress/ のファイルに Instagram API 呼び出し結果 (ig_post_id) を書き込む。
    ig_post_id が既にあれば API 呼び出しをスキップ（recovery）。
    """
    files = sorted([*IN_PROGRESS_DIR.glob("*_instagram.json"), *IN_PROGRESS_DIR.glob("*_reel.json")])
    if not files:
        print("[Phase2a] in_progress ファイルなし。スキップ。")
        return

    ip_path = files[0]
    data = json.loads(ip_path.read_text(encoding="utf-8-sig"))

    if data.get("ig_post_id"):
        print(f"[Phase2a] ig_post_id 既存。API 呼び出しスキップ: {data['ig_post_id']}")
        return

    try:
        post_id = _call_instagram_api(data)
        print(f"[OK] post_id={post_id}")
        data["status"]     = "posted"
        data["ig_post_id"] = post_id
        data["posted_at"]  = datetime.now(JST).isoformat()
    except Exception as e:
        print(f"[FAIL] Instagram API: {e}")
        data["status"] = "failed"
        data["error"]  = str(e)

    # ig_post_id を in_progress/ に書き戻す（この後 workflow が commit+push する）
    ip_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Phase2a] ig_post_id を in_progress に記録: {ip_path.name}")


def phase2b_cleanup():
    """
    Phase 2b: in_progress/ → posted/ に移動してクリーンアップ。
    """
    files = sorted([*IN_PROGRESS_DIR.glob("*_instagram.json"), *IN_PROGRESS_DIR.glob("*_reel.json")])
    if not files:
        print("[Phase2b] in_progress ファイルなし。スキップ。")
        return

    ip_path = files[0]
    data = json.loads(ip_path.read_text(encoding="utf-8-sig"))
    posted_path = POSTED_DIR / ip_path.name
    posted_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    ip_path.unlink()
    print(f"[Phase2b] 完了: {posted_path.name}  status={data.get('status')}")


if __name__ == "__main__":
    import sys
    phase = next((a for a in sys.argv[1:] if a.startswith("--phase")), None)

    if phase == "--phase1":
        ok = phase1_lock()
        sys.exit(0 if ok else 0)   # キュー空でも exit 0（workflow は staged 有無で判断）
    elif phase == "--phase2a":
        phase2a_post()
    elif phase == "--phase2b":
        phase2b_cleanup()
    else:
        # ローカル実行用: 3フェーズを順番に実行
        IN_PROGRESS_DIR.mkdir(exist_ok=True)
        POSTED_DIR.mkdir(exist_ok=True)
        if phase1_lock():
            phase2a_post()
            phase2b_cleanup()
