"""
1. postable_photos が 1 枚以下のレストランを削除
2. GPS がある残りのレストランを Google Maps Places API で店名・エリア補完
   (Places API 失敗時は Nominatim フォールバック)
3. GPS がないレストランはスキップ（手動入力が必要と明示）
"""
import os, json, time, requests, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")
KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

DATA_DIR = Path(__file__).parent.parent / "data"
RESTAURANTS_FILE = DATA_DIR / "restaurants.json"


def places_nearby(lat, lon):
    """Google Maps Places API Nearby Search で店名・エリアを取得"""
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    for radius in (100, 300):
        r = requests.get(url, params={
            "location": f"{lat},{lon}", "radius": radius,
            "type": "restaurant", "language": "ja", "key": KEY,
        }, timeout=10)
        d = r.json()
        status = d.get("status", "")
        results = d.get("results", [])
        print(f"    Places API radius={radius}m status={status} results={len(results)}")
        if status == "REQUEST_DENIED":
            print("    → Places API 未有効。Nominatim にフォールバック")
            return None
        if results:
            top = results[0]
            return {
                "name": top.get("name", ""),
                "vicinity": top.get("vicinity", ""),
                "place_id": top.get("place_id", ""),
                "rating": top.get("rating"),
            }
    return {}


# 主要駅の GPS 座標（API 不要・距離計算で最寄りを返す）
_STATION_COORDS: dict[str, tuple[float, float]] = {
    # ── JR 山手線 ──
    "東京駅":     (35.6812, 139.7671), "有楽町駅":   (35.6753, 139.7635),
    "新橋駅":     (35.6655, 139.7580), "浜松町駅":   (35.6554, 139.7569),
    "田町駅":     (35.6478, 139.7474), "高輪ゲートウェイ駅": (35.6336, 139.7411),
    "品川駅":     (35.6284, 139.7387), "大崎駅":     (35.6197, 139.7282),
    "五反田駅":   (35.6255, 139.7230), "目黒駅":     (35.6334, 139.7156),
    "恵比寿駅":   (35.6467, 139.7101), "渋谷駅":     (35.6580, 139.7016),
    "原宿駅":     (35.6699, 139.7025), "代々木駅":   (35.6830, 139.7025),
    "新宿駅":     (35.6896, 139.7006), "新大久保駅": (35.7004, 139.7003),
    "高田馬場駅": (35.7125, 139.7035), "目白駅":     (35.7209, 139.7073),
    "池袋駅":     (35.7281, 139.7107), "大塚駅":     (35.7318, 139.7281),
    "巣鴨駅":     (35.7339, 139.7394), "駒込駅":     (35.7380, 139.7469),
    "田端駅":     (35.7380, 139.7609), "西日暮里駅": (35.7326, 139.7667),
    "日暮里駅":   (35.7279, 139.7710), "鶯谷駅":     (35.7207, 139.7785),
    "上野駅":     (35.7142, 139.7774), "御徒町駅":   (35.7076, 139.7747),
    "秋葉原駅":   (35.6984, 139.7731), "神田駅":     (35.6914, 139.7703),
    # ── JR 埼京線・東北本線（板橋〜赤羽）──
    "板橋駅":     (35.7491, 139.7199), "十条駅":     (35.7617, 139.7225),
    "赤羽駅":     (35.7785, 139.7213), "北赤羽駅":   (35.7883, 139.7165),
    # ── JR 京浜東北線（王子方面）──
    "上中里駅":   (35.7500, 139.7528), "王子駅":     (35.7614, 139.7348),
    "東十条駅":   (35.7702, 139.7259),
    # ── JR 中央線・総武線 ──
    "中野駅":     (35.7077, 139.6655), "高円寺駅":   (35.7057, 139.6495),
    "阿佐ヶ谷駅": (35.7054, 139.6352), "荻窪駅":     (35.7059, 139.6198),
    "西荻窪駅":   (35.7051, 139.6029), "吉祥寺駅":   (35.7037, 139.5797),
    "飯田橋駅":   (35.7024, 139.7479), "四ツ谷駅":   (35.6861, 139.7304),
    # ── 東武東上線 ──
    "下板橋駅":       (35.7474, 139.7130), "板橋区役所前駅": (35.7507, 139.7052),
    "大山駅":         (35.7397, 139.7084), "中板橋駅":       (35.7426, 139.6923),
    "上板橋駅":       (35.7504, 139.6830), "東武練馬駅":     (35.7588, 139.6697),
    # ── 東急各線 ──
    "代官山駅":   (35.6487, 139.7034), "中目黒駅":   (35.6441, 139.6981),
    "祐天寺駅":   (35.6359, 139.6862), "学芸大学駅": (35.6255, 139.6826),
    "都立大学駅": (35.6104, 139.6924), "自由が丘駅": (35.6076, 139.6674),
    "三軒茶屋駅": (35.6437, 139.6703), "下北沢駅":   (35.6617, 139.6681),
    "二子玉川駅": (35.6138, 139.6272), "武蔵小山駅": (35.6200, 139.7071),
    "不動前駅":   (35.6258, 139.7094),
    # ── 東京メトロ 日比谷線・銀座線 ──
    "霞ケ関駅":   (35.6736, 139.7484), "日比谷駅":   (35.6745, 139.7591),
    "銀座駅":     (35.6715, 139.7652), "築地駅":     (35.6665, 139.7755),
    "茅場町駅":   (35.6803, 139.7817), "人形町駅":   (35.6843, 139.7819),
    "門前仲町駅": (35.6718, 139.7958), "月島駅":     (35.6611, 139.7826),
    "清澄白河駅": (35.6811, 139.8024),
    # ── 東京メトロ 半蔵門線・副都心線 ──
    "表参道駅":   (35.6655, 139.7124), "永田町駅":   (35.6757, 139.7427),
    "市ケ谷駅":   (35.6924, 139.7357), "神楽坂駅":   (35.7017, 139.7351),
    # ── 東京メトロ 南北線・三田線 ──
    "白金台駅":     (35.6415, 139.7229), "白金高輪駅":   (35.6393, 139.7293),
    "麻布十番駅":   (35.6555, 139.7371), "六本木一丁目駅": (35.6620, 139.7366),
    "六本木駅":     (35.6640, 139.7310), "赤坂駅":       (35.6741, 139.7353),
    "後楽園駅":     (35.7063, 139.7517),
    # ── 都営各線 ──
    "西新宿五丁目駅": (35.6916, 139.6890), "練馬駅": (35.7356, 139.6526),
    # ── 錦糸町・押上エリア ──
    "錦糸町駅": (35.6960, 139.8154), "両国駅":   (35.6963, 139.7940),
    "押上駅":   (35.7102, 139.8147), "浅草駅":   (35.7108, 139.7966),
    # ── 足立・葛飾 ──
    "北千住駅": (35.7494, 139.8006), "綾瀬駅":   (35.7604, 139.8236),
    "亀有駅":   (35.7601, 139.8469), "小岩駅":   (35.7364, 139.8785),
    # ── 品川・大田 ──
    "蒲田駅": (35.5619, 139.7163), "大森駅": (35.5900, 139.7336),
    # ── 日本橋・兜町 ──
    "日本橋駅": (35.6819, 139.7749), "豊洲駅": (35.6553, 139.7950),
    # ── 荒川 ──
    "日暮里駅": (35.7279, 139.7710), "町屋駅": (35.7401, 139.7800),
    # ── 石神井 ──
    "石神井公園駅": (35.7390, 139.6169),
    # ── 武蔵小杉 ──
    "武蔵小杉駅": (35.5760, 139.6563),
}


def nearest_station_by_coords(lat: float, lon: float, max_km: float = 5.0) -> str:
    """GPS 座標から最寄り駅名を距離計算で返す（max_km 以内のみ）"""
    import math

    def hav(la1, lo1, la2, lo2) -> float:
        R = 6371.0
        dlat = math.radians(la2 - la1)
        dlon = math.radians(lo2 - lo1)
        a = math.sin(dlat / 2) ** 2 + (
            math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(dlon / 2) ** 2
        )
        return R * 2 * math.asin(math.sqrt(a))

    best_name, best_dist = "", float("inf")
    for name, (slat, slon) in _STATION_COORDS.items():
        d = hav(lat, lon, slat, slon)
        if d < best_dist:
            best_dist, best_name = d, name
    if best_dist <= max_km:
        print(f"    最寄り駅 (GPS距離): {best_name} ({best_dist:.2f}km)")
        return best_name
    print(f"    最寄り駅: なし（最近={best_name} {best_dist:.1f}km > {max_km}km）")
    return ""


def nominatim_area(lat, lon):
    """OpenStreetMap Nominatim でGPS座標からエリア名取得（suburb/neighbourhood優先）"""
    headers = {"User-Agent": "gourmet-sns-app/1.0"}
    r = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": lat, "lon": lon, "format": "json", "accept-language": "ja", "zoom": 17},
        headers=headers, timeout=10,
    )
    d = r.json()
    addr = d.get("address", {})
    province = addr.get("province", addr.get("state", ""))
    iso = addr.get("ISO3166-2-lvl4", "")
    if not province and iso == "JP-13":
        province = "東京都"

    # suburb/neighbourhood レベルを優先取得（例: "恵比寿", "六本木"）
    suburb = (addr.get("suburb") or addr.get("neighbourhood") or
              addr.get("quarter") or "")
    city = addr.get("city", addr.get("town", addr.get("municipality", "")))

    if province and suburb:
        area = f"{province}{suburb}"
    elif province and city:
        area = f"{province}{city}"
    else:
        area = city or ""

    print(f"    Nominatim → area='{area}' (suburb='{suburb}', city='{city}')")
    return area


def geocoding_area(lat, lon):
    """Google Maps Geocoding API で都道府県+市区町村を取得"""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    r = requests.get(url, params={"latlng": f"{lat},{lon}", "language": "ja", "key": KEY}, timeout=10)
    d = r.json()
    for result in d.get("results", []):
        comps = result.get("address_components", [])
        pref = next((c["long_name"] for c in comps if "administrative_area_level_1" in c["types"]), "")
        ward = next((c["long_name"] for c in comps if "ward" in c["types"]), "")
        city = next((c["long_name"] for c in comps if "locality" in c["types"]), "")
        if pref:
            return pref + (ward or city)
    return ""


def main():
    with open(RESTAURANTS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    restaurants = data["restaurants"]

    # Step 1: postable が 1 枚以下を削除（name・承認済みエントリは保護）
    before = len(restaurants)
    def _is_protected(r):
        return bool(r.get("name")) or r.get("status") in ("approved", "posted") or bool(r.get("approved_posts"))
    removed = [r["id"] for r in restaurants
               if len(r.get("postable_photos", [])) <= 1 and not _is_protected(r)]
    skipped = [r["id"] for r in restaurants
               if len(r.get("postable_photos", [])) <= 1 and _is_protected(r)]
    restaurants = [r for r in restaurants
                   if len(r.get("postable_photos", [])) > 1 or _is_protected(r)]
    if removed:
        print(f"削除: {removed} ({before} → {len(restaurants)} 件)")
    if skipped:
        print(f"保護（削除スキップ）: {skipped}")
    if not removed and not skipped:
        print(f"削除対象なし（{len(restaurants)} 件）")

    # Step 2: GPS がある未設定レストランを補完
    for r in restaurants:
        gps = r.get("gps")
        if not gps:
            print(f"\n[{r['id']}] GPS なし → 店名・エリアは手動入力が必要")
            continue

        area_ok = r.get("area", "").endswith("駅")
        name_ok = bool(r.get("name", "").strip())
        if name_ok and area_ok:
            print(f"\n[{r['id']}] 設定済み: {r['name']} / {r['area']} → スキップ")
            continue

        print(f"\n[{r['id']}] {r['date']} GPS={gps['lat']:.5f},{gps['lon']:.5f}")

        # 店名: Places API（KEY がある場合のみ）
        if KEY and not name_ok:
            result = places_nearby(gps["lat"], gps["lon"])
            if result and result.get("name"):
                r["name"] = result["name"]
                r["google_maps"] = result

        # 最寄り駅: GPS 距離計算（API 不要）
        if not area_ok:
            station = nearest_station_by_coords(gps["lat"], gps["lon"])
            if station:
                r["area"] = station

        print(f"    → 店名: {r.get('name', '（未設定）')} | エリア: {r['area']}")
        time.sleep(0.3)

    data["restaurants"] = restaurants
    with open(RESTAURANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n=== 最終結果 ===")
    for r in restaurants:
        name = r.get("name") or "（未設定）"
        area = r.get("area") or "（未設定）"
        print(f"  {r['id']} {r['date']} | {name} | {area} | postable: {len(r.get('postable_photos',[]))}枚")


if __name__ == "__main__":
    main()
