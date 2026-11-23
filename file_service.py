# -*- coding: utf-8 -*-
# =====================================================================
#  file_service.py — الباك إند: كل التعامل مع نظام الملفات في نظام التشغيل
#  الواجهة (qt_app.py) تستدعي هذه الدوال فقط ولا تلمس القرص بنفسها.
#
#  الدوال:  read_text · write_text · delete_file · rename_file
#           copy_file · move_file · file_info · is_readonly
# =====================================================================
import os
import shutil
import stat
import tempfile
import threading
import time
from pathlib import Path

# مجلد إعدادات البرنامج داخل مجلد المستخدم (سنستخدمهما لاحقاً للملفات الحديثة والحفظ التلقائي)
CONFIG_DIR = Path.home() / ".al_sabri_notepad"
RECOVERY_DIR = CONFIG_DIR / "recovery"

MAX_FILE_SIZE = 20 * 1024 * 1024   # 20 ميغابايت: حد أقصى حتى لا تمتلئ الذاكرة


# ===================== الأخطاء (Error Handling) =====================
class FileServiceError(Exception):
    """خطأ في عمليات الملفات. رسالته عربية جاهزة للعرض للمستخدم."""


class FileMissingError(FileServiceError):
    """الملف أو المجلد غير موجود (ENOENT)."""


class FileReadOnlyError(FileServiceError):
    """الملف للقراءة فقط (لا توجد صلاحية كتابة)."""


class FileExistsConflict(FileServiceError):
    """يوجد ملف بالاسم نفسه في الوجهة (EEXIST)."""


def _translate(exc, path):
    """تحويل أخطاء نظام التشغيل (OSError) إلى رسائل عربية مفهومة.
    الأخطاء الخاصة أولاً، والعام OSError في الآخر."""
    if isinstance(exc, FileNotFoundError):
        return FileMissingError(f"الملف أو المسار غير موجود:\n{path}")
    if isinstance(exc, PermissionError):
        return FileServiceError(f"لا تملك الصلاحية اللازمة لتنفيذ العملية على:\n{path}")
    if isinstance(exc, IsADirectoryError):
        return FileServiceError(f"المسار مجلد وليس ملفاً:\n{path}")
    if isinstance(exc, FileExistsError):
        return FileExistsConflict(f"يوجد عنصر بالاسم نفسه مسبقاً:\n{path}")
    if isinstance(exc, OSError):
        return FileServiceError(f"خطأ من نظام التشغيل (رمز {exc.errno}): {exc.strerror}\n{path}")
    return FileServiceError(str(exc))


# ===================== قفل لكل ملف (للحفظ التلقائي لاحقاً) =====================
# الحفظ اليدوي (خيط الواجهة) والحفظ التلقائي (خيط خلفي) قد يكتبان في الملف نفسه معاً،
# فنستخدم قفلاً (Lock) لكل ملف حتى لا يتداخلا (Race Condition).
_locks = {}
_locks_guard = threading.Lock()


def _lock_for(path):
    key = os.path.normcase(os.path.abspath(path))
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


# ===================== القراءة =====================
def read_text(path):
    """قراءة ملف نصي وإرجاع محتواه.
    في النواة: open ثم read ثم close."""
    try:
        if os.path.isdir(path):
            raise IsADirectoryError(path)
        if os.path.getsize(path) > MAX_FILE_SIZE:
            raise FileServiceError("حجم الملف كبير جداً (أكثر من 20 ميغابايت).")
        with open(path, "rb") as f:      # نقرأ البايتات الخام أولاً ثم نفك ترميزها بأنفسنا
            data = f.read()
    except FileServiceError:
        raise
    except OSError as e:
        raise _translate(e, path) from e

    if b"\x00" in data[:8192]:           # وجود بايت صفري يعني أن الملف ثنائي وليس نصاً
        raise FileServiceError("يبدو أن الملف ثنائي (غير نصي) ولا يمكن عرضه في المحرر.")

    # نجرّب UTF-8 أولاً، ثم ترميز ويندوز العربي cp1256
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileServiceError("تعذّر قراءة الملف: ترميزه غير مدعوم.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ===================== الكتابة (حفظ آمن) =====================
def is_readonly(path):
    """هل الملف موجود وللقراءة فقط؟  os.access يسأل نظام التشغيل عن الصلاحية."""
    return os.path.isfile(path) and not os.access(path, os.W_OK)


def write_text(path, text):
    """حفظ آمن: نكتب في ملف مؤقت ← fsync ← os.replace (استبدال ذرّي).
    فإذا انقطع التيار في المنتصف يبقى الملف الأصلي سليماً.
    بعد الحفظ نعيد قراءة الملف للتحقق. ترجع حجم الملف بالبايت."""
    path = os.path.abspath(path)
    directory = os.path.dirname(path)

    with _lock_for(path):
        if not os.path.isdir(directory):
            raise FileMissingError(f"المجلد غير موجود:\n{directory}")

        existed = os.path.exists(path)
        if existed:
            if os.path.isdir(path):
                raise FileServiceError(f"المسار مجلد وليس ملفاً:\n{path}")
            if not os.access(path, os.W_OK):         # فحص الصلاحيات قبل الكتابة
                raise FileReadOnlyError(
                    f"الملف للقراءة فقط ولا يمكن الحفظ فيه.\nاستخدم «حفظ باسم» لحفظ نسخة جديدة:\n{path}")
        elif not os.access(directory, os.W_OK):
            raise FileServiceError(f"لا تملك صلاحية الكتابة في المجلد:\n{directory}")

        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".~notepad_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())                 # إجبار النظام على كتابة البيانات للقرص فعلاً
            if existed:
                shutil.copymode(path, tmp)           # نحافظ على صلاحيات الملف الأصلي
            else:
                os.chmod(tmp, 0o644)
            os.replace(tmp, path)                    # rename ذرّية: يستبدل الملف دفعة واحدة
            tmp = None
        except OSError as e:
            raise _translate(e, path) from e
        finally:
            if tmp and os.path.exists(tmp):          # تنظيف الملف المؤقت عند الفشل
                try:
                    os.remove(tmp)
                except OSError:
                    pass

        # التحقق من نجاح الحفظ
        if read_text(path) != text.replace("\r\n", "\n"):
            raise FileServiceError("فشل التحقق: المحتوى المحفوظ لا يطابق المحتوى الحالي.")
        return os.path.getsize(path)


# ===================== حذف / إعادة تسمية / نسخ / نقل =====================
def delete_file(path):
    """حذف ملف.  في النواة: unlink (ويندوز: DeleteFile)."""
    if not os.path.exists(path):
        raise FileMissingError(f"الملف غير موجود:\n{path}")
    if not os.path.isfile(path):
        raise FileServiceError("المسار المحدد ليس ملفاً.")
    try:
        os.remove(path)
    except OSError as e:
        raise _translate(e, path) from e
    if os.path.exists(path):
        raise FileServiceError("لم يتم حذف الملف.")


def rename_file(path, new_name):
    """إعادة تسمية ملف داخل مجلده. ترجع المسار الجديد.  في النواة: rename."""
    new_name = new_name.strip()
    if not new_name or new_name in (".", ".."):
        raise FileServiceError("الاسم الجديد غير صالح.")
    if any(c in new_name for c in '<>:"/\\|?*'):
        raise FileServiceError('الاسم يحتوي على رموز غير مسموحة:  < > : " / \\ | ? *')
    if not os.path.isfile(path):
        raise FileMissingError(f"الملف غير موجود:\n{path}")

    path = os.path.abspath(path)
    new_path = os.path.join(os.path.dirname(path), new_name)
    if os.path.normcase(new_path) == os.path.normcase(path):
        raise FileServiceError("الاسم الجديد مطابق للاسم الحالي.")
    if os.path.lexists(new_path):                    # التحقق من عدم وجود ملف بالاسم نفسه
        raise FileExistsConflict(f"يوجد ملف آخر بالاسم نفسه في المجلد:\n{new_path}")
    try:
        os.rename(path, new_path)
    except OSError as e:
        raise _translate(e, path) from e
    return new_path


def _prepare_transfer(src, dst_dir, overwrite):
    """فحوصات مشتركة للنسخ والنقل. ترجع مسار الملف في الوجهة."""
    if not os.path.isfile(src):
        raise FileMissingError(f"الملف المصدر غير موجود:\n{src}")
    if not os.path.isdir(dst_dir):
        raise FileMissingError(f"مجلد الوجهة غير موجود:\n{dst_dir}")
    dst = os.path.join(os.path.abspath(dst_dir), os.path.basename(src))
    if os.path.normcase(dst) == os.path.normcase(os.path.abspath(src)):
        raise FileServiceError("المصدر والوجهة متطابقان.")
    if os.path.exists(dst) and not overwrite:
        raise FileExistsConflict(dst)
    return dst


def copy_file(src, dst_dir, overwrite=False):
    """نسخ ملف إلى مجلد آخر. ترجع مسار النسخة الجديدة."""
    dst = _prepare_transfer(src, dst_dir, overwrite)
    try:
        shutil.copy2(src, dst)           # ينسخ المحتوى وتواريخ الملف وصلاحياته
    except OSError as e:
        raise _translate(e, dst) from e
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
        raise FileServiceError("فشل التحقق من نسخ الملف.")
    return dst


def move_file(src, dst_dir, overwrite=False):
    """نقل ملف إلى مجلد آخر. ترجع مسار الملف الجديد.
    على القرص نفسه: rename سريع. بين قرصين: نسخ ثم حذف الأصل."""
    dst = _prepare_transfer(src, dst_dir, overwrite)
    try:
        shutil.move(src, dst)
    except OSError as e:
        raise _translate(e, dst) from e
    if not os.path.exists(dst) or os.path.exists(src):
        raise FileServiceError("فشل التحقق من نقل الملف.")
    return dst


# ===================== معلومات الملف =====================
def human_size(n):
    """تحويل الحجم بالبايت إلى نص مقروء."""
    size = float(n)
    for unit in ("بايت", "ك.ب", "م.ب", "ج.ب"):
        if size < 1024 or unit == "ج.ب":
            return f"{int(size)} {unit}" if unit == "بايت" else f"{size:.2f} {unit}"
        size /= 1024


def file_info(path):
    """معلومات الملف كقاموس: الاسم، المسار، الحجم، النوع، آخر تعديل، الصلاحيات، الحالة."""
    path = os.path.abspath(path)
    try:
        st = os.stat(path)               # في النواة: stat — تقرأ بيانات الملف من نظام الملفات
    except OSError as e:
        raise _translate(e, path) from e
    ext = os.path.splitext(path)[1]
    writable = os.access(path, os.W_OK)
    return {
        "اسم الملف": os.path.basename(path),
        "المسار الكامل": path,
        "الحجم": f"{human_size(st.st_size)} ({st.st_size} بايت)",
        "الامتداد / النوع": (ext.lstrip(".").upper() + " — ملف نصي") if ext else "بدون امتداد",
        "آخر تعديل": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        "الصلاحيات": stat.filemode(st.st_mode),
        "حالة الملف": "قابل للكتابة (Read/Write)" if writable else "للقراءة فقط (Read-Only)",
    }


# ===================== تجربة سريعة:  python file_service.py =====================
if __name__ == "__main__":
    work = tempfile.mkdtemp()
    f = os.path.join(work, "test.txt")
    print("1) حفظ وقراءة:")
    write_text(f, "مرحباً بالعالم\nHello World")
    print("  ", repr(read_text(f)))

    print("2) معلومات الملف:")
    for k, v in file_info(f).items():
        print(f"   {k}: {v}")

    print("3) إعادة تسمية:")
    f = rename_file(f, "renamed.txt")
    print("  ", os.path.basename(f))

    print("4) نسخ ثم نقل:")
    sub = os.path.join(work, "sub")
    os.mkdir(sub)
    copied = copy_file(f, sub)
    print("   نسخ إلى:", copied)
    os.remove(copied)
    print("   نقل إلى:", move_file(f, sub))

    print("5) حالة الأخطاء:")
    for label, action in [
        ("ملف غير موجود", lambda: read_text(os.path.join(work, "nope.txt"))),
        ("حذف غير موجود", lambda: delete_file(os.path.join(work, "nope.txt"))),
    ]:
        try:
            action()
        except FileServiceError as e:
            print(f"   {label}: {str(e).splitlines()[0]}")

    ro = os.path.join(work, "readonly.txt")
    write_text(ro, "x")
    os.chmod(ro, 0o444)
    try:
        write_text(ro, "y")
        print("   (تنبيه: المستخدم الحالي يتجاوز الصلاحيات، لذلك لم يُمنع الحفظ)")
    except FileReadOnlyError as e:
        print("   قراءة فقط:", str(e).splitlines()[0])
    shutil.rmtree(work, ignore_errors=True)