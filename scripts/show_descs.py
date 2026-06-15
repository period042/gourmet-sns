import json, sys
sys.stdout.reconfigure(encoding="utf-8")
with open("data/restaurants.json", encoding="utf-8") as f:
    data = json.load(f)
for r in data["restaurants"]:
    descs = [p.get("food_desc","") for p in r.get("food_photos",[]) if p.get("food_desc")]
    print(f'{r["id"]} | {r.get("name","")} | {r.get("area","")}')
    for d in descs:
        print(f"  - {d}")
