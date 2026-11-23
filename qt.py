# -*- coding: utf-8 -*-
# =====================================================================
#  Al-sabri Notepad  —  PySide6 (Qt)
#  الواجهة (Front-End)، وتستدعي الباك إند:
#     file_service.py  ← كل عمليات الملفات
#     autosave.py      ← الحفظ التلقائي بخيط خلفي
#     recent_files.py  ← الملفات الحديثة
#  اتجاه كل فقرة ومحاذاتها يتحددان تلقائياً: عربي ← يمين | إنجليزي ← يسار
# =====================================================================
import os
import queue
import sys
import time
import traceback
import unicodedata

import file_service
from autosave import AutoSaveWorker
from recent_files import RecentFiles

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QKeySequence, QShortcut,
                           QTextCharFormat, QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog,
                               QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QTextEdit,
                               QVBoxLayout, QWidget)

APP_NAME = "Al-sabri Notepad"
FONTS = ["Consolas", "Tahoma", "Segoe UI", "Arial", "Calibri", "Courier New", "Times New Roman"]
SIZES = ["12", "14", "16", "18", "20", "24", "28", "32", "40"]
FILETYPES = "ملفات نصية (*.txt);;كل الملفات (*.*)"

# تنسيق الشكل الداكن الأزرق
STYLE = """
QMainWindow, QWidget#root { background: #242424; }
QFrame#toolbar, QFrame#findbar, QFrame#formatbar { background: #2b2b2b; }
QFrame#editorarea { background: #1e1e1e; }
QFrame#sep { background: #555; }
QLabel { color: #dce4ee; }
QCheckBox { color: #dce4ee; }
QPushButton#tool { background: transparent; color: #dce4ee; border: 1px solid #979da2;
                   border-radius: 16px; padding: 0 14px; min-height: 30px; }
QPushButton#tool:hover { background: #3a3a3a; }
QPushButton#menu { background: #1f6aa5; color: white; border: none;
                   border-radius: 16px; padding: 0 14px; min-height: 30px; }
QPushButton#menu:hover { background: #144870; }
QPushButton#small { background: #1f6aa5; color: white; border: none;
                    border-radius: 13px; padding: 0 12px; min-height: 26px; }
QPushButton#small:hover { background: #144870; }
QPushButton#gray { background: #4a4a4a; color: white; border: none;
                   border-radius: 13px; padding: 0 12px; min-height: 26px; }
QPushButton#gray:hover { background: #5a5a5a; }
QLineEdit, QComboBox { background: #343638; color: white; border: 1px solid #565b5e;
                       border-radius: 6px; padding: 3px 8px; min-height: 22px; }
QComboBox QAbstractItemView { background: #2b2b2b; color: white; selection-background-color: #1f6aa5; }
QMenu { background: #2b2b2b; color: white; border: 1px solid #555; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background: #1f6aa5; }
QMenu::item:disabled { color: #888; }
QStatusBar { background: #2b2b2b; color: #dce4ee; }
QStatusBar::item { border: none; }
"""


def same_path(a, b):
    """هل المساران يشيران إلى الملف نفسه؟"""
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 700)
        self.setMinimumSize(950, 500)

        # حالة البرنامج
        self.font_family = "Consolas"
        self.font_size = 20
        self.text_color = "#000000"
        self._fixing_direction = False
        self.current_path = None          # مسار الملف المفتوح (None = ملف جديد)
        self.autosave_enabled = True
        self.recent = RecentFiles()       # الملفات الحديثة

        central = QWidget()
        central.setObjectName("root")
        self.root_layout = QVBoxLayout(central)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self.setCentralWidget(central)

        self.build_toolbar()
        self.build_find_bar()
        self.build_format_bar()
        self.build_editor()
        self.build_statusbar()
        self.bind_shortcuts()
        self.update_title()

        # الحفظ التلقائي: خيط خلفي + مؤقّت في الواجهة يستقبل رسائله
        self.worker = AutoSaveWorker(interval=30)
        self.worker.start()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_worker)
        self.poll_timer.start(200)

    # ---------- أدوات مساعدة ----------
    def make_button(self, text, command, style="tool"):
        btn = QPushButton(text)
        btn.setObjectName(style)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda checked=False: command())
        return btn

    def make_separator(self):
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFixedSize(2, 24)
        return sep

    def make_bar(self, name):
        bar = QFrame()
        bar.setObjectName(name)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        return bar, layout

    def message(self, title, text, icon=QMessageBox.Icon.Information):
        """رسالة بزر عربي."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setText(text)
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        box.addButton("حسناً", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def confirm(self, title, text, yes="نعم", no="لا"):
        """سؤال بزرين عربيين. ترجع True إذا اختار المستخدم الأول."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(text)
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        yes_btn = box.addButton(yes, QMessageBox.ButtonRole.YesRole)
        no_btn = box.addButton(no, QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(no_btn)
        box.setEscapeButton(no_btn)
        box.exec()
        return box.clickedButton() == yes_btn

    # ================= الشريط العلوي =================
    def build_toolbar(self):
        self.toolbar, layout = self.make_bar("toolbar")
        layout.setContentsMargins(16, 9, 12, 9)

        self.title_label = QLabel(APP_NAME)
        self.title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        menu = QMenu(self)
        menu.addAction("حذف ملف", self.delete_file)
        menu.addAction("إعادة تسمية ملف", self.rename_file)
        menu.addAction("نسخ ملف", lambda: self.transfer_file(move=False))
        menu.addAction("نقل ملف", lambda: self.transfer_file(move=True))
        menu.addAction("معلومات الملف", self.file_info)
        menu.addSeparator()
        self.recent_menu = menu.addMenu("الملفات الحديثة")
        self.recent_menu.aboutToShow.connect(self.rebuild_recent_menu)
        menu.addSeparator()
        self.autosave_action = menu.addAction("الحفظ التلقائي")
        self.autosave_action.setCheckable(True)
        self.autosave_action.setChecked(True)
        self.autosave_action.toggled.connect(self.on_autosave_toggled)
        menu.addAction("فترة الحفظ التلقائي...", self.set_autosave_interval)

        menu_btn = QPushButton("إدارة الملفات")
        menu_btn.setObjectName("menu")
        menu_btn.setMenu(menu)
        layout.addWidget(menu_btn)

        # مرتبة بصرياً من اليسار إلى اليمين (جديد أقصى اليمين)
        items = [("خط", self.toggle_format), ("بحث", self.toggle_find), None,
                 ("إعادة", self.redo), ("تراجع", self.undo), None,
                 ("حفظ باسم", self.save_as_file), ("حفظ", self.save_file),
                 ("فتح", self.open_file), ("جديد", self.new_file)]
        for item in items:
            if item is None:
                layout.addWidget(self.make_separator())
            else:
                layout.addWidget(self.make_button(item[0], item[1]))
        self.root_layout.addWidget(self.toolbar)

    # ================= شريط البحث =================
    def build_find_bar(self):
        self.find_bar, layout = self.make_bar("findbar")

        self.find_msg = QLabel("")
        self.find_msg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(self.find_msg)
        layout.addStretch(1)

        self.case_check = QCheckBox("مطابقة الحروف")
        layout.addWidget(self.case_check)
        layout.addWidget(self.make_button("تمييز الكل", self.highlight_click, "small"))
        layout.addWidget(self.make_button("السابق", lambda: self.find_next(False), "small"))
        layout.addWidget(self.make_button("التالي", lambda: self.find_next(True), "small"))

        self.find_entry = QLineEdit()
        self.find_entry.setPlaceholderText("ابحث عن...")
        self.find_entry.setFixedWidth(260)
        self.find_entry.returnPressed.connect(lambda: self.find_next(True))
        layout.addWidget(self.find_entry)
        layout.addWidget(self.make_button("إغلاق", self.close_find, "gray"))

        self.find_bar.hide()
        self.root_layout.addWidget(self.find_bar)

    # ================= شريط الخط واللون =================
    def build_format_bar(self):
        self.format_bar, layout = self.make_bar("formatbar")
        layout.addStretch(1)

        layout.addWidget(self.make_button("لون النص", self.pick_color, "small"))

        self.size_combo = QComboBox()
        self.size_combo.addItems(SIZES)
        self.size_combo.setCurrentText(str(self.font_size))
        self.size_combo.currentTextChanged.connect(self.apply_font)
        layout.addWidget(self.size_combo)
        layout.addWidget(QLabel("الحجم:"))

        self.font_combo = QComboBox()
        self.font_combo.addItems(FONTS)
        self.font_combo.setCurrentText(self.font_family)
        self.font_combo.currentTextChanged.connect(self.apply_font)
        layout.addWidget(self.font_combo)
        layout.addWidget(QLabel("الخط:"))

        layout.addWidget(self.make_button("إغلاق", self.toggle_format, "gray"))
        self.format_bar.hide()
        self.root_layout.addWidget(self.format_bar)

    # ================= منطقة الكتابة =================
    def build_editor(self):
        area = QFrame()
        area.setObjectName("editorarea")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(10, 10, 10, 10)

        # QTextEdit (وليس QPlainTextEdit) لأنه الوحيد الذي يحترم اتجاه ومحاذاة كل فقرة
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)       # اللصق نص عادي فقط
        self.editor.setFont(QFont(self.font_family, self.font_size))
        self.apply_editor_style()

        self.editor.cursorPositionChanged.connect(self.update_position)
        self.editor.textChanged.connect(self.update_position)
        # عند أي تغيير في النص نضبط اتجاه الفقرات المتأثرة
        self.editor.document().contentsChange.connect(self.on_contents_change)
        # عند تغيّر حالة «معدّل / غير معدّل» نحدّث عنوان النافذة (علامة *)
        self.editor.document().modificationChanged.connect(self.update_title)

        layout.addWidget(self.editor)
        self.root_layout.addWidget(area, 1)   # هذه المنطقة هي التي تتمدد

    def apply_editor_style(self):
        self.editor.setStyleSheet(
            f"QTextEdit {{ background: #dddada; color: {self.text_color}; border: none;"
            f" selection-background-color: #1f6aa5; selection-color: white; }}")

    # ---------- الاتجاه التلقائي لكل فقرة ----------
    def on_contents_change(self, position, removed, added):
        if self._fixing_direction:
            return
        # نؤجل الضبط لحظة (بعد انتهاء الحدث الحالي) لتجنب تعديل المستند أثناء تغييره
        QTimer.singleShot(0, lambda: self.fix_range(position, added))

    def fix_range(self, position, added):
        doc = self.editor.document()
        was_modified = doc.isModified()        # ضبط الاتجاه ليس تعديلاً من المستخدم
        start = min(position, max(doc.characterCount() - 1, 0))
        block = doc.findBlock(start)
        end = position + added
        self._fixing_direction = True
        try:
            while block.isValid() and block.position() <= end:
                self.apply_block_direction(block)
                block = block.next()
        except Exception as e:                 # أي خطأ يظهر في الطرفية وشريط الحالة
            traceback.print_exc()
            self.set_status(f"خطأ في ضبط الاتجاه: {e}")
        finally:
            self._fixing_direction = False
        if not was_modified:
            doc.setModified(False)

    def apply_block_direction(self, block):
        """أول حرف قوي في الفقرة يحدد اتجاهها: عربي ← يمين، لاتيني ← يسار."""
        rtl = None
        for ch in block.text():
            kind = unicodedata.bidirectional(ch)
            if kind == "L":
                rtl = False
                break
            if kind in ("R", "AL"):
                rtl = True
                break
        if rtl is None:        # فقرة فارغة أو أرقام فقط: تبقى كما هي
            return
        direction = Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
        side = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        align = side | Qt.AlignmentFlag.AlignAbsolute
        fmt = block.blockFormat()
        if fmt.layoutDirection() == direction and fmt.alignment() == align:
            return
        fmt.setLayoutDirection(direction)
        fmt.setAlignment(align)
        cursor = QTextCursor(block)
        cursor.joinPreviousEditBlock()      # يدمج التغيير مع الكتابة فلا يفسد التراجع
        cursor.setBlockFormat(fmt)
        cursor.endEditBlock()

    # ================= شريط الحالة =================
    def build_statusbar(self):
        self.position_label = QLabel("سطر 1 ، عمود 1 | كلمات 0 | حروف 0")
        self.position_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.status_label = QLabel("جاهز")
        self.status_label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.statusBar().addWidget(self.position_label)            # يسار
        self.statusBar().addPermanentWidget(self.status_label)     # يمين

    def set_status(self, text):
        self.status_label.setText(text)

    def update_position(self):
        cursor = self.editor.textCursor()
        text = self.editor.toPlainText()
        self.position_label.setText(
            f"سطر {cursor.blockNumber() + 1} ، عمود {cursor.positionInBlock() + 1}"
            f" | كلمات {len(text.split())} | حروف {len(text)}")

    # ================= اختصارات لوحة المفاتيح =================
    def bind_shortcuts(self):
        for keys, command in [("Ctrl+N", self.new_file), ("Ctrl+O", self.open_file),
                              ("Ctrl+S", self.save_file), ("Ctrl+Shift+S", self.save_as_file),
                              ("Ctrl+F", self.toggle_find)]:
            QShortcut(QKeySequence(keys), self, activated=command)

    # ================= التراجع والإعادة =================
    def undo(self):
        if self.editor.document().isUndoAvailable():
            self.editor.undo()
        else:
            self.set_status("لا يوجد ما يمكن التراجع عنه")

    def redo(self):
        if self.editor.document().isRedoAvailable():
            self.editor.redo()
        else:
            self.set_status("لا يوجد ما يمكن إعادته")

    # ================= الخط واللون =================
    def toggle_format(self):
        self.format_bar.setVisible(not self.format_bar.isVisible())

    def apply_font(self, _text=None):
        self.font_family = self.font_combo.currentText()
        self.font_size = int(self.size_combo.currentText())
        self.editor.setFont(QFont(self.font_family, self.font_size))

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.text_color), self, "اختر لون النص")
        if color.isValid():
            self.text_color = color.name()
            self.apply_editor_style()

    # ================= البحث =================
    def toggle_find(self):
        if self.find_bar.isVisible():
            self.close_find()
        else:
            self.find_bar.show()
            self.find_entry.setFocus()
            self.find_entry.selectAll()

    def close_find(self):
        self.editor.setExtraSelections([])
        self.find_msg.setText("")
        self.find_bar.hide()
        self.editor.setFocus()

    def find_flags(self):
        flags = QTextDocument.FindFlag(0)
        if self.case_check.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def highlight_all(self, term):
        """تلوين كل النتائج بالأصفر، وترجع عددها."""
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#ffe066"))
        fmt.setForeground(QColor("black"))
        doc = self.editor.document()
        selections, cursor = [], QTextCursor(doc)
        while True:
            cursor = doc.find(term, cursor, self.find_flags())
            if cursor.isNull():
                break
            sel = QTextEdit.ExtraSelection()
            sel.cursor, sel.format = cursor, fmt
            selections.append(sel)
        self.editor.setExtraSelections(selections)
        return len(selections)

    def highlight_click(self):
        term = self.find_entry.text()
        if term:
            n = self.highlight_all(term)
            self.find_msg.setText(f"عدد النتائج: {n}" if n else "لم يتم العثور على النص")

    def find_next(self, forward=True):
        term = self.find_entry.text()
        if not term:
            return
        n = self.highlight_all(term)
        if n == 0:
            self.find_msg.setText("لم يتم العثور على النص")
            self.set_status(f"لم يتم العثور على «{term}»")
            return
        flags = self.find_flags()
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        if not self.editor.find(term, flags):          # الالتفاف إلى البداية/النهاية
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start if forward
                                else QTextCursor.MoveOperation.End)
            self.editor.setTextCursor(cursor)
            self.editor.find(term, flags)
        self.find_msg.setText(f"عدد النتائج: {n}")

    # ================= عنوان النافذة وحالة التعديل =================
    def update_title(self, *_):
        name = os.path.basename(self.current_path) if self.current_path else "بدون عنوان"
        star = "*" if self.editor.document().isModified() else ""
        ro = " (للقراءة فقط)" if self.current_path and file_service.is_readonly(self.current_path) else ""
        self.setWindowTitle(f"{star}{name}{ro} - {APP_NAME}")

    def finish_load(self):
        """بعد وضع نص جديد في المحرر: نصفّر التراجع وحالة التعديل."""
        doc = self.editor.document()
        doc.clearUndoRedoStacks()
        doc.setModified(False)
        self.update_title()
        self.update_position()

    # ================= التنبيه عند وجود تعديلات غير محفوظة =================
    def maybe_save(self):
        """ترجع True إذا يمكن المتابعة، و False إذا ألغى المستخدم."""
        if not self.editor.document().isModified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        box.setText("توجد تعديلات لم يتم حفظها.\nهل تريد حفظ الملف قبل الإغلاق؟")
        save_btn = box.addButton("حفظ", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton("عدم الحفظ", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("إلغاء", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.setEscapeButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save_btn:
            self.save_file()
            # إذا فشل الحفظ أو ألغى المستخدم نافذة الحفظ يبقى الملف معدّلاً فلا نتابع
            return not self.editor.document().isModified()
        if clicked == discard_btn:
            return True
        return False

    def closeEvent(self, event):
        """تعمل عند إغلاق النافذة بزر X."""
        if self.maybe_save():
            self.poll_timer.stop()
            self.worker.stop()              # إيقاف الخيط الخلفي
            self.remove_recovery()
            event.accept()
        else:
            event.ignore()

    # ================= ملف جديد / فتح / حفظ =================
    def new_file(self):
        if not self.maybe_save():
            return
        self.editor.clear()
        self.current_path = None
        self.remove_recovery()
        QTimer.singleShot(0, self.finish_load)
        self.set_status("ملف جديد")

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "فتح ملف", "", FILETYPES)
        if path:
            self.open_path(path)

    def open_path(self, path):
        """يفتح ملفاً من مسار معروف (يُستخدم من «فتح» ومن الملفات الحديثة)."""
        path = os.path.abspath(path)
        if not self.maybe_save():
            return
        try:
            text = file_service.read_text(path)
        except file_service.FileMissingError as e:
            self.message("الملف غير موجود",
                         f"{e}\n\nربما تم نقله أو حذفه خارج البرنامج، وستتم إزالته من القائمة الحديثة.",
                         QMessageBox.Icon.Warning)
            self.recent.remove(path)
            return
        except file_service.FileServiceError as e:
            self.message("تعذّر فتح الملف", str(e), QMessageBox.Icon.Critical)
            return
        self.editor.setPlainText(text)
        self.current_path = path
        QTimer.singleShot(0, self.finish_load)
        self.recent.add(path)
        self.set_status(f"تم فتح: {path}" + (" — للقراءة فقط" if file_service.is_readonly(path) else ""))

    def save_to_path(self, path):
        """يكتب النص في الملف عبر الباك إند. ترجع True عند النجاح."""
        try:
            size = file_service.write_text(path, self.editor.toPlainText())
        except file_service.FileServiceError as e:
            self.message("فشل الحفظ", str(e), QMessageBox.Icon.Critical)
            self.set_status("فشل الحفظ")
            return False
        self.current_path = os.path.abspath(path)
        self.editor.document().setModified(False)
        self.update_title()
        self.remove_recovery()
        self.recent.add(self.current_path)
        self.set_status(f"تم الحفظ بنجاح ({size} بايت): {self.current_path}")
        return True

    def save_file(self):
        if self.current_path is None:      # ملف جديد لم يُحفظ بعد
            self.save_as_file()
        else:
            self.save_to_path(self.current_path)

    def save_as_file(self):
        start = self.current_path or "document.txt"
        path, _ = QFileDialog.getSaveFileName(self, "حفظ باسم", start, FILETYPES)
        if not path:
            return
        if not os.path.splitext(path)[1]:  # ضمان الامتداد المناسب
            path += ".txt"
            if os.path.exists(path) and not self.confirm(
                    "الملف موجود", "يوجد ملف بهذا الاسم. هل تريد استبداله؟", "استبدال", "إلغاء"):
                return
        self.save_to_path(path)

    # ================= إدارة الملفات =================
    def pick_file(self, title):
        start = os.path.dirname(self.current_path) if self.current_path else ""
        path, _ = QFileDialog.getOpenFileName(self, title, start, "كل الملفات (*.*)")
        return path

    def after_move(self, old, new):
        """تحديث الملف المفتوح والقائمة الحديثة بعد إعادة تسمية أو نقل ملف."""
        if same_path(old, self.current_path):
            self.current_path = os.path.abspath(new)
            self.update_title()
        self.recent.replace(old, new)

    def delete_file(self):
        path = self.pick_file("اختر الملف المراد حذفه")
        if not path:
            return
        if not self.confirm("تأكيد الحذف", f"هل أنت متأكد من حذف الملف نهائياً؟\n\n{path}", "حذف", "إلغاء"):
            return
        try:
            file_service.delete_file(path)
        except file_service.FileServiceError as e:
            self.message("فشل الحذف", str(e), QMessageBox.Icon.Critical)
            return
        if same_path(path, self.current_path):   # كان مفتوحاً: يبقى نصه كملف غير محفوظ
            self.current_path = None
            self.editor.document().setModified(True)
            self.update_title()
        self.recent.remove(path)
        self.set_status(f"تم حذف: {path}")

    def rename_file(self):
        path = self.pick_file("اختر الملف المراد إعادة تسميته")
        if not path:
            return
        new, ok = QInputDialog.getText(self, "إعادة تسمية", "الاسم الجديد للملف:",
                                       text=os.path.basename(path))
        if not ok or not new.strip():
            return
        try:
            new_path = file_service.rename_file(path, new)
        except file_service.FileServiceError as e:
            self.message("فشل إعادة التسمية", str(e), QMessageBox.Icon.Critical)
            return
        self.after_move(path, new_path)
        self.set_status(f"تمت إعادة التسمية إلى: {new_path}")

    def transfer_file(self, move):
        verb = "نقل" if move else "نسخ"
        src = self.pick_file(f"اختر الملف المراد {verb}ه")
        if not src:
            return
        dst_dir = QFileDialog.getExistingDirectory(self, f"اختر المجلد الوجهة لـ{verb} الملف",
                                                   os.path.dirname(src))
        if not dst_dir:
            return
        func = file_service.move_file if move else file_service.copy_file
        try:
            try:
                dst = func(src, dst_dir)
            except file_service.FileExistsConflict:
                if not self.confirm("الملف موجود", "يوجد ملف بالاسم نفسه في الوجهة.\nهل تريد استبداله؟",
                                    "استبدال", "إلغاء"):
                    return
                dst = func(src, dst_dir, overwrite=True)
        except file_service.FileServiceError as e:
            self.message(f"فشل {verb} الملف", str(e), QMessageBox.Icon.Critical)
            return
        if move:
            self.after_move(src, dst)
        self.set_status(f"تم {verb} الملف إلى: {dst}")
        self.message(APP_NAME, f"تم {verb} الملف بنجاح إلى:\n{dst}")

    def file_info(self):
        path = self.current_path
        if not path or not os.path.exists(path):
            path = self.pick_file("اختر ملفاً لعرض معلوماته")
            if not path:
                return
        try:
            info = file_service.file_info(path)
        except file_service.FileServiceError as e:
            self.message("تعذّر قراءة المعلومات", str(e), QMessageBox.Icon.Critical)
            return
        self.message("معلومات الملف", "\n".join(f"{k}: {v}" for k, v in info.items()))

    # ================= الملفات الحديثة =================
    def rebuild_recent_menu(self):
        self.recent_menu.clear()
        if not self.recent.items:
            self.recent_menu.addAction("(فارغة)").setEnabled(False)
            return
        for p in self.recent.items:
            action = self.recent_menu.addAction(p)
            action.triggered.connect(lambda checked=False, p=p: self.open_path(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("مسح القائمة", self.recent.clear)

    # ================= الحفظ التلقائي (خيط خلفي) =================
    def on_autosave_toggled(self, checked):
        self.autosave_enabled = checked
        self.set_status("تم تفعيل الحفظ التلقائي" if checked else "تم إيقاف الحفظ التلقائي")

    def set_autosave_interval(self):
        n, ok = QInputDialog.getInt(self, "الحفظ التلقائي",
                                    "الفترة بين كل حفظ تلقائي (بالثواني):",
                                    self.worker.interval, 5, 3600)
        if ok:
            self.worker.interval = n
            self.set_status(f"فترة الحفظ التلقائي: {n} ثانية (تُطبَّق بعد الدورة الحالية)")

    def poll_worker(self):
        """تعمل في خيط الواجهة كل 200 ملّي ثانية: تستقبل رسائل الخيط الخلفي."""
        try:
            while True:
                msg = self.worker.results.get_nowait()
                kind = msg[0]
                if kind == "tick":
                    if self.autosave_enabled:
                        self.submit_autosave()
                elif kind == "saved":
                    self.on_autosaved(*msg[1:])
                elif kind == "error":
                    self.set_status(f"فشل الحفظ التلقائي: {msg[1]}")
        except queue.Empty:
            pass

    def submit_autosave(self):
        """نأخذ لقطة من النص (في خيط الواجهة) ونسلّمها للخيط الخلفي ليكتبها."""
        if not self.editor.document().isModified():
            return
        text = self.editor.toPlainText()
        if self.current_path:
            if file_service.is_readonly(self.current_path):
                return                      # لا نحاول الكتابة في ملف للقراءة فقط
            self.worker.submit(self.current_path, text, True)
        else:                               # ملف جديد: نسخة استرجاع في مجلد المستخدم
            self.worker.submit(file_service.RECOVERY_DIR / "untitled.txt", text, False)

    def on_autosaved(self, path, text, is_real):
        if is_real and same_path(path, self.current_path) and self.editor.toPlainText() == text:
            self.editor.document().setModified(False)   # لم يتغير النص أثناء الكتابة
        self.set_status(f"تم الحفظ التلقائي {time.strftime('%H:%M:%S')}"
                        + ("" if is_real else " (نسخة استرجاع)"))

    def remove_recovery(self):
        try:
            os.remove(file_service.RECOVERY_DIR / "untitled.txt")
        except OSError:
            pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = App()
    window.show()
    sys.exit(app.exec())
