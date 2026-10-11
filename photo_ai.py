"""
photo_ai.py — الميزات الذكية لبرنامج استوديو صور المعاملات
  1) كشف الوجه والقص بالمقاس مع توسيط الوجه
  2) ضبط الإضاءة تلقائياً
  3) تحسين الجودة إلى HD (تكبير + إزالة تشويش + حدة)
  4) إزالة الخلفية بالذكاء الاصطناعي (U2Net) مع بدائل تلقائية
  5) إزالة حبوب الوجه
  6) تبديل الملابس إلى ملابس رسمية (قوالب بدل رجالية ونسائية)
المتطلبات: numpy, opencv-python-headless, onnxruntime, Pillow
"""
import os
import sys
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

try:
    import cv2
except Exception:          # البرنامج يعمل بدونها لكن بميزات أقل
    cv2 = None

MODEL_NAME = "u2net_human_seg.onnx"
MODEL_DIR = os.path.join(os.path.expanduser("~"), ".photo_studio")
MODEL_URLS = ["https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx"]

# ------------------------------------------------------------------ قوائم القوالب والألوان
MEN_STYLES = {
    "بدلة رسمية بكرافتة": "suit_tie",
    "بدلة بدون كرافتة (ياقة مفتوحة)": "suit_open",
    "بدلة بفيونكة": "suit_bow",
    "قميص رسمي بكرافتة": "shirt_tie",
    "قميص رسمي (ياقة مفتوحة)": "shirt_open",
}
WOMEN_STYLES = {
    "بليزر رسمي مع بلوزة (V)": "blazer_v",
    "بليزر بدون ياقة (رقبة دائرية)": "blazer_round",
    "قميص رسمي بياقة": "shirt_collar",
}
JACKET_COLORS = {
    "كحلي": (28, 38, 72), "أسود": (26, 26, 30), "رمادي فحمي": (72, 76, 84),
    "رمادي فاتح": (150, 154, 162), "بني": (92, 64, 48), "بيج": (196, 176, 146),
    "أزرق ملكي": (36, 70, 140), "عنابي": (110, 28, 52), "أخضر زيتي": (60, 78, 56),
}
SHIRT_COLORS = {
    "أبيض": (246, 246, 248), "أزرق فاتح": (178, 205, 236), "وردي فاتح": (238, 205, 212),
    "رمادي فاتح": (214, 216, 220), "كريمي": (240, 232, 214), "أسود": (30, 30, 34),
}
TIE_COLORS = {
    "أحمر": (176, 28, 40), "كحلي": (24, 36, 92), "بورجندي": (110, 22, 40),
    "ذهبي": (190, 150, 50), "فضي": (176, 180, 188), "أخضر": (30, 100, 60),
    "أسود": (24, 24, 26), "أزرق سماوي": (60, 130, 200),
}


# ================================================================== 1) كشف الوجه والقص
_CASCADES = {}


def _cascade(name):
    if name not in _CASCADES:
        _CASCADES[name] = cv2.CascadeClassifier(cv2.data.haarcascades + name)
    return _CASCADES[name]


def detect_face(img):
    """يرجع (x, y, w, h) لأكبر وجه أمامي، أو None."""
    if cv2 is None:
        return None
    try:
        arr = np.array(img.convert("RGB"))
        h0, w0 = arr.shape[:2]
        sc = min(1.0, 800 / max(w0, h0))
        small = cv2.resize(arr, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA) if sc < 1 else arr
        gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY))
        min_sz = max(30, int(min(gray.shape) * 0.12))
        for neigh in (5, 3):
            for name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml"):
                faces = _cascade(name).detectMultiScale(gray, 1.1, neigh, minSize=(min_sz, min_sz))
                if len(faces):
                    f = max(faces, key=lambda r: r[2] * r[3])
                    return tuple(int(v / sc) for v in f)
    except Exception:
        pass
    return None


def auto_crop(img, aspect, face=None, zoom=2.5, top=0.65):
    """قص بنسبة aspect (العرض/الارتفاع) مع توسيط الوجه.
    zoom: ارتفاع الصورة بالنسبة لارتفاع الوجه (أكبر = رأس أصغر وكتفان أكثر)
    top : المسافة فوق الوجه (للشعر) بالنسبة لارتفاع الوجه."""
    img = img.convert("RGB")
    W, H = img.size
    face = face or detect_face(img)
    if face:
        fx, fy, fw, fh = face
        ch = fh * zoom
        cw = ch * aspect
        cx, y0 = fx + fw / 2, fy - fh * top
    else:                                   # بلا وجه: من المنتصف مع تفضيل الأعلى
        ch = min(H, W / aspect)
        cw = ch * aspect
        cx, y0 = W / 2, (H - ch) * 0.25
    x0 = cx - cw / 2
    l, t = max(0, int(-x0) + 1), max(0, int(-y0) + 1)
    r, b = max(0, int(x0 + cw - W) + 1), max(0, int(y0 + ch - H) + 1)
    arr = np.array(img)
    if l or t or r or b:                    # تمديد الحواف إذا خرج القص عن الصورة
        arr = np.pad(arr, ((t, b), (l, r), (0, 0)), mode="edge")
    x0, y0 = x0 + l, y0 + t
    box = (int(round(x0)), int(round(y0)), int(round(x0 + cw)), int(round(y0 + ch)))
    return Image.fromarray(arr).crop(box), face is not None


# ================================================================== 2) الإضاءة
def auto_light(img, face=None, target=140):
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    lo, hi = np.percentile(a, 0.5), np.percentile(a, 99.5)
    if hi - lo > 40:
        a = np.clip((a - lo) * 255.0 / (hi - lo), 0, 255)                              # توسيع المدى
    lum = a @ np.array([0.299, 0.587, 0.114], np.float32)
    if face:
        fx, fy, fw, fh = face
        reg = lum[max(0, int(fy + .15 * fh)):int(fy + .85 * fh), max(0, int(fx + .2 * fw)):int(fx + .8 * fw)]
        m = float(reg.mean()) if reg.size else float(lum.mean())
    else:
        m = float(lum.mean())
    m = min(max(m, 20.0), 235.0)
    gamma = float(np.clip(np.log(target / 255.0) / np.log(m / 255.0), 0.65, 1.5))
    a = 255.0 * (a / 255.0) ** gamma                                                    # ضبط سطوع الوجه
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ================================================================== 3) HD
def enhance_hd(img, target=None, denoise=True):
    """target = (العرض, الارتفاع) بالبكسل. تكبير على مراحل + إزالة تشويش + حدة."""
    img = img.convert("RGB")
    if cv2 is not None and denoise and max(img.size) < 1600:
        img = Image.fromarray(cv2.fastNlMeansDenoisingColored(np.array(img), None, 3, 3, 5, 15))
    if target:
        tw, th = target
        for _ in range(6):
            if img.width >= tw * 0.999:
                break
            f = min(1.6, tw / img.width)
            img = img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))), Image.LANCZOS)
            img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
        img = img.resize((tw, th), Image.LANCZOS)
    return img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=45, threshold=3))


# ================================================================== 4) إزالة الخلفية
_SESSION = None


def _model_path():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, getattr(sys, "_MEIPASS", ""), MODEL_DIR):
        p = os.path.join(d, MODEL_NAME)
        if d and os.path.exists(p):
            return p
    os.makedirs(MODEL_DIR, exist_ok=True)
    p = os.path.join(MODEL_DIR, MODEL_NAME)
    for url in MODEL_URLS:                      # تنزيل مرة واحدة (حوالي 170 ميجابايت)
        try:
            urllib.request.urlretrieve(url, p + ".part")
            os.replace(p + ".part", p)
            return p
        except Exception:
            continue
    return None


def _u2net_mask(img):
    global _SESSION
    import onnxruntime as ort
    if _SESSION is None:
        mp = _model_path()
        if not mp:
            return None
        _SESSION = ort.InferenceSession(mp, providers=["CPUExecutionProvider"])
    name = _SESSION.get_inputs()[0].name
    a = np.asarray(img.convert("RGB").resize((320, 320), Image.LANCZOS)).astype(np.float32)
    a = a / max(float(a.max()), 1e-6)
    a = (a - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    out = _SESSION.run(None, {name: a.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    out = (out - out.min()) / max(float(out.max() - out.min()), 1e-6)
    return Image.fromarray((out * 255).astype(np.uint8)).resize(img.size, Image.LANCZOS)


def _grabcut_mask(img, face):
    arr = np.array(img.convert("RGB"))
    H, W = arr.shape[:2]
    s = min(1.0, 600 / max(H, W))
    small = cv2.resize(arr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    h, w = small.shape[:2]
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    bw = max(3, int(0.04 * min(h, w)))
    border = np.concatenate([lab[:bw].reshape(-1, 3), lab[:, :bw].reshape(-1, 3), lab[:, -bw:].reshape(-1, 3)])
    bg = np.median(border, axis=0)                              # لون الخلفية من الحواف
    dist = np.sqrt(((lab - bg) ** 2).sum(2))
    m = np.full((h, w), cv2.GC_PR_FGD, np.uint8)
    m[dist < 22] = cv2.GC_PR_BGD
    m[dist < 10] = cv2.GC_BGD
    if face:
        fx, fy, fw, fh = [int(v * s) for v in face]
        m[fy + int(.25 * fh):fy + int(.85 * fh), fx + int(.25 * fw):fx + int(.75 * fw)] = cv2.GC_FGD
        m[:max(1, fy - int(.9 * fh)), :] = cv2.GC_BGD
    m[:bw, :] = np.where(dist[:bw, :] < 40, cv2.GC_BGD, m[:bw, :])
    cv2.grabCut(small, m, None, np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                4, cv2.GC_INIT_WITH_MASK)
    fg = ((m == cv2.GC_FGD) | (m == cv2.GC_PR_FGD)).astype(np.uint8) * 255
    return Image.fromarray(fg).resize(img.size, Image.LANCZOS)


def _guided(I, p, r, eps):
    k = (2 * r + 1, 2 * r + 1)
    box = lambda x: cv2.boxFilter(x, -1, k)
    mI, mp = box(I), box(p)
    a = (box(I * p) - mI * mp) / (box(I * I) - mI * mI + eps)
    b = mp - a * mI
    return box(a) * I + box(b)


def refine_mask(img, mask):
    """تنظيف القناع: أكبر جسم فقط، ملء الثقوب، وتنعيم الحواف حسب حواف الصورة."""
    arr = np.asarray(img.convert("RGB"))
    H, W = arr.shape[:2]
    m = np.clip((np.asarray(mask).astype(np.float32) / 255 - 0.35) / 0.45, 0, 1)
    b = (m > 0.5).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(b, 8)
    if n > 1:
        b = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    inv = 1 - b                                           # ثقوب لا تلمس الإطار = جزء من الجسم
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, 4)
    for i in range(1, n):
        x, y, w, h, _a = stats[i]
        if x > 0 and y > 0 and x + w < W and y + h < H:
            b[lab == i] = 1
    region = cv2.dilate(b, np.ones((5, 5), np.uint8), iterations=2).astype(np.float32)
    m = m * region
    m[b == 1] = np.maximum(m[b == 1], 0.9)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    m = np.clip(_guided(gray, m.astype(np.float32), max(4, W // 150), 1e-3), 0, 1)
    m = np.clip((m - 0.15) / 0.70, 0, 1)
    return Image.fromarray((m * 255).astype(np.uint8))


def replace_background(img, color, face=None):
    """يرجع (الصورة، ملاحظة). يستخدم الذكاء الاصطناعي ثم GrabCut ثم يتوقف."""
    img = img.convert("RGB")
    note, mask = "", None
    try:
        mask = _u2net_mask(img)
        if mask is None:
            note = "تعذر تحميل نموذج الذكاء الاصطناعي (يلزم إنترنت أول مرة)؛ استُخدمت طريقة بديلة."
    except Exception as e:
        note = f"تعذر تشغيل نموذج الذكاء الاصطناعي ({type(e).__name__})؛ استُخدمت طريقة بديلة."
    if mask is None and cv2 is not None:
        try:
            mask = _grabcut_mask(img, face)
        except Exception:
            mask = None
    if mask is None or cv2 is None:
        return img, note + " تعذرت إزالة الخلفية."
    mask = refine_mask(img, mask)
    cover = float(np.asarray(mask).mean() / 255)
    if not 0.08 < cover < 0.97:
        return img, note + " لم يُكتشف الشخص بشكل موثوق، تُركت الخلفية كما هي."
    m = np.asarray(mask).astype(np.float32)[..., None] / 255
    out = np.asarray(img).astype(np.float32) * m + np.array(color, np.float32) * (1 - m)
    return Image.fromarray(out.astype(np.uint8)), note


# ================================================================== 5) حبوب الوجه
def remove_blemishes(img, face, strength=1.0):
    """يزيل البقع الصغيرة (حبوب/نقاط حمراء أو داكنة) من الجبهة والخدين والذقن فقط.
    متحفّظ عمداً: لا يلمس الشعر والعيون والحواجب والشفاه."""
    if cv2 is None or not face:
        return img
    arr = np.array(img.convert("RGB"))
    H, W = arr.shape[:2]
    fx, fy, fw, fh = face
    x0, y0 = max(0, fx), max(0, fy)
    x1, y1 = min(W, fx + fw), min(H, fy + fh)
    if x1 - x0 < 40 or y1 - y0 < 40:
        return img
    roi = arr[y0:y1, x0:x1].copy()
    h, w = roi.shape[:2]
    zone = np.zeros((h, w), np.uint8)
    for a, b_, c, d in ((.28, .72, .12, .27),            # الجبهة (بعيداً عن خط الشعر)
                        (.14, .34, .50, .72), (.66, .86, .50, .72),   # الخدان
                        (.40, .60, .91, .98)):            # الذقن (تحت شفة الفم)
        zone[int(c * h):int(d * h), int(a * w):int(b_ * w)] = 255
    ycc = cv2.cvtColor(roi, cv2.COLOR_RGB2YCrCb)
    skin = cv2.inRange(ycc, (60, 138, 85), (255, 175, 128))
    skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    lab = cv2.cvtColor(roi, cv2.COLOR_RGB2LAB)
    k = max(7, int(w * 0.08)) | 1
    L, A = lab[..., 0].astype(np.float32), lab[..., 1].astype(np.float32)
    Lm = cv2.medianBlur(lab[..., 0], k).astype(np.float32)
    Am = cv2.medianBlur(lab[..., 1], k).astype(np.float32)
    s_ = max(0.4, strength)
    cand = (((Lm - L) > 16 / s_) | ((A - Am) > 10 / s_)) & (zone > 0)   # البشرة تُفحص حول البقعة لا عليها
    cand = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab_, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
    max_area = (w * 0.03) ** 2 * 3                      # البقع الصغيرة فقط
    keep = np.zeros((h, w), np.uint8)
    ring_k = np.ones((7, 7), np.uint8)
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if not 3 <= area <= max_area:
            continue
        comp = (lab_ == i).astype(np.uint8)
        ring = cv2.dilate(comp, ring_k, iterations=2) - cv2.dilate(comp, ring_k)
        if ring.sum() and (skin[ring > 0] > 0).mean() > 0.85:      # محاطة ببشرة فعلاً
            keep[comp > 0] = 255
    if keep.any():
        keep = cv2.dilate(keep, np.ones((3, 3), np.uint8), iterations=2)
        roi = cv2.inpaint(roi, keep, max(2, int(w * 0.012)), cv2.INPAINT_TELEA)
        arr[y0:y1, x0:x1] = roi
    return Image.fromarray(arr)


# ================================================================== 6) الملابس الرسمية
def _shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _neck_skin(img, cx, chin, u):
    a = np.asarray(img.convert("RGB"))
    H, W = a.shape[:2]
    y0, y1 = int(min(max(chin + .05 * u, 0), H - 2)), int(min(max(chin + .15 * u, 1), H - 1))
    x0, x1 = int(max(cx - .12 * u, 0)), int(min(cx + .12 * u, W - 1))
    reg = a[y0:max(y1, y0 + 1), x0:max(x1, x0 + 1)].reshape(-1, 3)
    return tuple(int(v) for v in reg.mean(0)) if reg.size else (200, 150, 120)


def dress(img, face, gender="men", style="suit_tie", jacket=(28, 38, 72),
          shirt=(246, 246, 248), tie=(176, 28, 40)):
    """يرسم بدلة/قميصاً رسمياً فوق منطقة الصدر والكتفين. الوجه والرقبة تبقى من الصورة الأصلية."""
    img = img.convert("RGB")
    W, H = img.size
    fx, fy, fw, fh = face
    cx, u, chin = fx + fw / 2, float(fw), fy + fh
    skin = _neck_skin(img, cx, chin, u)
    S = 2
    lay = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)

    def P(pts):
        return [(x * S, y * S) for x, y in pts]

    def poly(pts, fill, line=None, lw=1.2):
        d.polygon(P(pts), fill=tuple(fill) + (255,))
        if line:
            d.line(P(list(pts) + [pts[0]]), fill=tuple(line) + (255,), width=max(1, int(lw * S)))

    H1 = chin + 0.26 * u            # قاعدة الرقبة (أعلى الياقة)
    ey = H1 + 0.30 * u              # ارتفاع الكتف عند حافة الصورة
    bottom = H + 20
    has_jacket = style in ("suit_tie", "suit_open", "suit_bow", "blazer_v", "blazer_round")
    base_col = jacket if has_jacket else shirt
    jl, jd = _shade(jacket, 1.20), _shade(jacket, 0.72)
    sd = _shade(shirt, 0.84)

    def side(edge_x, sgn):
        nx, y0, y1 = cx + sgn * 0.46 * u, ey + 0.05 * u, H1 - 0.05 * u
        return [(edge_x + (nx - edge_x) * t, y0 + (y1 - y0) * t ** 1.7) for t in np.linspace(0, 1, 10)]

    # --- الجسم
    body = [(-20, bottom)] + side(-20, -1) + side(W + 20, 1)[::-1] + [(W + 20, bottom)]
    poly(body, base_col)
    # ظلال خفيفة على الكتفين
    d.line(P(side(-20, -1)), fill=_shade(base_col, 0.8) + (255,), width=2 * S)
    d.line(P(side(W + 20, 1)), fill=_shade(base_col, 0.8) + (255,), width=2 * S)

    def wings(spread=1.0, tip=0.27):
        for sg in (-1, 1):
            poly([(cx + sg * .17 * u, H1 - .20 * u), (cx + sg * .31 * u * spread, H1 - .12 * u),
                  (cx + sg * (.37 + .10 * (spread - 1)) * u, H1 + tip * u), (cx + sg * .05 * u, H1 + .12 * u)],
                 shirt, sd, 1.0)

    def lapels(wide=1.0):
        for sg in (-1, 1):
            poly([(cx + sg * .36 * u, H1 - .07 * u), (cx + sg * .66 * u * wide, H1 + .02 * u),
                  (cx + sg * .50 * u * wide, H1 + .30 * u), (cx + sg * .62 * u * wide, H1 + .46 * u),
                  (cx + sg * .04 * u, H1 + 1.15 * u)], jl, jd, 1.4)

    def vfill(top, apex, col):
        poly([(cx - top * u, H1 - .07 * u), (cx + top * u, H1 - .07 * u), (cx, H1 + apex * u)], col)

    def long_tie():
        poly([(cx - .075 * u, H1 + .10 * u), (cx + .075 * u, H1 + .10 * u),
              (cx + .095 * u, H1 + .28 * u), (cx - .095 * u, H1 + .28 * u)], tie, _shade(tie, .7), 1)
        poly([(cx - .085 * u, H1 + .28 * u), (cx + .085 * u, H1 + .28 * u), (cx + .17 * u, H1 + 1.35 * u),
              (cx, H1 + 1.45 * u), (cx - .17 * u, H1 + 1.35 * u)], tie, _shade(tie, .7), 1)
        poly([(cx - .085 * u, H1 + .28 * u), (cx, H1 + .28 * u), (cx, H1 + 1.45 * u), (cx - .17 * u, H1 + 1.35 * u)],
             _shade(tie, 1.18))

    def bow_tie():
        for sg in (-1, 1):
            poly([(cx + sg * .03 * u, H1 + .12 * u), (cx + sg * .24 * u, H1 + .01 * u),
                  (cx + sg * .24 * u, H1 + .25 * u)], tie, _shade(tie, .7), 1)
        poly([(cx - .045 * u, H1 + .08 * u), (cx + .045 * u, H1 + .08 * u),
              (cx + .045 * u, H1 + .17 * u), (cx - .045 * u, H1 + .17 * u)], _shade(tie, .85))

    def placket():
        d.line(P([(cx, H1 + .10 * u), (cx, bottom)]), fill=sd + (255,), width=2 * S)
        yy = H1 + .38 * u
        while yy < H:
            d.ellipse(P([(cx - .018 * u, yy - .018 * u), (cx + .018 * u, yy + .018 * u)]),
                      fill=_shade(shirt, .7) + (255,))
            yy += .32 * u

    st = style
    if st == "suit_tie":
        vfill(.36, 1.15, shirt); wings(); long_tie(); lapels()
    elif st == "suit_bow":
        vfill(.36, 1.15, shirt); wings(); bow_tie(); lapels()
    elif st == "suit_open":
        vfill(.36, .70, shirt)
        poly([(cx - .17 * u, H1 - .12 * u), (cx + .17 * u, H1 - .12 * u), (cx, H1 + .20 * u)], skin)
        wings(1.25, .33); lapels()
    elif st in ("shirt_tie", "shirt_open"):
        placket()
        if st == "shirt_tie":
            wings(); long_tie()
        else:
            poly([(cx - .17 * u, H1 - .12 * u), (cx + .17 * u, H1 - .12 * u), (cx, H1 + .22 * u)], skin)
            wings(1.25, .33)
    elif st == "blazer_v":
        vfill(.34, .80, shirt)
        poly([(cx - .19 * u, H1 - .10 * u), (cx + .19 * u, H1 - .10 * u), (cx, H1 + .26 * u)], skin)
        lapels(.9)
    elif st == "blazer_round":
        def bowl(half, depth, col):
            poly([(cx + np.sin(a) * half * u, H1 - .10 * u + np.cos(a) * depth * u)
                  for a in np.linspace(-np.pi / 2, np.pi / 2, 16)], col)
        bowl(.38, .46, shirt)          # التوب الداخلي
        bowl(.25, .20, skin)           # فتحة الرقبة (البشرة)
    elif st == "shirt_collar":
        placket()
        poly([(cx - .17 * u, H1 - .12 * u), (cx + .17 * u, H1 - .12 * u), (cx, H1 + .22 * u)], skin)
        wings(1.25, .33)

    # --- تحويل بدقة أعلى ثم إضافة ملمس قماش وتدرج
    lay = lay.convert("RGBa").resize((W, H), Image.LANCZOS).convert("RGBA")
    col = np.asarray(lay).astype(np.float32)
    alpha = col[..., 3:4] / 255
    rgb = col[..., :3]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vign = 1 - 0.16 * ((xx - cx) / (W / 2)) ** 2 - 0.10 * np.clip((yy - chin) / max(H - chin, 1), 0, 1)
    noise = np.random.default_rng(7).normal(0, 1, (H, W, 1)).astype(np.float32) * 0.014
    rgb = np.clip(rgb * vign[..., None] * (1 + noise), 0, 255)
    out = np.asarray(img).astype(np.float32) * (1 - alpha) + rgb * alpha
    # --- ظل الذقن على الياقة والرقبة
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).ellipse([cx - .36 * u, chin + .03 * u, cx + .36 * u, chin + .20 * u], fill=255)
    sh = np.asarray(sh.filter(ImageFilter.GaussianBlur(max(1, u * .05)))).astype(np.float32)[..., None] / 255
    out = out * (1 - sh * 0.30)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# ================================================================== خط المعالجة الكامل
def process_photo(img, w_cm, h_cm, o, preview=False):
    """o: قاموس الخيارات. يرجع (الصورة, قائمة ملاحظات).
    المفاتيح: crop, zoom, light, hd, blemish, bg(bool), bg_color, clothes(bool), gender, style, jacket, shirt, tie"""
    notes = []
    img = img.convert("RGB")
    if preview and max(img.size) > 1100:
        k = 1100 / max(img.size)
        img = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
    if cv2 is None:
        notes.append("مكتبة OpenCV غير مثبّتة؛ بعض الميزات معطّلة.")
    if o.get("crop", True):
        img, found = auto_crop(img, w_cm / h_cm, zoom=o.get("zoom", 2.5))
        if not found:
            notes.append("لم يُكتشف وجه أمامي واضح؛ تم القص من المنتصف.")
    if o.get("hd", True) and not preview:
        tw = min(4000, int(w_cm / 2.54 * 600))
        th = min(5600, int(h_cm / 2.54 * 600)) if o.get("crop", True) else int(tw * img.height / img.width)
        img = enhance_hd(img, (tw, th))
    face = detect_face(img)
    if o.get("light", True):
        img = auto_light(img, face)
    if o.get("blemish", True):
        if face:
            img = remove_blemishes(img, face)
        else:
            notes.append("تعذر تحديد الوجه لإزالة الحبوب.")
    if o.get("bg", True):
        img, n = replace_background(img, o.get("bg_color", (255, 255, 255)), face)
        if n.strip():
            notes.append(n.strip())
    if o.get("clothes", False):
        if face:
            img = dress(img, face, o.get("gender", "men"), o.get("style", "suit_tie"),
                        o.get("jacket", (28, 38, 72)), o.get("shirt", (246, 246, 248)),
                        o.get("tie", (176, 28, 40)))
        else:
            notes.append("تعذر تحديد الوجه لتبديل الملابس.")
    return img, notes
