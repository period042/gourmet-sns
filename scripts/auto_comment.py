"""
自動コメントスクリプト (Task 6)
自分の最新投稿に補足ハッシュタグをコメントする。
ig_hashtag_search は Meta Advanced Access が必要なため使用しない。
"""
import json
import os
import sys
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding='utf-8')

JST          = timezone(timedelta(hours=9))
ACCESS_TOKEN = os.environ.get('IG_ACCESS_TOKEN', '')
ACCOUNT_ID   = os.environ.get('IG_BUSINESS_ACCOUNT_ID', '')
GRAPH_URL    = 'https://graph.facebook.com/v22.0'

EXTRA_HASHTAGS = (
    "#グルメ #東京グルメ #居酒屋 #飯テロ #おすすめグルメ "
    "#東京居酒屋 #飲み歩き #食スタグラム #グルメ部 "
    "#グルメ好きな人と繋がりたい #居酒屋巡り #酒と飯ぐるめ "
    "#グルメ動画 #東京飯 #夜ご飯"
)

COMMENTED_LOG = Path(__file__).parent.parent / 'data' / 'commented_media.json'


def load_commented() -> set[str]:
    try:
        return set(json.loads(COMMENTED_LOG.read_text(encoding='utf-8')))
    except Exception:
        return set()


def save_commented(ids: set[str]):
    COMMENTED_LOG.parent.mkdir(exist_ok=True)
    COMMENTED_LOG.write_text(
        json.dumps(sorted(ids)[-2000:], ensure_ascii=False),
        encoding='utf-8'
    )


def get_own_media(limit: int = 10) -> list[dict]:
    """自分の最近の投稿一覧を取得。"""
    res = requests.get(f'{GRAPH_URL}/{ACCOUNT_ID}/media', params={
        'fields': 'id,timestamp,media_type',
        'access_token': ACCESS_TOKEN,
        'limit': limit,
    }, timeout=15)
    if not res.ok:
        print(f"[ERROR] 投稿取得失敗 {res.status_code}: {res.text[:300]}")
        return []
    return res.json().get('data', [])


def post_comment(media_id: str, text: str) -> bool:
    res = requests.post(f'{GRAPH_URL}/{media_id}/comments', params={
        'message': text,
        'access_token': ACCESS_TOKEN,
    }, timeout=15)
    if not res.ok:
        print(f"  [ERROR] コメント失敗 {media_id} | {res.status_code}: {res.text[:300]}")
        return False
    return True


def run():
    if not ACCESS_TOKEN or not ACCOUNT_ID:
        print("IG_ACCESS_TOKEN / IG_BUSINESS_ACCOUNT_ID が未設定")
        sys.exit(1)

    already    = load_commented()
    media_list = get_own_media(limit=10)
    if not media_list:
        print("投稿が見つかりません（スキップ）")
        return

    count = 0
    for m in media_list:
        mid = m['id']
        if mid in already:
            print(f"  [SKIP] コメント済み: {mid}")
            continue

        ok = post_comment(mid, EXTRA_HASHTAGS)
        already.add(mid)
        if ok:
            count += 1
            ts = m.get('timestamp', '')
            print(f"  [OK] コメント送信: {mid} ({ts[:10]})")

    save_commented(already)
    print(f"\n合計 {count} 件コメント完了")


if __name__ == '__main__':
    run()
