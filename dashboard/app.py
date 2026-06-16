"""
グルメ投稿レビューダッシュボード
起動: python dashboard/app.py
アクセス: http://localhost:5000
"""
import os
import json
import io
import uuid
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, abort, Response

import cloudinary
import cloudinary.uploader
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.create_overlay import create_overlay

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
QUEUE_DIR = BASE_DIR / "queue"
OVERLAID_DIR = BASE_DIR / "overlaid"
THUMB_DIR = DATA_DIR / "thumb_cache"
RESTAURANTS_FILE = DATA_DIR / "restaurants.json"

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")
PHOTOS_DIR = Path(os.environ.get("PHOTOS_DIR", r"C:\Users\user\iCloudPhotos\Photos"))

_HOME = str(Path.home())

def resolve_path(p: str) -> str:
    return p.replace(r"C:\Users\user", _HOME)

app = Flask(__name__)

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME", ""),
    api_key=os.environ.get("CLOUDINARY_API_KEY", ""),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET", ""),
)


def load_data() -> dict:
    if not RESTAURANTS_FILE.exists():
        return {"restaurants": []}
    return json.loads(RESTAURANTS_FILE.read_text(encoding="utf-8-sig"))


def save_data(data: dict):
    RESTAURANTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_restaurant(rid: str) -> dict | None:
    data = load_data()
    return next((r for r in data["restaurants"] if r["id"] == rid), None)


def _heic_to_jpeg_bytes(path: Path) -> bytes:
    """HEIC を JPEG バイト列に変換（キャッシュあり）"""
    THUMB_DIR.mkdir(exist_ok=True)
    cache_path = THUMB_DIR / (path.stem + ".jpg")
    if cache_path.exists():
        return cache_path.read_bytes()
    import pillow_heif
    from PIL import Image
    pillow_heif.register_heif_opener()
    img = Image.open(str(path)).convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    data = buf.getvalue()
    cache_path.write_bytes(data)
    return data


_STATUS_ORDER = {"pending": 0, "": 0, None: 0, "approved": 1, "posted": 2, "rejected": 3}

@app.route("/")
def index():
    data = load_data()
    restaurants = data.get("restaurants", [])
    # デフォルトソート: pending → approved → posted の順
    restaurants = sorted(restaurants, key=lambda r: _STATUS_ORDER.get(r.get("status"), 9))
    stats = {
        "total": len(restaurants),
        "pending": sum(1 for r in restaurants if r.get("status") in ("pending", "", None)),
        "approved": sum(1 for r in restaurants if r.get("status") == "approved"),
        "posted": sum(1 for r in restaurants if r.get("status") == "posted"),
    }
    queue_count = len(list(QUEUE_DIR.glob("*.json")))
    return render_template("index.html", restaurants=restaurants, stats=stats, queue_count=queue_count)


@app.route("/restaurant/<rid>")
def restaurant_detail(rid: str):
    r = get_restaurant(rid)
    if not r:
        abort(404)
    return render_template("detail.html", r=r)


@app.route("/photo/<path:filename>")
def serve_photo(filename: str):
    """iCloudPhotos から写真を配信。HEICは自動でJPEG変換。"""
    path = PHOTOS_DIR / filename
    if not path.exists():
        abort(404)
    if path.suffix.lower() == ".heic":
        try:
            jpeg_bytes = _heic_to_jpeg_bytes(path)
            return Response(jpeg_bytes, mimetype="image/jpeg")
        except Exception as e:
            abort(500)
    return send_file(str(path))


@app.route("/overlaid/<filename>")
def serve_overlaid(filename: str):
    path = OVERLAID_DIR / filename
    if path.exists():
        return send_file(str(path))
    abort(404)


@app.route("/api/restaurant/<rid>", methods=["PATCH"])
def update_restaurant(rid: str):
    data = load_data()
    for r in data["restaurants"]:
        if r["id"] == rid:
            body = request.json or {}
            new_name = body.get("name", r.get("name", ""))
            new_area = body.get("area", r.get("area", ""))
            if "name" in body:
                r["name"] = body["name"]
            if "area" in body:
                r["area"] = body["area"]
            if "catchphrase" in body:
                r["catchphrase"] = body["catchphrase"]
            if "yellow_word" in body:
                r["yellow_word"] = body["yellow_word"]
            if "hook_text" in body:
                r["hook_text"] = body["hook_text"]
            if "bullets" in body:
                r["bullets"] = body["bullets"]
            # キャプションは提供値 or 既存値をベースに、常にプレースホルダを置換
            ig = body.get("caption_instagram",
                          r.get("generated_posts", {}).get("instagram", ""))
            if ig and (new_name or new_area):
                ig = ig.replace("素敵なお店", new_name or "素敵なお店")
                ig = ig.replace("エリア未確認", new_area or "エリア未確認")
            r.setdefault("generated_posts", {})["instagram"] = ig
            x = body.get("caption_x", r.get("generated_posts", {}).get("x", ""))
            r.setdefault("generated_posts", {})["x"] = x
            save_data(data)
            # 更新後のキャプションをフロントに返す（textarea更新用）
            return jsonify({"ok": True,
                            "caption_instagram": ig,
                            "caption_x": x})
    return jsonify({"ok": False, "error": "not found"}), 404


@app.route("/api/restaurant/<rid>/generate_catchphrase")
def generate_catchphrase(rid: str):
    """料理写真をClaudeで分析し共感を呼ぶキャッチコピーを生成"""
    r = get_restaurant(rid)
    if not r:
        return jsonify({"ok": False}), 404
    exclude = request.args.get("exclude", "")
    catchphrase, yellow_word = _make_catchphrase_ai(r, exclude=exclude)
    return jsonify({"ok": True, "catchphrase": catchphrase, "yellow_word": yellow_word})


def _make_catchphrase_ai(r: dict, exclude: str = "") -> tuple[str, str]:
    """Claude vision で料理写真を分析し、共感を呼ぶキャッチコピーを生成。
    Returns (catchphrase, yellow_word)"""
    import anthropic, base64, io, re
    import pillow_heif
    from PIL import Image
    pillow_heif.register_heif_opener()
    from scripts.create_overlay import _normalize_area

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    area = r.get("area", "")
    if not api_key:
        descs = [p.get("food_desc", "") for p in r.get("food_photos", []) if p.get("food_desc")]
        return _make_catchphrase(descs, area, exclude)

    station = _normalize_area(area)
    loc = station.replace("駅", "") if station.endswith("駅") else area[:4]

    content = []
    photos = r.get("postable_photos") or r.get("food_photos", [])
    for p in photos[:2]:
        path = Path(resolve_path(p["path"]))
        if not path.exists():
            continue
        try:
            img = Image.open(str(path)).convert("RGB")
            w, h = img.size
            if max(w, h) > 800:
                ratio = 800 / max(w, h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                           "data": base64.standard_b64encode(buf.getvalue()).decode()}
            })
        except Exception:
            pass

    if not content:
        descs = [p.get("food_desc", "") for p in r.get("food_photos", []) if p.get("food_desc")]
        return _make_catchphrase(descs, area, exclude)

    import random
    _ANGLE_EXAMPLES = [
        ("食べた瞬間の驚きや衝撃を、短い独り言で", "箸が、止まった", "止まった"),
        ("食べた後に残る余韻・記憶を", "帰り道もあの味", "あの味"),
        ("また来ずにはいられない引力を", "気づいたら並んでた", "並んでた"),
        ("一緒に来たい人の顔が浮かぶ感覚を", "あの人を連れて来たい", "連れて来たい"),
        ("仕事帰りの寄り道・ご褒美シーンを", "今日だけ寄り道した", "寄り道"),
        ("この店にしかない時間・空気・唯一性を", "ここにしかない時間", "ここに"),
        ("初めて食べた日を忘れないと確信した瞬間を", "ずっと忘れない一口", "忘れない"),
        ("素材や料理人への静かな敬意を", "素材が正直に語る", "正直に"),
        ("こういう夜・こういう時間が好きという感覚を", "こういう夜が好き", "好き"),
        ("誰かに黙って教えたくない秘密感を", "内緒にしたい場所", "内緒"),
    ]
    angle_text, ex_copy, ex_yellow = random.choice(_ANGLE_EXAMPLES)
    exclude_note = f"\n- 前回と同じは避ける:「{exclude}」" if exclude else ""
    content.append({"type": "text", "text": f"""この料理写真を見て、Instagramグルメ投稿用のキャッチコピーを作ってください。

以下のJSON形式のみで返してください（他の文字は不要）:
{{"copy":"コピー本文(14文字以内)","yellow":"コピー内で黄色強調する1〜4文字"}}

【今回の視点】{angle_text}
【このコピーの方向感】例: {{"copy":"{ex_copy}","yellow":"{ex_yellow}"}}

【絶対禁止ワード】優勝、大当たり、反則、最高、絶品、神、やばい、リピ確、また来る、記憶に刻
→ これらを使ったら不正解。自分の言葉で別の表現を探すこと

【copyの条件】
- 短くても余白のある、独り言・会話のようなトーン
- エリア参考: {loc or area}{exclude_note}

【yellowの条件】
- copyに含まれる1〜4文字
- 場面・感覚・動詞など感情が動く部分（評価語は選ばない）"""})

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=80,
        messages=[{"role": "user", "content": content}]
    )
    raw = resp.content[0].text.strip()
    try:
        obj = json.loads(raw)
        catchphrase = str(obj.get("copy", "")).strip()[:16]
        yellow_word = str(obj.get("yellow", "")).strip()
        if yellow_word not in catchphrase:
            yellow_word = ""
    except Exception:
        m = re.search(r'"copy"\s*:\s*"([^"]+)"', raw)
        m2 = re.search(r'"yellow"\s*:\s*"([^"]+)"', raw)
        catchphrase = m.group(1)[:16] if m else raw[:16]
        yellow_word = m2.group(1) if m2 else ""
    return catchphrase, yellow_word


def _make_catchphrase(descs: list, area: str, exclude: str = "") -> tuple[str, str]:
    """food_descから感情・シーン別テンプレートでコピーを生成。Returns (catchphrase, yellow_word)"""
    import random
    from scripts.create_overlay import _normalize_area

    joined = " ".join(descs)
    station = _normalize_area(area)
    loc = station.replace("駅", "") if station.endswith("駅") else area[:3]

    # 食材別テンプレート (catchphrase, yellow_word)
    FOOD_TEMPLATES: dict[str, list[tuple[str, str]]] = {
        "日本酒": [
            ("日本酒との夜が好き", "好き"),
            ("今夜も日本酒に負けた", "負けた"),
            ("日本酒で全部忘れた", "忘れた"),
            ("日本酒に誘われて来た", "誘われて"),
        ],
        "生ウニ": [
            ("ウニに全部持ってかれた", "全部"),
            ("ウニのためだけに来た", "ためだけ"),
            ("ウニを食べて、黙った", "黙った"),
        ],
        "刺身": [
            ("刺身を見て息をのんだ", "息をのんだ"),
            ("今夜の刺身に感謝した", "感謝"),
            ("刺身と向き合う時間", "向き合う"),
        ],
        "焼き鳥": [
            ("焼き鳥の煙に誘われた", "誘われた"),
            ("焼き鳥で今日が終わる", "終わる"),
            ("焼き鳥と、いい夜だった", "いい夜"),
        ],
        "牛タン": [
            ("牛タンの前では無力だ", "無力"),
            ("牛タン一枚で元気出た", "元気"),
        ],
        "和牛": [
            ("和牛に言葉を失った", "言葉を失った"),
            ("和牛と目が合った気がした", "目が合った"),
            ("和牛、ずるい", "ずるい"),
        ],
        "ラーメン": [
            ("スープ飲んで、深呼吸した", "深呼吸"),
            ("ラーメンに救われた夜", "救われた"),
            ("一口目から、もう帰れない", "帰れない"),
        ],
        "天ぷら": [
            ("揚げたての一口に勝てない", "勝てない"),
            ("天ぷらの音で幸せになれた", "幸せ"),
        ],
        "牡蠣": [
            ("牡蠣に全部持ってかれた", "全部"),
            ("牡蠣で海を思い出した", "思い出した"),
        ],
        "もつ焼き": [
            ("もつ焼きと煙と、いい夜", "いい夜"),
            ("もつ焼きで、明日も頑張れる", "頑張れる"),
        ],
        "豚しゃぶ": [
            ("豚しゃぶを、ゆっくり食べた", "ゆっくり"),
            ("豚しゃぶに時間を忘れた", "忘れた"),
        ],
    }

    DETECT = [
        ("牡蠣", "牡蠣"), ("ウニ", "生ウニ"), ("うに", "生ウニ"),
        ("刺身", "刺身"), ("天ぷら", "天ぷら"),
        ("焼き鳥", "焼き鳥"), ("もつ焼き", "もつ焼き"),
        ("牛タン", "牛タン"), ("和牛", "和牛"),
        ("豚しゃぶ", "豚しゃぶ"), ("ラーメン", "ラーメン"),
        ("日本酒", "日本酒"), ("地酒", "日本酒"),
    ]

    EVAL_WORDS = ["が優勝", "が反則", "が大当たり", "が最高！", "が絶品！"]

    matched: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for key, label in DETECT:
        if key in joined and label not in seen_labels:
            matched.extend(FOOD_TEMPLATES.get(label, []))
            for ev in EVAL_WORDS:
                c = label + ev
                if len(c) <= 14:
                    matched.append((c, label))
            seen_labels.add(label)

    generic: list[tuple[str, str]] = [
        ("箸が、止まった", "止まった"),
        ("帰り道もあの味", "あの味"),
        ("気づいたら並んでた", "並んでた"),
        ("あの人を連れて来たい", "連れて来たい"),
        ("今日だけ寄り道した", "寄り道"),
        ("ここにしかない時間", "ここに"),
        ("ずっと忘れない一口", "忘れない"),
        ("素材が正直に語る", "正直に"),
        ("こういう夜が好き", "好き"),
        ("内緒にしたい場所", "内緒"),
        ("また来る理由ができた", "理由"),
        ("終電を忘れてた", "忘れてた"),
        ("言葉にならなかった", "ならなかった"),
        ("涙が出そうだった", "涙"),
        ("ひとりで来たくなる", "ひとりで"),
        ("誰にも教えたくない", "誰にも"),
        ("また来ると決めた夜", "決めた"),
        ("雨の日にも来たくなる", "雨の日"),
        ("一口で、全部わかった", "全部"),
        ("静かに、うまかった", "うまかった"),
        ("黙って食べてしまった", "黙って"),
        ("こんな店が近くにあった", "近くに"),
        ("食べた瞬間、笑ってた", "笑ってた"),
        ("また来ないと損だと思った", "損"),
    ]
    if loc:
        generic += [
            (f"{loc}に、通いたくなる", "通いたくなる"),
            (f"{loc}の夜が忘れられない", "忘れられない"),
            (f"{loc}で、こんな夜", "こんな夜"),
        ]

    all_templates = matched + generic
    valid = [(c, y) for c, y in all_templates if len(c) <= 14 and c != exclude]
    if not valid:
        valid = [(c, y) for c, y in all_templates if len(c) <= 14]
    return random.choice(valid) if valid else ("また来ると決めた", "決めた")


@app.route("/api/restaurant/<rid>/generate_caption")
def generate_caption(rid: str):
    """Instagramキャプションをテンプレートから自動生成"""
    r = get_restaurant(rid)
    if not r:
        return jsonify({"ok": False}), 404
    caption = _generate_instagram_caption(r)
    return jsonify({"ok": True, "caption": caption})


def _generate_instagram_caption(r: dict) -> str:
    """酒と飯、ぐるめ。キャプションテンプレ v1.0"""
    import random

    name    = r.get("name") or "素敵なお店"
    area    = r.get("area", "")
    from scripts.create_overlay import _normalize_area
    station      = _normalize_area(area)
    station_name = station.replace("駅", "") if station.endswith("駅") else station
    disp_station = station if station else area

    descs    = [p.get("food_desc", "") for p in r.get("food_photos", []) if p.get("food_desc")]
    combined = " ".join(descs)
    foods    = descs[:4] if descs else ["おまかせ料理"]

    def stars(n: int) -> str:
        return "★" * n + "☆" * (5 - n)

    def rand_stars() -> int:
        return random.choice([3, 4, 4, 4, 5])

    # ── カテゴリ判定 ──
    if any(kw in combined for kw in ["日本酒", "地酒", "純米", "大吟醸", "銘柄", "亜麻猫", "而今", "十四代", "飛露喜", "陽乃鳥"]):
        cat = "sake"
    elif any(kw in combined for kw in ["焼き鳥", "串焼き", "もつ", "ホルモン", "炭火"]):
        cat = "yakitori"
    elif any(kw in combined for kw in ["刺身", "まぐろ", "鮨", "寿司", "ホタテ", "海老", "海鮮", "魚"]):
        cat = "seafood"
    elif any(kw in combined for kw in ["ラーメン", "つけ麺", "担々麺"]):
        cat = "ramen"
    elif any(kw in combined for kw in ["和牛", "牛", "ステーキ", "焼肉"]):
        cat = "meat"
    else:
        cat = "gourmet"

    # ── 冒頭3行（カテゴリ固定型） ──
    top = foods[0] if foods else "料理"
    if cat == "sake":
        opening         = f"🍶 日本酒好きなら保存。\n{disp_station}で見つけた当たり店。\n銘柄の数も料理のレベルも高かった。"
        rec_bullets     = ["✅ 日本酒が好き", "✅ 美味しい肴が食べたい", "✅ 飲み会で失敗したくない"]
        category_tag    = "日本酒好きなら保存"
        genre_tags      = ["#日本酒好き", "#日本酒居酒屋", "#酒場好き", "#日本酒スタグラム", "#日本酒", "#sake"]
        budget          = "4,000〜8,000円"
        osusume         = next((d for d in descs if "日本酒" in d), top)
    elif cat == "yakitori":
        opening         = f"🔥 焼鳥好きなら保存。\n{disp_station}で飲むなら候補に入れたい一軒。\n特に{top}が絶品。"
        rec_bullets     = ["✅ 焼き鳥が好き", "✅ 炭火の香りが好き", "✅ コスパ良く飲みたい"]
        category_tag    = "焼鳥好きなら保存"
        genre_tags      = ["#焼鳥好き", "#焼鳥居酒屋", "#串焼き", "#やきとり", "#焼鳥", "#炭火焼き"]
        budget          = "3,000〜6,000円"
        osusume         = top
    elif cat == "seafood":
        opening         = f"🐟 魚好きなら保存。\n正直、刺身目当てで再訪したい。\n日本酒との相性も最高。"
        rec_bullets     = ["✅ 新鮮な魚が食べたい", "✅ 日本酒と肴を楽しみたい", "✅ 飲み会の場所に迷っている"]
        category_tag    = "魚好きなら保存"
        genre_tags      = ["#海鮮好き", "#刺身好き", "#鮮魚居酒屋", "#海鮮料理", "#刺身", "#鮮魚"]
        budget          = "4,000〜8,000円"
        osusume         = top
    elif cat == "ramen":
        opening         = f"🍜 ラーメン好きなら保存。\n{disp_station}のおすすめ一杯。\n一度食べたら忘れられない。"
        rec_bullets     = ["✅ ラーメンが好き", "✅ 本格的な一杯が食べたい", "✅ 近くの良店を探している"]
        category_tag    = "ラーメン好きなら保存"
        genre_tags      = ["#ラーメン好き", "#ラーメン巡り", "#ラーメン部", "#ラーメン", "#らーめん", "#ramen"]
        budget          = "1,000〜1,500円"
        osusume         = top
    elif cat == "meat":
        opening         = f"🥩 肉好きなら保存。\n{disp_station}で食べる価値あり。\n特に{top}は必食。"
        rec_bullets     = ["✅ 和牛・肉料理が好き", "✅ 本格派のお店に行きたい", "✅ 特別な日に使いたい"]
        category_tag    = "肉好きなら保存"
        genre_tags      = ["#肉好き", "#和牛好き", "#ステーキ好き", "#焼肉", "#肉スタグラム", "#和牛"]
        budget          = "6,000〜12,000円"
        osusume         = top
    else:
        opening         = f"🍽️ グルメ好きなら保存。\n{disp_station}で見つけた一軒。\nコスパも雰囲気も文句なし。"
        rec_bullets     = ["✅ 美味しいものが食べたい", "✅ 飲み会で失敗したくない", "✅ 新しいお店を開拓したい"]
        category_tag    = "グルメ好きなら保存"
        genre_tags      = ["#グルメ好き", "#居酒屋好き", "#外食好き", "#グルメ記録", "#外食グルメ", "#グルメ旅"]
        budget          = "3,000〜6,000円"
        osusume         = top

    # ── 評価表 ──
    has_drink = any(kw in combined for kw in ["日本酒", "酒", "ワイン", "ビール", "焼酎"])
    rating = (
        f"料理　{stars(rand_stars())}\n"
        f"お酒　{stars(rand_stars() if has_drink else random.choice([3, 4]))}\n"
        f"コスパ{stars(rand_stars())}\n"
        f"再訪度{stars(rand_stars())}"
    )

    # ── ひとこと ──
    hitokoto = random.choice([
        f"{station_name or name}ならかなりおすすめ。\n保存して次の飲み会候補にどうぞ。",
        f"次の飲み会に迷ったら、ここで間違いない。\n保存しておくと便利です。",
        f"定期的に来たい一軒になりました。\n保存して次の飲み会候補にどうぞ。",
    ])

    # ── CTA ──
    cta = random.choice([
        "💬 質問\nあなたなら何を注文しますか？\nコメントで教えてください。",
        "🔖 保存推奨\n次の飲み会候補として保存しておいてください。",
    ])

    # ── ハッシュタグ 25〜30個 ──
    area_tag = (disp_station.replace("駅", "").replace("東京都", "")
                .replace("都", "").replace("道", "").replace("府", "").replace("県", ""))
    base_large  = ["#グルメ", "#東京グルメ", "#居酒屋", "#飯テロ", "#グルメスタグラム"]
    base_medium = ["#グルメ好きな人と繋がりたい", "#居酒屋巡り", "#飲み歩き",
                   "#グルメ記録", "#おすすめグルメ", "#食スタグラム", "#グルメ部", "#酒と飯ぐるめ"]
    area_tags   = [f"#{area_tag}グルメ", f"#{area_tag}居酒屋", f"#{area_tag}飲み"] if area_tag else []
    raw_tags    = [f"#{category_tag}"] + base_large + area_tags + genre_tags + base_medium
    seen_t, final_tags = set(), []
    for t in raw_tags:
        if t not in seen_t:
            seen_t.add(t)
            final_tags.append(t)
        if len(final_tags) >= 28:
            break

    SEP = "ーーーーー"
    lines = [
        opening,
        "",
        SEP,
        "👥 こんな人におすすめ",
        "",
        "\n".join(rec_bullets),
        "",
        SEP,
        "⭐ 酒と飯、ぐるめ。評価",
        "",
        rating,
        "",
        SEP,
        "💬 ひとこと",
        "",
        hitokoto,
        "",
        SEP,
        f"📍 {name}",
        f"🚉 {disp_station}",
        f"💰 予算：{budget}",
        f"🍶 おすすめ：{osusume}",
        "",
        SEP,
        cta,
        "",
        SEP,
        "",
        " ".join(final_tags),
    ]
    return "\n".join(lines)


def _build_bullets(r: dict, exclude: list = None) -> list[str]:
    """レストランデータから3点チェックリストを生成（exclude指定で別パターン）"""
    import random
    exclude = exclude or []
    descs = [p.get("food_desc", "") for p in r.get("food_photos", []) if p.get("food_desc")]
    seen, bullets = set(), []
    for d in descs:
        clean = d.strip()
        if clean and clean not in seen and clean not in exclude:
            bullets.append(clean)
            seen.add(clean)
        if len(bullets) >= 3:
            break

    combined = " ".join(descs)
    area = r.get("area", "")
    from scripts.create_overlay import _normalize_area
    station = _normalize_area(area)

    fillers = []
    if "日本酒" in combined or "地酒" in combined:
        fillers += ["日本酒の品揃えが豊富", "希少銘柄が揃う一軒", "日本酒ペアリングが秀逸"]
    if "焼き鳥" in combined or "串" in combined:
        fillers += ["焼き鳥の種類が充実", "串メニューが豊富", "炭火の香りが絶品"]
    if "海鮮" in combined or "刺身" in combined or "寿司" in combined or "鮨" in combined:
        fillers += ["海鮮の鮮度が抜群", "魚介が充実", "旬の魚が揃う"]
    if "天ぷら" in combined:
        fillers += ["天ぷらの衣が絶妙", "揚げたてが最高"]
    if "和牛" in combined or "牛" in combined:
        fillers += ["和牛の質が高い", "肉の旨みが段違い"]
    if station:
        fillers += [f"{station}の人気店", f"{station}で今一番熱い店"]
    fillers += ["また来たい一軒", "コスパ最高の一軒", "雰囲気も最高", "予約必須の名店"]

    random.shuffle(fillers)
    for f in fillers:
        if len(bullets) >= 3:
            break
        if f not in bullets and f not in exclude:
            bullets.append(f)

    return bullets[:3]


def _make_hook_text(r: dict, exclude: str = "") -> str:
    """フックテキスト（黄色バー保存訴求）を食材から生成"""
    import random
    descs = [p.get("food_desc", "") for p in r.get("food_photos", []) if p.get("food_desc")]
    combined = " ".join(descs)

    _HOOK_MAP = [
        (["日本酒", "地酒", "純米", "大吟醸"],
         ["日本酒好きなら保存！", "日本酒マニア必見", "酒好き必見！", "日本酒リスト最高"]),
        (["焼き鳥", "串焼き", "もつ", "ホルモン"],
         ["焼き鳥好きなら保存！", "串好き必見！", "焼き鳥好きに刺さる"]),
        (["牛", "和牛", "ステーキ", "タン"],
         ["肉好きなら保存！", "肉好き必見！", "和牛好きは要保存"]),
        (["ラーメン", "つけ麺", "担々麺"],
         ["ラーメン好きなら保存！", "ラーメン通必見", "麺好き必見！"]),
        (["刺身", "寿司", "海鮮", "まぐろ", "鮨"],
         ["海鮮好きなら保存！", "寿司好き必見！", "海鮮好きは保存して"]),
        (["鍋", "しゃぶ", "すき焼き"],
         ["鍋好きなら保存！", "鍋好き必見！"]),
        (["ワイン", "イタリアン", "パスタ"],
         ["イタリアン好きなら保存！", "ワイン好き必見！", "イタリアン好き必見"]),
        (["フレンチ", "コース", "アミューズ"],
         ["フレンチ好きなら保存！", "コース料理好き必見", "美食家は保存！"]),
        (["天ぷら", "懐石", "和食", "お椀"],
         ["和食好きなら保存！", "和食好き必見！", "懐石好きは要保存"]),
    ]

    for keywords, texts in _HOOK_MAP:
        if any(kw in combined for kw in keywords):
            options = [t for t in texts if t != exclude]
            return random.choice(options or texts)

    from scripts.create_overlay import _normalize_area
    station = _normalize_area(r.get("area", ""))
    loc = station.replace("駅", "") if station.endswith("駅") else ""
    fallbacks = ["グルメ好きなら保存！", "食いしん坊必見！", "グルメ必見！", "保存推奨！"]
    if loc:
        fallbacks += [f"{loc}グルメ必見！", f"{loc}で大当たり"]
    options = [t for t in fallbacks if t != exclude]
    return random.choice(options or fallbacks)


@app.route("/api/restaurant/<rid>/generate_bullets")
def generate_bullets(rid: str):
    """サブコピー（チェックリスト）3点を自動生成"""
    r = get_restaurant(rid)
    if not r:
        return jsonify({"ok": False}), 404
    exclude_raw = request.args.get("exclude", "")
    excludes = [e for e in exclude_raw.split("|") if e] if exclude_raw else []
    bullets = _build_bullets(r, exclude=excludes)
    return jsonify({"ok": True, "bullets": bullets})


@app.route("/api/restaurant/<rid>/generate_hook")
def generate_hook(rid: str):
    """フックテキスト（黄色バー）を自動生成"""
    r = get_restaurant(rid)
    if not r:
        return jsonify({"ok": False}), 404
    exclude = request.args.get("exclude", "")
    hook = _make_hook_text(r, exclude=exclude)
    return jsonify({"ok": True, "hook": hook})


@app.route("/api/restaurant/<rid>/overlay_preview")
def overlay_preview(rid: str):
    """選択写真 + キャッチコピー + エリアでオーバーレイ生成してJPEGを返す"""
    r = get_restaurant(rid)
    if not r:
        abort(404)
    filename = request.args.get("filename", "")
    catchphrase = request.args.get("catchphrase", "")
    area = request.args.get("area", r.get("area", ""))
    if not filename:
        abort(400)
    path = PHOTOS_DIR / filename
    if not path.exists():
        abort(404)
    try:
        preview_dir = OVERLAID_DIR / "preview"
        # クエリパラメータの入力値を優先、なければ保存済みデータを使用
        hook_text_param = request.args.get("hook_text", "").strip()
        bullets_param   = request.args.get("bullets", "").strip()
        hook_text = hook_text_param if hook_text_param else r.get("hook_text", "")
        bullets = [b for b in bullets_param.split("|") if b.strip()]
        yellow_word = request.args.get("yellow_word", r.get("yellow_word", ""))
        out_path  = create_overlay(str(path), area, catchphrase, preview_dir,
                                   bullets=bullets, target_copy=hook_text,
                                   yellow_word=yellow_word)
        return send_file(out_path, mimetype="image/jpeg")
    except Exception as e:
        abort(500)


@app.route("/api/restaurant/<rid>/approve", methods=["POST"])
def approve(rid: str):
    """
    1. 選択写真の1枚目にオーバーレイ生成
    2. Cloudinary にアップロード
    3. queue/ に投稿JSON生成
    4. status を approved に変更
    """
    data = load_data()
    r = next((x for x in data["restaurants"] if x["id"] == rid), None)
    if not r:
        return jsonify({"ok": False, "error": "not found"}), 404

    body = request.json or {}
    name = r.get("name", "")
    area = r.get("area", "")
    catchphrase = body.get("catchphrase", r.get("catchphrase", ""))

    if not area:
        return jsonify({"ok": False, "error": "エリアを入力してください"}), 400

    # クライアントから選択写真リストを受け取る（なければpostable_photosの先頭10枚）
    selected_filenames = body.get("selected_photos", [])
    # food_photos（人物あり含む）と postable_photos の両方を対象にする
    all_food = {p["filename"]: p for p in r.get("food_photos", [])}
    all_food.update({p["filename"]: p for p in r.get("postable_photos", [])})
    postable_map = all_food

    if selected_filenames:
        selected = [postable_map[fn] for fn in selected_filenames if fn in postable_map]
    else:
        selected = postable[:10]

    if not selected:
        return jsonify({"ok": False, "error": "投稿可能な写真がありません"}), 400

    selected = selected[:10]

    # 1枚目にオーバーレイ（エリア＋キャッチコピー）
    try:
        bullets     = [b for b in (r.get("bullets") or []) if b.strip()]
        hook_text   = r.get("hook_text", "")
        yellow_word = r.get("yellow_word", "")
        overlay_path = create_overlay(resolve_path(selected[0]["path"]), area, catchphrase,
                                      bullets=bullets, target_copy=hook_text,
                                      yellow_word=yellow_word)
    except Exception as e:
        return jsonify({"ok": False, "error": f"オーバーレイ生成失敗: {e}"}), 500

    # Cloudinary にアップロード
    cloud_urls = []
    try:
        res = cloudinary.uploader.upload(overlay_path, folder="gourmet")
        cloud_urls.append(res["secure_url"])
        for p in selected[1:]:
            res2 = cloudinary.uploader.upload(resolve_path(p["path"]), folder="gourmet")
            cloud_urls.append(res2["secure_url"])
    except Exception as e:
        return jsonify({"ok": False, "error": f"Cloudinaryアップロード失敗: {e}"}), 500

    generated = r.get("generated_posts", {})
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    queue_ig = {
        "id": f"{ts}_{rid}_instagram",
        "platform": "instagram",
        "restaurant_id": rid,
        "restaurant_name": name,
        "area": area,
        "photo_urls": cloud_urls,
        "caption": generated.get("instagram", f"{name} | {area}\n#gourmet #japanesefood"),
        "created_at": datetime.now().isoformat(),
        "status": "approved",
        "overlay_source_path": selected[0]["path"],
    }
    (QUEUE_DIR / f"{queue_ig['id']}.json").write_text(
        json.dumps(queue_ig, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    r["status"] = "approved"
    r["approved_posts"] = [queue_ig["id"]]
    save_data(data)

    return jsonify({"ok": True, "queue_ig": queue_ig["id"]})


@app.route("/api/restaurant/<rid>", methods=["DELETE"])
def delete_restaurant(rid: str):
    data = load_data()
    before = len(data["restaurants"])
    data["restaurants"] = [r for r in data["restaurants"] if r["id"] != rid]
    if len(data["restaurants"]) == before:
        return jsonify({"ok": False, "error": "not found"}), 404
    save_data(data)
    return jsonify({"ok": True})


def _get_photo_meta(photo_path: str) -> dict:
    """写真 EXIF から日付・GPS を取得"""
    try:
        import pillow_heif
        from PIL import Image
        pillow_heif.register_heif_opener()
        img = Image.open(photo_path)
        exif = img.getexif()
        date_raw = str(exif.get(36867) or exif.get(306) or "")
        date = date_raw[:10].replace(":", "-") if date_raw else ""
        gps = exif.get_ifd(34853)
        lat = lon = None
        if gps:
            def _dd(vals):
                return sum(float(v) / (60 ** i) for i, v in enumerate(vals))
            if gps.get(2) and gps.get(4):
                lat = _dd(gps[2]) * (1 if gps.get(1, "N") == "N" else -1)
                lon = _dd(gps[4]) * (1 if gps.get(3, "E") == "E" else -1)
        return {"date": date, "lat": lat, "lon": lon}
    except Exception:
        return {"date": "", "lat": None, "lon": None}


TABELOG_PATH = BASE_DIR / "data" / "tabelog_visited.json"

def _clean_tabelog_area(raw: str) -> str:
    """食べログ area フィールドから「駅名/ジャンル」部分を抽出"""
    import re
    m = re.search(r'[぀-ヿ一-鿿]{2,}(?:、[぀-ヿ一-鿿0-9（）A-Za-z]{2,})*\/[぀-ヿ一-鿿、]+', raw)
    return m.group(0) if m else ""


@app.route("/api/restaurant/<rid>/suggest_name")
def suggest_name(rid: str):
    """写真 EXIF 日付 → 食べログ訪問履歴で同月の店名候補を返す"""
    r = get_restaurant(rid)
    if not r:
        return jsonify({"ok": False}), 404

    # EXIF 日付取得（複数枚から最初に取れたものを使用）
    photo_date = ""
    for p in (r.get("food_photos") or [])[:5]:
        path = resolve_path(p.get("path", ""))
        if Path(path).exists():
            meta = _get_photo_meta(path)
            if meta["date"]:
                photo_date = meta["date"]  # "YYYY-MM-DD"
                break

    r_station = r.get("area", "").replace("駅", "")
    candidates: list[dict] = []
    if photo_date and TABELOG_PATH.exists():
        tabelog = json.loads(TABELOG_PATH.read_text(encoding="utf-8-sig"))
        ym = photo_date[:7].replace("-", "/")  # "YYYY/MM"
        for entry in tabelog:
            if not (entry.get("date") or "").startswith(ym):
                continue
            cleaned = _clean_tabelog_area(entry.get("area", ""))
            tabelog_stations = cleaned.split("/")[0] if "/" in cleaned else cleaned
            if r_station and tabelog_stations and r_station not in tabelog_stations:
                continue
            candidates.append({
                "name": entry["name"],
                "area": cleaned,
            })

    return jsonify({"ok": True, "candidates": candidates, "date": photo_date})


@app.route("/api/restaurant/<rid>/reject", methods=["POST"])
def reject(rid: str):
    data = load_data()
    for r in data["restaurants"]:
        if r["id"] == rid:
            r["status"] = "rejected"
            save_data(data)
            return jsonify({"ok": True})
    return jsonify({"ok": False}), 404


@app.route("/queue")
def queue_list():
    items = []
    for f in sorted(QUEUE_DIR.glob("*.json")):
        items.append(json.loads(f.read_text(encoding="utf-8-sig")))
    return render_template("queue.html", items=items)


@app.route("/api/queue/<item_id>", methods=["DELETE"])
def delete_queue_item(item_id: str):
    path = QUEUE_DIR / f"{item_id}.json"
    if not path.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    path.unlink()
    return jsonify({"ok": True})


@app.route("/api/queue/<item_id>/remove_image_subcopy", methods=["POST"])
def remove_image_subcopy(item_id: str):
    """画像オーバーレイをサブコピー(bullets)なしで再生成してCloudinaryに再アップロード"""
    path = QUEUE_DIR / f"{item_id}.json"
    if not path.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    item = json.loads(path.read_text(encoding="utf-8-sig"))

    source_path = resolve_path(item.get("overlay_source_path", ""))
    if not source_path:
        return jsonify({"ok": False, "error": "元写真パスが保存されていません。再承認が必要です"}), 400
    if not Path(source_path).exists():
        return jsonify({"ok": False, "error": f"元写真ファイルが見つかりません: {source_path}"}), 400

    data = load_data()
    r = next((x for x in data["restaurants"] if x["id"] == item.get("restaurant_id")), None)
    r_area = (r or {}).get("area", item.get("area", ""))
    r_catchphrase = (r or {}).get("catchphrase", "")
    r_hook = (r or {}).get("hook_text", "")
    r_yellow = (r or {}).get("yellow_word", "")

    try:
        preview_dir = OVERLAID_DIR / "preview"
        new_overlay = create_overlay(
            source_path, r_area, r_catchphrase, preview_dir,
            bullets=[], target_copy=r_hook, yellow_word=r_yellow
        )
        res = cloudinary.uploader.upload(str(new_overlay), folder="gourmet")
        new_url = res["secure_url"]
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    item["photo_urls"][0] = new_url
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "url": new_url})


@app.route("/api/queue/<item_id>", methods=["PATCH"])
def patch_queue_item(item_id: str):
    path = QUEUE_DIR / f"{item_id}.json"
    if not path.exists():
        return jsonify({"ok": False, "error": "not found"}), 404
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    body = request.get_json(force=True, silent=True) or {}
    if "caption" in body:
        data["caption"] = body["caption"]
    if "scheduled_at" in body:
        data["scheduled_at"] = body["scheduled_at"]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


if __name__ == "__main__":
    QUEUE_DIR.mkdir(exist_ok=True)
    OVERLAID_DIR.mkdir(exist_ok=True)
    THUMB_DIR.mkdir(exist_ok=True)
    app.run(debug=True, port=5000)
