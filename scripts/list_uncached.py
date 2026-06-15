import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PHOTOS_DIR = Path(r"C:\Users\user\iCloudPhotos\Photos")
CACHE_FILE  = Path(r"C:\Users\user\Documents\gourmet-sns\data\classify_cache.json")
OUT_FILE    = Path(r"C:\Users\user\Documents\gourmet-sns\data\uncached_files.json")

cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
exts  = {".jpg", ".jpeg", ".heic", ".png"}
all_files   = sorted([f.name for f in PHOTOS_DIR.iterdir() if f.suffix.lower() in exts])
uncached    = [f for f in all_files if f not in cache]

OUT_FILE.write_text(json.dumps(uncached, ensure_ascii=False), encoding="utf-8")
print(f"全体: {len(all_files)}枚 / 処理済み: {len(cache)}枚 / 残り: {len(uncached)}枚")
print(f"リスト保存: {OUT_FILE}")
