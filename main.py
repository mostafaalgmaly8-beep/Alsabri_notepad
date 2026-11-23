# -*- coding: utf-8 -*-
# =====================================================================
#  main.py — نقطة تشغيل البرنامج:   python main.py
#  يفتح نافذة Al-sabri Notepad من ملف الواجهة qt.py
# =====================================================================
import sys

from PySide6.QtWidgets import QApplication

from qt import App, STYLE


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)      # التنسيق الداكن الأزرق
    window = App()
    window.show()
    sys.exit(app.exec())          # حلقة الأحداث: البرنامج ينتظر المستخدم حتى يغلق النافذة


if __name__ == "__main__":
    main()