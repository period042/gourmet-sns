"""
GPS座標 + 料理の特徴キーワードで Google Maps Text Search を使い店名を推察する
"""
import json, sys, requests, os, time
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")
KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

TARGETS = [
    {
        "id": "r0012",
        "lat": 35.74624722222222,
        "lon": 139.72036666666668,
        "keywords": ["焼き鳥", "もつ焼き", "串焼き"],
        "area": "東京都北区",
    },
    {
        "id": "r0014",
        "lat": 35.65139722222222,
        "lon": 139.70903055555556,
        "keywords": ["和食 コース", "日本酒 海鮮", "天ぷら 刺身"],
        "area": "東京都渋谷区",
    },
    {
        "id": "r0018",
        "lat": 39.71726666666667,
        "lon": 140.12191666666666,
        "keywords": ["日本酒 居酒屋", "新政 日本酒"],
        "area": "秋田県秋田市",
    },
]


def text_search(query, lat, lon, radius=300):
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    r = requests.get(url, params={
        "query": query,
        "location": f"{lat},{lon}",
        "radius": radius,
        "language": "ja",
        "key": KEY,
    }, timeout=10)
    d = r.json()
    return d.get("status"), d.get("results", [])


for t in TARGETS:
    print(f"\n{'='*60}")
    print(f"[{t['id']}] {t['area']} GPS={t['lat']:.5f},{t['lon']:.5f}")
    seen = {}
    for kw in t["keywords"]:
        status, results = text_search(kw, t["lat"], t["lon"], radius=300)
        print(f"  キーワード「{kw}」: status={status} results={len(results)}")
        for res in results[:5]:
            name = res["name"]
            addr = res.get("formatted_address", res.get("vicinity", ""))
            rating = res.get("rating", "-")
            dist_raw = res.get("geometry", {}).get("location", {})
            if name not in seen:
                seen[name] = {"addr": addr, "rating": rating, "count": 0}
            seen[name]["count"] += 1
        time.sleep(0.3)
    print(f"\n  --- 候補（複数キーワードにヒットした順）---")
    ranked = sorted(seen.items(), key=lambda x: (-x[1]["count"], -(x[1]["rating"] or 0)))
    for name, info in ranked[:8]:
        mark = "★" * info["count"]
        print(f"  {mark} {name} | {info['addr']} | rating={info['rating']}")
