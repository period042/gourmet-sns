"""
週次まとめ投稿スクリプト (Task 5)
posted/ の直近7日分を集計し、エリア別ランキングキャプションを生成して
Instagram キューに追加する。
"""
import json
import os
import sys
import re
import random
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')

JST = timezone(timedelta(hours=9))
POSTED_DIR = os.path.join(os.path.dirname(__file__), '..', 'posted')
QUEUE_DIR  = os.path.join(os.path.dirname(__file__), '..', 'queue')

HASHTAGS = (
    "#グルメ #東京グルメ #居酒屋 #飯テロ #グルメスタグラム "
    "#グルメ好きな人と繋がりたい #居酒屋巡り #飲み歩き #おすすめグルメ "
    "#食スタグラム #グルメ部 #酒と飯ぐるめ #食べ歩き #東京居酒屋 "
    "#グルメ投稿 #飯活 #週間まとめ #グルメまとめ #東京グルメまとめ"
)


def load_posted_week() -> list[dict]:
    cutoff = datetime.now(JST) - timedelta(days=7)
    results = []
    for fname in os.listdir(POSTED_DIR):
        if not fname.endswith('.json') or 'instagram' not in fname:
            continue
        path = os.path.join(POSTED_DIR, fname)
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
            posted_at_str = d.get('posted_at') or d.get('scheduled_at', '')
            if not posted_at_str:
                continue
            posted_at = datetime.fromisoformat(posted_at_str.replace('Z', '+00:00'))
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=JST)
            if posted_at >= cutoff:
                results.append(d)
        except Exception:
            continue
    return results


def build_summary_caption(items: list[dict]) -> str:
    if not items:
        return ""

    # エリア別にグループ化
    area_map: dict[str, list[str]] = {}
    for item in items:
        area  = item.get('area', '').strip()
        name  = item.get('restaurant_name', '').strip()
        if area and name:
            area_map.setdefault(area, []).append(name)

    lines = [
        "🗓️ 今週の酒と飯まとめ。",
        f"この1週間で{len(items)}軒をレポートしました。",
        "保存して飲み会の参考に。",
        "",
        "ーーーーー",
        "📍 エリア別ピックアップ",
        "",
    ]
    for area, names in sorted(area_map.items(), key=lambda x: -len(x[1])):
        lines.append(f"【{area}】")
        for n in names[:3]:
            lines.append(f"  ✅ {n}")
        lines.append("")

    cta = random.choice([
        "💬 気になるお店はコメントで教えてください！",
        "🔖 あとで行きたい店があれば保存しておいてください。",
    ])
    lines += [
        "ーーーーー",
        cta,
        "",
        "ーーーーー",
        "",
        HASHTAGS,
    ]
    return "\n".join(lines)


def enqueue_summary(caption: str, photo_urls: list[str]):
    now = datetime.now(JST)
    # 翌週月曜 12:00 JST をデフォルト投稿時刻にする
    days_ahead = (7 - now.weekday()) % 7 or 7
    post_time  = (now + timedelta(days=days_ahead)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    item_id = now.strftime('%Y%m%d_%H%M%S') + '_summary_instagram'
    item = {
        "id": item_id,
        "platform": "instagram",
        "restaurant_id": "summary",
        "restaurant_name": "週次まとめ",
        "area": "東京",
        "photo_urls": photo_urls,
        "caption": caption,
        "status": "approved",
        "created_at": now.isoformat(),
        "scheduled_at": post_time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    path = os.path.join(QUEUE_DIR, item_id + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(item, f, ensure_ascii=False, indent=2)
    print(f"キューに追加: {path}")
    print(f"投稿予定: {item['scheduled_at']}")


if __name__ == '__main__':
    items = load_posted_week()
    print(f"直近7日の投稿: {len(items)} 件")
    if not items:
        print("投稿がないためスキップ")
        sys.exit(0)

    caption = build_summary_caption(items)
    print("\n--- キャプション ---")
    print(caption[:400])

    # まとめ投稿用の写真を直近投稿から最大10枚収集
    photos: list[str] = []
    for item in items[:10]:
        urls = item.get('photo_urls') or []
        if urls:
            photos.append(urls[0])
    photos = photos[:10]

    enqueue_summary(caption, photos)
