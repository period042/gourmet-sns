"""
食べログ「いったの記録」から店名を restaurants.json に自動補完する

使い方:
  python scripts/tabelog_match.py            # スクレイピング + 突合 + 自動更新
  python scripts/tabelog_match.py --dry-run  # 更新内容の確認のみ（書き込みなし）
  python scripts/tabelog_match.py --refresh  # キャッシュを無視して再スクレイピング

設定:
  TABELOG_USER_ID: 食べログのユーザーID（スクリプト内またはenv変数で指定）
"""
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RESTAURANTS_FILE = DATA_DIR / "restaurants.json"
TABELOG_CACHE_FILE = DATA_DIR / "tabelog_visited.json"

TABELOG_USER_ID = "000544650"
TABELOG_LIST_URL = f"https://tabelog.com/rvwr/{TABELOG_USER_ID}/visited_restaurants/list/"
TABELOG_ORAL_URL = f"https://tabelog.com/rvwr/{TABELOG_USER_ID}/visited_restaurants/oral_list/"

OVERSEAS_KEYWORDS = ["ラツィオ", "ヴェネツィア", "バルセロナ", "Barcelona", "Roma", "Venice", "州"]


# ── スクレイピング ──────────────────────────────────────────────

_EXTRACT_JS = """
() => {
    const items = [];
    document.querySelectorAll(".simple-rvw").forEach(el => {
        const name = el.querySelector(".simple-rvw__rst-name-target")?.textContent?.trim();
        const date = el.querySelector(".p-preview-visit__visited-date")
                       ?.textContent?.replace("訪問", "").trim();
        const area = el.querySelector(".simple-rvw__rst-area")?.textContent?.trim()
                  || el.querySelector("[class*=area]")?.textContent?.trim();
        if (name) items.push({ name, date, area });
    });
    return items;
}
"""


def _is_logged_in(page) -> bool:
    return page.evaluate("""
        () => Array.from(document.querySelectorAll('a')).some(a => a.href && a.href.includes('/logout'))
        || !!document.querySelector('[class*="logout"], [class*="mypage"], [class*="user-icon"]')
    """)


def _scrape_pages(page, start_url: str, label: str) -> list[dict]:
    page.goto(start_url, wait_until="networkidle")
    time.sleep(1)

    entries = []
    page_num = 1
    while True:
        page_entries = page.evaluate(_EXTRACT_JS)
        entries.extend(page_entries)
        print(f"  [{label}] p{page_num}: {len(page_entries)}件 (計{len(entries)}件)", flush=True)

        if len(page_entries) == 0:
            break

        next_btn = page.locator("a.c-pagination__next-arrow, a[rel=next], .c-pagination__next")
        if next_btn.count() == 0:
            break
        href = next_btn.first.get_attribute("href")
        if not href:
            break
        url = "https://tabelog.com" + href if href.startswith("/") else href
        page.goto(url, wait_until="networkidle")
        time.sleep(0.8)
        page_num += 1
        if page_num > 60:
            break

    return entries


def scrape_tabelog() -> list[dict]:
    """Playwright で全ページをスクレイピングして返す（非ヘッドレス・ログイン対応）"""
    from playwright.sync_api import sync_playwright

    all_entries = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # まず口コミありリストをロードしてログイン状態を確認
        page.goto(TABELOG_LIST_URL, wait_until="networkidle")
        time.sleep(1)

        logged_in = _is_logged_in(page)
        if not logged_in:
            import os
            email = os.environ.get("TABELOG_EMAIL", "")
            password = os.environ.get("TABELOG_PASS", "")

            page.goto("https://tabelog.com/account/login/", wait_until="networkidle")

            if email and password:
                print("価格.com IDで自動ログイン中...")
                # 価格.com IDボタンをクリック
                page.click("button.p-login-panel__btn--kakaku")
                page.wait_for_load_state("networkidle")
                time.sleep(1)
                # メールアドレスとパスワードを入力
                page.fill("#js-mail-address", email)
                page.fill("#password", password)
                page.click("#js-login-button")
                page.wait_for_load_state("networkidle")
                time.sleep(3)
                logged_in = _is_logged_in(page)
                if logged_in:
                    print("ログイン成功。")
                else:
                    print(f"ログイン後URL: {page.url}")
                    print("ログイン失敗またはCAPTCHA。ブラウザで手動で解除してください。")
                    print("完了後 Enter を押してください。")
                    input(">>> Enter: ")
                    logged_in = _is_logged_in(page)
            else:
                print("環境変数 TABELOG_EMAIL / TABELOG_PASS を設定して再実行してください。")
                print("続行しますが oral_list は取得できません。")

        # 1. 行った(口コミあり) をスクレイプ
        reviewed = _scrape_pages(page, TABELOG_LIST_URL, "口コミあり")
        all_entries.extend(reviewed)

        # 2. 行った(口コミなし) をスクレイプ（ログイン済みのみ有効）
        try:
            page.goto(TABELOG_ORAL_URL, wait_until="networkidle")
        except Exception as e:
            print(f"  oral_list アクセスエラー（ログイン必要）: {e}")
            browser.close()
            no_date = [e2 for e2 in all_entries if not e2.get("date")]
            if no_date:
                print(f"  ※日付なしエントリ: {len(no_date)}件")
            return all_entries
        time.sleep(2)
        oral_body = page.inner_text("body").strip()
        oral_item_count = page.evaluate("() => document.querySelectorAll('.simple-rvw').length")

        if oral_item_count > 0:
            oral = _scrape_pages(page, TABELOG_ORAL_URL, "口コミなし")
            all_entries.extend(oral)
            print(f"  口コミなし合計: {len(oral)}件追加")
        elif oral_body:
            print(f"  oral_list: コンテンツあり({len(oral_body)}文字)だが.simple-rvwセレクタ不一致")
            # デバッグ用にHTML保存
            html = page.content()
            debug_path = DATA_DIR / "oral_list_debug.html"
            debug_path.write_text(html, encoding="utf-8")
            print(f"  → {debug_path} にHTML保存（手動確認してください）")
        else:
            print("  oral_list: 空ページ（ログインが必要か、口コミなし訪問が0件）")

        browser.close()

    no_date = [e for e in all_entries if not e.get("date")]
    if no_date:
        print(f"  ※日付なしエントリ: {len(no_date)}件")

    return all_entries


def load_tabelog(refresh: bool = False) -> list[dict]:
    """キャッシュがあれば読み込み、なければスクレイピング"""
    if not refresh and TABELOG_CACHE_FILE.exists():
        cache = json.loads(TABELOG_CACHE_FILE.read_text(encoding="utf-8"))
        print(f"キャッシュ読込: {len(cache)}件 ({TABELOG_CACHE_FILE.name})")
        print("  再取得するには --refresh を付けて実行してください")
        return cache

    print("食べログをスクレイピング中...")
    entries = scrape_tabelog()
    TABELOG_CACHE_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"スクレイピング完了: {len(entries)}件 → {TABELOG_CACHE_FILE.name} に保存")
    return entries


# ── 突合ロジック ─────────────────────────────────────────────────

def clean_area(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s.split("/")[0].strip()


def is_overseas(r: dict) -> bool:
    area = r.get("area", "")
    return any(kw in area for kw in OVERSEAS_KEYWORDS)


def match(tabelog: list[dict], restaurants: list[dict]) -> tuple[list, list, list]:
    """
    返り値:
      auto    : [(rid, date, area, name, tbl_area)]  自動更新可
      ambig   : [(rid, date, area, [(name, tbl_area)])]  複数候補
      no_match: [(rid, date, area)]  記録なし
    """
    # 食べログを年月インデックス化
    tbl_by_ym: dict[str, list] = defaultdict(list)
    for e in tabelog:
        ym = (e.get("date") or "")[:7]  # '2025/05'
        if ym:
            tbl_by_ym[ym].append({"name": e["name"], "area": clean_area(e.get("area", ""))})

    auto, ambig, no_match = [], [], []

    for r in restaurants:
        if r.get("name") or is_overseas(r):
            continue
        date = r.get("date", "")
        if not date:
            continue
        ym = date[:7].replace("-", "/")

        # 同月に既に名前がついているエントリの店名を除外（二重マッチ防止）
        named_in_month = {
            r2["name"] for r2 in restaurants
            if r2.get("name") and r2.get("date", "")[:7].replace("-", "/") == ym
        }
        cands = [c for c in tbl_by_ym.get(ym, []) if c["name"] not in named_in_month]

        if len(cands) == 1:
            auto.append((r["id"], date, r.get("area", ""), cands[0]["name"], cands[0]["area"]))
        elif len(cands) > 1:
            ambig.append((r["id"], date, r.get("area", ""), [(c["name"], c["area"]) for c in cands]))
        else:
            no_match.append((r["id"], date, r.get("area", "")))

    return auto, ambig, no_match


# ── メイン ──────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    refresh = "--refresh" in sys.argv

    tabelog = load_tabelog(refresh=refresh)

    with open(RESTAURANTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    restaurants = data["restaurants"]

    auto, ambig, no_match = match(tabelog, restaurants)

    print("\n=== 自動更新（1件一致）===")
    if auto:
        for rid, date, rst_area, name, tbl_area in auto:
            print(f"  {rid} {date} [{rst_area}] → {name} ({tbl_area})")
    else:
        print("  なし")

    print("\n=== 複数候補（手動確認が必要）===")
    if ambig:
        for rid, date, rst_area, cands in ambig:
            print(f"  {rid} {date} [{rst_area}]:")
            for n, a in cands:
                print(f"    - {n} ({a})")
    else:
        print("  なし")

    print("\n=== 食べログ記録なし ===")
    if no_match:
        for rid, date, rst_area in no_match:
            print(f"  {rid} {date} [{rst_area}]")
    else:
        print("  なし")

    if dry_run:
        print("\n[dry-run] 変更は保存されていません")
        return

    if not auto:
        print("\n自動更新対象なし")
        return

    # 自動更新を適用
    auto_map = {rid: name for rid, _, _, name, _ in auto}
    for r in restaurants:
        if r["id"] in auto_map:
            r["name"] = auto_map[r["id"]]

    with open(RESTAURANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n{len(auto)}件を restaurants.json に保存しました")


if __name__ == "__main__":
    main()
