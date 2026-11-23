# -*- coding: utf-8 -*-
# =====================================================================
#  autosave.py — الحفظ التلقائي عبر خيط خلفي (Background Thread)
#
#  الفكرة (منتج/مستهلك):
#   • هذا الخيط يعمل كمؤقّت وككاتب في آن واحد: ينتظر مهمة بمهلة = فترة الحفظ،
#     وإذا انتهت المهلة يرسل رسالة "tick" لخيط الواجهة.
#   • خيط الواجهة هو الوحيد الذي يلمس عناصر الواجهة (Qt لا يسمح بلمسها من خيط آخر)،
#     فيأخذ لقطة نصية من المحرر ويضعها في طابور jobs.
#   • هذا الخيط ينفّذ عملية الكتابة البطيئة على القرص، فلا تتجمد الواجهة،
#     ويعيد النتيجة عبر طابور results.
#   • التزامن: queue.Queue آمن للخيوط، و write_text يستخدم قفلاً لكل ملف
#     فلا يتداخل الحفظ اليدوي مع التلقائي.
# =====================================================================
import queue
import threading

import file_service


class AutoSaveWorker(threading.Thread):
    def __init__(self, interval=30):
        super().__init__(name="AutoSaveWorker", daemon=True)
        self.interval = interval            # الفترة بالثواني
        self.jobs = queue.Queue()           # من الواجهة إلى الخيط
        self.results = queue.Queue()        # من الخيط إلى الواجهة
        self._stop_event = threading.Event()

    def submit(self, path, text, is_real):
        """is_real=True: الملف الأصلي، False: نسخة استرجاع لملف جديد لم يُحفظ."""
        self.jobs.put((str(path), text, is_real))

    def stop(self):
        self._stop_event.set()
        self.jobs.put(None)                 # إيقاظ الخيط لينتهي

    def run(self):
        while not self._stop_event.is_set():
            try:
                job = self.jobs.get(timeout=self.interval)
            except queue.Empty:
                self.results.put(("tick",))     # حان وقت الحفظ الدوري
                continue
            if job is None:
                break
            path, text, is_real = job
            try:
                if not is_real:
                    file_service.RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
                file_service.write_text(path, text)
                self.results.put(("saved", path, text, is_real))
            except file_service.FileServiceError as e:
                self.results.put(("error", str(e).splitlines()[0]))
            except Exception as e:              # حماية الخيط من التوقف لأي خطأ غير متوقع
                self.results.put(("error", str(e)))