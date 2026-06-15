"""
1枚目の写真にオーバーレイ。tokyo._gourmet スタイル。
レイアウト:
  左上: 黄色バー + 保存訴求テキスト (target_copy)
  上段: メインコピー（大・左寄せ、評価語のみ黄色）
  下段: チェックリスト3点 + 駅名バッジ（右下）
"""

import os
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

OVERLAID_DIR = Path(__file__).parent.parent / "overlaid"
OUTPUT_SIZE  = (1080, 1080)

WHITE    = (255, 255, 255)
YELLOW   = (255, 212,   0)   # #FFD400
BLACK    = (  0,   0,   0)
BADGE_BG = ( 18,  18,  18)

_FONT_VF    = r"C:\Windows\Fonts\NotoSansJP-VF.ttf"   # Variable Font（Black weight 指定可）
_FONT_HEAVY = [
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
]

# 自動黄色化: 文末の評価語
_EVAL_RE = re.compile(
    r"(最高|優勝|絶品|反則|大当たり|すぎた|だった|リピ確|想像以上|バグってる)[！!]?$"
)

# エリア→駅名（suburb/neighbourhood レベルを先頭に置くことで優先マッチ）
_AREA_STATION = {
    # ── suburb レベル（区より先に評価されるよう先頭）──
    # 渋谷区内
    "恵比寿": "恵比寿駅", "代官山": "代官山駅", "中目黒": "中目黒駅",
    "広尾": "広尾駅", "笹塚": "笹塚駅", "幡ヶ谷": "幡ヶ谷駅",
    # 港区内
    "六本木": "六本木駅", "西麻布": "六本木駅", "麻布": "麻布十番駅",
    "南青山": "表参道駅", "北青山": "表参道駅", "表参道": "表参道駅",
    "赤坂": "赤坂駅", "白金台": "白金台駅", "白金高輪": "白金高輪駅",
    "高輪": "高輪ゲートウェイ駅", "芝浦": "田町駅",
    # 千代田区内
    "神田": "神田駅", "秋葉原": "秋葉原駅", "丸の内": "東京駅",
    "有楽町": "有楽町駅", "日比谷": "日比谷駅",
    "霞が関": "霞ケ関駅", "永田町": "永田町駅",
    # 新宿区内
    "神楽坂": "神楽坂駅", "飯田橋": "飯田橋駅",
    "市ヶ谷": "市ケ谷駅", "四谷": "四ツ谷駅",
    "高田馬場": "高田馬場駅", "早稲田": "早稲田駅",
    # 目黒区内
    "自由が丘": "自由が丘駅", "学芸大学": "学芸大学駅",
    "祐天寺": "祐天寺駅", "武蔵小山": "武蔵小山駅",
    # 世田谷区内
    "三軒茶屋": "三軒茶屋駅", "下北沢": "下北沢駅",
    "二子玉川": "二子玉川駅", "経堂": "経堂駅", "用賀": "用賀駅",
    # 品川区内
    "五反田": "五反田駅", "大崎": "大崎駅", "戸越": "戸越銀座駅",
    # 中央区内
    "銀座": "銀座駅", "日本橋": "日本橋駅", "築地": "築地駅",
    "月島": "月島駅", "茅場町": "茅場町駅", "人形町": "人形町駅",
    # 台東区内
    "浅草": "浅草駅", "入谷": "入谷駅", "蔵前": "蔵前駅",
    # 墨田区内
    "錦糸町": "錦糸町駅", "両国": "両国駅", "押上": "押上駅",
    # 江東区内
    "門前仲町": "門前仲町駅", "清澄白河": "清澄白河駅", "豊洲": "豊洲駅",
    # 豊島区内
    "池袋": "池袋駅", "巣鴨": "巣鴨駅", "大塚": "大塚駅",
    # その他
    "中野": "中野駅", "東中野": "東中野駅",
    "高円寺": "高円寺駅", "阿佐ヶ谷": "阿佐ヶ谷駅",
    "荻窪": "荻窪駅", "吉祥寺": "吉祥寺駅",
    "赤羽": "赤羽駅", "王子": "王子駅",
    "北千住": "北千住駅", "亀有": "亀有駅", "小岩": "小岩駅",
    "日暮里": "日暮里駅", "練馬": "練馬駅",
    # ── 東京23区（ward レベル・フォールバック）──
    "豊島区": "池袋駅",   "渋谷区": "渋谷駅",   "北区":   "赤羽駅",
    "台東区": "上野駅",   "港区":   "新橋駅",   "千代田区": "東京駅",
    "新宿区": "新宿駅",   "中野区": "中野駅",   "板橋区": "板橋駅",
    "墨田区": "錦糸町駅", "足立区": "北千住駅", "江東区": "門前仲町駅",
    "目黒区": "目黒駅",   "品川区": "品川駅",   "大田区": "蒲田駅",
    "世田谷区": "三軒茶屋駅", "杉並区": "高円寺駅", "練馬区": "練馬駅",
    "中央区": "日本橋駅", "文京区": "後楽園駅", "荒川区": "日暮里駅",
    "葛飾区": "亀有駅",   "江戸川区": "小岩駅",
    # ── 日本の主要都市 ──
    "秋田市": "秋田駅",   "仙台市": "仙台駅",   "山形市": "山形駅",
    "新潟市": "新潟駅",   "金沢市": "金沢駅",   "富山市": "富山駅",
    "名古屋市": "名古屋駅", "京都市": "京都駅", "大阪市": "梅田駅",
    "神戸市": "三宮駅",   "広島市": "広島駅",   "福岡市": "博多駅",
    "札幌市": "札幌駅",   "那覇市": "おもろまち駅",
    # ── 海外 ──
    "ローマ": "ローマ",   "ヴェネツィア": "ヴェネツィア", "バルセロナ": "バルセロナ",
    "パリ": "パリ",       "ニューヨーク": "ニューヨーク", "ロンドン": "ロンドン",
}

# 保存訴求テキスト自動選択
_SAVE_TEXT_MAP = [
    (["日本酒", "地酒", "純米", "大吟醸"],  "日本酒好きなら保存！"),
    (["焼き鳥", "串焼き", "もつ", "ホルモン"], "焼き鳥好きなら保存！"),
    (["牛", "和牛", "ステーキ", "タン"],    "肉好きなら保存！"),
    (["ラーメン", "つけ麺", "担々麺"],      "ラーメン好きなら保存！"),
    (["刺身", "寿司", "海鮮", "まぐろ"],    "海鮮好きなら保存！"),
    (["鍋", "しゃぶ", "すき焼き"],         "鍋好きなら保存！"),
    (["ワイン", "イタリアン", "パスタ"],    "イタリアン好きなら保存！"),
]


# ── フォント ──────────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Noto Sans JP Variable Black → YuGothB の優先順でロード"""
    if os.path.exists(_FONT_VF):
        try:
            font = ImageFont.truetype(_FONT_VF, size)
            font.set_variation_by_axes([900])   # wght=900 (Black)
            return font
        except Exception:
            pass
    for fp in _FONT_HEAVY:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ── 計測ヘルパー ─────────────────────────────────────────────

def _tw(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    if not text:
        return 0
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _th(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    if not text:
        return 0
    b = draw.textbbox((0, 0), text, font=font)
    return b[3] - b[1]


# ── テキスト描画 ─────────────────────────────────────────────

def _shadow(canvas: Image.Image, pos: tuple, text: str, font,
            opacity: int = 128, blur: int = 10):
    """シャドウをcanvasにコンポジット（透明度50%・ぼかし10px）"""
    tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d   = ImageDraw.Draw(tmp)
    d.text((pos[0] + 4, pos[1] + 4), text, font=font, fill=(0, 0, 0, opacity))
    canvas.alpha_composite(tmp.filter(ImageFilter.GaussianBlur(blur)))


def _draw_t(canvas: Image.Image, pos: tuple, text: str, font,
            fill: tuple, stroke: int = 8):
    """縁取り付きテキストをcanvasに描画"""
    d = ImageDraw.Draw(canvas)
    d.text(pos, text, font=font, fill=(*fill, 255),
           stroke_width=stroke, stroke_fill=(0, 0, 0, 255))


def _draw_pin_icon(canvas: Image.Image, cx: int, cy: int, pin_h: int, color: tuple):
    """テアドロップ形のロケーションピンをPILで描画（色=color）"""
    tmp = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d   = ImageDraw.Draw(tmp)
    r   = int(pin_h * 0.36)        # 円の半径
    hcy = cy - int(pin_h * 0.10)  # 円の中心（少し上寄り）
    # 外円
    d.ellipse([(cx - r, hcy - r), (cx + r, hcy + r)], fill=(*color, 255))
    # 内穴（白）
    ir = max(int(r * 0.38), 3)
    d.ellipse([(cx - ir, hcy - ir), (cx + ir, hcy + ir)], fill=(255, 255, 255, 190))
    # 下向き三角（ピンの先端）
    tip_y = cy + int(pin_h * 0.46)
    d.polygon([
        (cx - int(r * 0.55), hcy + int(r * 0.55)),
        (cx + int(r * 0.55), hcy + int(r * 0.55)),
        (cx, tip_y),
    ], fill=(*color, 255))
    canvas.alpha_composite(tmp)


# ── テキスト補助 ─────────────────────────────────────────────

def _normalize_area(area: str) -> str:
    if not area:
        return area
    if area.endswith("駅"):
        return area
    for key, station in _AREA_STATION.items():
        if key in area:
            return station
    return area


def _guess_save_text(catchphrase: str, bullets: list) -> str:
    combined = catchphrase + " ".join(bullets)
    for keywords, text in _SAVE_TEXT_MAP:
        if any(kw in combined for kw in keywords):
            return text
    return "グルメ好きなら保存！"


def _split_yellow(text: str) -> tuple[str, str]:
    """(前, 黄色部分) に分割。評価語を黄色にする"""
    m = _EVAL_RE.search(text)
    if m:
        return text[:m.start()], text[m.start():]
    # 「が/は/も/で」の後ろ2-6文字
    m2 = re.search(r"[がはもで]([^がはもで]{2,6}[！!]?)$", text)
    if m2:
        return text[:m2.start(1)], text[m2.start(1):]
    return text, ""


def _wrap_text(draw, text: str, font, max_w: int) -> list[str]:
    if _tw(draw, text, font) <= max_w:
        return [text]
    lines, cur = [], ""
    for ch in text:
        if _tw(draw, cur + ch, font) > max_w:
            if cur:
                lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


# ── メイン ───────────────────────────────────────────────────

def create_overlay(
    photo_path: str,
    area: str,
    catchphrase: str,
    out_dir=None,
    *,
    target_copy: str = "",
    yellow_word: str = "",
    bullets: list | None = None,
) -> str:
    import pillow_heif
    pillow_heif.register_heif_opener()

    out_dir = Path(out_dir) if out_dir else OVERLAID_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"overlay_{Path(photo_path).stem}.jpg"

    bullets  = bullets or []
    station  = _normalize_area(area)
    save_txt = target_copy or _guess_save_text(catchphrase, bullets)
    badge_txt = station  # ピンアイコンは描画で付与するのでテキストはstation名のみ

    # ── 写真補正 ──
    img = Image.open(photo_path).convert("RGB")
    img = _fit_square(img)
    img = ImageEnhance.Brightness(img).enhance(1.10)
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = ImageEnhance.Color(img).enhance(1.05)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=115, threshold=3))

    W, H = img.size  # 1080×1080

    # ── 下部グラデーション（チェックリスト背景のみ・写真全体は暗くしない）──
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(grad)
    gs   = int(H * 0.53)
    for i in range(H - gs):
        t = i / (H - gs)
        gd.rectangle([(0, gs + i), (W, gs + i + 1)],
                     fill=(0, 0, 0, int(190 * (t ** 1.1))))
    canvas = Image.alpha_composite(img.convert("RGBA"), grad)

    # ── フォントサイズ（画像幅の 11〜13%）──
    SZ_MAIN    = 124                       # 11.5% of 1080
    SZ_SUB     = int(SZ_MAIN * 0.55)      # 68px  (55%)
    SZ_STATION = int(SZ_MAIN * 0.42)      # 52px  (40%)
    SZ_TOP     = 38

    f_main = _load_font(SZ_MAIN)
    f_sub  = _load_font(SZ_SUB)
    f_sta  = _load_font(SZ_STATION)
    f_top  = _load_font(SZ_TOP)

    draw = ImageDraw.Draw(canvas)

    # ── 保存訴求バー（左上・黄色）──
    BAR_Y  = 16
    BAR_H  = 58
    BAR_PX = 20
    bar_w  = _tw(draw, save_txt, f_top) + BAR_PX * 2

    bar_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(bar_layer).rectangle(
        [(0, BAR_Y), (bar_w, BAR_Y + BAR_H)], fill=(*YELLOW, 255)
    )
    canvas.alpha_composite(bar_layer)

    draw = ImageDraw.Draw(canvas)
    draw.text(
        (BAR_PX, BAR_Y + (BAR_H - SZ_TOP) // 2 - 2),
        save_txt, font=f_top, fill=(*BLACK, 255),
    )

    # ── メインコピー（左寄せ・最大2行）──
    LEFT  = 24
    CY    = BAR_Y + BAR_H + 16
    MAX_W = W - LEFT * 2

    # フォントサイズ自動縮小（最大2行に収める）
    for sz in (SZ_MAIN, 104, 88, 74, 62):
        f_main = _load_font(sz)
        lines  = _wrap_text(draw, catchphrase, f_main, MAX_W)
        if len(lines) <= 2:
            break

    # 黄色語の決定 - catchphrase 全体での絶対位置を記録（折り返し跨ぎに対応）
    if yellow_word and yellow_word in catchphrase:
        ypart = yellow_word
    else:
        _, ypart = _split_yellow(catchphrase)

    yabs_start = catchphrase.find(ypart) if ypart else -1
    yabs_end   = yabs_start + len(ypart) if yabs_start >= 0 else -1

    char_offset = 0
    for line in lines[:2]:
        lh = _th(draw, line, f_main)

        # 行内での黄色範囲（絶対位置→相対位置に変換、行を跨いでも正しく適用）
        ys = max(0, yabs_start - char_offset)
        ye = min(len(line), yabs_end - char_offset)

        if ypart and 0 <= ys < ye:
            segs = [
                (line[:ys],   WHITE),
                (line[ys:ye], YELLOW),
                (line[ye:],   WHITE),
            ]
        else:
            segs = [(line, WHITE)]

        char_offset += len(line)

        # シャドウ先行描画
        cx = LEFT
        for seg_t, _ in segs:
            if seg_t:
                _shadow(canvas, (cx, CY), seg_t, f_main)
            cx += _tw(ImageDraw.Draw(canvas), seg_t, f_main)

        # 縁取り+テキスト
        cx = LEFT
        for seg_t, col in segs:
            if seg_t:
                _draw_t(canvas, (cx, CY), seg_t, f_main, col, stroke=8)
                cx += _tw(ImageDraw.Draw(canvas), seg_t, f_main)

        CY += lh + 14

    # ── チェックリスト（✓ を黄色、テキストを白）──
    if bullets:
        bx  = 28
        by  = max(CY + 50, int(H * 0.615))
        ck  = "✓  "
        for b in bullets[:3]:
            full = f"✓  {b}"
            bh   = _th(ImageDraw.Draw(canvas), full, f_sub)
            ck_w = _tw(ImageDraw.Draw(canvas), ck, f_sub)
            _shadow(canvas, (bx, by), full, f_sub, opacity=100, blur=6)
            _draw_t(canvas, (bx, by), ck, f_sub, YELLOW, stroke=5)
            _draw_t(canvas, (bx + ck_w, by), b, f_sub, WHITE, stroke=5)
            by += bh + 14

    # ── 駅名バッジ（右下・角丸ダーク＋ピンアイコン）──
    if badge_txt:
        BP     = 18
        PIN_H  = SZ_STATION                  # ピン全体の高さ ≈ フォントサイズ
        PIN_W  = int(SZ_STATION * 0.60)      # ピン描画幅
        GAP    = 10
        d_tmp  = ImageDraw.Draw(canvas)
        txt_w  = _tw(d_tmp, badge_txt, f_sta)
        txt_h  = _th(d_tmp, badge_txt, f_sta)
        bw     = PIN_W + GAP + txt_w + BP * 2
        bh     = txt_h + BP * 2
        bx     = W - bw - 22
        by_b   = H - bh - 22

        badge_l = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(badge_l).rounded_rectangle(
            [(bx, by_b), (bx + bw, by_b + bh)],
            radius=14, fill=(*BADGE_BG, 220),
        )
        canvas.alpha_composite(badge_l)

        # ピンアイコン（黄色）
        pin_cx = bx + BP + PIN_W // 2
        pin_cy = by_b + bh // 2
        _draw_pin_icon(canvas, pin_cx, pin_cy, PIN_H, YELLOW)

        # テキスト
        tx = bx + BP + PIN_W + GAP
        ty = by_b + (bh - txt_h) // 2
        _shadow(canvas, (tx, ty), badge_txt, f_sta, opacity=80, blur=6)
        _draw_t(canvas, (tx, ty), badge_txt, f_sta, WHITE, stroke=3)

    canvas.convert("RGB").save(str(out_path), "JPEG", quality=93)
    return str(out_path)


def _fit_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    s    = min(w, h)
    img  = img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    return img.resize(OUTPUT_SIZE, Image.LANCZOS)


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        out = create_overlay(sys.argv[1], sys.argv[2],
                             sys.argv[3] if len(sys.argv) >= 4 else "")
        print(f"保存: {out}")
    else:
        print("Usage: python create_overlay.py <photo_path> <area> [catchphrase]")
