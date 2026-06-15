"""キャッシュに分類結果をバッチ書き込みするユーティリティ"""
import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CACHE_FILE = Path(r"C:\Users\user\Documents\gourmet-sns\data\classify_cache.json")

def merge(new_entries: dict):
    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    before = len(cache)
    cache.update(new_entries)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    added = len(cache) - before
    food = sum(1 for v in cache.values() if v.get("is_food"))
    print(f"追加: {added}件 / 合計: {len(cache)}件 (食べ物: {food}件)")

if __name__ == "__main__":
    # コマンドライン引数からJSONファイルを読み込む
    if len(sys.argv) > 1:
        data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        merge(data)
