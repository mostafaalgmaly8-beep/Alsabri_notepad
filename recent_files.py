# -*- coding: utf-8 -*-
# =====================================================================
#  recent_files.py — قائمة الملفات المفتوحة حديثاً (تُحفظ في JSON داخل مجلد المستخدم)
# =====================================================================
import json
import os

from file_service import CONFIG_DIR

RECENT_FILE = CONFIG_DIR / "recent.json"
MAX_RECENT = 10


class RecentFiles:
    def __init__(self):
        self.items = []
        self.load()

    def load(self):
        try:
            with open(RECENT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.items = [p for p in data if isinstance(p, str)][:MAX_RECENT]
        except (OSError, ValueError):
            self.items = []          # لا يوجد ملف أو ملف تالف: نبدأ بقائمة فارغة

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(RECENT_FILE, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
        except OSError:
            pass                     # فشل حفظ القائمة لا يجب أن يوقف البرنامج

    def add(self, path):
        path = os.path.abspath(path)
        self.remove(path, save=False)
        self.items.insert(0, path)
        del self.items[MAX_RECENT:]
        self.save()

    def remove(self, path, save=True):
        key = os.path.normcase(os.path.abspath(path))
        self.items = [p for p in self.items if os.path.normcase(p) != key]
        if save:
            self.save()

    def replace(self, old, new):
        """تحديث المسار بعد إعادة تسمية أو نقل ملف."""
        self.remove(old, save=False)
        self.add(new)

    def clear(self):
        self.items = []
        self.save()