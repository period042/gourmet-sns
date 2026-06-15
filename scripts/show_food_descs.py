import json, sys
sys.stdout.reconfigure(encoding="utf-8")

with open("data/restaurants.json", encoding="utf-8") as f:
    data = json.load(f)
with open("data/classify_cache.json", encoding="utf-8") as f:
    cache = json.load(f)

for r in data["restaurants"]:
    if r["id"] not in ("r0012", "r0014", "r0018"):
        continue
    gps = r.get("gps", {})
    print(f"\n=== {r['id']} {r['date']} lat={gps.get('lat'):.5f} lon={gps.get('lon'):.5f}")
    print(f"    food_photos: {len(r.get('food_photos',[]))}枚 / postable: {len(r.get('postable_photos',[]))}枚")
    for p in r.get("food_photos", []):
        fn = p["filename"]
        desc = cache.get(fn, {}).get("food_desc", "")
        has_p = cache.get(fn, {}).get("has_person", False)
        mark = "[人物あり]" if has_p else ""
        print(f"  {fn} {mark}")
        print(f"    {desc}")
