"""
写真21-200をJPEGに変換してtmp_classify/に保存するスクリプト
"""
import os
import json
from pathlib import Path
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

PHOTOS_DIR = r"C:\Users\user\iCloudPhotos\Photos"
DATA_DIR = Path(__file__).parent.parent / "data"
TMP_DIR = DATA_DIR / "tmp_classify"
CACHE_FILE = DATA_DIR / "classify_cache.json"

START = 20   # 0-indexed (skip first 20 already done)
END   = 200  # exclusive

TMP_DIR.mkdir(exist_ok=True)

# Load existing cache
cache = {}
if CACHE_FILE.exists():
    with open(CACHE_FILE, encoding="utf-8") as f:
        cache = json.load(f)

EXTS = {".jpg", ".jpeg", ".heic", ".png"}
all_photos = sorted([
    p for p in Path(PHOTOS_DIR).iterdir()
    if p.suffix.lower() in EXTS
], key=lambda p: p.name)

target = all_photos[START:END]
print(f"対象: {len(target)} 枚 (index {START}-{END-1})")

batch = []
skipped_cached = 0
for i, p in enumerate(target):
    key = p.name
    if key in cache:
        skipped_cached += 1
        continue
    tmp_path = TMP_DIR / (p.stem + ".jpg")
    if not tmp_path.exists():
        try:
            img = Image.open(str(p))
            img.thumbnail((800, 800))
            img = img.convert("RGB")
            img.save(str(tmp_path), "JPEG", quality=80)
        except Exception as e:
            print(f"  変換失敗 {p.name}: {e}")
            continue
    batch.append({"filename": key, "tmp": str(tmp_path.relative_to(DATA_DIR.parent))})
    if (i + 1) % 20 == 0:
        print(f"  変換済み: {i+1}/{len(target)}")

batch_file = DATA_DIR / "tmp_batch2.json"
with open(batch_file, "w", encoding="utf-8") as f:
    json.dump(batch, f, ensure_ascii=False, indent=2)

print(f"\n完了: {len(batch)} 枚変換 ({skipped_cached} 枚キャッシュ済みスキップ)")
print(f"バッチファイル: {batch_file}")
