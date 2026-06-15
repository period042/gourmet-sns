"""
Phase 1: 写真スキャン・食べ物分類・レストランクラスタリング・GPS逆ジオコーディング

実行: python scripts/analyze_photos.py
結果: data/restaurants.json に保存

Gemini 1.5 Flash 無料枠: 1,500リクエスト/日, 15リクエスト/分
全7,600枚を処理するには約5日かかります（分割実行可）
"""
import os
import json
import time
import argparse
import base64
from datetime import datetime, timedelta
from pathlib import Path
import requests
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import io
import pillow_heif

pillow_heif.register_heif_opener()

PHOTOS_DIR = r"C:\Users\user\iCloudPhotos\Photos"
DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "classify_cache.json"
OUTPUT_FILE = DATA_DIR / "restaurants.json"

GEMINI_API_KEY      = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

SAME_VISIT_HOURS = 3

CLASSIFY_PROMPT = (
    "この写真を分析してください。\n"
    "1行目: 食べ物・飲み物の写真か? yes/no のみ\n"
    "2行目: yes の場合のみ、料理名・ジャンルを日本語で15字以内で\n"
    "人物メイン・風景・書籍・製品(非食品)・文書 は no。"
)


def get_exif(path: str) -> dict:
    ext = Path(path).suffix.lower()
    try:
        if ext == ".heic":
            return _get_exif_heic(path)
        img = Image.open(path)
        raw = img._getexif()
        if not raw:
            return {}
        return _parse_exif_dict(raw)
    except Exception:
        return {}


def _get_exif_heic(path: str) -> dict:
    try:
        heif = pillow_heif.open_heif(path, convert_hdr_to_8bit=False)
        exif_bytes = heif.info.get("exif")
        if not exif_bytes:
            return {}
        from PIL.Image import Exif
        e = Exif()
        if exif_bytes[:4] != b"Exif":
            exif_bytes = b"Exif\x00\x00" + exif_bytes
        e.load(exif_bytes)

        EXIF_IFD_TAG = 34665
        GPS_TAG_ID   = 34853
        DT_ORIG_TAG  = 36867
        DT_TAG       = 306

        result = {}
        for tag_id, value in e.items():
            if tag_id == DT_TAG and "taken_at" not in result:
                result["taken_at"] = str(value)
            elif tag_id == GPS_TAG_ID:
                gps_ifd = e.get_ifd(GPS_TAG_ID)
                gps = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
                if gps:
                    result["gps_raw"] = gps
            elif tag_id == EXIF_IFD_TAG:
                exif_ifd = e.get_ifd(EXIF_IFD_TAG)
                if DT_ORIG_TAG in exif_ifd:
                    result["taken_at"] = str(exif_ifd[DT_ORIG_TAG])
        return result
    except Exception:
        return {}


def _parse_exif_dict(raw: dict) -> dict:
    result = {}
    for tag_id, value in raw.items():
        tag = TAGS.get(tag_id, tag_id)
        if tag == "DateTimeOriginal":
            result["taken_at"] = str(value)
        elif tag == "GPSInfo":
            gps = {}
            try:
                for k, v in value.items():
                    gps[GPSTAGS.get(k, k)] = v
            except Exception:
                pass
            if gps:
                result["gps_raw"] = gps
    return result


def parse_gps(gps_raw: dict) -> dict | None:
    try:
        def dms(vals, ref):
            d, m, s = float(vals[0]), float(vals[1]), float(vals[2])
            dd = d + m / 60 + s / 3600
            return -dd if ref in ("S", "W") else dd
        lat = dms(gps_raw["GPSLatitude"], gps_raw.get("GPSLatitudeRef", "N"))
        lon = dms(gps_raw["GPSLongitude"], gps_raw.get("GPSLongitudeRef", "E"))
        return {"lat": round(lat, 6), "lon": round(lon, 6)}
    except Exception:
        return None


def parse_taken_at(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def open_as_pil(path: str, max_px: int = 1024) -> Image.Image:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_px:
        ratio = max_px / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    return img


def classify_photo(path: str, client, cache: dict) -> dict:
    """Gemini API で分類"""
    key = os.path.basename(path)
    if key in cache:
        return cache[key]

    try:
        img = open_as_pil(path)
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[img, CLASSIFY_PROMPT],
        )
        lines = resp.text.strip().splitlines()
        is_food = lines[0].strip().lower().startswith("yes")
        desc = lines[1].strip() if is_food and len(lines) > 1 else ""
        result = {"is_food": is_food, "food_desc": desc}
    except Exception as e:
        err = str(e)
        if "429" in err or "quota" in err.lower():
            raise
        print(f"  [warn] classify failed: {e}")
        result = {"is_food": False, "food_desc": ""}

    cache[key] = result
    return result


def classify_photo_anthropic(path: str, client, cache: dict) -> dict:
    """Anthropic Claude Haiku で分類"""
    key = os.path.basename(path)
    if key in cache:
        return cache[key]

    img = open_as_pil(path)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    img_b64 = base64.standard_b64encode(buf.getvalue()).decode()

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=60,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                {"type": "text", "text": CLASSIFY_PROMPT},
            ],
        }],
    )
    lines = resp.content[0].text.strip().splitlines()
    is_food = lines[0].strip().lower().startswith("yes")
    desc = lines[1].strip() if is_food and len(lines) > 1 else ""
    result = {"is_food": is_food, "food_desc": desc}

    cache[key] = result
    return result


def nearby_restaurant(lat: float, lon: float) -> dict:
    if not GOOGLE_MAPS_API_KEY:
        return {}
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {"location": f"{lat},{lon}", "radius": 100,
              "type": "restaurant", "language": "ja", "key": GOOGLE_MAPS_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("results"):
            top = data["results"][0]
            return {"name": top.get("name", ""), "vicinity": top.get("vicinity", ""),
                    "place_id": top.get("place_id", ""), "rating": top.get("rating")}
    except Exception as e:
        print(f"  [warn] Google Maps: {e}")
    return {}


def scan_photos() -> list[dict]:
    exts = {".jpg", ".jpeg", ".heic", ".png", ".dng"}
    all_files = [f for f in os.listdir(PHOTOS_DIR) if Path(f).suffix.lower() in exts]
    total = len(all_files)
    photos = []
    for i, fname in enumerate(all_files, 1):
        if i % 200 == 0 or i == total:
            print(f"  EXIFスキャン: {i}/{total}", flush=True)
        full = os.path.join(PHOTOS_DIR, fname)
        exif = get_exif(full)
        gps = parse_gps(exif.get("gps_raw", {})) if "gps_raw" in exif else None
        taken_at = parse_taken_at(exif.get("taken_at"))
        photos.append({
            "filename": fname,
            "path": full,
            "taken_at": taken_at.isoformat() if taken_at else None,
            "gps": gps,
        })
    photos.sort(key=lambda p: p["taken_at"] or "")
    return photos


def cluster_by_time(photos: list[dict]) -> list[list[dict]]:
    clusters, current, prev_dt = [], [], None
    for p in photos:
        if not p["taken_at"]:
            clusters.append([p])
            continue
        dt = datetime.fromisoformat(p["taken_at"])
        if prev_dt and (dt - prev_dt) > timedelta(hours=SAME_VISIT_HOURS):
            if current:
                clusters.append(current)
            current = []
        current.append(p)
        prev_dt = dt
    if current:
        clusters.append(current)
    return clusters


def build_restaurants(clusters, food_photos) -> list[dict]:
    restaurants = []
    for i, cluster in enumerate(clusters):
        food_list = [p for p in cluster if food_photos.get(p["filename"], {}).get("is_food")]
        if len(food_list) < 2:
            continue
        gps = next((p["gps"] for p in cluster if p.get("gps")), None)
        maps_result = nearby_restaurant(gps["lat"], gps["lon"]) if gps else {}
        date_str = cluster[0]["taken_at"][:10] if cluster[0].get("taken_at") else "unknown"
        restaurants.append({
            "id": f"r{i+1:04d}",
            "name": maps_result.get("name", ""),
            "area": maps_result.get("vicinity", ""),
            "date": date_str,
            "gps": gps,
            "google_maps": maps_result,
            "all_photos": [
                {"filename": p["filename"], "path": p["path"], "taken_at": p["taken_at"],
                 "gps": p.get("gps"),
                 "is_food": food_photos.get(p["filename"], {}).get("is_food", False),
                 "food_desc": food_photos.get(p["filename"], {}).get("food_desc", "")}
                for p in cluster
            ],
            "food_photos": [
                {"filename": p["filename"], "path": p["path"], "taken_at": p["taken_at"],
                 "food_desc": food_photos.get(p["filename"], {}).get("food_desc", "")}
                for p in food_list
            ],
            "status": "pending",
            "approved_posts": [],
        })
    return restaurants


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="処理する写真数の上限")
    parser.add_argument("--provider", choices=["gemini", "anthropic"], default="gemini")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    print("=== Phase 1: 写真スキャン ===")
    photos = scan_photos()
    print(f"  {len(photos)} 枚の画像を検出")

    provider_label = "Claude Haiku 4.5 (Anthropic)" if args.provider == "anthropic" else "Gemini 2.5 Flash Lite"
    print(f"\n=== Phase 2: 食べ物分類 ({provider_label}) ===")

    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    uncached = [p for p in photos if p["filename"] not in cache]
    print(f"  キャッシュ済み: {len(cache)} 枚 / 未処理: {len(uncached)} 枚")
    remaining = uncached
    if args.limit:
        remaining = remaining[:args.limit]
        print(f"  サンプルモード: {args.limit} 枚に制限")

    if args.provider == "anthropic":
        import anthropic as anthropic_sdk
        client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
        classify_fn = classify_photo_anthropic
        seconds_per_req = 60 / 50  # 50 RPM (Haiku paid tier)
    else:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        classify_fn = classify_photo
        seconds_per_req = 60 / 14  # 14 RPM (Gemini free tier)

    food_photos = {k: v for k, v in cache.items()}
    daily_count = 0
    last_req_time = 0.0
    consecutive_failures = 0  # 連続429失敗数 (日次クォータ枯渇検知用)

    for idx, p in enumerate(remaining, 1):
        if args.provider == "gemini" and daily_count >= 1490:
            print(f"\n  本日の無料枠上限に達しました。明日続きを実行してください。")
            break

        # リクエスト間隔を確保 (last_req_time基準)
        wait = seconds_per_req - (time.time() - last_req_time)
        if wait > 0:
            time.sleep(wait)

        print(f"  [{idx}/{len(remaining)}] {p['filename']}", end=" ... ", flush=True)

        # 429時は指数バックオフでリトライ (最大4回: 30→60→120→240s)
        backoff = 30
        succeeded = False
        for attempt in range(4):
            try:
                last_req_time = time.time()
                result = classify_fn(p["path"], client, cache)
                food_photos[p["filename"]] = result
                daily_count += 1
                consecutive_failures = 0
                label = ("FOOD: " + result["food_desc"]) if result["is_food"] else "skip"
                print(label)
                succeeded = True
                break
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower() or "overloaded" in str(e).lower():
                    print(f"\n  rate limit (試行{attempt+1}/4). {backoff}s 待機...", flush=True)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 300)
                    last_req_time = time.time()
                else:
                    print(f"error: {e}")
                    break

        if not succeeded:
            consecutive_failures += 1
            print(f"  スキップ ({p['filename']})")
            if consecutive_failures >= 3:
                print(f"\n  3件連続で失敗: 本日の日次クォータが枯渇しました。明日続きを実行してください。")
                break

        if idx % 50 == 0:
            CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [進捗保存: キャッシュ {len(cache)}件]")

    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    food_count = sum(1 for v in food_photos.values() if v.get("is_food"))
    print(f"\n  食べ物写真: {food_count} / {len(food_photos)} (処理済み)")

    print("\n=== Phase 3: 時刻ベースクラスタリング ===")
    clusters = cluster_by_time(photos)
    print(f"  {len(clusters)} クラスタ生成")

    print("\n=== Phase 4: レストラン候補構築 ===")
    restaurants = build_restaurants(clusters, food_photos)
    print(f"  {len(restaurants)} 店舗候補")

    # 既存データとマージ
    existing = {}
    if OUTPUT_FILE.exists():
        for r in json.loads(OUTPUT_FILE.read_text(encoding="utf-8")).get("restaurants", []):
            existing[r["id"]] = r
    for r in restaurants:
        if r["id"] in existing:
            old = existing[r["id"]]
            if old.get("name"):
                r["name"] = old["name"]
            if old.get("area"):
                r["area"] = old["area"]
            r["status"] = old.get("status", "pending")
            r["approved_posts"] = old.get("approved_posts", [])

    output = {
        "generated_at": datetime.now().isoformat(),
        "total_photos": len(photos),
        "food_photos": food_count,
        "restaurants": restaurants,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 完了: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
