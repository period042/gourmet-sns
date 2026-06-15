"""
Phase 2: Instagram用キャプションをGemini APIで生成する

実行: python scripts/generate_posts.py
結果: data/restaurants.json の各レストランに generated_posts フィールドを追加
"""
import os
import json
from pathlib import Path
from datetime import datetime
from google import genai
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

DATA_DIR = Path(__file__).parent.parent / "data"
RESTAURANTS_FILE = DATA_DIR / "restaurants.json"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

SYSTEM_INSTRUCTION = """
あなたは日本のグルメインフルエンサーとしてInstagram投稿文を生成します。

【バズる投稿の条件】
- 読んだ人が「行ってみたい」と思う具体的な描写
- 食感・味・見た目・コスパを盛り込む
- ですます調、親しみやすい口語
- 2026年Instagram仕様: ハッシュタグは最大5個
- 地域名・料理名のキーワードをキャプション本文に自然に入れる（検索対策）
"""

INSTAGRAM_PROMPT = """
Instagram投稿文を生成してください。

【フォーマット】
1行目: 📍 {name} | {area}
(空行)
料理の詳細感想 (3〜4行、ですます調)
(空行)
One-line English description (15 words max)
(空行)
━━━━━━━━━━━
🏠 {name}
📍 {area}
━━━━━━━━━━━
(空行)
ハッシュタグ5個以内

【条件】
- 店名: {name}（未確認の場合は「素敵なお店」等と表現）
- エリア: {area}
- 料理の特徴: {food_descs}
- 全体250〜400文字
- ハッシュタグ例: #ジャンル #エリアグルメ #グルメ #foodie #japanesefood

出力は投稿文のみ。説明不要。
"""


def open_as_pil(path: str, max_px: int = 800) -> Image.Image | None:
    try:
        return Image.open(path).convert("RGB").resize(
            tuple(int(d * min(1, max_px / max(Image.open(path).size))) for d in Image.open(path).size),
            Image.LANCZOS
        )
    except Exception:
        return None


def generate_instagram_caption(
    client,
    name: str,
    area: str,
    food_descs: list[str],
    sample_paths: list[str],
) -> str:
    from google.genai import types
    prompt = INSTAGRAM_PROMPT.format(
        name=name or "未確認の飲食店",
        area=area or "エリア未確認",
        food_descs="、".join(food_descs) or "グルメ料理",
    )
    content = []
    for p in sample_paths[:2]:
        try:
            img = Image.open(p).convert("RGB")
            w, h = img.size
            if max(w, h) > 800:
                ratio = 800 / max(w, h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            content.append(img)
        except Exception:
            pass
    content.append(prompt)

    resp = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=content,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
    )
    return resp.text.strip()


def main():
    if not RESTAURANTS_FILE.exists():
        print("❌ restaurants.json が見つかりません。先に analyze_photos.py を実行してください。")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)

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
            continue  # 生成済みスキップ

        name = r.get("name", "")
        area = r.get("area", "")
        food_descs = [p["food_desc"] for p in food_photos[:5] if p.get("food_desc")]
        paths = [p["path"] for p in food_photos[:3]]

        print(f"  生成中: {r['id']} ({name or '店名未定'} / {r['date']})")

        try:
            caption = generate_instagram_caption(client, name, area, food_descs, paths)
        except Exception as e:
            print(f"    [warn] 生成失敗: {e}")
            continue

        r.setdefault("generated_posts", {})["instagram"] = caption
        r["generated_posts"]["generated_at"] = datetime.now().isoformat()
        updated += 1

    data["generated_at"] = datetime.now().isoformat()
    RESTAURANTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完了: {updated} 件のキャプション生成済み")


if __name__ == "__main__":
    main()
