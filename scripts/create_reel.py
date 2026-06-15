"""
Reels 生成スクリプト (Task 7)
posted/ の photo_urls (Cloudinary) から写真をダウンロードし
ffmpeg でスライドショー動画を生成し、Cloudinary にアップロードして
Instagram キューに追加する。
"""
import json
import os
import sys
import subprocess
import hashlib
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

JST       = timezone(timedelta(hours=9))
REPO_ROOT = Path(__file__).parent.parent
REEL_DIR  = REPO_ROOT / 'data' / 'reels'
QUEUE_DIR = REPO_ROOT / 'queue'
POSTED_DIR= REPO_ROOT / 'posted'

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY    = os.environ.get("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "")

REEL_HASHTAGS = (
    "#グルメ #東京グルメ #居酒屋 #飯テロ #グルメスタグラム "
    "#グルメ好きな人と繋がりたい #居酒屋巡り #飲み歩き #おすすめグルメ "
    "#食スタグラム #グルメ部 #酒と飯ぐるめ #食べ歩き #東京居酒屋 "
    "#グルメ動画 #reels #instagramreels #グルメリール"
)

SLIDE_DURATION = 3
WIDTH, HEIGHT  = 720, 1280
FPS            = 30


def find_posted(restaurant_id: str) -> dict | None:
    for fname in sorted(os.listdir(POSTED_DIR), reverse=True):
        if restaurant_id in fname and fname.endswith('.json'):
            return json.load(open(os.path.join(POSTED_DIR, fname), encoding='utf-8'))
    return None


def to_jpeg_url(url: str) -> str:
    """Cloudinary URL を JPEG 強制取得に変換（HEIC 対策）"""
    import re
    url = re.sub(r'(/upload/)(v\d+/)', r'\1f_jpg/\2', url)
    url = re.sub(r'\.(heic|HEIC)$', '.jpg', url)
    return url


def download_photos(urls: list[str], tmpdir: str) -> list[str]:
    paths = []
    for i, url in enumerate(urls):
        url  = to_jpeg_url(url)
        dest = os.path.join(tmpdir, f'photo_{i:02d}.jpg')
        print(f"  ダウンロード中 ({i+1}/{len(urls)}): {url[-50:]}")
        urllib.request.urlretrieve(url, dest)
        paths.append(dest)
    return paths


def build_reel(photos: list[str], output_path: str) -> bool:
    if not photos:
        print("写真が見つかりません")
        return False

    concat_txt = output_path + '_concat.txt'
    with open(concat_txt, 'w', encoding='utf-8') as f:
        for p in photos:
            f.write(f"file '{p}'\n")
            f.write(f"duration {SLIDE_DURATION}\n")
        f.write(f"file '{photos[-1]}'\n")

    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS}"
    )
    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0', '-i', concat_txt,
        '-vf', vf,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-pix_fmt', 'yuv420p',
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        os.remove(concat_txt)
    except Exception:
        pass
    if result.returncode != 0:
        print("ffmpeg エラー:", result.stderr[-800:])
        Path(output_path).unlink(missing_ok=True)
        return False
    return True


def upload_to_cloudinary(video_path: str) -> str:
    """動画を Cloudinary にアップロードし、secure_url を返す。"""
    import requests as req
    timestamp = int(time.time())
    folder = "gourmet/reels"
    params_to_sign = f"folder={folder}&timestamp={timestamp}"
    sig = hashlib.sha1(f"{params_to_sign}{CLOUDINARY_API_SECRET}".encode()).hexdigest()

    print(f"  Cloudinary アップロード中: {os.path.basename(video_path)} ...")
    with open(video_path, 'rb') as f:
        resp = req.post(
            f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/video/upload",
            data={
                "api_key": CLOUDINARY_API_KEY,
                "timestamp": timestamp,
                "signature": sig,
                "folder": folder,
            },
            files={"file": f},
            timeout=120,
        )
    if not resp.ok:
        raise RuntimeError(f"Cloudinary upload failed: {resp.status_code} {resp.text[:200]}")
    url = resp.json()["secure_url"]
    print(f"  アップロード完了: {url}")
    return url


def enqueue_reel(video_url: str, caption: str, restaurant_id: str, restaurant_name: str, area: str = "東京"):
    now       = datetime.now(JST)
    item_id   = now.strftime('%Y%m%d_%H%M%S') + f'_{restaurant_id}_reel'
    # 13:00 固定。当日 13:00 をすでに過ぎていれば翌日 13:00
    post_time = now.replace(hour=13, minute=0, second=0, microsecond=0)
    if now >= post_time:
        post_time += timedelta(days=1)
    item = {
        "id": item_id,
        "platform": "instagram",
        "media_type": "REELS",
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_name,
        "area": area,
        "video_url": video_url,
        "video_path": "",
        "photo_urls": [],
        "caption": caption,
        "status": "approved",
        "created_at": now.isoformat(),
        "scheduled_at": post_time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    path = QUEUE_DIR / (item_id + '.json')
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"キューに追加: {path}")
    print(f"投稿予定: {item['scheduled_at']}")


if __name__ == '__main__':
    restaurant_id = sys.argv[1] if len(sys.argv) > 1 else 'r0001'
    print(f"Reels 生成: {restaurant_id}")

    posted = find_posted(restaurant_id)
    if not posted:
        print(f"posted/ に {restaurant_id} のデータが見つかりません")
        sys.exit(1)

    urls  = posted.get('photo_urls', [])
    rname = posted.get('restaurant_name', restaurant_id)
    area  = posted.get('area', '東京')
    if not urls:
        print("photo_urls が空です")
        sys.exit(1)

    print(f"店名: {rname} / 写真: {len(urls)} 枚")
    REEL_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        photos = download_photos(urls, tmpdir)
        out_path = str(REEL_DIR / f"{restaurant_id}_{datetime.now(JST).strftime('%Y%m%d_%H%M%S')}.mp4")
        print(f"動画生成中 → {out_path}")
        ok = build_reel(photos, out_path)

    if not ok:
        sys.exit(1)

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"動画生成完了: {out_path} ({size_mb:.1f} MB)")

    video_url = upload_to_cloudinary(out_path)

    caption = (
        f"🎬 {rname} のおすすめメニューをまとめました。\n"
        "保存して飲み会の参考に。\n\n"
        "ーーーーー\n\n"
        f"{REEL_HASHTAGS}"
    )
    enqueue_reel(video_url, caption, restaurant_id, rname, area)
