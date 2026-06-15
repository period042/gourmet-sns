"""
Google Calendar から各レストランの訪問日に合致する店舗名候補を取得し
restaurants.json の name フィールドを更新する

使い方:
  python scripts/calendar_lookup.py            # 未設定の店名をカレンダーから補完
  python scripts/calendar_lookup.py --dry-run  # 確認のみ（書き込みなし）

フロー上の位置:
  1. cluster_cached.py   （クラスタリング）
  2. geocode_and_clean.py（GPS→駅名補完）
  3. calendar_lookup.py  （カレンダーから店名補完）  ← ここ
  4. tabelog_match.py    （食べログから店名補完）
  5. ダッシュボードで確認・承認

事前準備:
  Google Cloud Console > APIs & Services > Credentials
  > OAuth 2.0 クライアント ID（デスクトップアプリ）を作成
  > credentials.json としてこのスクリプトと同じフォルダに配置
  初回実行時のみブラウザで Google 認証が開く。token.json に保存される。
"""
import json, sys, os, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

DRY_RUN = "--dry-run" in sys.argv

OVERSEAS_KEYWORDS = ["ラツィオ", "ヴェネツィア", "バルセロナ", "Barcelona", "Roma", "Venice", "州"]

def is_overseas(r: dict) -> bool:
    area = r.get("area", "")
    return any(kw in area for kw in OVERSEAS_KEYWORDS)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = Path(__file__).parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent / "token.json"
RESTAURANTS_FILE = BASE_DIR / "data" / "restaurants.json"

# 店舗名らしくない汎用語・活動・非飲食イベント（部分一致で除外）
EXCLUDE_SUB = re.compile(
    r"テニス|ゴルフ|ジム|卓球|水泳|サッカー|野球|バスケ|スポーツ|ランニング|"
    r"カット|美容|サロン|床屋|ヘア|"
    r"家賃|振り込み|振込|支払い|年会費|会費|保険|税|給料|"
    r"誕生日|バースデー|記念日|"
    r"公園|キャンプ|花見|ピクニック|"
    r"研修|勉強|講習|資格|試験|面接|"
    r"病院|クリニック|歯医者|"
    r"おうちごはん|自炊|弁当|"
    r"出発|帰宅|起床|就寝|移動|フライト|搭乗|"
    r"^\d+$",  # 数字のみ
    re.IGNORECASE,
)

# 完全一致で除外（短い汎用語）
EXCLUDE_EXACT = re.compile(
    r"^(会議|MTG|meeting|打ち合わせ|ランチ|lunch|dinner|夜|朝|移動|出張|"
    r"休み|休暇|電話|call|zoom|teams|予約|reservation|AM|PM|帰宅|"
    r"[A-Z]{2,4}|[ぁ-ん]{1,2})$",  # 2-4字の大文字略語・ひらがな1-2字
    re.IGNORECASE,
)


def get_calendar_service():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                print(f"ERROR: {CREDS_FILE} が見つかりません")
                print("Google Cloud Console で OAuth2 クライアント ID（デスクトップアプリ）を作成し")
                print(f"{CREDS_FILE} として保存してください")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds)


def get_events_on_date(service, date_str: str):
    """指定日の全カレンダーイベントを取得"""
    JST = timezone(timedelta(hours=9))
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=JST)
    time_min = dt.isoformat()
    time_max = (dt + timedelta(days=1)).isoformat()

    events = []
    # プライマリカレンダーのみ対象
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    events.extend(result.get("items", []))
    return events


def looks_like_restaurant(title: str, event: dict, target_date: str) -> bool:
    """イベントタイトルが店舗名っぽいか判定"""
    t = title.strip()
    if not t or len(t) < 2:
        return False
    if EXCLUDE_EXACT.match(t):
        return False
    if EXCLUDE_SUB.search(t):
        return False
    # 記号のみ・数字のみは除外
    if re.match(r"^[\d\s\-:./]+$", t):
        return False
    # 全角スペース含む地名（「○○　○○」形式）は除外
    if "　" in t:
        return False
    # 複数日にわたるイベント（旅行など）は除外
    start = event.get("start", {})
    end = event.get("end", {})
    start_date = start.get("date", start.get("dateTime", ""))[:10]
    end_date   = end.get("date",   end.get("dateTime",   ""))[:10]
    if start_date and end_date and start_date != end_date and start_date != target_date:
        return False
    # 0:00 や 0:05 など深夜0時台の自動イベントは除外
    start_dt_str = start.get("dateTime", "")
    if start_dt_str:
        try:
            from datetime import datetime, timezone, timedelta
            JST = timezone(timedelta(hours=9))
            dt = datetime.fromisoformat(start_dt_str).astimezone(JST)
            if dt.hour == 0 and dt.minute < 30:
                return False
        except Exception:
            pass
    return True


def _best_candidate(candidates_with_time: list) -> str:
    """複数候補から最もレストランらしいものを選ぶ（夕方〜夜のイベント優先）"""
    if not candidates_with_time:
        return ""
    # 17:00-23:00 の候補を優先
    evening = [(name, h) for name, h in candidates_with_time if 17 <= h <= 23]
    if evening:
        return evening[0][0]
    # 11:00-16:00 次点
    lunch = [(name, h) for name, h in candidates_with_time if 11 <= h < 17]
    if lunch:
        return lunch[0][0]
    return candidates_with_time[0][0]


def main():
    service = get_calendar_service()

    with open(RESTAURANTS_FILE, encoding="utf-8") as f:
        data = json.load(f)

    updated_list = []
    for r in data["restaurants"]:
        date = r["date"]
        if date == "unknown":
            continue
        if r.get("name") or is_overseas(r):
            continue

        print(f"\n[{r['id']}] {date} のカレンダーを検索中...")
        events = get_events_on_date(service, date)

        if not events:
            print(f"  → イベントなし")
            continue

        candidates_with_time = []
        for ev in events:
            title = ev.get("summary", "").strip()
            start = ev.get("start", {})
            start_time = start.get("dateTime", start.get("date", ""))
            print(f"  イベント: [{start_time}] {title}")
            if looks_like_restaurant(title, ev, date):
                # 開始時刻（JST hour）を取得
                try:
                    from datetime import datetime, timezone, timedelta
                    JST = timezone(timedelta(hours=9))
                    dt_str = start.get("dateTime", "")
                    hour = datetime.fromisoformat(dt_str).astimezone(JST).hour if dt_str else 12
                except Exception:
                    hour = 12
                candidates_with_time.append((title, hour))

        candidates = [name for name, _ in candidates_with_time]
        if candidates:
            chosen = _best_candidate(candidates_with_time)
            print(f"  → 候補: {candidates}  採用: 【{chosen}】")
            updated_list.append((r["id"], date, chosen))
            if not DRY_RUN:
                r["name"] = chosen
        else:
            print(f"  → 店舗名らしいイベントなし")

    print(f"\n=== カレンダー補完結果: {len(updated_list)}件 ===")
    for rid, date, name in updated_list:
        print(f"  {rid} {date} → {name}")

    if DRY_RUN:
        print("\n[dry-run] 変更は保存されていません")
        return

    if updated_list:
        with open(RESTAURANTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("restaurants.json を更新しました")


if __name__ == "__main__":
    main()
