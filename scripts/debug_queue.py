"""
pick_queue ロジック検証: 投稿後にファイルが削除されると仮定したシミュレーション
"""
import json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8')

JST = timezone(timedelta(hours=9))
QUEUE_DIR = Path(__file__).parent.parent / 'queue'


def pick_queue(simulate_now: datetime, skip_files: set):
    now = simulate_now
    files = sorted(QUEUE_DIR.glob("*_instagram.json"))
    for f in files:
        if f.name in skip_files:
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            if data.get('platform') != 'instagram' or data.get('status') != 'approved':
                continue
            sched = data.get('scheduled_at')
            if sched:
                sched_dt = datetime.fromisoformat(sched)
                if sched_dt.tzinfo is None:
                    sched_dt = sched_dt.replace(tzinfo=JST)
                if sched_dt > now + timedelta(minutes=15):
                    continue
            return f, data
        except Exception as e:
            print(f"  ERROR {f.name}: {e}")
    return None, None


if __name__ == '__main__':
    now_real = datetime.now(JST)
    print(f"実時刻: {now_real.strftime('%Y-%m-%d %H:%M:%S JST')}")
    print()

    # cron 発火時刻（投稿後はファイル削除を仮定して skip_files に追加）
    crons = [
        datetime(2026, 6, 13, 16, 30, tzinfo=JST),
        datetime(2026, 6, 13, 17,  5, tzinfo=JST),
        datetime(2026, 6, 13, 18,  0, tzinfo=JST),
        datetime(2026, 6, 13, 19,  0, tzinfo=JST),
    ]

    posted = set()  # 投稿済みとして除外するファイル名

    for t in crons:
        f, data = pick_queue(simulate_now=t, skip_files=posted)
        if data:
            photos = data.get('photo_urls', [])
            caption_len = len(data.get('caption', ''))
            ok = bool(photos) and caption_len > 0
            status_str = 'OK' if ok else 'NG'
            print(f"[{t.strftime('%H:%M')}] [{status_str}] {data.get('restaurant_name')}  ({f.name})")
            print(f"         scheduled_at={data.get('scheduled_at')}  photos={len(photos)}枚  caption={caption_len}文字")
            if not photos:
                print(f"         !! photo_urls が空 → 投稿不可")
            posted.add(f.name)  # 投稿済みとしてマーク
        else:
            print(f"[{t.strftime('%H:%M')}] queue empty")
        print()

    print(f"本日の投稿件数（シミュレーション）: {len(posted)} 件")
