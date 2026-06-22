#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""週次まとめキューアイテム生成（指定日時版）
Usage: python scripts/_gen_summary.py "2026-06-22T20:00:00"
"""
import sys
import os
import json
import random
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')

JST = timezone(timedelta(hours=9))
POSTED_DIR = os.path.join(os.path.dirname(__file__), '..', 'posted')
QUEUE_DIR  = os.path.join(os.path.dirname(__file__), '..', 'queue')

SCHEDULED_AT = sys.argv[1] if len(sys.argv) > 1 else '2026-06-22T20:00:00'

HASHTAGS = (
    "#グルメ #東京グルメ #居酒屋 #飯テロ #グルメスタグラム "
    "#グルメ好きな人と繋がりたい #居酒屋巡り #飲み歩き #おすすめグルメ "
    "#食スタグラム #グルメ部 #酒と飯ぐるめ #食べ歩き #東京居酒屋 "
    "#グルメ投稿 #飯活 #週間まとめ #グルメまとめ #東京グルメまとめ"
)


def load_posted_week() -> list[dict]:
    cutoff = datetime.now(JST) - timedelta(days=7)
    results = []
    for fname in sorted(os.listdir(POSTED_DIR)):
        if not fname.endswith('.json') or 'instagram' not in fname:
            continue
        path = os.path.join(POSTED_DIR, fname)
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
            # summaryやまとめ投稿は除外
            if d.get('restaurant_id') == 'summary':
                continue
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

    area_map: dict[str, list[str]] = {}
    for item in items:
        area = item.get('area', '').strip()
        name = item.get('restaurant_name', '').strip()
        if area and name and 'まとめ' not in name:
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
        "scheduled_at": SCHEDULED_AT,
    }
    path = os.path.join(QUEUE_DIR, item_id + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(item, f, ensure_ascii=False, indent=2)
    print(f"キューに追加: {path}")
    print(f"投稿予定: {item['scheduled_at']}")
    return path


if __name__ == '__main__':
    items = load_posted_week()
    print(f"直近7日の投稿: {len(items)} 件")

    real_items = items  # already filtered in load_posted_week
    if not real_items:
        print("投稿がないためスキップ")
        sys.exit(0)

    caption = build_summary_caption(items)
    print("\n--- キャプション ---")
    print(caption)
    print("-------------------")

    photos: list[str] = []
    for item in real_items[:10]:
        urls = item.get('photo_urls') or []
        if urls:
            photos.append(urls[0])

    enqueue_summary(caption, photos)
