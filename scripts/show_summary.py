import json
with open('data/restaurants.json', encoding='utf-8') as f:
    data = json.load(f)
rs = data['restaurants']
print(f'Total restaurants: {len(rs)}')
with_cap = sum(1 for r in rs if r.get('generated_posts', {}).get('instagram'))
print(f'With captions: {with_cap}')
print()
for r in rs:
    cap = r.get('generated_posts', {}).get('instagram', '')
    print(r['id'], '|', r['date'], '|', len(r['food_photos']), 'food photos | caption:', len(cap), 'chars')
