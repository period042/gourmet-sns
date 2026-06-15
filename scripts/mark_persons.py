"""classify_cache.json に has_person フラグを書き込む"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "classify_cache.json"

HAS_PERSON = {
    "20260425_021211273_iOS.jpg",
    "20260425_021215374_iOS.jpg",
    "20260425_083428130_iOS.jpg",
    "20260425_083438745_iOS.jpg",
    "34a8794be39e730d79e520d340aa0492.jpeg",
    "4920518599655229884.14d3352d19027818e86e73a5f5b4724f.23082722.jpg",
    "4920518599655229884.305db0a46cd403999c187f5fdbeb333b.23082713.jpg",
    "4920518599655229884.4af7cca33f9fe57712e8ec37144c5517.23082713.jpg",
    "4920518599655229884.558ed879d6e4ebe550051f7ba60a1360.23082722.jpg",
    "4920518599655229884.5cd01dd4dbb6c37d8b78219e42d840bd.23082713.jpg",
    "4920518599655229884.7788406b9622816f17da2641787eaead.23082713.jpg",
    "4920518599655229884.8758199608dd6c2744393508c24384b1.23082713.jpg",
    "4920518599655229884.951c053d33027381d68b8d9c706bfbd8.23082713.jpg",
    "4920518599655229884.b3a65454c3c30998e046ef47bc38fdaa.23082714.jpg",
    "4920518599655229884.c640c41e636fcae9a62df25cf4672127.23082722.jpg",
    "4920518599655229884.c925e78ffe25e409220de1ba93718c35.23082713.jpg",
    "4920518599655229884.d34c82cab186e9545959db8effd6651c.23082713.jpg",
    "4920518599655229884.df4625cae80f931ce615a9b38a1bd9a5.23082722.jpg",
    "4920518599655229884.fc747538159972137fb35083bc74b83e.23082713.jpg",
    "IMG_0029.HEIC",
    "IMG_0030.HEIC",
    "IMG_0046.HEIC",
}

with open(CACHE_FILE, encoding="utf-8") as f:
    cache = json.load(f)

updated = 0
for fname, entry in cache.items():
    new_val = fname in HAS_PERSON
    if entry.get("has_person") != new_val:
        entry["has_person"] = new_val
        updated += 1
    elif "has_person" not in entry:
        entry["has_person"] = new_val
        updated += 1

with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)

food_total = sum(1 for v in cache.values() if v.get("is_food"))
person_food = sum(1 for v in cache.values() if v.get("is_food") and v.get("has_person"))
ok_food = food_total - person_food
print(f"has_person フラグ書き込み完了: {updated} 件更新")
print(f"食べ物写真 {food_total} 枚 → 人物あり {person_food} 枚 / 投稿可 {ok_food} 枚")
