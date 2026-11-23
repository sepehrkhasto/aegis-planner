# SPDX-License-Identifier: GPL-3.0-or-later
"""«تازه‌ها»: what an update changed, in three groups (added · improved · fixed) - and where to see each thing.

``CHANGES[version]`` is a list. Newer versions use ``Note`` entries (kind, title, detail, where); older ones are plain
strings (shown as one list). ``where`` is a key of ``tour.FEATURES``: the «نشانم بده» button closes the card, opens that page
and puts the tour's spotlight on the new thing. The card is shown once per version after an update and any time from
Settings → About or Ctrl+K «تازه‌ها»."""
from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .. import __version__
from ..core.jalali import fa
from .micro import MotionDialog
from .widgets import button, label


class Note(NamedTuple):
    kind: str                       # "added" | "improved" | "fixed"
    title: str
    detail: str = ""
    where: str | None = None        # key of tour.FEATURES, or None when there is nothing to point at


KINDS = (("added", "تازه"), ("improved", "بهتر شد"), ("fixed", "رفع شد"))

CHANGES: dict[str, list] = {
    "2.11.10": [
        Note("improved", "ویرایش هدف و عادت در صفحهٔ کامل",
             "هدف و عادت هم مثل تسک در یک صفحهٔ تمام‌عرض ویرایش می‌شوند؛ با Ctrl+Enter ذخیره کن و اگر چیزی نوشته باشی، پیش از دور ریختن می‌پرسد.", "forms"),
        Note("added", "انتخابگر ساعت",
             "به‌جای کادر ساعت قدیمی، یک شبکهٔ کوچک ساعت و دقیقه (با گام پنج‌دقیقه‌ای) باز می‌شود؛ با کلیک، چرخ ماوس یا کیبورد انتخاب کن."),
        Note("added", "بررسی اختیاری به‌روزرسانی",
             "در تنظیمات ← درباره می‌توانی بررسی نسخهٔ جدید را روشن کنی. پیش‌فرض خاموش است و هیچ داده‌ای از ولت فرستاده نمی‌شود."),
        Note("added", "متن‌باز با پروانهٔ GPL‑3.0",
             "کد کامل برنامه روی GitHub منتشر شده است تا هر کسی بتواند آن را بخواند و بسنجد."),
        Note("fixed", "بازبینی کامل کد",
             "چند مورد کم‌پیش‌آمد درست شد: تاریخ‌های خارج از بازه در افزودن سریع، «۱۲:۳۰ شب»، تسک تکراری با تاریخ نامعتبر، یادداشت‌های مهاجرت‌شدهٔ تکراری و خطای ذخیرهٔ خروجی در پوشهٔ بدون دسترسی."),
    ],
    "2.5.0": [
        Note("improved", "ویرایش تسک در صفحهٔ کامل",
             "تسک حالا مثل یادداشت در یک صفحهٔ تمام‌عرض باز می‌شود: عنوان درشت، کارت زمان‌بندی و دسته‌بندی، زیرتسک‌ها و توضیح، همه یک‌جا. اگر چیزی نوشته باشی و برگردی، پیش از دور ریختن می‌پرسد.", "forms"),
        Note("added", "راهنما در تنظیمات",
             "بخش تازهٔ «راهنما»: بیش از بیست پرسش و پاسخ با جست‌وجو، فهرست امکانات و سیاست حریم خصوصی کامل."),
        Note("added", "انتخابگر تاریخ تقویمی",
             "به‌جای سه فهرست روز و ماه و سال، یک تقویم جلالی کوچک باز می‌شود؛ با کلیک یا کیبورد روز را انتخاب کن."),
        Note("added", "«کار بعدی» در صفحهٔ امروز",
             "نواری بالای فهرست، مهم‌ترین کار همین لحظه را نشان می‌دهد؛ با یک کلیک تمرکز را روی همان کار شروع کن یا انجامش بده. پیشرفت روز هم کنارش است."),
        Note("improved", "تنظیمات ظاهر و کنترل‌ها",
             "تنظیمات ظاهر در چند کارت دسته‌بندی شد و اندازهٔ متن و چگالی پیش‌نمایش زنده دارند. فیلتر اهداف تب شد، دکمه‌های قبلی/امروز/بعدی تقویم یک کپسول شدند و کادرهای عددی دکمهٔ − و + گرفتند."),
        Note("fixed", "گزینه‌های بیشتر و قفل خودکار",
             "«گزینه‌های بیشتر» در فرم‌ها دوباره باز می‌شود و قفل خودکار هنگام باز بودن ویرایشگر دیگر پیام ذخیره‌نشده نمی‌دهد."),
    ],
    "2.4.0": [
        Note("improved", "فیلترهای چیپی و تب وضعیت",
             "فیلترهای تسک‌ها و تقویم حالا چیپ‌های گرد هستند که با انتخاب، رنگ می‌گیرند و مقدارشان را نشان می‌دهند. «باز / انجام‌شده / همه» یک تب با لغزش نرم است و گروه‌بندی یک چیپ روشن/خاموش. نوار ابزار یادداشت‌ها هم همین‌شکل شد."),
        Note("improved", "برگهٔ ویرایش تسک، عادت و هدف",
             "ویرایشگرها بدون نوار عنوان سیستم‌عامل، با سایهٔ نرم، دکمهٔ بستن، عنوان درشت و میان‌بر Ctrl+Enter برای ذخیره باز می‌شوند. با کشیدن هر جای خالی جابه‌جا می‌شوند."),
        Note("improved", "جزئیات بصری",
             "نوار پیشرفت باریک‌تر و آرام‌تر شد، نقشهٔ حرارتی عادت‌ها جمع‌وجور شد، صفر فارسی در تایل‌ها دیگر شبیه حلقهٔ درشت نیست، ردیف تسک باز دیگر نشان «انجام‌نشده» تکراری ندارد و مسیر ناوبری تنظیمات (تکراری) برداشته شد."),
    ],
    "2.3.1": [
        Note("fixed", "خطای پنجره‌ی رنگ و آمار یادداشت",
             "پنجره‌ی «رنگ یادداشت» و «آمار» بعد از یک بار باز شدن باعث خطا در ساخت، حذف و باز کردن یادداشت‌ها می‌شد. رفع شد."),
        Note("improved", "یکدست شدن همه‌ی صفحه‌ها",
             "همه‌ی صفحه‌ها با یک هدر مشترک شروع می‌شوند: عنوان، یک خط توضیح و خط ظریف حکاکی‌شده. سر ستون‌های کانبان نقطه‌ی وضعیت و شمارنده‌ی گرد دارند و سربرگ جدول‌ها سبک‌تر شد."),
        Note("improved", "دسترس‌پذیری",
             "کلید سوییچ نمای کارت/فهرست با Tab و کلیدهای جهت‌نما کار می‌کند و نام خوانا برای صفحه‌خوان دارد."),
    ],
    "2.3.0": [
        Note("added", "یادداشت‌های چندبخشی: متن، نوشتن با قلم و فلوچارت",
             "در یک یادداشت می‌توانی خط اول را تایپ کنی، بعد با قلم نوری یا ماوس بنویسی و بکشی، و بعد فلوچارت بسازی. فشار قلم دیده می‌شود؛ پاک‌کن، بازگردانی، رنگ و ضخامت دارد و برنامه را کند نمی‌کند."),
        Note("improved", "گالری یادداشت‌ها و ویرایشگر تمام‌صفحه",
             "صفحه‌ی اول یادداشت‌ها گالری کارت‌هاست (نمای کارت یا فهرست، پوشه‌ها، پیش‌نمایش نوشته و طرح). با کلیک روی هر یادداشت، همان یادداشت تمام‌صفحه باز می‌شود؛ Esc برمی‌گرداند."),
        Note("added", "خروجی یادداشت",
             "از دکمه‌ی خروجی بالای هر یادداشت: PDF چندصفحه‌ای، تصویر PNG یا Markdown همراه با تصویر طرح‌ها و فلوچارت‌ها."),
        Note("added", "چاپ تقویم روز و ماه",
             "از صفحه‌ی تقویم، چاپ یا ذخیره‌ی PDF روزانه، هفتگی و ماهانه، جدا از گزارش‌ها."),
        Note("fixed", "رفع یک کرش نادر",
             "یک سناریوی نادر هنگام تغییر سریع صفحه و تم که برنامه را می‌بست رفع شد."),
    ],
    "2.2.0": [
        Note("added", "لندینگ سینمایی لوکس‌تر",
             "دوربین آرام با پارالاکس ماوس، عمق میدان با تغییر فوکوس بین پنل‌ها، بازتاب نور لبه‌ی شیشه، فلر لنز، جرقه‌ها، شعار «برنامه‌ات، فقط مال خودت» و لوگوی سه‌بعدی فلزی. رنگ فیلم از تم انتخابی تو می‌آید و هر بار کمی فرق دارد."),
        Note("added", "صدای لندینگ",
             "موسیقی و جلوه‌های آرام همراه فیلم (فقط ویندوز). تنظیمات ← ظاهر ← «صدای لندینگ» خاموشش می‌کند."),
        Note("added", "۱۳ تم رنگی تازه",
             "علاوه بر نوآر، عاج و چینی، سیزده پالت منتخب در تنظیمات ← تم. بقیه‌ی تم‌های قدیمی حذف شدند؛ اگر یکی از آن‌ها را داشتی به نوآر برمی‌گردی."),
        Note("added", "تم خودکار با غروب",
             "تنظیمات ← ظاهر ← «تم خودکار با غروب»: بعد از غروب تم شبانه و بعد از طلوع تم روزانه."),
        Note("improved", "مُهر شدن هنگام قفل و باز کردن",
             "یک حلقه‌ی نور دور نشان بسته می‌شود و با کلیک ظریفی مهر می‌شود؛ هنگام باز کردن برعکس. ردیف‌های تازه یکی‌یکی با ۳۰ میلی‌ثانیه فاصله بالا می‌آیند و فشردن دکمه‌ها نرم‌تر شد."),
    ],
    "2.1.0": [
        Note("added", "لندینگ سینمایی هنگام باز کردن برنامه",
             "یک فیلم حدود ۲۰ ثانیه‌ای سه‌بعدی و لوکس: جرقه، چرخش لوگو، پنل‌های شیشه‌ای تقویم و تسک و عادت، و قفل. با «رد کردن»، Enter یا Esc هر لحظه می‌توانی رد کنی."),
        Note("added", "کلید خاموش‌کردن در تنظیمات",
             "تنظیمات ← ظاهر ← «لندینگ سینمایی». با «کاهش حرکت» فقط صفحه‌ی آخر با دکمه‌ی ورود نشان داده می‌شود."),
    ],
    "2.0.0": [
        Note("improved", "تغییر رمز امن‌تر",
             "با هر تغییر رمز، کلید داده‌ی ولت هم عوض می‌شود و ولت و همه‌ی پشتیبان‌ها دوباره رمز می‌شوند؛ رمز قدیمی دیگر هیچ‌کدام را باز نمی‌کند. اگر کلید بازیابی داشتی، یک کلید تازه نشانت داده می‌شود."),
        Note("improved", "تسک‌های تکراری همیشه جلوتر ساخته می‌شوند",
             "حتی اگر چند هفته برنامه را باز نکنی، تسک‌های تکراری از امروز تا ۳۰ روز (یا ۸ هفته) آینده آماده‌اند و رخدادی که پاک کرده‌ای برنمی‌گردد."),
        Note("improved", "ذخیره‌ی روان در ولت‌های خیلی بزرگ",
             "رمزنگاری و نوشتن روی دیسک برای ولت‌های بزرگ در پس‌زمینه انجام می‌شود و برنامه هنگام ذخیره نمی‌ایستد."),
        Note("improved", "افزودن سریع هوشمندتر",
             "«۲ صبحانه» دیگر ساعت حساب نمی‌شود، «۱ شب» یعنی ۰۱:۰۰، سال در «۱۵ مهر ۱۴۰۶» خوانده می‌شود و کلمه‌های «در/برای» وسط عنوان حفظ می‌شوند."),
        Note("fixed", "تقویم و کانبان",
             "کشیدن یک روز از تسک چندروزه آن را درست جابه‌جا می‌کند؛ کشیدن تسک تکراری به «انجام‌شده» رخداد بعدی را می‌سازد."),
        Note("fixed", "یادداشت‌ها و قفل",
             "بعد از حذف یادداشت یا قفل شدن، ویرایشگر خالی و غیرفعال می‌شود؛ پیام‌ها و کلید بازیابی روی صفحه‌ی قفل نمی‌مانند."),
        Note("fixed", "ده‌ها اصلاح کوچک",
             "مقاوم‌تر در برابر داده‌ی بدشکل، ذخیره‌ی ناموفق هنگام قفل، و پوشه‌ی پشتیبانِ در دسترس‌نبودن."),
    ],
    "1.5.1": [
        Note("added", "حذف برنامه با صفحه‌ی تأیید",
             "حذف از تنظیمات ویندوز یک صفحه‌ی هم‌سبک برنامه نشان می‌دهد: چه چیزی پاک می‌شود، و اینکه پوشه‌ی پشتیبان‌ها می‌ماند."),
        Note("improved", "پشتیبان‌گیری مطمئن‌تر",
             "اگر فایل ولت آسیب دیده باشد یا پوشه‌ی پشتیبان در دسترس نباشد، برنامه پیام روشن می‌دهد و چیزی از دست نمی‌رود."),
        Note("improved", "کلید بازیابی",
             "با پیشوند AEGIS- یا بدون آن پذیرفته می‌شود، و کلیدِ کپی‌شده بعد از یک دقیقه از کلیپ‌بورد پاک می‌شود."),
        Note("improved", "قفل خودکار بی‌صدا",
             "اگر وسط کار قفل شود هیچ پنجره‌ی اضافه‌ای باز نمی‌ماند و کارِ ذخیره‌نشده اول ذخیره می‌شود."),
        Note("fixed", "ساعت‌های لبه‌ای",
             "«۱۲ شب» در افزودن سریع حالا ۲۳:۵۹ همان روز است و ساعت‌های نامعتبر یادآوری را خراب نمی‌کنند."),
        Note("fixed", "هدف‌ها و تسک‌های بایگانی‌شده",
             "پیشرفت هدف بعد از بایگانی‌شدن تسک‌ها کم نمی‌شود."),
        Note("fixed", "مصرف حافظه در کار طولانی",
             "پنجره‌ها و منوهای بسته‌شده دیگر در حافظه نمی‌مانند؛ برنامه بعد از چند روز باز بودن هم سبک می‌ماند."),
        Note("fixed", "شناسه‌های یکتا",
             "ساخت دسته‌ای تسک‌ها دیگر هیچ‌وقت دو شناسه‌ی یکسان نمی‌سازد و ولت‌های قدیمی خودشان را اصلاح می‌کنند."),
    ],
    "1.5.0": [
        Note("added", "تقویمِ قابل‌کشیدن",
             "روی شبکه‌ی هفته یا روز بکش تا تسک بسازی؛ تسک را بکش تا جابه‌جا شود و از لبه‌ی پایینش بکش تا طولش عوض شود.", "calendar"),
        Note("added", "ساخت سریع روی تقویم",
             "بعد از کشیدن فقط عنوان را بنویس و Enter بزن. روی ماه هم می‌شود چند روز را برای تسک چندروزه کشید.", "calendar"),
        Note("added", "نمای سال، مینی‌تقویم و میان‌بُرها",
             "مینی‌تقویم کنار صفحه، نمای «سال» و کلیدهای T ، M ، W ، D ، A ، Y برای رفتن بین نماها.", "calendar_year"),
        Note("added", "تور معرفی",
             "یک تور نورافکنی روی خود برنامه، برای همه‌ی بخش‌ها؛ از تنظیمات ← درباره دوباره ببینش.", "tour"),
        Note("added", "تم‌های روشن تازه",
             "چهار تم روشن اضافه شد و انتخاب تم حالا دو بخش دارد: تیره و روشن.", "themes"),
        Note("improved", "فرم‌های جمع‌وجورتر",
             "فقط چیزهای ضروری اول می‌آید؛ بقیه پشت «گزینه‌های بیشتر» است.", "forms"),
        Note("improved", "لیست‌های کشویی شیشه‌ای",
             "مرتب‌سازی و فیلتر شکل تازه دارند و فیلتر فعال با یک نقطه دیده می‌شود.", "sort"),
        Note("improved", "عوض‌کردن تم سریع‌تر شد",
             "صفحه‌ها فقط وقتی باز می‌شوند ساخته می‌شوند، پس تم زودتر روی همه‌چیز می‌نشیند.", "themes"),
        Note("improved", "متن‌ها بازنویسی شد",
             "پیام‌ها یکدست‌تر و طبیعی‌تر شدند؛ صفحه‌ی ورود حالا «خوش برگشتی» می‌گوید."),
        Note("improved", "حالت‌های خالی روشن‌تر",
             "تسک‌ها، سطل زباله و پشتیبان‌ها وقتی خالی‌اند می‌گویند چه کار کنی."),
        Note("fixed", "بستن جست‌وجو",
             "پنجره‌ی Ctrl+K دکمه‌ی × دارد و با کلیک بیرون از آن هم بسته می‌شود.", "palette"),
        Note("fixed", "نمودار PDF", "برچسب مقیاس دیگر روی آخرین ستون نمی‌افتد."),
        Note("fixed", "پنجره‌ی رمز", "نوار قدرت رمز جمع‌وجورتر شد و پیام خطای خالی جا نمی‌گیرد."),
    ],
    "1.4.1": [
        "لیست «امروز»: کارهای انجام‌شده حالا تیک‌خورده و خط‌خورده دیده می‌شوند و با یک کلیک به حالت باز برمی‌گردند",
        "هیت‌مپ عادت‌ها روی پنجره‌های عریض مربع‌ها را بزرگ می‌کند تا یک سال کامل کارت را پر کند",
        "افزودن سریع از هرجا: اگر Ctrl+Alt+Space دست برنامهٔ دیگری بود، خودکار روی Ctrl+Shift+Space می‌رود و تنظیمات همان را نشان می‌دهد",
        "عدد «۰» در کاشی‌ها آرام و کم‌رنگ شد تا شبیه دکمهٔ رادیویی دیده نشود",
    ],
    "1.4.0": [
        "گواهی ولت: کارت شمارهٔ ولت، اثر انگشت و تاریخ تولد ولتِ تو - با نوری که همراه ماوس می‌چرخد؛ قابل ذخیره به‌صورت تصویر (تنظیمات ← ولت)",
        "گزارش PDF با سربرگ برند - فقط عددها و نمودارها، بدون حتی یک کلمه از متن کارها (گزارش‌ها ← PDF)",
        "«مهر هفته»: هر هفته یک کارت زیبا از پیشرفتت، آمادهٔ ذخیره یا کپی",
        "نور محیطی ظریف که با ساعت روز کمی گرم و سرد می‌شود، و کارت آرام «شروع روز» (هر دو در تنظیمات قابل خاموش‌شدن)",
        "۲۲ آیکون با لبه‌های برش‌خورده و هم‌خانوادهٔ سپر، فونت وزن‌دار واقعی و تم «ابسیدین» برای صفحه‌های OLED (تنظیمات)",
        "روی لپ‌تاپ‌های کوچک: پنجره از صفحه بیرون نمی‌زند، سایدبار فشرده می‌شود و تنظیمات اسکرول افقی ندارد؛ آیکون فایل‌های .aegis و تصویرهای نصب‌کننده هم تازه شد",
    ],
    "1.3.0": [
        "ساعت تمرکز تازه: حلقهٔ ۶۰ نشانه، عددهای درشت و ثابت و یک نفس آرام وقتی تایمر می‌رود",
        "نمودارها با کراس‌هیر و راهنمای شیشه‌ای، و روند کوچک در کاشی‌های «امروز»",
        "Ctrl+K نسخهٔ ۲: شیشه‌ای، بخش «اخیراً» و پیش‌نمایش گزینهٔ انتخاب‌شده",
        "افزودن سریع از هرجای ویندوز با Ctrl+Alt+Space (در تنظیمات قابل خاموش‌شدن)",
        "خالی‌بودن صفحه‌ها با سپر خطی، اسکلتون بارگذاری گزارش‌ها، اسکرول نرم و آیکون سینی که قفل/باز را نشان می‌دهد",
        "ساخت ولت با مراسم مهر: نوار قدرت رمز مثل شمش فلزی پر می‌شود و درهای سپر با یک جمله باز می‌شوند",
    ],
    "1.2.0": [
        "هویت تازهٔ ایجیس: «نوآر» - مشکیِ مات و عمیق با پلاتین؛ زمردی و رُز و تم روزِ «چینی» هم هستند (طلا در تنظیمات)",
        "نشان فلزی جدید، قلم برند، دانهٔ ظریف و کارت‌های چندلایه",
        "سایدبار: کپسول لغزان، نور دنبال‌کنندهٔ ماوس، آیکون‌های زنده، جمع‌شدن نرم و نشان تعداد",
        "hover کارت‌ها با نور و حاشیهٔ زنده، یک «برق» روی دکمهٔ اصلی و اعداد غلتان",
        "باز و بسته شدن ولت مثل دو نیمهٔ سپر، و «مهر روز» وقتی همهٔ کارهای امروز تمام شد",
    ],
    "1.1.0": [
        "Ctrl+K حالا تسک می‌سازد: «تسک بساز فردا ساعت ۱۰ جلسه»",
        "واگرد ۱۰ ثانیه‌ای بعد از حذف و انجام گروهی (Ctrl+Z)",
        "ویرایش عنوان با F2، گروه‌بندی تسک‌ها و پیش‌نمایش با Space",
        "راست‌کلیک غنی‌تر: موعد و اولویت سریع، کپی عنوان",
        "تم «طلا و مشکی»، تم «کنتراست بالا» و حالت تمرکز کامل (Ctrl+Shift+F)",
        "صدای ظریف اختیاری و چگالی ردیف‌ها در تنظیمات",
    ],
}


def entries_for(version: str) -> list[Note]:
    """Every entry of a version as ``Note`` (an old plain string becomes an untitled «added» one with kind ``""``)."""
    out = []
    for e in CHANGES.get(version, []):
        out.append(e if isinstance(e, Note) else Note("", e))
    return out


def notes_for(version: str) -> list[str]:
    """The entries as plain lines (title — detail), for callers that only need text."""
    return [e.title if not e.detail else f"{e.title}: {e.detail}" for e in entries_for(version)]


class _Dot(QWidget):
    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.setFixedSize(10, 22)

    def paintEvent(self, _e) -> None:  # noqa: N802
        from .fx_widgets import _fpal
        pal = _fpal(self)
        col = {"added": pal["accent"], "improved": pal["accent2"], "fixed": pal["ok"]}.get(self.key, pal["muted"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        p.drawEllipse(QRectF(1, 8, 7, 7))


class _Row(QWidget):
    """One change: a bold title, a quiet line under it and - when there is something to look at - «نشانم بده»."""
    def __init__(self, note: Note, show):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(note.title)
        f = QFont(t.font())
        f.setWeight(QFont.Weight.DemiBold)
        t.setFont(f)
        t.setWordWrap(True)
        col.addWidget(t)
        if note.detail:
            col.addWidget(label(note.detail, "Muted", True))
        lay.addLayout(col, 1)
        if note.where:
            b = button("نشانم بده ‹", "Link", lambda k=note.where: show(k))
            b.setToolTip("همین‌جا را روی خود برنامه نشان می‌دهد")
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)


class WhatsNew(MotionDialog):
    MAX_H = 660

    def __init__(self, win, version: str = __version__):
        super().__init__(win)
        self.win, self.version = win, version
        self._pending: str | None = None
        self.setWindowTitle("تازه‌ها")
        self.setProperty("theme", win.theme)
        self.setFixedWidth(600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 24, 30, 20)
        lay.setSpacing(6)
        t = label(f"تازه‌های نسخه‌ی {fa(version)}", "H1")
        lay.addWidget(t)
        self.sub = label("چه چیزی اضافه شد، چه چیزی بهتر شد و چه چیزی درست شد - و از کجا می‌شود دیدش.", "Muted", True)
        lay.addWidget(self.sub)
        lay.addSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        body = QWidget()
        body.setObjectName("WnBody")
        body.setStyleSheet("QWidget#WnBody { background: transparent; }")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(2)
        self.rows: list[_Row] = []
        entries = entries_for(version)
        for kind, name in KINDS:
            items = [e for e in entries if e.kind == kind]
            if not items:
                continue
            head = QHBoxLayout()
            head.setSpacing(6)
            head.addWidget(_Dot(kind))
            h = label(f"{name}  —  {fa(len(items))}", "Muted")
            f = QFont(h.font())
            f.setWeight(QFont.Weight.DemiBold)
            h.setFont(f)
            head.addWidget(h)
            head.addStretch(1)
            bl.addSpacing(8)
            bl.addLayout(head)
            for e in items:
                r = _Row(e, self._show)
                self.rows.append(r)
                bl.addWidget(r)
        loose = [e for e in entries if e.kind not in dict(KINDS)]
        for e in loose:                                              # versions written before the three groups: one plain list
            r = _Row(e, self._show)
            self.rows.append(r)
            bl.addWidget(r)
        bl.addStretch(1)
        self.scroll.setWidget(body)
        lay.addWidget(self.scroll, 1)
        lay.addSpacing(8)
        row = QHBoxLayout()
        self.tour_btn = button("دیدن معرفی کامل برنامه", "Link", self._tour)
        self.ok = button("بریم", "Primary", self.accept)
        row.addWidget(self.ok)
        row.addWidget(self.tour_btn)
        row.addStretch(1)
        lay.addLayout(row)
        body.adjustSize()
        want = body.sizeHint().height() + 150
        scr = win.screen().availableGeometry().height() if win.screen() else 900
        self.setFixedHeight(max(300, min(self.MAX_H, scr - 90, want)))

    # ---- «نشانم بده»
    def _show(self, key: str) -> None:
        self._pending = key
        self.accept()

    def _tour(self) -> None:
        self._pending = "__tour__"
        self.accept()

    def done(self, r: int) -> None:
        self.win.set_pref("seen_version", self.version)
        super().done(r)
        key, self._pending = self._pending, None
        if key == "__tour__":
            QTimer.singleShot(200, self.win.show_tour)
        elif key:
            QTimer.singleShot(200, lambda: self.win.show_feature(key))
