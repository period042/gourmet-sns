"""r0018 を時刻で2軒に分割: 日なた(〜18:59) / 長屋酒場(19:00〜)"""
import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE_DIR = Path(__file__).parent.parent
RESTAURANTS_FILE = BASE_DIR / "data" / "restaurants.json"

SPLIT_HOUR = 19  # 19:00 を境界とする

with open(RESTAURANTS_FILE, encoding="utf-8") as f:
    data = json.load(f)

r18 = next((r for r in data["restaurants"] if r["id"] == "r0018"), None)
if not r18:
    print("r0018 が見つかりません")
    sys.exit(1)

def photo_hour(p: dict) -> int:
    t = p.get("taken_at", "")
    if "T" in t:
        return int(t.split("T")[1][:2])
    return 0

# 全写真を時刻で振り分け
def split_photos(photos):
    first  = [p for p in photos if photo_hour(p) < SPLIT_HOUR]
    second = [p for p in photos if photo_hour(p) >= SPLIT_HOUR]
    return first, second

all_first,  all_second  = split_photos(r18.get("all_photos", []))
food_first, food_second = split_photos(r18.get("food_photos", []))
post_first, post_second = split_photos(r18.get("postable_photos", []))

print(f"日なた  : all={len(all_first)} food={len(food_first)} postable={len(post_first)}")
print(f"長屋酒場: all={len(all_second)} food={len(food_second)} postable={len(post_second)}")

# postable が 2 枚未満なら分割しない
if len(post_second) < 2:
    print(f"警告: 長屋酒場のpostableが{len(post_second)}枚のみ。分割しません")
    sys.exit(0)

r_hinata = {
    **r18,
    "id": "r0018",
    "name": "日なた",
    "area": r18.get("area", "秋田県秋田市"),
    "all_photos": all_first,
    "food_photos": food_first,
    "postable_photos": post_first,
    "status": "pending",
    "approved_posts": [],
}

r_nagaya = {
    **r18,
    "id": "r0019",
    "name": "長屋酒場",
    "area": r18.get("area", "秋田県秋田市"),
    "all_photos": all_second,
    "food_photos": food_second,
    "postable_photos": post_second,
    "status": "pending",
    "approved_posts": [],
}

# r0018 を r0018+r0019 に置き換え
restaurants = [r for r in data["restaurants"] if r["id"] != "r0018"]
# r0018 の位置に挿入
insert_idx = next((i for i, r in enumerate(data["restaurants"]) if r["id"] == "r0018"), len(restaurants))
restaurants.insert(insert_idx, r_hinata)
restaurants.insert(insert_idx + 1, r_nagaya)

data["restaurants"] = restaurants
with open(RESTAURANTS_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("\n=== 分割完了 ===")
for r in data["restaurants"]:
    print(f"  {r['id']} {r['date']} | {r.get('name','未設定')} | {r.get('area','')} | postable: {len(r.get('postable_photos',[]))}枚")
