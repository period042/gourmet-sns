import json
with open('data/restaurants.json', encoding='utf-8') as f:
    data = json.load(f)
for r in data['restaurants']:
    food_files = [p['filename'] for p in r['food_photos']]
    print(r['date'], '|', food_files)
