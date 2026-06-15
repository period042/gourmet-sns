"""候補絞り込み：GPS距離 + 料理マッチでスコアリング"""
import json, sys, requests, os, time, math
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")
KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p = math.pi / 180
    a = 0.5 - math.cos((lat2-lat1)*p)/2 + math.cos(lat1*p)*math.cos(lat2*p)*(1-math.cos((lon2-lon1)*p))/2
    return 2 * R * math.asin(math.sqrt(a))


def text_search(query, lat, lon, radius=500):
    r = requests.get("https://maps.googleapis.com/maps/api/place/textsearch/json", params={
        "query": query, "location": f"{lat},{lon}", "radius": radius,
        "language": "ja", "key": KEY,
    }, timeout=10)
    return r.json().get("results", [])


# r0012: 北区滝野川 焼き鳥
print("=== r0012 東京都北区滝野川 ===")
lat, lon = 35.74624722222222, 139.72036666666668
results = text_search("焼き鳥 もつ焼き", lat, lon, radius=400)
for res in results[:10]:
    loc = res["geometry"]["location"]
    dist = haversine(lat, lon, loc["lat"], loc["lng"])
    print(f"  {dist:5.0f}m  {res['name']:30s}  {res.get('formatted_address','')[:50]}  rating={res.get('rating','-')}")
time.sleep(0.3)

# r0014: 渋谷区東 和食
print("\n=== r0014 東京都渋谷区東 ===")
lat, lon = 35.65139722222222, 139.70903055555556
results = text_search("割烹 和食 日本料理", lat, lon, radius=400)
for res in results[:10]:
    loc = res["geometry"]["location"]
    dist = haversine(lat, lon, loc["lat"], loc["lng"])
    print(f"  {dist:5.0f}m  {res['name']:30s}  {res.get('formatted_address','')[:50]}  rating={res.get('rating','-')}")
time.sleep(0.3)

# r0018: 秋田市 新政
print("\n=== r0018 秋田県秋田市中通 ===")
lat, lon = 39.71726666666667, 140.12191666666666
results = text_search("新政 日本酒", lat, lon, radius=800)
for res in results[:10]:
    loc = res["geometry"]["location"]
    dist = haversine(lat, lon, loc["lat"], loc["lng"])
    print(f"  {dist:5.0f}m  {res['name']:30s}  {res.get('formatted_address','')[:50]}  rating={res.get('rating','-')}")
