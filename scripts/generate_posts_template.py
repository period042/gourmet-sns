"""
Gemini APIの代替: food_desc から Instagram キャプションをテンプレートで生成する
API不要・オフラインで動作
"""
import json
import random
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data"
RESTAURANTS_FILE = DATA_DIR / "restaurants.json"

OPENING_LINES = [
    "最高のひと皿に出会いました✨",
    "思わず唸る美味しさでした🍽️",
    "これは絶対に行ってほしいお店です！",
    "記憶に残る食体験でした✨",
    "美食の旅、またひとつ宝物が増えました🌸",
    "今日のグルメ探訪、大当たりでした！",
    "思い出に残る最高の食事でした😊",
]

DETAIL_TEMPLATES = [
    "{desc_joined}と、どれも素材の旨みが際立つ一品。目で見ても美しく、食べても満足感が高いです。",
    "いただいたのは{desc_joined}。どれも丁寧な仕事が感じられ、素材の個性が輝いていました。",
    "{desc_joined}をいただきました。想像以上のクオリティで、コスパも含めて大満足です！",
    "今回は{desc_joined}を堪能。シズル感あふれる料理の連続で、箸が止まりませんでした🍴",
]

CLOSING_TEMPLATES = [
    "また絶対訪れたいと思えるお店でした。ぜひチェックしてみてください！",
    "気になった方はぜひ行ってみてください。絶対後悔しませんよ！",
    "次回も必ず訪れたい、そんな素敵なお店でした。",
    "一緒に行った仲間も大満足。リピート確定です😋",
]

ENGLISH_DESC_MAP = {
    "フレンチ": "Exquisite French cuisine with refined flavors",
    "コース": "Multi-course dining experience at its finest",
    "寿司": "Fresh sushi with premium ingredients",
    "刺身": "Fresh sashimi platter with seasonal fish",
    "焼き鳥": "Authentic yakitori with perfectly charred skewers",
    "ラーメン": "Soul-warming ramen with rich broth",
    "鉄板焼き": "Teppanyaki grilled to perfection",
    "天ぷら": "Crispy tempura with seasonal vegetables",
    "海鮮": "Fresh seafood direct from the market",
    "ウニ": "Premium sea urchin with an exquisite umami flavor",
    "和食": "Traditional Japanese kaiseki dining",
    "もつ": "Flavorful offal stew with deep umami",
    "カキ": "Fresh oysters with a briny ocean taste",
    "秋田": "Regional Akita cuisine with local specialties",
    "日本酒": "Accompanied by fine Japanese sake selection",
    "ベトナム": "Vibrant Vietnamese flavors bursting with freshness",
}

HASHTAG_SETS = {
    "フレンチ": ["#フレンチ", "#フランス料理", "#コース料理", "#グルメ", "#foodie"],
    "焼き鳥": ["#焼き鳥", "#居酒屋グルメ", "#串焼き", "#グルメ", "#japanesefood"],
    "海鮮": ["#海鮮", "#シーフード", "#鮮魚", "#グルメ", "#seafood"],
    "ウニ": ["#生ウニ", "#海鮮グルメ", "#ウニ", "#グルメ", "#seafoodlover"],
    "和食": ["#和食", "#日本料理", "#懐石", "#グルメ", "#japanesefood"],
    "ベトナム": ["#ベトナム料理", "#エスニック", "#アジアグルメ", "#グルメ", "#asianfood"],
    "もつ": ["#もつ料理", "#居酒屋", "#もつ鍋", "#グルメ", "#japanesefood"],
    "default": ["#グルメ", "#foodstagram", "#japanesefood", "#foodie", "#美食"],
}


def pick_hashtags(food_descs: list[str]) -> list[str]:
    for key in HASHTAG_SETS:
        if key == "default":
            continue
        if any(key in d for d in food_descs):
            return HASHTAG_SETS[key]
    return HASHTAG_SETS["default"]


def pick_english(food_descs: list[str]) -> str:
    for key, eng in ENGLISH_DESC_MAP.items():
        if any(key in d for d in food_descs):
            return eng
    return "A delightful Japanese dining experience worth visiting"


def generate_caption(name: str, area: str, food_descs: list[str], date: str) -> str:
    display_name = name or "素敵なお店"
    display_area = area or "エリア未確認"
    desc_short = [d.split("、")[0].split("（")[0][:20] for d in food_descs[:4]]
    desc_joined = "・".join(desc_short) if desc_short else "グルメ料理"

    opening = random.choice(OPENING_LINES)
    detail = random.choice(DETAIL_TEMPLATES).format(desc_joined=desc_joined)
    closing = random.choice(CLOSING_TEMPLATES)
    english = pick_english(food_descs)
    hashtags = " ".join(pick_hashtags(food_descs))

    caption = f"""📍 {display_name} | {display_area}

{opening}

{detail}
{closing}

{english}

━━━━━━━━━━━
🏠 {display_name}
📍 {display_area}
━━━━━━━━━━━

{hashtags}"""
    return caption.strip()


def main():
    if not RESTAURANTS_FILE.exists():
        print("ERROR: restaurants.json が見つかりません")
        return

    data = json.loads(RESTAURANTS_FILE.read_text(encoding="utf-8"))
    restaurants = data["restaurants"]

    updated = 0
    for r in restaurants:
        if r.get("status") == "posted":
            continue
        food_photos = r.get("food_photos", [])
        if len(food_photos) < 1:
            continue
        if r.get("generated_posts", {}).get("instagram"):
            print(f"  スキップ (生成済み): {r['id']}")
            continue

        name = r.get("name", "")
        area = r.get("area", "")
        food_descs = [p["food_desc"] for p in food_photos if p.get("food_desc")]
        date = r.get("date", "")

        print(f"  生成中: {r['id']} ({name or '店名未定'} / {date})")
        caption = generate_caption(name, area, food_descs, date)

        r.setdefault("generated_posts", {})["instagram"] = caption
        r["generated_posts"]["generated_at"] = datetime.now().isoformat()
        r["generated_posts"]["method"] = "template"
        updated += 1

    data["generated_at"] = datetime.now().isoformat()
    RESTAURANTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完了: {updated} 件のキャプション生成済み (テンプレート方式)")
    print("\n--- サンプル (最初の1件) ---")
    for r in restaurants:
        if r.get("generated_posts", {}).get("instagram"):
            print(r["generated_posts"]["instagram"].encode("utf-8").decode("utf-8"))
            break


if __name__ == "__main__":
    main()
