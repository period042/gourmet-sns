"""
分類用サムネイル生成（256KB以下になるよう圧縮）
出力先: data/thumbs/<filename>.jpg
"""
import json, sys
from pathlib import Path
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()
sys.stdout.reconfigure(encoding="utf-8")

PHOTOS_DIR = Path(r"C:\Users\user\iCloudPhotos\Photos")
CACHE_FILE  = Path(r"C:\Users\user\Documents\gourmet-sns\data\classify_cache.json")
THUMB_DIR   = Path(r"C:\Users\user\Documents\gourmet-sns\data\thumbs")
THUMB_DIR.mkdir(exist_ok=True)

cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
exts  = {".jpg", ".jpeg", ".heic", ".png"}
all_files = sorted([f for f in PHOTOS_DIR.iterdir() if f.suffix.lower() in exts])
uncached  = [f for f in all_files if f.name not in cache]

print(f"サムネイル生成: {len(uncached)}枚")
errors = 0
for i, src in enumerate(uncached, 1):
    dst = THUMB_DIR / (src.stem + ".jpg")
    if dst.exists():
        continue
    try:
        img = Image.open(str(src)).convert("RGB")
        img.thumbnail((400, 400), Image.LANCZOS)
        img.save(str(dst), "JPEG", quality=65)
        if i % 200 == 0 or i == len(uncached):
            print(f"  {i}/{len(uncached)}", flush=True)
    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  [err] {src.name}: {e}")

done = len(list(THUMB_DIR.glob("*.jpg")))
print(f"完了: {done}枚のサムネイル生成済み")
