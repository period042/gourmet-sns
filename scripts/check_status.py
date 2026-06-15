import json
from pathlib import Path

data = json.loads(Path("data/restaurants.json").read_text(encoding="utf-8"))
rs = data["restaurants"]
print(f"レストラン数: {len(rs)}")
total_food = sum(len(r.get("food_photos", [])) for r in rs)
total_postable = sum(len(r.get("postable_photos", [])) for r in rs)
print(f"food_photos合計: {total_food}")
print(f"postable_photos合計: {total_postable}")
for r in rs:
    rid = r["id"]
    name = r.get("name", "")
    food = len(r.get("food_photos", []))
    postable = len(r.get("postable_photos", []))
    status = r.get("status", "")
    print(f"  {rid} {name} | food={food} postable={postable} status={status}")
