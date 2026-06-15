"""
一括キャプション更新スクリプト
- 「📌 結論\n\n」をキャプション冒頭から削除
- ハッシュタグを25-28個に拡充
- scheduled_at 15:30:00 → 18:00:00 に変更
"""
import json
import os
import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

QUEUE_DIR = os.path.join(os.path.dirname(__file__), '..', 'queue')

GENRE_TAGS = {
    "日本酒好きなら保存": ["#日本酒好き", "#日本酒居酒屋", "#酒場好き", "#日本酒スタグラム", "#日本酒", "#sake"],
    "焼鳥好きなら保存":   ["#焼鳥好き", "#焼鳥居酒屋", "#串焼き", "#やきとり", "#焼鳥", "#炭火焼き"],
    "魚好きなら保存":     ["#海鮮好き", "#刺身好き", "#鮮魚居酒屋", "#海鮮料理", "#刺身", "#鮮魚"],
    "ラーメン好きなら保存": ["#ラーメン好き", "#ラーメン巡り", "#ラーメン部", "#ラーメン", "#らーめん", "#ramen"],
    "肉好きなら保存":     ["#肉好き", "#和牛好き", "#ステーキ好き", "#焼肉", "#肉スタグラム", "#和牛"],
    "グルメ好きなら保存": ["#グルメ好き", "#居酒屋好き", "#外食好き", "#グルメ記録", "#外食グルメ", "#グルメ旅"],
}

BASE_LARGE  = ["#グルメ", "#東京グルメ", "#居酒屋", "#飯テロ", "#グルメスタグラム"]
BASE_MEDIUM = [
    "#グルメ好きな人と繋がりたい", "#居酒屋巡り", "#飲み歩き",
    "#おすすめグルメ", "#食スタグラム", "#グルメ部", "#酒と飯ぐるめ",
    "#食べ歩き", "#東京居酒屋", "#グルメ投稿", "#飯活", "#グルメ好き", "#居酒屋好き",
]


def extract_area_tag(caption: str) -> str:
    """キャプション内の🚉行から駅名を取得してエリアタグを生成"""
    m = re.search(r"🚉 (.+?)駅", caption)
    if not m:
        return ""
    station = m.group(1)
    # 東京都・道・府・県・都 などを除去
    for r in ["東京都", "都", "道", "府", "県"]:
        station = station.replace(r, "")
    return station.strip()


def build_new_tags(old_tag_line: str, caption: str) -> str:
    tags = old_tag_line.split()

    # カテゴリタグを抽出（「なら保存」で終わるタグ）
    category_tag = next((t for t in tags if t.endswith("なら保存")), "#グルメ好きなら保存")
    genre_key    = category_tag.lstrip("#")
    genre_tags   = GENRE_TAGS.get(genre_key, GENRE_TAGS["グルメ好きなら保存"])

    # エリアタグをキャプション本文から正確に再生成
    area = extract_area_tag(caption)
    area_tags = [f"#{area}グルメ", f"#{area}居酒屋", f"#{area}飲み"] if area else []

    raw = [category_tag] + BASE_LARGE + area_tags + genre_tags + BASE_MEDIUM

    seen, final = set(), []
    for t in raw:
        if t not in seen:
            seen.add(t)
            final.append(t)
        if len(final) >= 28:
            break

    return " ".join(final)


def update_file(path: str):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    caption: str = data.get("caption", "")
    changed = False

    # 1. 「📌 結論\n\n」を冒頭から削除
    prefix = "📌 結論\n\n"
    if caption.startswith(prefix):
        caption = caption[len(prefix):]
        changed = True

    # 2. ハッシュタグ行（最終行）を拡充
    lines = caption.rstrip("\n").split("\n")
    last_line = lines[-1] if lines else ""
    if last_line.strip().startswith("#"):
        new_tags = build_new_tags(last_line, caption)
        if new_tags != last_line:
            lines[-1] = new_tags
            caption = "\n".join(lines)
            changed = True

    # 3. scheduled_at: 15:30:00 → 18:00:00
    sa = data.get("scheduled_at", "")
    if isinstance(sa, str) and "T15:30:00" in sa:
        data["scheduled_at"] = sa.replace("T15:30:00", "T18:00:00")
        changed = True

    if changed:
        data["caption"] = caption
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    return False


if __name__ == "__main__":
    updated = []
    for fname in sorted(os.listdir(QUEUE_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(QUEUE_DIR, fname)
        if update_file(path):
            updated.append(fname)
            print(f"  更新: {fname}")
        else:
            print(f"  スキップ: {fname}")
    print(f"\n合計 {len(updated)} 件を更新しました。")
