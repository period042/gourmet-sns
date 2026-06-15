"""
Facebook Places API で各レストランの location_id を取得し
data/restaurants.json に保存するスクリプト。

実行方法:
  $env:IG_ACCESS_TOKEN="xxx"; python scripts/fetch_location_ids.py
"""
import json
import os
import sys
import time
import requests
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

RESTAURANTS_JSON = Path(__file__).parent.parent / 'data' / 'restaurants.json'
GRAPH_URL        = 'https://graph.facebook.com/v22.0'


def search_place(token: str, name: str, lat: float, lon: float) -> str | None:
    """Facebook Places 検索で最も近い一致の place_id を返す。"""
    res = requests.get(f'{GRAPH_URL}/search', params={
        'type':     'place',
        'q':         name,
        'center':   f'{lat},{lon}',
        'distance': 200,          # 200m 以内
        'fields':   'id,name,location',
        'access_token': token,
    }, timeout=15)

    if not res.ok:
        print(f"  API エラー {res.status_code}: {res.text[:200]}")
        return None

    data = res.json().get('data', [])
    if not data:
        return None

    # 最初の結果（関連度が最も高い）を採用
    best = data[0]
    print(f"  → {best['id']}  {best['name']}")
    return best['id']


def main():
    token = os.environ.get('IG_ACCESS_TOKEN', '')
    if not token:
        print("IG_ACCESS_TOKEN が未設定です")
        sys.exit(1)

    raw         = json.loads(RESTAURANTS_JSON.read_text(encoding='utf-8'))
    restaurants = raw['restaurants'] if isinstance(raw, dict) else raw
    updated = 0

    for r in restaurants:
        rid  = r.get('id', '')
        name = r.get('name', '')
        gps  = r.get('gps') or {}
        lat  = gps.get('lat')
        lon  = gps.get('lon')

        if r.get('facebook_place_id'):
            print(f"[SKIP] {rid} {name}  既存: {r['facebook_place_id']}")
            continue

        if not (lat and lon):
            print(f"[SKIP] {rid} {name}  GPS なし")
            continue

        print(f"[SEARCH] {rid} {name}  ({lat}, {lon})")
        place_id = search_place(token, name, lat, lon)

        if place_id:
            r['facebook_place_id'] = place_id
            updated += 1

        time.sleep(0.5)   # API レート制限対策

    if isinstance(raw, dict):
        raw['restaurants'] = restaurants
        out = raw
    else:
        out = restaurants
    RESTAURANTS_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    print(f"\n{updated} 件を更新しました → {RESTAURANTS_JSON}")


if __name__ == '__main__':
    main()
