"""
استوديو صور المعاملات — ترتيب صور شخصية على ورقة طباعة (A6 / A5 / A4 ...)
التشغيل:
    pip install PySide6 Pillow
    python photo_studio.py
(ضع الملف photo_core.py في نفس المجلد)
"""
import os
import sys
import json
from dataclasses import asdict

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal, QRectF, QPointF, QSizeF, QMarginsF, QThread, QSettings
from PySide6.QtGui import (QPixmap, QImage, QPainter, QColor, QPen, QFont, QPageSize,
                           QPageLayout, QIcon, QAction)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QGroupBox, QScrollArea, QSlider, QSpinBox, QDoubleSpinBox,
    QComboBox, QCheckBox, QRadioButton, QLineEdit, QFileDialog, QMessageBox, QColorDialog,
    QGraphicsView, QGraphicsScene, QAbstractSpinBox, QButtonGroup, QSplashScreen, QDockWidget, QProgressBar,
)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

import photo_core as pc
import photo_ai as ai

# ======================================================================= الأنماط
DARK = """
QWidget{background:#14141f;color:#e6e6f0;font-size:13px}
QLabel{background:transparent}
QPushButton{background:#2a2a3d;border:1px solid #3a3a52;border-radius:6px;padding:7px 10px}
QPushButton:hover{background:#36364f}
QPushButton#primary{background:#89b4fa;color:#11111b;font-weight:bold}
QPushButton#green{background:#a6e3a1;color:#11111b;font-weight:bold}
QPushButton#blue{background:#74a7ff;color:#11111b;font-weight:bold}
QPushButton#danger{background:#f38ba8;color:#11111b;font-weight:bold}
QGroupBox{border:1px solid #2f2f45;border-radius:8px;margin-top:14px;padding:10px}
QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top right;padding:0 6px;color:#89b4fa}
QDoubleSpinBox,QSpinBox,QComboBox{background:#1d1d2e;border:1px solid #3a3a52;border-radius:6px;padding:4px}
QScrollArea{border:none}
QSlider::groove:horizontal{height:4px;background:#3a3a52}
QSlider::handle:horizontal{background:#4d8dff;width:14px;margin:-6px 0;border-radius:3px}
QFrame#card{background:#191927;border:1px solid #2f2f45;border-radius:8px}
"""
LIGHT = """
QWidget{background:#f3f4f8;color:#1b1b2a;font-size:13px}
QLabel{background:transparent}
QPushButton{background:#e2e4ee;border:1px solid #c5c8d8;border-radius:6px;padding:7px 10px}
QPushButton:hover{background:#d4d7e6}
QPushButton#primary{background:#4d8dff;color:white;font-weight:bold}
QPushButton#green{background:#5cc47a;color:white;font-weight:bold}
QPushButton#blue{background:#4d8dff;color:white;font-weight:bold}
QPushButton#danger{background:#e8607f;color:white;font-weight:bold}
QGroupBox{border:1px solid #c5c8d8;border-radius:8px;margin-top:14px;padding:10px}
QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top right;padding:0 6px;color:#2f5fd0}
QDoubleSpinBox,QSpinBox,QComboBox{background:white;border:1px solid #c5c8d8;border-radius:6px;padding:4px}
QScrollArea{border:none}
QSlider::groove:horizontal{height:4px;background:#c5c8d8}
QSlider::handle:horizontal{background:#4d8dff;width:14px;margin:-6px 0;border-radius:3px}
QFrame#card{background:white;border:1px solid #c5c8d8;border-radius:8px}
"""


# ======================================================================= أدوات
def resource(name: str) -> str:
    """مسار ملف مرفق (يعمل من الكود المباشر ومن داخل ملف EXE)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def make_button(text, name=None, slot=None):
    b = QPushButton(text)
    b.setMinimumWidth(0)
    if name:
        b.setObjectName(name)
    if slot:
        b.clicked.connect(slot)
    return b


def make_slider(lo, hi, val):
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    return s


def plus_minus(spin):
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
    spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return spin


# ======================================================================= عارض يدعم التكبير والسحب
class PanZoomView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._item = None

    def set_image(self, pil):
        pm = pil_to_qpixmap(pil)
        first = self._item is None
        if first:
            self._item = self.scene().addPixmap(pm)
        else:
            self._item.setPixmap(pm)
        self.scene().setSceneRect(self._item.boundingRect())
        if first:
            self.fit()

    def fit(self):
        if self._item is not None:
            self.resetTransform()
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, f):
        self.scale(f, f)

    def wheelEvent(self, e):
        self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)


# ======================================================================= نافذة تحسين الألوان
class EnhanceDialog(QDialog):
    def __init__(self, base: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تحسين الألوان والوضوح")
        self.resize(900, 640)
        self.base = base
        self.result_img = None
        self.small = base.copy()
        self.small.thumbnail((900, 900))

        self.view = PanZoomView()
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(make_button("تكبير +", slot=lambda: self.view.zoom(1.25)))
        zoom_row.addWidget(make_button("تصغير −", slot=lambda: self.view.zoom(0.8)))
        zoom_row.addWidget(make_button("إظهار كاملة", slot=self.view.fit))
        warn = QLabel("⚠️ تنبيه: دقة الصورة الأصلية منخفضة نسبياً مقارنة بالمقاس المطلوب."
                      if min(base.size) < 600 else "")
        warn.setStyleSheet("color:#f9a825;font-size:11px")
        preview = QVBoxLayout()
        preview.addWidget(QLabel("حرّك عجلة الفأرة للتكبير، واسحب الصورة لمعاينة الوجه:"))
        preview.addWidget(self.view, 1)
        preview.addLayout(zoom_row)
        preview.addWidget(warn)

        self.s_bright = make_slider(-50, 50, 0)
        self.s_contrast = make_slider(-50, 50, 0)
        self.s_sharp = make_slider(0, 100, 0)
        self.s_smooth = make_slider(0, 65, 0)
        self.lbl_smooth = QLabel("مستوى تصفية الوجه: 0 / 65")

        controls = QVBoxLayout()
        title = QLabel("أدوات الضبط والمعايرة المعتدلة")
        title.setStyleSheet("color:#89b4fa;font-weight:bold")
        controls.addWidget(title)
        for text, sl in (("الإضاءة:", self.s_bright), ("التباين:", self.s_contrast),
                         ("الحدة والوضوح (نطاق متوازن لمنع التحبيب):", self.s_sharp),
                         ("تصفية الوجه (0 = بدون، مستوى معتدل):", self.s_smooth)):
            controls.addWidget(QLabel(text))
            controls.addWidget(sl)
        controls.addWidget(self.lbl_smooth)
        controls.addWidget(make_button("استعادة الأصل", slot=self.reset))
        controls.addStretch(1)
        controls.addWidget(make_button("تطبيق التعديلات", "green", self.apply))
        controls.addWidget(make_button("إلغاء", slot=self.reject))

        root = QHBoxLayout(self)
        root.addLayout(preview, 3)
        root.addLayout(controls, 2)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self.update_preview)
        for sl in (self.s_bright, self.s_contrast, self.s_sharp, self.s_smooth):
            sl.valueChanged.connect(lambda _=0: self.timer.start())
        self.update_preview()

    def params(self):
        return (self.s_bright.value(), self.s_contrast.value(),
                self.s_sharp.value(), self.s_smooth.value())

    def update_preview(self):
        self.lbl_smooth.setText(f"مستوى تصفية الوجه: {self.s_smooth.value()} / 65")
        self.view.set_image(pc.enhance_image(self.small, *self.params()))

    def reset(self):
        for sl in (self.s_bright, self.s_contrast, self.s_sharp, self.s_smooth):
            sl.setValue(0)

    def apply(self):
        self.result_img = pc.enhance_image(self.base, *self.params())
        self.accept()


# ======================================================================= نافذة القص والميلان
class CropView(QWidget):
    changed = Signal()

    def __init__(self, small: Image.Image, aspect: float):
        super().__init__()
        self.base, self.aspect = small, aspect
        self.angle, self.cx, self.cy, self.scale = 0.0, 0.5, 0.5, 1.0
        self._drag = False
        self.setMinimumSize(420, 520)
        self._rebuild()

    def _rebuild(self):
        rot = self.base.rotate(self.angle, resample=Image.BILINEAR, expand=True,
                               fillcolor=(255, 255, 255)) if self.angle else self.base
        self.pix = pil_to_qpixmap(rot)
        self.update()

    def set_angle(self, a):
        self.angle = a
        self._rebuild()

    def set_scale(self, s):
        self.scale = s
        self.update()

    def _img_rect(self):
        w, h = self.width(), self.height()
        pw, ph = self.pix.width(), self.pix.height()
        k = min(w / pw, h / ph)
        dw, dh = pw * k, ph * k
        return QRectF((w - dw) / 2, (h - dh) / 2, dw, dh)

    def _crop_rect(self):
        r = self._img_rect()
        W, H = r.width(), r.height()
        if W / H > self.aspect:
            mh, mw = H, H * self.aspect
        else:
            mw, mh = W, W / self.aspect
        cw, ch = mw * self.scale, mh * self.scale
        x = min(max(self.cx * W - cw / 2, 0), W - cw)
        y = min(max(self.cy * H - ch / 2, 0), H - ch)
        return QRectF(r.x() + x, r.y() + y, cw, ch)

    def paintEvent(self, _):
        p = QPainter(self)
        r = self._img_rect()
        p.drawPixmap(r, self.pix, QRectF(self.pix.rect()))
        c = self._crop_rect()
        shade = QColor(0, 0, 0, 150)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), c.top() - r.top()), shade)
        p.fillRect(QRectF(r.left(), c.bottom(), r.width(), r.bottom() - c.bottom()), shade)
        p.fillRect(QRectF(r.left(), c.top(), c.left() - r.left(), c.height()), shade)
        p.fillRect(QRectF(c.right(), c.top(), r.right() - c.right(), c.height()), shade)
        p.setPen(QPen(QColor("#89b4fa"), 2))
        p.drawRect(c)
        p.setPen(QPen(QColor(255, 255, 255, 110), 1))
        for i in (1, 2):                       # خطوط الأثلاث للمساعدة في توسيط الوجه
            x = c.left() + c.width() * i / 3
            y = c.top() + c.height() * i / 3
            p.drawLine(QPointF(x, c.top()), QPointF(x, c.bottom()))
            p.drawLine(QPointF(c.left(), y), QPointF(c.right(), y))

    def _move(self, pos):
        r = self._img_rect()
        self.cx = min(max((pos.x() - r.x()) / r.width(), 0), 1)
        self.cy = min(max((pos.y() - r.y()) / r.height(), 0), 1)
        self.update()

    def mousePressEvent(self, e):
        self._drag = True
        self._move(e.position())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._move(e.position())

    def mouseReleaseEvent(self, _):
        self._drag = False

    def wheelEvent(self, e):
        f = 1.05 if e.angleDelta().y() > 0 else 0.95
        self.scale = min(max(self.scale * f, 0.2), 1.0)
        self.changed.emit()
        self.update()


class CropDialog(QDialog):
    def __init__(self, item: pc.PhotoItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("القص وتعديل الاستقامة")
        self.resize(560, 760)
        self.full = item.current
        self.aspect = item.w / item.h
        small = self.full.copy()
        small.thumbnail((900, 900))
        self.view = CropView(small, self.aspect)

        self.s_angle = make_slider(-200, 200, 0)       # ‎-20.0° … +20.0°
        self.s_size = make_slider(20, 100, 100)
        self.lbl_angle = QLabel("زاوية الميلان: 0.0°")
        self.lbl_size = QLabel("حجم القص: 100%")
        self.s_angle.valueChanged.connect(self._angle)
        self.s_size.valueChanged.connect(self._size)
        self.view.changed.connect(self._sync_size)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("اسحب لتحديد مركز القص، وعجلة الفأرة لتغيير الحجم (النسبة ثابتة)."))
        lay.addWidget(self.view, 1)
        lay.addWidget(self.lbl_angle)
        lay.addWidget(self.s_angle)
        lay.addWidget(self.lbl_size)
        lay.addWidget(self.s_size)
        row = QHBoxLayout()
        row.addWidget(make_button("تطبيق التعديلات والقص", "green", self.apply))
        row.addWidget(make_button("إعادة ضبط", slot=self.reset))
        row.addWidget(make_button("إلغاء", slot=self.reject))
        lay.addLayout(row)
        self.result_img = None

    def _angle(self, v):
        self.lbl_angle.setText(f"زاوية الميلان: {v / 10:.1f}°")
        self.view.set_angle(v / 10)

    def _size(self, v):
        self.lbl_size.setText(f"حجم القص: {v}%")
        self.view.set_scale(v / 100)

    def _sync_size(self):
        self.s_size.blockSignals(True)
        self.s_size.setValue(int(self.view.scale * 100))
        self.s_size.blockSignals(False)
        self.lbl_size.setText(f"حجم القص: {self.s_size.value()}%")

    def reset(self):
        self.s_angle.setValue(0)
        self.s_size.setValue(100)
        self.view.cx = self.view.cy = 0.5
        self.view.update()

    def apply(self):
        v = self.view
        self.result_img = pc.crop_rotated(self.full, v.angle, v.cx, v.cy, v.scale, self.aspect)
        self.accept()


# ======================================================================= نافذة لون الخلفية
class BackgroundDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("لون خلفية الصورة")
        self.choice = None            # ("color", rgb) | ("restore", None)
        self.tol = 40
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("اختر اللون المناسب لصورة المعاملات الرسمية:"))
        grid = QGridLayout()
        for i, (name, rgb) in enumerate(pc.BACKGROUNDS.items()):
            b = QPushButton(name)
            dark = sum(rgb) < 380
            b.setStyleSheet(f"background:rgb{rgb};color:{'white' if dark else 'black'};font-weight:bold")
            b.clicked.connect(lambda _=False, c=rgb: self._pick(c))
            grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addWidget(make_button("اختيار لون مخصص...", slot=self._custom))
        self.lbl = QLabel("حساسية اكتشاف الخلفية: 40")
        self.sl = make_slider(10, 90, 40)
        self.sl.valueChanged.connect(self._tol)
        lay.addWidget(self.lbl)
        lay.addWidget(self.sl)
        lay.addWidget(make_button("استعادة الصورة الأصلية", slot=self._restore))
        lay.addWidget(make_button("إلغاء", slot=self.reject))

    def _tol(self, v):
        self.tol = v
        self.lbl.setText(f"حساسية اكتشاف الخلفية: {v}")

    def _pick(self, rgb):
        self.choice = ("color", rgb)
        self.accept()

    def _custom(self):
        c = QColorDialog.getColor(QColor(255, 255, 255), self, "لون الخلفية")
        if c.isValid():
            self._pick((c.red(), c.green(), c.blue()))

    def _restore(self):
        self.choice = ("restore", None)
        self.accept()


# ======================================================================= التحسين الاحترافي (ذكاء اصطناعي)
class Worker(QThread):
    done = Signal(object, object)          # (صورة أو None, ملاحظات)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            img, notes = self.fn()
            self.done.emit(img, notes)
        except Exception as e:             # لا نترك البرنامج ينهار
            self.done.emit(None, [f"حدث خطأ أثناء المعالجة: {e}"])


class ProDialog(QDialog):
    def __init__(self, item: pc.PhotoItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✨ تحسين احترافي بالذكاء الاصطناعي")
        self.resize(1000, 720)
        self.item, self.result_img, self.worker = item, None, None

        def chk(text, on=True):
            c = QCheckBox(text)
            c.setChecked(on)
            return c

        self.c_crop = chk("قص تلقائي بالمقاس مع توسيط الوجه")
        self.sl_zoom = make_slider(20, 36, 26)
        self.lbl_zoom = QLabel("حجم الرأس: متوسط")
        self.sl_zoom.valueChanged.connect(
            lambda v: self.lbl_zoom.setText("حجم الرأس: " + ("كبير" if v < 24 else "متوسط" if v < 30 else "صغير (كتفان أكثر)")))
        self.c_light = chk("ضبط الإضاءة تلقائياً")
        self.c_hd = chk("تحسين الجودة إلى HD (دقة طباعة 600 DPI)")
        self.c_blem = chk("إزالة حبوب الوجه")
        self.c_bg = chk("إزالة الخلفية بالذكاء الاصطناعي")
        self.cmb_bg = QComboBox()
        self.cmb_bg.addItems(pc.BACKGROUNDS.keys())
        self.c_clo = chk("تغيير الملابس إلى ملابس رسمية", False)
        self.cmb_gender = QComboBox()
        self.cmb_gender.addItems(["رجال", "سيدات"])
        self.cmb_style, self.cmb_jacket = QComboBox(), QComboBox()
        self.cmb_shirt, self.cmb_tie = QComboBox(), QComboBox()
        self.cmb_jacket.addItems(ai.JACKET_COLORS.keys())
        self.cmb_shirt.addItems(ai.SHIRT_COLORS.keys())
        self.cmb_tie.addItems(ai.TIE_COLORS.keys())
        self.cmb_gender.currentIndexChanged.connect(self._fill_styles)
        self.cmb_style.currentIndexChanged.connect(self._tie_enabled)
        self._fill_styles()

        form = QVBoxLayout()
        for w in (self.c_crop, self.lbl_zoom, self.sl_zoom, self.c_light, self.c_hd, self.c_blem, self.c_bg, self.cmb_bg):
            form.addWidget(w)
        form.addWidget(self.c_clo)
        grid = QGridLayout()
        for r, (t, w) in enumerate((("النوع:", self.cmb_gender), ("القالب:", self.cmb_style),
                                    ("لون البدلة:", self.cmb_jacket), ("لون القميص:", self.cmb_shirt),
                                    ("لون الكرافتة:", self.cmb_tie))):
            grid.addWidget(QLabel(t), r, 0)
            grid.addWidget(w, r, 1)
        form.addLayout(grid)
        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setStyleSheet("color:#f9a825")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.hide()
        self.btn_prev = make_button("👁️ معاينة", slot=self.preview)
        self.btn_ok = make_button("✅ تطبيق على الصورة", "green", self.apply)
        self.btn_cancel = make_button("إلغاء", slot=self.reject)
        form.addWidget(self.lbl_note)
        form.addStretch(1)
        form.addWidget(self.bar)
        form.addWidget(self.btn_prev)
        form.addWidget(self.btn_ok)
        form.addWidget(self.btn_cancel)

        self.lbl_before, self.lbl_after = QLabel(), QLabel()
        for lb, t in ((self.lbl_before, "قبل"), (self.lbl_after, "بعد (اضغط معاينة)")):
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setMinimumSize(300, 420)
            lb.setText(t)
        pm = pil_to_qpixmap(item.current)
        self.lbl_before.setPixmap(pm.scaled(330, 520, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        pics = QHBoxLayout()
        pics.addWidget(self.lbl_before)
        pics.addWidget(self.lbl_after)
        root = QHBoxLayout(self)
        root.addLayout(form, 2)
        root.addLayout(pics, 5)

    def _fill_styles(self):
        self.cmb_style.clear()
        self.cmb_style.addItems((ai.MEN_STYLES if self.cmb_gender.currentIndex() == 0 else ai.WOMEN_STYLES).keys())
        self.cmb_jacket.setCurrentText("كحلي" if self.cmb_gender.currentIndex() == 0 else "عنابي")
        self._tie_enabled()

    def _tie_enabled(self):
        st = (ai.MEN_STYLES if self.cmb_gender.currentIndex() == 0 else ai.WOMEN_STYLES).get(self.cmb_style.currentText(), "")
        self.cmb_tie.setEnabled(st in ("suit_tie", "suit_bow", "shirt_tie"))

    def options(self):
        men = self.cmb_gender.currentIndex() == 0
        styles = ai.MEN_STYLES if men else ai.WOMEN_STYLES
        return dict(crop=self.c_crop.isChecked(), zoom=self.sl_zoom.value() / 10, light=self.c_light.isChecked(),
                    hd=self.c_hd.isChecked(), blemish=self.c_blem.isChecked(), bg=self.c_bg.isChecked(),
                    bg_color=pc.BACKGROUNDS[self.cmb_bg.currentText()], clothes=self.c_clo.isChecked(),
                    gender="men" if men else "women", style=styles.get(self.cmb_style.currentText(), "suit_tie"),
                    jacket=ai.JACKET_COLORS[self.cmb_jacket.currentText()],
                    shirt=ai.SHIRT_COLORS[self.cmb_shirt.currentText()], tie=ai.TIE_COLORS[self.cmb_tie.currentText()])

    def _busy(self, on):
        self.bar.setVisible(on)
        for b in (self.btn_prev, self.btn_ok):
            b.setEnabled(not on)

    def _run(self, preview, after):
        o, src, (w, h) = self.options(), self.item.current, (self.item.w, self.item.h)
        self.lbl_note.setText("جارٍ المعالجة... (أول استخدام لإزالة الخلفية قد يحتاج تنزيل النموذج)")
        self._busy(True)
        self.worker = Worker(lambda: ai.process_photo(src, w, h, o, preview=preview))
        self.worker.done.connect(after)
        self.worker.start()

    def preview(self):
        self._run(True, self._on_preview)

    def _on_preview(self, img, notes):
        self._busy(False)
        self.lbl_note.setText("\n".join(notes))
        if img is not None:
            pm = pil_to_qpixmap(img)
            self.lbl_after.setPixmap(pm.scaled(330, 520, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))

    def apply(self):
        self._run(False, self._on_apply)

    def _on_apply(self, img, notes):
        self._busy(False)
        if img is None:
            self.lbl_note.setText("\n".join(notes))
            return
        self.result_img = img
        self.accept()


# ======================================================================= بطاقة الصورة
class ItemCard(QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, item: pc.PhotoItem):
        super().__init__()
        self.setObjectName("card")
        self.item = item

        self.thumb = QLabel()
        self.thumb.setFixedSize(76, 100)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel(self.fontMetrics().elidedText(item.name, Qt.TextElideMode.ElideMiddle, 300))
        name.setToolTip(item.name)
        name.setMinimumWidth(0)
        name.setStyleSheet("color:#89b4fa;font-weight:bold")

        self.sp_w = plus_minus(QDoubleSpinBox())
        self.sp_h = plus_minus(QDoubleSpinBox())
        for sp, v in ((self.sp_w, item.w), (self.sp_h, item.h)):
            sp.setRange(0.5, 30.0)
            sp.setSingleStep(0.1)
            sp.setDecimals(1)
            sp.setValue(v)
        self.sp_n = plus_minus(QSpinBox())
        self.sp_n.setRange(1, 300)
        self.sp_n.setValue(item.copies)
        self.ed_name = QLineEdit(item.name_text)
        self.ed_name.setPlaceholderText("الاسم")
        self.ed_id = QLineEdit(item.id_text)
        self.ed_id.setPlaceholderText("الرقم القومي")
        self.ed_name.textChanged.connect(self._text)
        self.ed_id.textChanged.connect(self._text)
        self.sp_w.valueChanged.connect(self._edited)
        self.sp_h.valueChanged.connect(self._edited)
        self.sp_n.valueChanged.connect(self._edited)

        form = QGridLayout()
        form.addWidget(QLabel("العرض (سم):"), 0, 0)
        form.addWidget(self.sp_w, 0, 1)
        form.addWidget(QLabel("الارتفاع (سم):"), 1, 0)
        form.addWidget(self.sp_h, 1, 1)
        form.addWidget(QLabel("عدد النسخ:"), 2, 0)
        form.addWidget(self.sp_n, 2, 1)
        form.addWidget(QLabel("الاسم:"), 3, 0)
        form.addWidget(self.ed_name, 3, 1)
        form.addWidget(QLabel("الرقم القومي:"), 4, 0)
        form.addWidget(self.ed_id, 4, 1)
        top = QHBoxLayout()
        top.addLayout(form, 1)
        top.addWidget(self.thumb)

        btns = QGridLayout()
        btns.addWidget(make_button("✨ تحسين احترافي (ذكاء اصطناعي)", "primary", self.pro), 0, 0, 1, 2)
        btns.addWidget(make_button("🎨 تحسين الألوان", slot=self.enhance), 1, 0)
        btns.addWidget(make_button("✂️ قص وميلان", slot=self.crop), 1, 1)
        btns.addWidget(make_button("🖼️ لون الخلفية", slot=self.background), 2, 0)
        btns.addWidget(make_button("↩️ استرجاع الأصل", slot=self.restore), 2, 1)
        btns.addWidget(make_button("🔍 ضبط الحواف", slot=self.trim), 3, 1)
        btns.addWidget(make_button("🗑️ حذف", "danger", lambda: self.removed.emit(self)), 3, 0)

        lay = QVBoxLayout(self)
        lay.addWidget(name)
        lay.addLayout(top)
        lay.addLayout(btns)
        self.refresh_thumb()

    def refresh_thumb(self):
        pm = pil_to_qpixmap(self.item.current)
        self.thumb.setPixmap(pm.scaled(76, 100, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))

    def _edited(self):
        self.item.w, self.item.h = self.sp_w.value(), self.sp_h.value()
        self.item.copies = self.sp_n.value()
        self.changed.emit()

    def _text(self):
        self.item.name_text = self.ed_name.text()
        self.item.id_text = self.ed_id.text()
        self.changed.emit()

    def _done(self, img):
        self.item.current = img
        self.refresh_thumb()
        self.changed.emit()

    def pro(self):
        d = ProDialog(self.item, self.window())
        if d.exec() and d.result_img is not None:
            self._done(d.result_img)

    def enhance(self):
        d = EnhanceDialog(self.item.current, self.window())
        if d.exec() and d.result_img is not None:
            self._done(d.result_img)

    def crop(self):
        d = CropDialog(self.item, self.window())
        if d.exec() and d.result_img is not None:
            self._done(d.result_img)

    def background(self):
        d = BackgroundDialog(self.window())
        if not d.exec() or not d.choice:
            return
        kind, rgb = d.choice
        if kind == "restore":
            self._done(self.item.original.copy())
        else:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._done(pc.replace_background(self.item.current, rgb, d.tol))
            finally:
                QApplication.restoreOverrideCursor()

    def restore(self):
        self._done(self.item.original.copy())

    def trim(self):
        self._done(pc.trim_edges(self.item.current, 1.5))


# ======================================================================= النافذة الرئيسية
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("استوديو صور المعاملات")
        self.resize(1250, 820)
        self.items, self.cards = [], []
        self.s = pc.Settings()
        self.page, self.dpi, self.dark = 0, 100.0, True
        self.layout_pages = [[]]

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh_preview)

        self._build_ui()
        self._default_state = self.saveState()
        st = QSettings("PhotoStudio", "PhotoStudio")      # استعادة آخر ترتيب للنوافذ
        if st.value("geometry"):
            self.restoreGeometry(st.value("geometry"))
        if st.value("state"):
            self.restoreState(st.value("state"))
        QTimer.singleShot(0, self.fit_page)

    # -------------------------------------------------------------- واجهة
    def _build_ui(self):
        # ---- شريط الأدوات العلوي
        self.btn_add = make_button("إضافة صور جديدة (+)", "primary", self.add_images)
        self.btn_theme = make_button("☀️ نمط فاتح", slot=self.toggle_theme)
        self.lbl_page = QLabel()
        bar = QHBoxLayout()
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_theme)
        bar.addWidget(self.lbl_page, 1)
        bar.addWidget(make_button("السابقة ▸", slot=lambda: self.go(-1)))
        bar.addWidget(make_button("◂ التالية", slot=lambda: self.go(1)))
        bar2 = QHBoxLayout()
        bar2.addWidget(make_button("تكبير (+)", slot=lambda: self.zoom(1.25)))
        bar2.addWidget(make_button("تصغير (−)", slot=lambda: self.zoom(0.8)))
        bar2.addWidget(make_button("مقدمة الصفحة", slot=self.fit_page))
        bar2.addWidget(make_button("100% الحجم الحقيقي", slot=self.real_size))

        # ---- المعاينة
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.preview)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left = QVBoxLayout()
        left.addLayout(bar)
        left.addLayout(bar2)
        left.addWidget(self.scroll, 1)

        # ---- لوحة الإعدادات
        g1 = QGroupBox("إعدادات ورق الطباعة والإخراج")
        self.cmb_paper = QComboBox()
        self.cmb_paper.addItems(pc.PAPERS.keys())
        self.cmb_paper.currentTextChanged.connect(self.paper_changed)
        self.rb_portrait = QRadioButton("عمودي (Portrait)")
        self.rb_land = QRadioButton("أفقي (Landscape)")
        self.rb_portrait.setChecked(True)
        self.rb_land.toggled.connect(self.orient_changed)
        f1 = QVBoxLayout(g1)
        r = QHBoxLayout()
        r.addWidget(QLabel("مقاس الورق:"))
        r.addWidget(self.cmb_paper, 1)
        f1.addLayout(r)
        r = QHBoxLayout()
        r.addWidget(self.rb_portrait)
        r.addWidget(self.rb_land)
        f1.addLayout(r)

        g2 = QGroupBox("المسافات بين الصور وخطوط القص بالمقص")
        self.sp_gx = plus_minus(QDoubleSpinBox())
        self.sp_gy = plus_minus(QDoubleSpinBox())
        for sp, v in ((self.sp_gx, self.s.gap_x), (self.sp_gy, self.s.gap_y)):
            sp.setRange(0.0, 3.0)
            sp.setSingleStep(0.05)
            sp.setDecimals(2)
            sp.setValue(v)
            sp.valueChanged.connect(self.settings_changed)
        self.chk_lines = QCheckBox("إظهار خطوط القص بالمقص")
        self.chk_lines.setChecked(True)
        self.chk_lines.toggled.connect(self.settings_changed)
        self.cmb_style = QComboBox()
        self.cmb_style.addItems(["إطار كامل", "علامات الزوايا"])
        self.cmb_style.currentIndexChanged.connect(self.settings_changed)
        self.sp_mm = plus_minus(QDoubleSpinBox())
        self.sp_mm.setRange(0.05, 2.0)
        self.sp_mm.setSingleStep(0.05)
        self.sp_mm.setDecimals(2)
        self.sp_mm.setValue(self.s.line_mm)
        self.sp_mm.valueChanged.connect(self.settings_changed)
        self.btn_color = make_button("لون الخط", slot=self.pick_line_color)
        self.sp_cap = plus_minus(QDoubleSpinBox())
        self.sp_cap.setRange(4.0, 24.0)
        self.sp_cap.setSingleStep(0.5)
        self.sp_cap.setDecimals(1)
        self.sp_cap.setValue(self.s.caption_pt)
        self.sp_cap.valueChanged.connect(self.settings_changed)
        self.chk_inside = QCheckBox("كتابة الاسم والرقم داخل الصورة")
        self.chk_inside.setChecked(self.s.caption_inside)
        self.chk_inside.toggled.connect(self.settings_changed)
        self.chk_bold = QCheckBox("خط عريض للاسم والرقم")
        self.chk_bold.setChecked(self.s.caption_bold)
        self.chk_bold.toggled.connect(self.settings_changed)
        f2 = QGridLayout(g2)
        f2.addWidget(QLabel("المسافة الأفقية (سم):"), 0, 0)
        f2.addWidget(self.sp_gx, 0, 1)
        f2.addWidget(QLabel("المسافة العمودية (سم):"), 1, 0)
        f2.addWidget(self.sp_gy, 1, 1)
        f2.addWidget(self.chk_lines, 2, 0)
        f2.addWidget(self.cmb_style, 2, 1)
        f2.addWidget(QLabel("سماكة الخط (مم):"), 3, 0)
        f2.addWidget(self.sp_mm, 3, 1)
        f2.addWidget(self.btn_color, 4, 0, 1, 2)
        f2.addWidget(QLabel("حجم خط الاسم والرقم (نقطة):"), 5, 0)
        f2.addWidget(self.sp_cap, 5, 1)
        f2.addWidget(self.chk_bold, 6, 0, 1, 2)
        f2.addWidget(self.chk_inside, 7, 0, 1, 2)

        prj = QHBoxLayout()
        prj.addWidget(make_button("💾 حفظ المشروع", slot=self.save_project))
        prj.addWidget(make_button("📂 فتح مشروع", slot=self.open_project))

        self.rb_group = QRadioButton("تجميع نسخ كل صورة")
        self.rb_seq = QRadioButton("توزيع الصور بالتتابع")
        self.rb_group.setChecked(True)
        self.rb_seq.toggled.connect(self.settings_changed)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_group)
        grp.addButton(self.rb_seq)
        dist = QHBoxLayout()
        dist.addWidget(self.rb_group)
        dist.addWidget(self.rb_seq)

        self.cards_box = QVBoxLayout()
        settings_w = QWidget()
        sl = QVBoxLayout(settings_w)
        sl.addWidget(g1)
        sl.addWidget(g2)
        sl.addLayout(prj)
        sl.addLayout(dist)
        sl.addStretch(1)
        items_w = QWidget()
        il = QVBoxLayout(items_w)
        il.addLayout(self.cards_box)
        il.addStretch(1)

        def scroller(widget):
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(widget)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            sa.setMinimumWidth(380)
            return sa

        # ---- نوافذ قابلة للسحب والتعويم وإعادة الترتيب (من شريط عنوان كل نافذة)
        self.dock_settings = QDockWidget("⚙️ الإعدادات", self)
        self.dock_settings.setObjectName("dock_settings")
        self.dock_settings.setWidget(scroller(settings_w))
        self.dock_items = QDockWidget("🖼️ الصور", self)
        self.dock_items.setObjectName("dock_items")
        self.dock_items.setWidget(scroller(items_w))
        feats = (QDockWidget.DockWidgetFeature.DockWidgetMovable
                 | QDockWidget.DockWidgetFeature.DockWidgetFloatable
                 | QDockWidget.DockWidgetFeature.DockWidgetClosable)
        for dk in (self.dock_settings, self.dock_items):
            dk.setFeatures(feats)
        self.setDockNestingEnabled(True)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_settings)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_items)
        self.splitDockWidget(self.dock_settings, self.dock_items, Qt.Orientation.Vertical)
        self.resizeDocks([self.dock_settings, self.dock_items], [380, 460], Qt.Orientation.Vertical)

        view_menu = self.menuBar().addMenu("عرض")
        view_menu.addAction(self.dock_settings.toggleViewAction())
        view_menu.addAction(self.dock_items.toggleViewAction())
        view_menu.addSeparator()
        act = QAction("إعادة ترتيب النوافذ للوضع الافتراضي", self)
        act.triggered.connect(self.reset_layout)
        view_menu.addAction(act)

        # ---- الشريط السفلي
        bottom = QHBoxLayout()
        bottom.addWidget(make_button("🖨️ طباعة مباشرة (100%)", "blue", self.print_pages))
        bottom.addWidget(make_button("📄 حفظ PDF عالي الجودة", "green", self.export_pdf))
        bottom.addWidget(make_button("🖼️ حفظ كصور PNG (600 DPI)", "blue", self.export_png))

        root = QVBoxLayout()
        root.addLayout(left, 1)
        root.addLayout(bottom)
        w = QWidget()
        w.setLayout(root)
        self.setCentralWidget(w)

    def reset_layout(self):
        self.restoreState(self._default_state)
        self.dock_settings.show()
        self.dock_items.show()

    def closeEvent(self, e):
        st = QSettings("PhotoStudio", "PhotoStudio")
        st.setValue("geometry", self.saveGeometry())
        st.setValue("state", self.saveState())
        super().closeEvent(e)

    # -------------------------------------------------------------- إعدادات
    def settings_changed(self, *_):
        s = self.s
        s.gap_x, s.gap_y = self.sp_gx.value(), self.sp_gy.value()
        s.show_lines = self.chk_lines.isChecked()
        s.line_style = "full" if self.cmb_style.currentIndex() == 0 else "corners"
        s.line_mm = self.sp_mm.value()
        s.sequential = self.rb_seq.isChecked()
        s.caption_pt = self.sp_cap.value()
        s.caption_bold = self.chk_bold.isChecked()
        s.caption_inside = self.chk_inside.isChecked()
        self.schedule()

    def paper_changed(self, name):
        self.s.paper_w, self.s.paper_h = pc.PAPERS[name]
        self.fit_page()

    def orient_changed(self, _):
        self.s.landscape = self.rb_land.isChecked()
        self.fit_page()

    def pick_line_color(self):
        c = QColorDialog.getColor(QColor(*self.s.line_color), self, "لون خط القص")
        if c.isValid():
            self.s.line_color = (c.red(), c.green(), c.blue())
            self.schedule()

    def toggle_theme(self):
        self.dark = not self.dark
        QApplication.instance().setStyleSheet(DARK if self.dark else LIGHT)
        self.btn_theme.setText("☀️ نمط فاتح" if self.dark else "🌙 نمط داكن")

    # -------------------------------------------------------------- الصور
    def add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "اختر الصور", "", "صور (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)")
        for p in paths:
            try:
                self.add_item(pc.PhotoItem.from_path(p))
            except Exception as e:
                QMessageBox.warning(self, "تعذر فتح الصورة", f"{os.path.basename(p)}\n{e}")
        self.schedule()

    def add_item(self, item):
        card = ItemCard(item)
        card.changed.connect(self.schedule)
        card.removed.connect(self.remove_card)
        self.items.append(item)
        self.cards.append(card)
        self.cards_box.addWidget(card)

    def remove_card(self, card):
        i = self.cards.index(card)
        self.cards.pop(i)
        self.items.pop(i)
        card.setParent(None)
        card.deleteLater()
        self.schedule()

    # -------------------------------------------------------------- المعاينة
    def schedule(self):
        self.timer.start()

    def refresh_preview(self):
        self.layout_pages = pc.layout(self.items, self.s)
        n = len(self.layout_pages)
        self.page = max(0, min(self.page, n - 1))
        img = pc.render_page(self.items, self.layout_pages[self.page], self.s, self.dpi)
        pm = pil_to_qpixmap(img)
        self.preview.setPixmap(pm)
        self.preview.resize(pm.size())
        pw, ph = self.s.page_size()
        total = sum(len(p) for p in self.layout_pages)
        self.lbl_page.setText(f"الصفحة {self.page + 1} من {n}  |  الصور: {total}  |  "
                              f"الورق ({pw:.1f} × {ph:.1f} سم)")

    def go(self, d):
        self.page = max(0, min(self.page + d, len(self.layout_pages) - 1))
        self.refresh_preview()

    def zoom(self, f):
        self.dpi = max(30.0, min(220.0, self.dpi * f))
        self.refresh_preview()

    def fit_page(self):
        vp = self.scroll.viewport().size()
        pw, ph = self.s.page_size()
        self.dpi = max(30.0, min(220.0, min((vp.width() - 24) / (pw / 2.54),
                                            (vp.height() - 24) / (ph / 2.54))))
        self.refresh_preview()

    def real_size(self):
        self.dpi = float(self.logicalDpiX())
        self.refresh_preview()

    # -------------------------------------------------------------- الإخراج
    def _need_items(self):
        if not self.items:
            QMessageBox.information(self, "لا توجد صور", "أضف صوراً أولاً.")
            return False
        return True

    def export_pdf(self):
        if not self._need_items():
            return
        path, _ = QFileDialog.getSaveFileName(self, "حفظ PDF", "PhotoPrint.pdf", "PDF (*.pdf)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pc.save_pdf(pc.render_all(self.items, self.s, 300), path, 300)
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "تم", f"تم حفظ الملف:\n{path}")

    def export_png(self):
        if not self._need_items():
            return
        path, _ = QFileDialog.getSaveFileName(self, "حفظ PNG", "PhotoPrint.png", "PNG (*.png)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            files = pc.save_png(pc.render_all(self.items, self.s, 600), path, 600)
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "تم", "تم حفظ:\n" + "\n".join(files))

    def print_pages(self):
        if not self._need_items():
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        size = QPageSize(QSizeF(self.s.paper_w * 10, self.s.paper_h * 10), QPageSize.Unit.Millimeter)
        orient = QPageLayout.Orientation.Landscape if self.s.landscape else QPageLayout.Orientation.Portrait
        printer.setPageLayout(QPageLayout(size, orient, QMarginsF(0, 0, 0, 0)))
        printer.setFullPage(True)
        if not QPrintDialog(printer, self).exec():
            return
        res = printer.resolution()
        pw, ph = self.s.page_size()
        target = QRectF(0, 0, pw / 2.54 * res, ph / 2.54 * res)      # حجم حقيقي 100%
        painter = QPainter(printer)
        try:
            for i, img in enumerate(pc.render_all(self.items, self.s, min(res, 300))):
                if i:
                    printer.newPage()
                painter.drawImage(target, QImage.fromData(self._png_bytes(img)))
        finally:
            painter.end()

    @staticmethod
    def _png_bytes(img):
        import io
        b = io.BytesIO()
        img.save(b, "PNG")
        return b.getvalue()

    # -------------------------------------------------------------- المشروع
    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "حفظ المشروع", "project.json", "مشروع (*.json)")
        if not path:
            return
        base = os.path.dirname(path)
        folder = os.path.splitext(path)[0] + "_data"
        os.makedirs(folder, exist_ok=True)
        data = {"settings": asdict(self.s), "items": []}
        for i, it in enumerate(self.items):
            cur, ori = os.path.join(folder, f"c{i}.png"), os.path.join(folder, f"o{i}.png")
            it.current.save(cur)
            it.original.save(ori)
            data["items"].append({"name": it.name, "w": it.w, "h": it.h, "copies": it.copies,
                                  "name_text": it.name_text, "id_text": it.id_text,
                                  "current": os.path.relpath(cur, base),
                                  "original": os.path.relpath(ori, base)})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "تم", "تم حفظ المشروع.")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "فتح مشروع", "", "مشروع (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            base = os.path.dirname(path)
            for card in self.cards:
                card.setParent(None)
                card.deleteLater()
            self.items.clear()
            self.cards.clear()
            for k, v in data["settings"].items():
                setattr(self.s, k, tuple(v) if k == "line_color" else v)
            for d in data["items"]:
                cur = Image.open(os.path.join(base, d["current"])).convert("RGB")
                ori = Image.open(os.path.join(base, d["original"])).convert("RGB")
                self.add_item(pc.PhotoItem(d["name"], ori, cur, d["w"], d["h"], d["copies"],
                                           d.get("name_text", ""), d.get("id_text", "")))
            self._sync_controls()
            self.fit_page()
        except Exception as e:
            QMessageBox.warning(self, "تعذر فتح المشروع", str(e))

    def _sync_controls(self):
        s = self.s
        widgets = (self.sp_gx, self.sp_gy, self.chk_lines, self.cmb_style, self.sp_mm,
                   self.rb_seq, self.rb_land, self.cmb_paper, self.sp_cap, self.chk_bold, self.chk_inside)
        for w in widgets:
            w.blockSignals(True)
        self.sp_gx.setValue(s.gap_x)
        self.sp_gy.setValue(s.gap_y)
        self.chk_lines.setChecked(s.show_lines)
        self.cmb_style.setCurrentIndex(0 if s.line_style == "full" else 1)
        self.sp_mm.setValue(s.line_mm)
        self.sp_cap.setValue(s.caption_pt)
        self.chk_bold.setChecked(s.caption_bold)
        self.chk_inside.setChecked(s.caption_inside)
        self.rb_seq.setChecked(s.sequential)
        self.rb_group.setChecked(not s.sequential)
        self.rb_land.setChecked(s.landscape)
        self.rb_portrait.setChecked(not s.landscape)
        for name, (w, h) in pc.PAPERS.items():
            if abs(w - s.paper_w) < 0.05 and abs(h - s.paper_h) < 0.05:
                self.cmb_paper.setCurrentText(name)
        for w in widgets:
            w.blockSignals(False)


# ======================================================================= التشغيل
def main():
    if sys.platform == "win32":      # ليظهر شعار البرنامج في شريط المهام
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ziad.photostudio.app")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setFont(QFont("Tahoma", 10))
    if os.path.exists(resource("icon.png")):
        app.setWindowIcon(QIcon(resource("icon.png")))

    # ---- الواجهة الافتتاحية (شعار البرنامج)
    splash = None
    if os.path.exists(resource("logo.png")):
        pm = QPixmap(resource("logo.png")).scaledToWidth(
            680, Qt.TransformationMode.SmoothTransformation)
        splash = QSplashScreen(pm, Qt.WindowType.WindowStaysOnTopHint
                               | Qt.WindowType.FramelessWindowHint)
        splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        splash.setStyleSheet("background: transparent;")
        splash.show()
        app.processEvents()

    app.setStyleSheet(DARK)
    win = MainWindow()

    def start():
        win.show()
        if splash:
            splash.finish(win)

    QTimer.singleShot(2500 if splash else 0, start)     # مدة ظهور الشعار: 2.5 ثانية
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
