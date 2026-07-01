"""
残りの写真を分類してclassify_cache.jsonに追記し、
既存レストランデータを保護したままrestaurants.jsonを再生成する。

実行: python scripts/analyze_remaining.py [--provider gemini|anthropic] [--limit N]
"""
import os, json, time, base64, io, argparse
from pathlib import Path
from datetime import datetime, timedelta

import pillow_heif
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
pillow_heif.register_heif_opener()

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

_photos_env = os.environ.get("PHOTOS_DIR", "")
PHOTOS_DIR   = Path(_photos_env) if _photos_env else Path(r"C:\Users\user\iCloudPhotos\Photos")
DATA_DIR     = Path(__file__).parent.parent / "data"
CACHE_FILE   = DATA_DIR / "classify_cache.json"
OUTPUT_FILE  = DATA_DIR / "restaurants.json"
BACKUP_FILE  = DATA_DIR / "restaurants_backup.json"

SAME_VISIT_HOURS = 3
CLASSIFY_PROMPT = (
    "この写真を分析してください。\n"
    "1行目: 食べ物・飲み物の写真か? yes/no のみ\n"
    "2行目: yes の場合のみ、料理名・ジャンルを日本語で15字以内で\n"
    "人物メイン・風景・書籍・製品(非食品)・文書 は no。"
)


# ── EXIF ──────────────────────────────────────────────────────────────────────

def get_exif(path: Path) -> dict:
    try:
        if path.suffix.lower() == ".heic":
            heif = pillow_heif.open_heif(str(path), convert_hdr_to_8bit=False)
            exif_bytes = heif.info.get("exif")
            if not exif_bytes:
                return {}
            from PIL.Image import Exif
            e = Exif()
            if exif_bytes[:4] != b"Exif":
                exif_bytes = b"Exif\x00\x00" + exif_bytes
            e.load(exif_bytes)
            res = {}
            for tid, val in e.items():
                if tid == 306 and "taken_at" not in res:
                    res["taken_at"] = str(val)
                elif tid == 34853:
                    gps = {GPSTAGS.get(k, k): v for k, v in e.get_ifd(34853).items()}
                    if gps: res["gps_raw"] = gps
                elif tid == 34665:
                    exif_ifd = e.get_ifd(34665)
                    if 36867 in exif_ifd:
                        res["taken_at"] = str(exif_ifd[36867])
            return res
        img = Image.open(str(path))
        raw = img._getexif()
        if not raw:
            return {}
        res = {}
        for tid, val in raw.items():
            tag = TAGS.get(tid, tid)
            if tag == "DateTimeOriginal":
                res["taken_at"] = str(val)
            elif tag == "GPSInfo":
                gps = {GPSTAGS.get(k, k): v for k, v in val.items()}
                if gps: res["gps_raw"] = gps
        return res
    except Exception:
        return {}


def parse_gps(gps: dict):
    try:
        def dms(vals, ref):
            d, m, s = float(vals[0]), float(vals[1]), float(vals[2])
            dd = d + m / 60 + s / 3600
            return -dd if ref in ("S", "W") else dd
        return {"lat": round(dms(gps["GPSLatitude"], gps.get("GPSLatitudeRef","N")), 6),
                "lon": round(dms(gps["GPSLongitude"], gps.get("GPSLongitudeRef","E")), 6)}
    except Exception:
        return None


def parse_taken_at(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


# ── 分類 ───────────────────────────────────────────────────────────────────────

def open_small(path: Path, max_px=1024) -> Image.Image:
    img = Image.open(str(path)).convert("RGB")
    w, h = img.size
    if max(w, h) > max_px:
        ratio = max_px / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    return img


def classify_gemini(path: Path, client, cache: dict) -> dict:
    key = path.name
    if key in cache:
        return cache[key]
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[open_small(path), CLASSIFY_PROMPT],
        )
        lines = resp.text.strip().splitlines()
        is_food = lines[0].strip().lower().startswith("yes")
        desc = lines[1].strip() if is_food and len(lines) > 1 else ""
        result = {"is_food": is_food, "food_desc": desc}
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            raise
        result = {"is_food": False, "food_desc": ""}
    cache[key] = result
    return result


def classify_anthropic(path: Path, client, cache: dict) -> dict:
    key = path.name
    if key in cache:
        return cache[key]
    img = open_small(path)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    img_b64 = base64.standard_b64encode(buf.getvalue()).decode()
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=60,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
            {"type": "text", "text": CLASSIFY_PROMPT},
        ]}],
    )
    lines = resp.content[0].text.strip().splitlines()
    is_food = lines[0].strip().lower().startswith("yes")
    desc = lines[1].strip() if is_food and len(lines) > 1 else ""
    result = {"is_food": is_food, "food_desc": desc}
    cache[key] = result
    return result


# ── クラスタリング & restaurants.json生成 ────────────────────────────────────────

def rebuild_restaurants(cache: dict):
    """キャッシュ済みの全写真を使い、既存データを保護しながらrestaurants.jsonを再生成"""
    # 既存データ読み込み（date+gps で照合できるよう保存）
    existing_by_date = {}
    if OUTPUT_FILE.exists():
        old = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        for r in old.get("restaurants", []):
            key = r.get("date", "")
            existing_by_date.setdefault(key, []).append(r)

    exts = {".jpg", ".jpeg", ".heic", ".png"}
    target = [f for f in PHOTOS_DIR.iterdir() if f.suffix.lower() in exts and f.name in cache]

    photos = []
    for i, f in enumerate(target, 1):
        if i % 200 == 0:
            print(f"  EXIF: {i}/{len(target)}", flush=True)
        exif = get_exif(f)
        gps = parse_gps(exif.get("gps_raw", {})) if "gps_raw" in exif else None
        taken_at = parse_taken_at(exif.get("taken_at"))
        photos.append({"filename": f.name, "path": str(f),
                        "taken_at": taken_at.isoformat() if taken_at else None, "gps": gps})
    photos.sort(key=lambda p: p["taken_at"] or "")
    print(f"  スキャン完了: {len(photos)}件")

    # 時刻クラスタリング
    clusters, current, prev_dt = [], [], None
    for p in photos:
        if not p["taken_at"]:
            clusters.append([p]); continue
        dt = datetime.fromisoformat(p["taken_at"])
        if prev_dt and (dt - prev_dt) > timedelta(hours=SAME_VISIT_HOURS):
            if current: clusters.append(current)
            current = []
        current.append(p)
        prev_dt = dt
    if current: clusters.append(current)
    print(f"  クラスター数: {len(clusters)}")

    restaurants = []
    for i, cluster in enumerate(clusters):
        food_list = [p for p in cluster if cache.get(p["filename"], {}).get("is_food")]
        postable  = [p for p in food_list if not cache.get(p["filename"], {}).get("has_person")]
        if len(food_list) < 2:
            continue
        gps = next((p["gps"] for p in cluster if p.get("gps")), None)
        date_str = cluster[0]["taken_at"][:10] if cluster[0].get("taken_at") else "unknown"

        # 既存データのマージ（date で照合し、GPSが近い or 1件のみなら採用）
        old_r = None
        candidates = existing_by_date.get(date_str, [])
        if len(candidates) == 1:
            old_r = candidates[0]
        elif len(candidates) > 1 and gps:
            # GPS距離で最近傍を選ぶ
            def dist(r):
                og = r.get("gps") or {}
                if not og:
                    return 999
                return ((og.get("lat",0)-gps["lat"])**2 + (og.get("lon",0)-gps["lon"])**2)**0.5
            old_r = min(candidates, key=dist)

        entry = {
            "id": f"r{len(restaurants)+1:04d}",
            "name": (old_r or {}).get("name", ""),
            "area": (old_r or {}).get("area", ""),
            "catchphrase": (old_r or {}).get("catchphrase", ""),
            "date": date_str,
            "gps": gps,
            "status": (old_r or {}).get("status", "pending"),
            "approved_posts": (old_r or {}).get("approved_posts", []),
            "generated_posts": (old_r or {}).get("generated_posts", {}),
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
        }
        restaurants.append(entry)

    output = {"restaurants": restaurants, "generated_at": datetime.now().isoformat()}
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    approved = sum(1 for r in restaurants if r["status"] in ("approved","posted"))
    print(f"\n保存完了: {len(restaurants)}件 (うち承認済み/投稿済み: {approved}件)")
    return restaurants


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["gemini","anthropic"], default="gemini")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rebuild-only", action="store_true", help="分類をスキップしてクラスタリングのみ実行")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    # 既存restaurants.jsonをバックアップ
    if OUTPUT_FILE.exists() and not BACKUP_FILE.exists():
        BACKUP_FILE.write_bytes(OUTPUT_FILE.read_bytes())
        print(f"バックアップ保存: {BACKUP_FILE}")

    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}

    if not args.rebuild_only:
        exts = {".jpg", ".jpeg", ".heic", ".png"}
        all_files = [f for f in PHOTOS_DIR.iterdir() if f.suffix.lower() in exts]
        uncached = [f for f in all_files if f.name not in cache]
        print(f"\n=== 食べ物分類 ({args.provider}) ===")
        print(f"  キャッシュ済み: {len(cache)} / 未処理: {len(uncached)}")

        targets = uncached[:args.limit] if args.limit else uncached

        if args.provider == "anthropic":
            import anthropic as sdk
            client = sdk.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            classify_fn = classify_anthropic
            sec_per_req = 60 / 50
        else:
            from google import genai
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            classify_fn = classify_gemini
            sec_per_req = 60 / 14

        daily = 0
        last_t = 0.0
        consecutive_fail = 0

        for idx, path in enumerate(targets, 1):
            if args.provider == "gemini" and daily >= 1490:
                print(f"\n本日の無料枠上限(1490件)に達しました。明日また実行してください。")
                print(f"進捗: {len(cache)}件処理済み / {len(uncached)}件中")
                break

            wait = sec_per_req - (time.time() - last_t)
            if wait > 0:
                time.sleep(wait)

            pct = idx / len(targets) * 100
            print(f"  [{idx}/{len(targets)} {pct:.1f}%] {path.name}", end=" ... ", flush=True)

            backoff = 30
            ok = False
            for attempt in range(4):
                try:
                    last_t = time.time()
                    result = classify_fn(path, client, cache)
                    daily += 1
                    consecutive_fail = 0
                    print(("FOOD: " + result["food_desc"]) if result["is_food"] else "skip")
                    ok = True
                    break
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower() or "overloaded" in str(e).lower():
                        print(f"\n  rate limit (試行{attempt+1}/4). {backoff}s待機...", flush=True)
                        time.sleep(backoff)
                        backoff = min(backoff * 2, 300)
                        last_t = time.time()
                    else:
                        print(f"error: {e}")
                        break

            if not ok:
                consecutive_fail += 1
                print(f"  スキップ: {path.name}")
                if consecutive_fail >= 3:
                    print(f"\n3件連続失敗: 日次クォータ枯渇の可能性。明日続きを実行してください。")
                    break

            if idx % 50 == 0:
                CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
                food_n = sum(1 for v in cache.values() if v.get("is_food"))
                print(f"  [保存] キャッシュ {len(cache)}件 (食べ物: {food_n}件)")

        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        food_total = sum(1 for v in cache.values() if v.get("is_food"))
        print(f"\n分類完了: {len(cache)}件処理済み (食べ物: {food_total}件)")

    print("\n=== クラスタリング & restaurants.json 再生成 ===")
    rebuild_restaurants(cache)


if __name__ == "__main__":
    main()
