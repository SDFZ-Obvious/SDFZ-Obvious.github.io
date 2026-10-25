# -*- coding: utf-8 -*-
"""MARETU-style word-cloud poster generator.

Recreates the layer stack of 模板.psd:
    background -> radial gradient mask -> grid -> word cloud (multiply 29 %)
    -> grunge texture (color burn) -> top/bottom bars
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    Property, QEasingCurve, QElapsedTimer, QPointF, QPropertyAnimation,
    QRectF, QRunnable, Qt, QThread, QThreadPool, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QIcon, QImage, QKeyEvent, QLinearGradient,
    QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
    QShortcut, QKeySequence, QDragEnterEvent, QDropEvent,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QProgressDialog, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpacerItem, QVBoxLayout, QWidget,
)

from render_core import (
    DEFAULT_RADIUS, FULL_H, FULL_W, TEXTURE_STRENGTH, WORDCLOUD_BOX,
    WORDCLOUD_DEFAULT_CENTER, WORDCLOUD_OPACITY, Renderer, load_image,
    wordcloud_rect,
)

APP_TITLE = "MARETU 词云海报"
MONO = "Microsoft YaHei UI"
ACCENT = "#ff3b5c"
ACCENT_DARK = "#d92b49"

# --------------------------------------------------------------------------- paths


def resource_path(rel: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    return Path(__file__).resolve().parent / rel


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    if img.mode == "RGBA":
        data = img.tobytes()
        qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes()
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def human_size(path: str) -> str:
    try:
        kb = os.path.getsize(path) / 1024
        return f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
    except OSError:
        return ""


# --------------------------------------------------------------------------- widgets


class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True):
        if checked == self._checked:
            return
        self._checked = checked
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._offset)
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()
        else:
            self.set_offset(1.0 if checked else 0.0)
        self.toggled.emit(checked)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(0, 2, self.width(), self.height() - 4)
        if self._checked:
            grad = QLinearGradient(track.topLeft(), track.topRight())
            grad.setColorAt(0, QColor(ACCENT))
            grad.setColorAt(1, QColor("#ff7a3d"))
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
        else:
            p.setBrush(QColor("#2a2f3a"))
            p.setPen(QPen(QColor("#3a4050"), 1))
        p.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        d = self.height() - 12
        x = 6 + self._offset * (self.width() - d - 12)
        knob = QRectF(x, 6, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 9, 12, 90))
        p.drawEllipse(knob.translated(0, 1))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(knob)


class Thumb(QWidget):
    """Rounded image thumbnail with a placeholder state."""

    def __init__(self, size: int = 58, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pix: QPixmap | None = None
        self._alpha = False
        self._placeholder = "＋"
        self._accent = False

    def set_image(self, img: Image.Image | None):
        self._pix = pil_to_pixmap(img) if img is not None else None
        self._alpha = bool(img is not None and img.mode == "RGBA")
        self.update()

    def set_placeholder(self, text: str):
        self._placeholder = text
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.setClipPath(path)
        if self._pix is None:
            p.fillPath(path, QColor("#0e1015"))
            p.setPen(QPen(QColor("#2a2f3a"), 1, Qt.DashLine))
            p.drawPath(path)
            p.setPen(QColor("#5b6170"))
            f = QFont(MONO)
            f.setPointSize(16)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
        else:
            if self._alpha:
                p.setClipPath(path)
                p.fillRect(self.rect(), QColor("#e7eaef"))
                p.setClipping(False)
            scaled = self._pix.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            p.drawPixmap(0, 0, scaled.copy(x, y, self.width(), self.height()))
            p.setClipping(False)
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.drawPath(path)


class AssetRow(QFrame):
    picked = Signal(str)
    cleared = Signal()

    SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

    def __init__(self, title: str, hint: str, placeholder: str = "＋", parent=None):
        super().__init__(parent)
        self.setObjectName("assetRow")
        self.setAcceptDrops(True)
        self._path: str | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        self.thumb = Thumb(58)
        self.thumb.set_placeholder(placeholder)
        lay.addWidget(self.thumb)

        col = QVBoxLayout()
        col.setSpacing(3)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("assetTitle")
        self.sub_lbl = QLabel(hint)
        self.sub_lbl.setObjectName("assetHint")
        self.sub_lbl.setWordWrap(True)
        col.addWidget(self.title_lbl)
        col.addWidget(self.sub_lbl)
        lay.addLayout(col, 1)

        self.pick_btn = QPushButton("选择")
        self.pick_btn.setObjectName("miniBtn")
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.clicked.connect(self._choose)
        lay.addWidget(self.pick_btn, 0, Qt.AlignVCenter)

        self.clear_btn = QPushButton("×")
        self.clear_btn.setObjectName("iconBtn")
        self.clear_btn.setFixedSize(24, 24)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear)
        self.clear_btn.setVisible(False)
        lay.addWidget(self.clear_btn, 0, Qt.AlignVCenter)

    # ------------------------------------------------------------------
    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
        )
        if path:
            self.picked.emit(path)

    def set_data(self, path: str, img: Image.Image, size_text: str):
        self._path = path
        self.thumb.set_image(img)
        self.title_lbl.setText(Path(path).name)
        self.sub_lbl.setText(f"{size_text} · {human_size(path)}")
        self.clear_btn.setVisible(True)
        self.pick_btn.setText("更换")
        self.setProperty("filled", True)
        self.style().unpolish(self)
        self.style().polish(self)

    def clear(self):
        self._path = None
        self.thumb.set_image(None)
        self.title_lbl.setText("未选择")
        self.sub_lbl.setText("点击“选择”或将图片拖到这里")
        self.clear_btn.setVisible(False)
        self.pick_btn.setText("选择")
        self.setProperty("filled", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.cleared.emit()

    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(self.SUFFIXES):
                    self.setProperty("dragover", True)
                    self.style().unpolish(self)
                    self.style().polish(self)
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dragover", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragover", False)
        self.style().unpolish(self)
        self.style().polish(self)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(self.SUFFIXES):
                self.picked.emit(path)
                event.acceptProposedAction()
                return


class Preview(QWidget):
    wcMoved = Signal(float, float)
    dragStarted = Signal()
    dragFinished = Signal()
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 400)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)
        self.setAcceptDrops(True)
        self._pix: QPixmap | None = None
        self._wc_rect = QRectF()
        self._has_bg = False
        self._has_wc = False
        self._dragging = False
        self._drop_hot = False
        self._grab_offset = QPointF()
        self._img_rect = QRectF()
        self._hover_wc = False
        self.setMouseTracking(True)
        self._last_render_ms = 0

    # ------------------------------------------------------------------
    def set_content(self, pix: QPixmap | None, wc_rect: QRectF, has_bg: bool, has_wc: bool):
        self._pix = pix
        self._wc_rect = wc_rect
        self._has_bg = has_bg
        self._has_wc = has_wc
        self.update()

    def set_wc_rect(self, rect: QRectF):
        self._wc_rect = rect
        self.update()

    def _fit_rect(self) -> QRectF:
        if self._pix is None:
            return QRectF()
        margin = 26
        avail_w = self.width() - margin * 2
        avail_h = self.height() - margin * 2
        k = min(avail_w / FULL_W, avail_h / FULL_H)
        w, h = FULL_W * k, FULL_H * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_image(self, pos: QPointF) -> QPointF:
        r = self._img_rect
        if r.width() <= 0:
            return QPointF()
        k = r.width() / FULL_W
        return QPointF((pos.x() - r.x()) / k, (pos.y() - r.y()) / k)

    # ------------------------------------------------------------------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#08090c"))

        # faint dot grid
        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        step = 26
        for x in range(0, self.width(), step):
            for y in range(0, self.height(), step):
                p.drawPoint(x, y)

        self._img_rect = self._fit_rect()
        if self._pix is None or self._img_rect.isNull():
            return
        r = self._img_rect

        # shadow + border
        p.setPen(Qt.NoPen)
        for i in range(6):
            p.setBrush(QColor(0, 0, 0, 26 - i * 4))
            p.drawRoundedRect(r.adjusted(-i - 2, -i - 1, i + 2, i + 3), 8 + i, 8 + i)
        p.drawPixmap(r.toRect(), self._pix)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawRect(r)

        if self._drop_hot:
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(QColor(255, 59, 92, 18))
            p.drawRect(r.adjusted(1, 1, -1, -1))

        if not self._has_bg:
            self._paint_empty_hint(p, r)

        if self._has_wc and not self._wc_rect.isNull():
            self._paint_wc_box(p, r)

    def _paint_empty_hint(self, p: QPainter, r: QRectF):
        p.setPen(QPen(QColor(ACCENT), 1.2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        inner = r.adjusted(28, 28, -28, -28)
        p.drawRoundedRect(inner, 12, 12)

        # readable plate over the bright gradient
        plate = QRectF(inner.center().x() - 300, inner.center().y() - 56, 600, 112)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 214))
        p.drawRoundedRect(plate, 14, 14)

        p.setPen(QColor("#17191f"))
        f = QFont(MONO)
        f.setPointSize(15)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.drawText(plate.adjusted(0, -18, 0, 0), Qt.AlignCenter, "把「背景」图片拖到这里")
        p.setPen(QColor("#565d6b"))
        f.setPointSize(10)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.drawText(plate.adjusted(0, 34, 0, 0), Qt.AlignCenter,
                   "也可以使用右侧面板选择文件 · 支持 JPG / PNG / WEBP")

    def _paint_wc_box(self, p: QPainter, r: QRectF):
        k = r.width() / FULL_W
        box = QRectF(
            r.x() + self._wc_rect.x() * k, r.y() + self._wc_rect.y() * k,
            self._wc_rect.width() * k, self._wc_rect.height() * k,
        )
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(ACCENT), 1.4, Qt.DashLine))
        p.drawRect(box)

        # corner ticks
        p.setPen(QPen(QColor(ACCENT), 2.2))
        ln = min(16.0, box.width() / 4, box.height() / 4)
        for cx, cy, dx, dy in (
            (box.left(), box.top(), 1, 1), (box.right(), box.top(), -1, 1),
            (box.left(), box.bottom(), 1, -1), (box.right(), box.bottom(), -1, -1),
        ):
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx * ln, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * ln))

        # label chip
        text = "词云 · 拖动移动"
        f = QFont(MONO)
        f.setPointSize(9)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text) + 16
        chip = QRectF(box.left(), box.top() - 26, tw, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawRoundedRect(chip, 5, 5)
        p.setPen(QColor("#ffffff"))
        p.drawText(chip, Qt.AlignCenter, text)

        # centre cross
        c = box.center()
        p.setPen(QPen(QColor(255, 255, 255, 120), 1))
        p.drawLine(QPointF(c.x() - 5, c.y()), QPointF(c.x() + 5, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 5), QPointF(c.x(), c.y() + 5))

    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton or self._pix is None:
            return super().mousePressEvent(event)
        if not self._has_wc:
            return super().mousePressEvent(event)
        pos = event.position()
        if not self._img_rect.contains(pos):
            return super().mousePressEvent(event)
        img_pt = self._to_image(pos)
        centre = self._wc_rect.center()
        self._grab_offset = img_pt - centre
        self._dragging = True
        self.setCursor(Qt.ClosedHandCursor)
        self.dragStarted.emit()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            pt = self._to_image(event.position()) - self._grab_offset
            x = max(-200.0, min(FULL_W + 200.0, pt.x()))
            y = max(-200.0, min(FULL_H + 200.0, pt.y()))
            self.wcMoved.emit(x, y)
            return
        if self._has_wc and self._img_rect.contains(event.position()):
            inside = self._wc_rect.contains(self._to_image(event.position()))
            cursor = Qt.OpenHandCursor if inside else Qt.ArrowCursor
            if cursor != self.cursor():
                self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            self.dragFinished.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._has_wc and event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            c = self._wc_rect.center()
            dx = -step if event.key() == Qt.Key_Left else step if event.key() == Qt.Key_Right else 0
            dy = -step if event.key() == Qt.Key_Up else step if event.key() == Qt.Key_Down else 0
            self.wcMoved.emit(c.x() + dx, c.y() + dy)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ drops
    SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(self.SUFFIXES):
                    self._drop_hot = True
                    self.update()
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._drop_hot = False
        self.update()

    def dropEvent(self, event: QDropEvent):
        self._drop_hot = False
        self.update()
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(self.SUFFIXES):
                self.fileDropped.emit(path)
                event.acceptProposedAction()
                return


class FadeOverlay(QWidget):
    """Soft fade that hints there is more content below the scroll viewport."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, QColor(8, 9, 12, 0))
        g.setColorAt(1.0, QColor(8, 9, 12, 255))
        p.fillRect(self.rect(), g)


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(15, 13, 15, 14)
        self.body.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.value_lbl = QLabel("")
        self.value_lbl.setObjectName("valueChip")
        self.value_lbl.setVisible(False)
        head.addWidget(self.value_lbl)
        self.body.addLayout(head)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("cardSub")
            s.setWordWrap(True)
            self.body.addWidget(s)

    def set_value(self, text: str):
        self.value_lbl.setText(text)
        self.value_lbl.setVisible(bool(text))


class SliderRow(QWidget):
    changed = Signal(int)

    def __init__(self, label: str, minimum: int, maximum: int, value: int,
                 suffix: str = "", step: int = 1, parent=None):
        super().__init__(parent)
        self._suffix = suffix
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.name = QLabel(label)
        self.name.setObjectName("fieldLabel")
        self.val = QLabel(f"{value}{suffix}")
        self.val.setObjectName("fieldValue")
        top.addWidget(self.name)
        top.addStretch(1)
        top.addWidget(self.val)
        lay.addLayout(top)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(max(step, (maximum - minimum) // 10))
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_change)
        lay.addWidget(self.slider)

    def _on_change(self, v: int):
        self.val.setText(f"{v}{self._suffix}")
        self.changed.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int):
        self.slider.setValue(int(v))


class InlineSlider(QWidget):
    """Compact single-line slider: label | slider | value."""

    changed = Signal(int)

    def __init__(self, label: str, minimum: int, maximum: int, value: int,
                 suffix: str = "", parent=None):
        super().__init__(parent)
        self._suffix = suffix
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.name = QLabel(label)
        self.name.setObjectName("fieldLabel")
        self.name.setFixedWidth(76)
        lay.addWidget(self.name)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, (maximum - minimum) // 10))
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_change)
        lay.addWidget(self.slider, 1)

        self.val = QLabel(f"{value}{suffix}")
        self.val.setObjectName("fieldValue")
        self.val.setFixedWidth(46)
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.val)

    def _on_change(self, v: int):
        self.val.setText(f"{v}{self._suffix}")
        self.changed.emit(v)

    def setValue(self, v: int):
        self.slider.setValue(int(v))


# --------------------------------------------------------------------------- main window

QSS = f"""
* {{ font-family: "{MONO}"; }}
QMainWindow, QWidget#root {{ background: #08090c; }}
QWidget {{ color: #e7e8ec; font-size: 13px; }}
QFrame#header {{ background: #0b0c10; border-bottom: 1px solid #1a1d24; }}
QLabel#appTitle {{ font-size: 17px; font-weight: 700; letter-spacing: 0.4px; }}
QLabel#appSub {{ color: #858b98; font-size: 12px; }}
QLabel#chip {{ background: #151821; border: 1px solid #262b36; color: #aeb4c0;
               border-radius: 10px; padding: 4px 10px; font-size: 11px; }}
QFrame#card {{ background: #101217; border: 1px solid #1d2129; border-radius: 14px; }}
QFrame#footerPanel {{ background: #08090c; border-top: 1px solid #1a1d24; }}
QLabel#cardTitle {{ font-size: 14px; font-weight: 700; color: #f0f1f4; }}
QLabel#cardSub {{ color: #7f8593; font-size: 11.5px; }}
QLabel#valueChip {{ background: #171b23; color: {ACCENT}; border: 1px solid #2a2130;
                    border-radius: 9px; padding: 3px 9px; font-size: 11px;
                    font-family: "Cascadia Mono", "Consolas", monospace; }}
QLabel#fieldLabel {{ color: #b9bec9; font-size: 12px; }}
QLabel#fieldValue {{ color: #f2f3f5; font-size: 12px;
                     font-family: "Cascadia Mono", "Consolas", monospace; }}
QLabel#assetTitle {{ font-size: 12.5px; font-weight: 600; color: #e9eaee; }}
QLabel#assetHint {{ font-size: 11px; color: #7c8290; }}
QFrame#assetRow {{ background: #0d0f14; border: 1px dashed #262b36; border-radius: 12px; }}
QFrame#assetRow[filled="true"] {{ border: 1px solid #262b36; background: #0e1016; }}
QFrame#assetRow[dragover="true"] {{ border: 1px solid {ACCENT}; background: #171017; }}
QPushButton {{ background: #191d26; border: 1px solid #2a303d; border-radius: 8px;
               padding: 6px 14px; color: #dfe2e8; font-size: 12px; }}
QPushButton:hover {{ background: #202634; border-color: #394152; }}
QPushButton:pressed {{ background: #151922; }}
QPushButton#miniBtn {{ padding: 5px 12px; font-size: 11.5px; border-radius: 7px; }}
QPushButton#iconBtn {{ padding: 0; border-radius: 12px; font-size: 14px; color: #9aa0ad;
                       background: transparent; border: 1px solid #2a303d; }}
QPushButton#iconBtn:hover {{ color: #ffffff; border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white;
                       font-size: 14px; font-weight: 700; border-radius: 11px; }}
QPushButton#primary:hover {{ background: #ff4d6b; }}
QPushButton#primary:pressed {{ background: {ACCENT_DARK}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid #262b36; color: #aab0bc; }}
QPushButton#ghost:hover {{ border-color: #3a4150; color: #ffffff; }}
QPushButton#moreBtn {{ background: rgba(23, 27, 35, 0.94); border: 1px solid #2b3140;
                       color: #c9ced8; border-radius: 12px; padding: 3px 14px; font-size: 11px; }}
QPushButton#moreBtn:hover {{ border-color: {ACCENT}; color: #ffffff; }}
QSlider::groove:horizontal {{ height: 4px; background: #222734; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0;
                              border-radius: 8px; background: #ffffff;
                              border: 2px solid {ACCENT}; }}
QSlider::handle:horizontal:hover {{ background: #ffe9ee; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a4150; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: #4c5466; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLabel#status {{ color: #6f7583; font-size: 11px; }}
QLabel#sectionHint {{ color: #767c8a; font-size: 11px; }}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} · PSD 合成器")
        self.resize(1480, 940)
        self.setMinimumSize(1120, 720)
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(min(1480, avail.width() - 60), min(940, avail.height() - 60))

        self.renderer = Renderer(resource_path("assets"))
        self.bg_path: str | None = None
        self.wc_path: str | None = None
        self.tex_img: Image.Image | None = None
        self.wc_img: Image.Image | None = None
        self.radius = DEFAULT_RADIUS
        self.wc_cx, self.wc_cy = WORDCLOUD_DEFAULT_CENTER
        self.wc_scale = 1.0
        self.wc_opacity = WORDCLOUD_OPACITY
        self.grayscale = True
        self.texture = TEXTURE_STRENGTH
        self.show_deco = True
        self._render_ms = 0.0
        self._last_draft = QElapsedTimer()
        self._last_draft.start()
        self._export_dialog: QProgressDialog | None = None
        self._syncing = False

        self._build_ui()
        self._apply_style()
        self._final_timer = QTimer(self)
        self._final_timer.setSingleShot(True)
        self._final_timer.setInterval(220)
        self._final_timer.timeout.connect(lambda: self.render_now(False))
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(16)
        self._draft_timer.timeout.connect(lambda: self.render_now(True))
        self.render_now(False)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(20, 18, 18, 18)
        body.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.preview = Preview()
        self.preview.wcMoved.connect(self._on_wc_moved)
        self.preview.dragStarted.connect(self._on_drag_start)
        self.preview.dragFinished.connect(self._on_drag_end)
        self.preview.fileDropped.connect(self.load_background)
        left.addWidget(self.preview, 1)
        self.status = QLabel("1920 × 1080 · 等待素材")
        self.status.setObjectName("status")
        left.addWidget(self.status, 0, Qt.AlignLeft)

        body.addLayout(left, 1)
        body.addWidget(self._build_panel())

        outer.addLayout(body, 1)

        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._choose_bg)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.export_png)

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        bar.setFixedHeight(68)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 0, 24, 0)
        lay.setSpacing(14)

        mark = QLabel("M")
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(
            f"background: {ACCENT}; color: white; border-radius: 9px;"
            "font-size: 18px; font-weight: 800;"
        )
        lay.addWidget(mark)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("MARETU 词云海报")
        title.setObjectName("appTitle")
        sub = QLabel("基于 模板.psd 的图层合成 · 背景 × 渐变蒙版 × 词云 × 做旧纹理")
        sub.setObjectName("appSub")
        col.addWidget(title)
        col.addWidget(sub)
        lay.addLayout(col)

        lay.addStretch(1)
        chip = QLabel("画布 1920 × 1080")
        chip.setObjectName("chip")
        lay.addWidget(chip)
        chip2 = QLabel("v1.1")
        chip2.setObjectName("chip")
        lay.addWidget(chip2)

        help_btn = QPushButton("使用说明")
        help_btn.setObjectName("ghost")
        help_btn.setCursor(Qt.PointingHandCursor)
        help_btn.clicked.connect(self._show_help)
        lay.addWidget(help_btn)
        return bar

    def _build_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(392)
        shell = QVBoxLayout(panel)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 16)
        lay.setSpacing(12)

        # ---- assets
        card = Card("素材", "「背景图片」以颜色加深叠加，即做旧层。")
        self.bg_row = AssetRow("背景图片", "点击“选择”或将图片拖到这里", "背")
        self.bg_row.picked.connect(self.load_background)
        self.bg_row.cleared.connect(self.clear_background)
        self.wc_row = AssetRow("词云图片", "点击“选择”或将图片拖到这里", "词")
        self.wc_row.picked.connect(self.load_wordcloud)
        self.wc_row.cleared.connect(self.clear_wordcloud)
        card.body.addWidget(self.bg_row)
        card.body.addWidget(self.wc_row)
        self.o_slider = InlineSlider("词云透明度", 0, 100, int(round(self.wc_opacity * 100)), " %")
        self.o_slider.changed.connect(self._on_wc_opacity)
        card.body.addWidget(self.o_slider)
        lay.addWidget(card)

        # ---- gradient mask
        card = Card("渐变蒙版", "控制中心亮区的大小。半径越小，四周压得越黑。")
        self.radius_slider = SliderRow("蒙版半径", 180, 1100, int(self.radius), " px")
        self.radius_slider.changed.connect(self._on_radius)
        card.body.addWidget(self.radius_slider)
        lay.addWidget(card)

        # ---- word cloud transform
        card = Card("词云位置", "在画面中拖动，或调整以下数值。")
        self.x_slider = SliderRow("水平 X", 0, FULL_W, int(self.wc_cx), " px")
        self.y_slider = SliderRow("垂直 Y", 0, FULL_H, int(self.wc_cy), " px")
        self.s_slider = SliderRow("大小", 30, 160, 100, " %")
        self.x_slider.changed.connect(lambda v: self._on_wc_xy(v, None))
        self.y_slider.changed.connect(lambda v: self._on_wc_xy(None, v))
        self.s_slider.changed.connect(self._on_wc_scale)
        card.body.addWidget(self.x_slider)
        card.body.addWidget(self.y_slider)
        card.body.addWidget(self.s_slider)
        row = QHBoxLayout()
        hint = QLabel("提示：方向键微调，Shift + 方向键每次 10px")
        hint.setObjectName("sectionHint")
        row.addWidget(hint)
        row.addStretch(1)
        center_btn = QPushButton("居中")
        center_btn.setObjectName("ghost")
        center_btn.setCursor(Qt.PointingHandCursor)
        center_btn.clicked.connect(self._center_wc)
        row.addWidget(center_btn)
        card.body.addLayout(row)
        lay.addWidget(card)

        # ---- style
        card = Card("风格", "还原 PSD 的黑白与做旧质感。")
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t1 = QLabel("黑白模式")
        t1.setObjectName("fieldLabel")
        d1 = QLabel("将最终画面转为黑白")
        d1.setObjectName("sectionHint")
        col.addWidget(t1)
        col.addWidget(d1)
        row.addLayout(col)
        row.addStretch(1)
        self.mono_switch = Switch(True)
        self.mono_switch.toggled.connect(self._on_mono)
        row.addWidget(self.mono_switch)
        card.body.addLayout(row)

        self.tex_slider = SliderRow("做旧强度", 0, 100, int(self.texture * 100), " %")
        self.tex_slider.changed.connect(self._on_texture)
        card.body.addWidget(self.tex_slider)

        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        t2 = QLabel("网格与边框")
        t2.setObjectName("fieldLabel")
        d2 = QLabel("保留模板底部的透视网格和上下黑边")
        d2.setObjectName("sectionHint")
        col.addWidget(t2)
        col.addWidget(d2)
        row.addLayout(col)
        row.addStretch(1)
        self.deco_switch = Switch(True)
        self.deco_switch.toggled.connect(self._on_deco)
        row.addWidget(self.deco_switch)
        card.body.addLayout(row)
        lay.addWidget(card)

        lay.addStretch(1)
        scroll.setWidget(inner)
        shell.addWidget(scroll, 1)

        # ---- footer (outside the scroll area, always visible)
        footer = QFrame()
        footer.setObjectName("footerPanel")
        foot = QVBoxLayout(footer)
        foot.setContentsMargins(8, 12, 8, 8)
        foot.setSpacing(8)
        self.export_btn = QPushButton("导出 PNG · 1920 × 1080")
        self.export_btn.setObjectName("primary")
        self.export_btn.setFixedHeight(46)
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self.export_png)
        foot.addWidget(self.export_btn)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.msg = QLabel("")
        self.msg.setObjectName("status")
        row.addWidget(self.msg, 1)
        self.more_btn = QPushButton("更多设置 ⌄")
        self.more_btn.setObjectName("moreBtn")
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.clicked.connect(self._scroll_more)
        self.more_btn.setVisible(False)
        row.addWidget(self.more_btn)
        reset = QPushButton("重置")
        reset.setObjectName("ghost")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(self.reset_all)
        row.addWidget(reset)
        foot.addLayout(row)
        shell.addWidget(footer)

        self.scroll = scroll
        self._fade = FadeOverlay(panel)
        self.scroll.verticalScrollBar().valueChanged.connect(self._update_more_btn)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._update_more_btn)
        return panel

    def _apply_style(self):
        self.setStyleSheet(QSS)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(30)
        self._shadow.setOffset(0, 8)
        self._shadow.setColor(QColor(0, 0, 0, 140))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_fade()

    def _place_fade(self):
        if not hasattr(self, "_fade"):
            return
        g = self.scroll.geometry()
        self._fade.setGeometry(g.x(), g.y() + g.height() - 56, g.width(), 56)
        self._fade.raise_()
        self._update_more_btn()

    def _update_more_btn(self, *_):
        if not hasattr(self, "more_btn"):
            return
        bar = self.scroll.verticalScrollBar()
        more = bar.maximum() > 0 and bar.value() < bar.maximum() - 2
        self.more_btn.setVisible(more)
        if hasattr(self, "_fade"):
            self._fade.setVisible(more)

    def _scroll_more(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(min(bar.maximum(), bar.value() + int(self.scroll.viewport().height() * 0.8)))

    # ------------------------------------------------------------------ state
    def load_background(self, path: str):
        try:
            img = load_image(path)
        except Exception as exc:
            QMessageBox.warning(self, "无法打开图片", f"{path}\n\n{exc}")
            return
        self.bg_path = path
        self.tex_img = img
        self.bg_row.set_data(path, img, f"{img.width} × {img.height}")
        self._schedule(final_only=False)
        self._set_msg("背景已载入 · 将以颜色加深叠加")

    def clear_background(self):
        self.bg_path = None
        self.tex_img = None
        self.bg_row.clear()
        self._schedule(final_only=False)

    def load_wordcloud(self, path: str):
        try:
            img = load_image(path)
        except Exception as exc:
            QMessageBox.warning(self, "无法打开图片", f"{path}\n\n{exc}")
            return
        self.wc_path = path
        self.wc_img = img
        self.wc_row.set_data(path, img, f"{img.width} × {img.height}")
        self._schedule(final_only=False)
        self._set_msg("词云已载入 · 可直接拖动")

    def clear_wordcloud(self):
        self.wc_path = None
        self.wc_img = None
        self.wc_row.clear()
        self._schedule(final_only=False)

    def reset_all(self):
        self.clear_background()
        self.clear_wordcloud()
        self.radius = DEFAULT_RADIUS
        self.radius_slider.setValue(int(self.radius))
        self.wc_cx, self.wc_cy = WORDCLOUD_DEFAULT_CENTER
        self.x_slider.setValue(int(self.wc_cx))
        self.y_slider.setValue(int(self.wc_cy))
        self.wc_scale = 1.0
        self.s_slider.setValue(100)
        self.wc_opacity = WORDCLOUD_OPACITY
        self.o_slider.setValue(int(round(self.wc_opacity * 100)))
        self.grayscale = True
        self.mono_switch.setChecked(True)
        self.texture = TEXTURE_STRENGTH
        self.tex_slider.setValue(int(self.texture * 100))
        self.show_deco = True
        self.deco_switch.setChecked(True)
        self.render_now(False)

    # ------------------------------------------------------------------ events
    def _on_radius(self, value: int):
        self.radius = float(value)
        self._schedule()

    def _on_wc_xy(self, x, y):
        if self._syncing:
            return
        if x is not None:
            self.wc_cx = float(x)
        if y is not None:
            self.wc_cy = float(y)
        self._update_wc_rect_only()
        self._schedule(dragging=True)

    def _on_wc_scale(self, value: int):
        self.wc_scale = value / 100.0
        self._update_wc_rect_only()
        self._schedule(dragging=True)

    def _on_wc_opacity(self, value: int):
        self.wc_opacity = value / 100.0
        self._schedule()

    def _on_mono(self, checked: bool):
        self.grayscale = checked
        self._schedule()

    def _on_texture(self, value: int):
        self.texture = value / 100.0
        self._schedule()

    def _on_deco(self, checked: bool):
        self.show_deco = checked
        self._schedule()

    def _on_wc_moved(self, x: float, y: float):
        self.wc_cx, self.wc_cy = x, y
        self._syncing = True
        self.x_slider.setValue(int(round(x)))
        self.y_slider.setValue(int(round(y)))
        self._syncing = False
        self._update_wc_rect_only()
        if self._last_draft.elapsed() > 45:
            self._last_draft.restart()
            self.render_now(True)

    def _on_drag_start(self):
        self._set_msg("拖动中 …")

    def _on_drag_end(self):
        self._set_msg("")
        self._schedule(final_only=False)

    def _center_wc(self):
        self.wc_cx, self.wc_cy = WORDCLOUD_DEFAULT_CENTER
        self.x_slider.setValue(int(self.wc_cx))
        self.y_slider.setValue(int(self.wc_cy))
        self._update_wc_rect_only()
        self._schedule(final_only=False)

    # ------------------------------------------------------------------ rendering
    def _wc_rect(self) -> tuple[float, float, float, float]:
        if self.wc_img is None:
            return (0, 0, 0, 0)
        return wordcloud_rect(self.wc_img.size, (self.wc_cx, self.wc_cy), self.wc_scale)

    def _update_wc_rect_only(self):
        r = self._wc_rect()
        self.preview.set_wc_rect(QRectF(*r))

    def _schedule(self, dragging: bool = False, final_only: bool = False):
        if not final_only:
            if dragging:
                if self._last_draft.elapsed() > 45:
                    self._last_draft.restart()
                    self.render_now(True)
            else:
                self.render_now(True)
        self._final_timer.start()

    def render_now(self, draft: bool):
        t0 = time.perf_counter()
        scale = 0.34 if draft else 0.55
        try:
            img = self.renderer.render(
                self.tex_img, self.wc_img,
                radius=self.radius,
                wc_center=(self.wc_cx, self.wc_cy),
                wc_scale=self.wc_scale,
                wc_opacity=self.wc_opacity,
                grayscale=self.grayscale,
                texture_strength=self.texture,
                show_deco=self.show_deco,
                scale=scale,
            )
        except Exception:
            traceback.print_exc()
            return
        self._render_ms = (time.perf_counter() - t0) * 1000
        pix = pil_to_pixmap(img)
        r = self._wc_rect()
        self.preview.set_content(
            pix, QRectF(*r), self.tex_img is not None, self.wc_img is not None
        )
        state = "草稿" if draft else "预览"
        self.status.setText(
            f"1920 × 1080 · {state} {int(scale * 100)}% · {self._render_ms:.0f} ms"
        )

    def _set_msg(self, text: str):
        if hasattr(self, "msg"):
            self.msg.setText(text)

    # ------------------------------------------------------------------ export
    def export_png(self):
        default = f"maretu_poster_{time.strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 PNG", str(Path.home() / "Pictures" / default),
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg)"
        )
        if not path:
            return
        self.export_btn.setEnabled(False)
        self.export_btn.setText("正在导出 …")
        dlg = QProgressDialog("正在渲染 1920 × 1080 …", "", 0, 0, self)
        dlg.setWindowTitle("导出")
        dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.show()
        self._export_dialog = dlg

        params = dict(
            texture=self.tex_img, wordcloud=self.wc_img,
            radius=self.radius, wc_center=(self.wc_cx, self.wc_cy),
            wc_scale=self.wc_scale, wc_opacity=self.wc_opacity,
            grayscale=self.grayscale,
            texture_strength=self.texture,
            show_deco=self.show_deco, scale=1.0,
        )
        renderer = self.renderer

        class Worker(QThread):
            done = Signal(bool, str)

            def run(self_inner):
                try:
                    img = renderer.render(**params)
                    if path.lower().endswith((".jpg", ".jpeg")):
                        img.save(path, quality=95)
                    else:
                        img.save(path)
                    self_inner.done.emit(True, path)
                except Exception as exc:
                    traceback.print_exc()
                    self_inner.done.emit(False, str(exc))

        self._worker = Worker(self)
        self._worker.done.connect(lambda ok, info: self._export_done(ok, info, dlg, path))
        self._worker.start()

    def _export_done(self, ok: bool, info: str, dlg: QProgressDialog, path: str):
        dlg.close()
        self.export_btn.setEnabled(True)
        self.export_btn.setText("导出 PNG · 1920 × 1080")
        if ok:
            box = QMessageBox(self)
            box.setWindowTitle("导出成功")
            box.setText(f"已保存到：\n{path}")
            open_btn = box.addButton("打开所在文件夹", QMessageBox.AcceptRole)
            box.addButton("关闭", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() == open_btn:
                os.startfile(str(Path(path).parent))
            self._set_msg("导出完成")
        else:
            QMessageBox.critical(self, "导出失败", info)

    def _choose_bg(self):
        self.bg_row._choose()

    def _show_help(self):
        box = QMessageBox(self)
        box.setWindowTitle("使用说明")
        box.setTextFormat(Qt.RichText)
        box.setText(
            "<b>MARETU 词云海报</b> — 基于 模板.psd 的图层合成<br><br>"
            "1. 选择<b>背景图片</b>（会以「颜色加深」叠加，即做旧层）<br>"
            "2. 选择<b>词云图片</b>（深色文字 + 透明底 PNG 效果最好）<br>"
            "3. 拖动<b>蒙版半径</b>控制中心亮区大小<br>"
            "4. 在画面里直接拖动<b>词云</b>，或用 X / Y / 大小 / 透明度滑杆微调<br>"
            "5. 点击<b>导出 PNG</b> 得到 1920×1080 成品<br><br>"
            "<span style='color:#8a8f9a'>画布底色固定为白色，不可替换；"
            "快捷键：Ctrl+O 选背景，Ctrl+E 导出；方向键可微调词云（Shift 加速）。</span>"
        )
        box.exec()


def _parse_args(argv):
    opts = {
        "shot": None, "bg": None, "wc": None, "export": None,
        "radius": None, "x": None, "y": None, "wcscale": None,
        "tex": None, "wcopacity": None, "mono": True, "deco": True,
    }
    keymap = {"--shot": "shot", "--bg": "bg", "--wc": "wc", "--export": "export",
              "--radius": "radius", "--x": "x", "--y": "y", "--wcscale": "wcscale",
              "--tex": "tex", "--wcopacity": "wcopacity"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in keymap and i + 1 < len(argv):
            opts[keymap[a]] = argv[i + 1]
            i += 2
            continue
        if a == "--color":
            opts["mono"] = False
        elif a == "--nodeco":
            opts["deco"] = False
        i += 1
    return opts


def _cli_export(opts) -> int:
    from render_core import Renderer, load_image as _load

    renderer = Renderer(resource_path("assets"))
    tex = _load(opts["bg"]) if opts["bg"] else None
    wc = _load(opts["wc"]) if opts["wc"] else None
    img = renderer.render(
        tex, wc,
        radius=float(opts["radius"]) if opts["radius"] else DEFAULT_RADIUS,
        wc_center=(float(opts["x"]) if opts["x"] else WORDCLOUD_DEFAULT_CENTER[0],
                   float(opts["y"]) if opts["y"] else WORDCLOUD_DEFAULT_CENTER[1]),
        wc_scale=float(opts["wcscale"]) / 100.0 if opts["wcscale"] else 1.0,
        wc_opacity=float(opts["wcopacity"]) / 100.0 if opts["wcopacity"] else WORDCLOUD_OPACITY,
        grayscale=bool(opts["mono"]),
        texture_strength=float(opts["tex"]) / 100.0 if opts["tex"] else TEXTURE_STRENGTH,
        show_deco=bool(opts["deco"]),
        scale=1.0,
    )
    img.save(opts["export"])
    print(opts["export"])
    return 0


def main():
    opts = _parse_args(sys.argv[1:])
    if opts["export"]:
        sys.exit(_cli_export(opts))

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setWindowIcon(QIcon(str(resource_path("assets/icon.png"))))
    win = MainWindow()
    if opts["bg"]:
        win.load_background(opts["bg"])
    if opts["wc"]:
        win.load_wordcloud(opts["wc"])
    if opts["radius"]:
        win.radius_slider.setValue(int(float(opts["radius"])))
    if not opts["mono"]:
        win.mono_switch.setChecked(False)
    win.render_now(False)
    if opts["shot"]:
        win.show()
        app.processEvents()
        QTimer.singleShot(30, lambda: None)
        app.processEvents()
        win._place_fade()
        win.render_now(False)
        app.processEvents()
        win.grab().save(opts["shot"])
        app.quit()
        return
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()




