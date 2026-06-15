from dotenv import load_dotenv; load_dotenv()
import os, requests, sys
sys.stdout.reconfigure(encoding="utf-8")

KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
coords = [
    ("r0012", 35.74624722222222, 139.72036666666668),
    ("r0014", 35.65139722222222, 139.70903055555556),
    ("r0018", 39.71726666666667, 140.12191666666666),
]
for rid, lat, lon in coords:
    r = requests.get(
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
        params={"location": f"{lat},{lon}", "radius": 100,
                "type": "restaurant", "language": "ja", "key": KEY},
        timeout=10,
    )
    d = r.json()
    status = d["status"]
    results = d.get("results", [])
    print(f"{rid}: status={status} results={len(results)}")
    for res in results[:3]:
        print(f"  - {res['name']} | {res.get('vicinity','')} | rating={res.get('rating')}")
