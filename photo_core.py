"""
photo_core.py — منطق برنامج «استوديو صور المعاملات» (بدون واجهة رسومية).
يعتمد على Pillow فقط.
"""
from dataclasses import dataclass, field
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageDraw, ImageChops

# مقاسات الورق المتاحة (العرض × الارتفاع بالسنتيمتر، الوضع العمودي)
PAPERS = {
    "A6 — 10.5 × 14.8 سم": (10.5, 14.8),
    "10 × 15 سم": (10.0, 15.0),
    "A5 — 14.8 × 21 سم": (14.8, 21.0),
    "A4 — 21 × 29.7 سم": (21.0, 29.7),
    "Letter — 21.6 × 27.9 سم": (21.59, 27.94),
}

# ألوان الخلفية الجاهزة
BACKGROUNDS = {
    "أبيض (قياسي)": (255, 255, 255),
    "أزرق فاتح (جوازات/معاملات)": (135, 190, 235),
    "أزرق غامق (رسمي)": (40, 80, 160),
    "رمادي فاتح": (215, 215, 215),
    "أخضر رسمي": (40, 140, 70),
    "أحمر رسمي": (190, 30, 30),
}


def cm2px(v: float, dpi: float) -> int:
    return int(round(v / 2.54 * dpi))


@dataclass
class PhotoItem:
    name: str
    original: Image.Image
    current: Image.Image
    w: float = 3.0       # العرض بالسم
    h: float = 4.0       # الارتفاع بالسم
    copies: int = 1
    name_text: str = ""   # الاسم (يُكتب تحت الصورة)
    id_text: str = ""     # الرقم القومي (سطر ثانٍ تحت الصورة)

    @staticmethod
    def from_path(path: str) -> "PhotoItem":
        import os
        img = Image.open(path)
        img = ImageOps.exif_transpose(img).convert("RGB")
        return PhotoItem(os.path.basename(path), img, img.copy())


@dataclass
class Settings:
    paper_w: float = 10.5
    paper_h: float = 14.8
    landscape: bool = False
    gap_x: float = 0.4
    gap_y: float = 0.3
    margin: float = 0.5
    show_lines: bool = True
    line_style: str = "full"          # full = إطار كامل | corners = علامات الزوايا
    line_mm: float = 0.2
    line_color: tuple = (0, 0, 0)
    sequential: bool = False          # False: تجميع نسخ كل صورة | True: توزيع بالتتابع
    caption_pt: float = 7.0           # حجم خط النص تحت الصورة (نقطة)
    caption_bold: bool = True
    caption_inside: bool = True       # True: النص داخل إطار الصورة | False: أسفل الصورة

    def page_size(self):
        return (self.paper_h, self.paper_w) if self.landscape else (self.paper_w, self.paper_h)


# ---------------------------------------------------------------- النص تحت الصورة
def caption_lines(it) -> list:
    return [t.strip() for t in (it.name_text, it.id_text) if t and t.strip()]


def caption_extra(it, s: "Settings") -> float:
    """الارتفاع (سم) الذي يحجزه النص أسفل الصورة."""
    n = len(caption_lines(it))
    if s.caption_inside:
        return 0.0
    return n * s.caption_pt * 1.3 / 72 * 2.54 + 0.12 if n else 0.0


def shape(text: str) -> str:
    """تشكيل الحروف العربية وترتيبها (يحتاج arabic-reshaper و python-bidi)."""
    try:
        import arabic_reshaper
        try:
            from bidi import get_display            # python-bidi الحديث
        except ImportError:
            from bidi.algorithm import get_display  # الإصدارات القديمة
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


_FONT_CACHE = {}


def get_font(size_px: int, bold: bool):
    from PIL import ImageFont
    key = (size_px, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    names = (["C:/Windows/Fonts/tahomabd.ttf", "C:/Windows/Fonts/arialbd.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else
             ["C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    names += ["/System/Library/Fonts/Supplemental/Arial.ttf"]
    font = None
    for n in names:
        try:   # BASIC لأن التشكيل يتم يدوياً في shape()
            font = ImageFont.truetype(n, size_px, layout_engine=ImageFont.Layout.BASIC)
            break
        except Exception:
            continue
    font = font or ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


# ---------------------------------------------------------------- الترتيب
def build_sequence(items, sequential: bool):
    if not sequential:
        return [i for i, it in enumerate(items) for _ in range(it.copies)]
    left = [it.copies for it in items]
    seq = []
    while any(left):
        for i, c in enumerate(left):
            if c > 0:
                seq.append(i)
                left[i] -= 1
    return seq


def layout(items, s: Settings):
    """يرجع قائمة صفحات؛ كل صفحة قائمة من (x, y, w, h, index) بالسنتيمتر."""
    pw, ph = s.page_size()
    eps = 1e-6
    pages = [[]]
    x = y = s.margin
    row_h = 0.0
    for idx in build_sequence(items, s.sequential):
        it = items[idx]
        cell_h = it.h + caption_extra(it, s)
        if x > s.margin and x + it.w > pw - s.margin + eps:   # سطر جديد
            x = s.margin
            y += row_h + s.gap_y
            row_h = 0.0
        if y + cell_h > ph - s.margin + eps and pages[-1]:     # صفحة جديدة
            pages.append([])
            x = y = s.margin
            row_h = 0.0
        pages[-1].append((x, y, it.w, it.h, idx))
        x += it.w + s.gap_x
        row_h = max(row_h, cell_h)
    return pages


# ---------------------------------------------------------------- الرسم
def render_page(items, placements, s: Settings, dpi: float) -> Image.Image:
    pw, ph = s.page_size()
    canvas = Image.new("RGB", (cm2px(pw, dpi), cm2px(ph, dpi)), "white")
    d = ImageDraw.Draw(canvas)
    t = max(1, int(round(s.line_mm / 25.4 * dpi)))
    for x, y, w, h, idx in placements:
        px, py = cm2px(x, dpi), cm2px(y, dpi)
        W, H = max(1, cm2px(w, dpi)), max(1, cm2px(h, dpi))
        photo = ImageOps.fit(items[idx].current, (W, H), Image.LANCZOS)
        canvas.paste(photo, (px, py))
        _draw_caption(d, items[idx], s, dpi, px, py, W, H, t)
        if not s.show_lines:
            continue
        if s.line_style == "full":
            d.rectangle([px - t, py - t, px + W + t - 1, py + H + t - 1],
                        outline=s.line_color, width=t)
        else:  # علامات الزوايا للخارج
            L = cm2px(max(0.1, min(s.gap_x, s.gap_y) / 2), dpi)
            for cx, cy, sx, sy in ((px, py, -1, -1), (px + W, py, 1, -1),
                                   (px, py + H, -1, 1), (px + W, py + H, 1, 1)):
                d.line([(cx, cy), (cx + sx * L, cy)], fill=s.line_color, width=t)
                d.line([(cx, cy), (cx, cy + sy * L)], fill=s.line_color, width=t)
    return canvas


def _draw_caption(d, it, s: Settings, dpi, px, py, W, H, t):
    lines = caption_lines(it)
    if not lines:
        return
    base = max(6, int(round(s.caption_pt / 72 * dpi)))
    cx = px + W / 2
    if s.caption_inside:
        pad = max(2, int(0.04 / 2.54 * dpi))
        band = min(int(len(lines) * base * 1.3) + 2 * pad, int(H * 0.4))
        d.rectangle([px, py + H - band, px + W - 1, py + H - 1], fill=(255, 255, 255))
        y = py + H - band + pad
    else:
        y = py + H + t + max(1, int(0.03 / 2.54 * dpi))
    for line in lines:
        text, size = shape(line), base
        font = get_font(size, s.caption_bold)
        while size > 6 and d.textlength(text, font=font) > W:   # يصغّر الخط ليناسب عرض الصورة
            size = int(size * 0.94)
            font = get_font(size, s.caption_bold)
        d.text((cx, y), text, font=font, fill=(0, 0, 0), anchor="ma")
        y += int(size * 1.3)


def render_all(items, s: Settings, dpi: float):
    return [render_page(items, p, s, dpi) for p in layout(items, s)]


def save_pdf(pages, path, dpi=300):
    first, rest = pages[0], pages[1:]
    first.save(path, "PDF", resolution=dpi, save_all=True,
               append_images=rest, quality=95, subsampling=0)


def save_png(pages, path, dpi=600):
    import os
    stem, ext = os.path.splitext(path)
    out = []
    for i, p in enumerate(pages, 1):
        f = path if len(pages) == 1 else f"{stem}_p{i}{ext or '.png'}"
        p.save(f, "PNG", dpi=(dpi, dpi))
        out.append(f)
    return out


# ---------------------------------------------------------------- معالجة الصور
def smooth_skin(img: Image.Image, amount: float) -> Image.Image:
    """تنعيم يحافظ على الحواف (العينين، الشعر، الملابس): يُطبّق على المناطق المستوية فقط."""
    amount = max(0.0, min(1.0, amount))
    r = max(1.0, img.width / 400)
    blur = img.filter(ImageFilter.GaussianBlur(r))
    edges = (img.convert("L").filter(ImageFilter.FIND_EDGES)
             .filter(ImageFilter.GaussianBlur(max(1.0, img.width / 600))))
    mask = edges.point(lambda v: int(255 * max(0.0, 1 - v / 24.0) * amount))
    return Image.composite(blur, img, mask)


def enhance_image(img, brightness=0, contrast=0, sharp=0, smooth=0) -> Image.Image:
    """brightness/contrast: -50..50 ، sharp: 0..100 ، smooth: 0..65"""
    out = img.convert("RGB")
    if brightness:
        out = ImageEnhance.Brightness(out).enhance(1 + brightness / 100)
    if contrast:
        out = ImageEnhance.Contrast(out).enhance(1 + contrast / 100)
    if sharp:
        out = ImageEnhance.Sharpness(out).enhance(1 + sharp / 100)
    if smooth:
        out = smooth_skin(out, smooth / 100)
    return out


def background_mask(img: Image.Image, tol: int = 40) -> Image.Image:
    """قناع الخلفية بملء لوني من الحواف (يعمل جيداً مع الخلفيات الموحدة)."""
    try:  # دقة أعلى إن كانت rembg مثبّتة
        from rembg import remove
        fg = remove(img, only_mask=True).convert("L")
        return fg.point(lambda v: 255 - v)
    except Exception:
        pass
    scale = min(1.0, 700 / max(img.size))
    small = img.convert("RGB").resize(
        (max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    SENT = (255, 0, 255)
    w, h = small.size
    work = small.copy()
    for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0)):
        if work.getpixel(pt) != SENT:
            ImageDraw.floodfill(work, pt, SENT, thresh=tol)
    diff = ImageChops.difference(work, Image.new("RGB", (w, h), SENT)).convert("L")
    mask = diff.point(lambda v: 255 if v == 0 else 0)
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    return mask.resize(img.size, Image.LANCZOS)


def replace_background(img: Image.Image, color, tol: int = 40) -> Image.Image:
    img = img.convert("RGB")
    mask = background_mask(img, tol)
    return Image.composite(Image.new("RGB", img.size, tuple(color)), img, mask)


def trim_edges(img: Image.Image, pct: float = 1.5) -> Image.Image:
    dx, dy = int(img.width * pct / 100), int(img.height * pct / 100)
    return img.crop((dx, dy, img.width - dx, img.height - dy))


def crop_rotated(img: Image.Image, angle: float, cx: float, cy: float,
                 scale: float, aspect: float) -> Image.Image:
    """تدوير ثم قص بنسبة ثابتة. cx, cy مركز القص (0..1)، scale حجم القص (0..1) من أكبر مستطيل ممكن."""
    rot = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255)) \
        if angle else img
    W, H = rot.size
    if W / H > aspect:
        mh, mw = H, H * aspect
    else:
        mw, mh = W, W / aspect
    cw, ch = mw * scale, mh * scale
    x0 = min(max(cx * W - cw / 2, 0), W - cw)
    y0 = min(max(cy * H - ch / 2, 0), H - ch)
    return rot.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
