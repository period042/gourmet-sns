"""
classify_cache.json の分類済み写真を使ってクラスタリング・restaurants.json 生成
Phase 2 (API分類) をスキップし、キャッシュ済みデータだけで Phase 3+ を実行する
"""
import os, json, time, requests
from pathlib import Path
from datetime import datetime, timedelta

PHOTOS_DIR = r"C:\Users\user\iCloudPhotos\Photos"
DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "classify_cache.json"
OUTPUT_FILE = DATA_DIR / "restaurants.json"
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
SAME_VISIT_HOURS = 3


def get_exif_basic(path: str) -> dict:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    import pillow_heif
    pillow_heif.register_heif_opener()
    ext = Path(path).suffix.lower()
    if ext == ".heic":
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
            EXIF_IFD_TAG, GPS_TAG_ID, DT_ORIG_TAG, DT_TAG = 34665, 34853, 36867, 306
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
    try:
        img = Image.open(path)
        raw = img._getexif()
        if not raw:
            return {}
        result = {}
        for tag_id, val in raw.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "GPSInfo":
                gps = {}
                for k, v in val.items():
                    gps[GPSTAGS.get(k, k)] = v
                result["gps_raw"] = gps
            elif tag == "DateTimeOriginal":
                result["taken_at"] = val
        return result
    except Exception:
        return {}


def parse_gps(gps: dict):
    try:
        def to_deg(val):
            d, m, s = val
            return float(d) + float(m)/60 + float(s)/3600
        lat = to_deg(gps["GPSLatitude"])
        lon = to_deg(gps["GPSLongitude"])
        if gps.get("GPSLatitudeRef") == "S": lat = -lat
        if gps.get("GPSLongitudeRef") == "W": lon = -lon
        return {"lat": lat, "lon": lon}
    except Exception:
        return None


def parse_taken_at(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def date_from_filename(fname: str):
    """Extract date from iCloud filenames like '*.YYMMDDHT.jpg' where YYMMDD=date HH=hour."""
    import re
    stem = Path(fname).stem
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
        s = parts[1]
        try:
            return datetime.strptime(f"20{s[:2]}-{s[2:4]}-{s[4:6]} {s[6:8]}:00:00",
                                     "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return None


def nearby_restaurant(lat, lon):
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
            return {"name": top.get("name",""), "vicinity": top.get("vicinity",""),
                    "place_id": top.get("place_id",""), "rating": top.get("rating")}
    except Exception as e:
        print(f"  [warn] Maps: {e}")
    return {}


def _check_existing_edits() -> list[str]:
    """既存 restaurants.json に手動編集済みエントリがあれば警告リストを返す"""
    if not OUTPUT_FILE.exists():
        return []
    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except Exception:
        return []
    warnings = []
    for r in existing.get("restaurants", []):
        reasons = []
        if r.get("name"):
            reasons.append(f"name={r['name']!r}")
        if r.get("status") not in ("pending", "", None):
            reasons.append(f"status={r['status']!r}")
        if r.get("catchphrase"):
            reasons.append("catchphrase設定済み")
        if r.get("approved_posts"):
            reasons.append("approved_posts設定済み")
        if reasons:
            warnings.append(f"  {r['id']} ({', '.join(reasons)})")
    return warnings


def main():
    import sys as _sys
    DATA_DIR.mkdir(exist_ok=True)

    # 上書き保護: 既存データに手動編集済みエントリがあれば --force なしに実行を止める
    force = "--force" in _sys.argv
    edits = _check_existing_edits()
    if edits and not force:
        print("ERROR: restaurants.json に手動編集済みエントリがあります。上書きすると分割・承認データが消えます。")
        print("  対象エントリ:")
        for w in edits:
            print(w)
        print("\n強制上書きする場合は --force を付けて実行してください。")
        _sys.exit(1)

    # Load cache
    if not CACHE_FILE.exists():
        print("ERROR: classify_cache.json が見つかりません")
        return
    with open(CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)
    food_set = {k for k, v in cache.items() if v.get("is_food")}
    print(f"キャッシュ読込: {len(cache)}件 (うちFOOD: {len(food_set)}件)")

    # Phase 1: scan only cached photos
    print("\n=== Phase 1: 写真スキャン (キャッシュ対象のみ) ===")
    exts = {".jpg", ".jpeg", ".heic", ".png"}
    all_files = [f for f in os.listdir(PHOTOS_DIR) if Path(f).suffix.lower() in exts]
    # Only process files that are in the cache
    target_files = [f for f in all_files if f in cache]
    print(f"  キャッシュ対象: {len(target_files)}件 / 全体: {len(all_files)}件")

    photos = []
    for i, fname in enumerate(target_files, 1):
        if i % 50 == 0:
            print(f"  EXIF: {i}/{len(target_files)}", flush=True)
        full = os.path.join(PHOTOS_DIR, fname)
        exif = get_exif_basic(full)
        gps = parse_gps(exif.get("gps_raw", {})) if "gps_raw" in exif else None
        taken_at = parse_taken_at(exif.get("taken_at")) or date_from_filename(fname)
        photos.append({
            "filename": fname,
            "path": full,
            "taken_at": taken_at.isoformat() if taken_at else None,
            "gps": gps,
        })
    photos.sort(key=lambda p: p["taken_at"] or "")
    print(f"  スキャン完了: {len(photos)}件")

    # Phase 3: cluster by time
    print("\n=== Phase 3: 時系列クラスタリング ===")
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
    print(f"  クラスター数: {len(clusters)}")

    # Phase 4: build restaurants
    print("\n=== Phase 4: レストランデータ生成 ===")
    restaurants = []
    for i, cluster in enumerate(clusters):
        food_list = [p for p in cluster if cache.get(p["filename"], {}).get("is_food")]
        # 人物写真は投稿候補から除外
        postable = [p for p in food_list if not cache.get(p["filename"], {}).get("has_person")]
        if len(postable) < 2:
            continue
        gps = next((p["gps"] for p in cluster if p.get("gps")), None)
        maps_result = {}
        if gps:
            maps_result = nearby_restaurant(gps["lat"], gps["lon"])
            time.sleep(0.2)
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
                 "is_food": cache.get(p["filename"], {}).get("is_food", False),
                 "food_desc": cache.get(p["filename"], {}).get("food_desc", "")}
                for p in cluster
            ],
            "food_photos": [
                {"filename": p["filename"], "path": p["path"], "taken_at": p["taken_at"],
                 "food_desc": cache.get(p["filename"], {}).get("food_desc", ""),
                 "has_person": cache.get(p["filename"], {}).get("has_person", False)}
                for p in food_list
            ],
            "postable_photos": [
                {"filename": p["filename"], "path": p["path"], "taken_at": p["taken_at"],
                 "food_desc": cache.get(p["filename"], {}).get("food_desc", "")}
                for p in postable
            ],
            "status": "pending",
            "approved_posts": [],
        })

    print(f"  レストラン候補: {len(restaurants)}件")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"restaurants": restaurants, "generated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
    print(f"\n保存完了: {OUTPUT_FILE}")
    print("\n=== 結果サマリー ===")
    for r in restaurants:
        name = r['name'] or '(店名未取得)'
        print(f"  {r['date']} | {name} | 食べ物写真: {len(r['food_photos'])}枚")


if __name__ == "__main__":
    main()
