<div dir="rtl" align="right">

# راهنمای گام‌به‌گام انتشار روی GitHub (برای مبتدی)

این راهنما فرض می‌کند هیچ‌چیز نصب نیست. مسیر: **حساب ← نصب Git ← ساخت مخزن ← آپلود کد ← تنظیمات ← انتشار فایل exe**. نام کاربری گیت‌هابِ خودت را در متن جای `YOUR_USERNAME` بگذار.

## ۱. ساخت حساب GitHub

1. به github.com برو و Sign up بزن (ایمیل، رمز، نام کاربری).
2. ایمیل را تأیید کن.
3. **حتماً** احراز هویت دومرحله‌ای را روشن کن: Settings ← Password and authentication ← Two-factor authentication. کدهای بازیابی را جایی امن نگه دار.
4. توصیهٔ حریم خصوصی: Settings ← Emails ← تیک «Keep my email addresses private» و «Block command line pushes that expose my email». آدرس noreply خودت (مثل `12345+USERNAME@users.noreply.github.com`) همان‌جا نوشته شده است.

## ۲. نصب Git

1. از git-scm.com نسخهٔ Windows را دانلود و نصب کن. **همهٔ گزینه‌ها را پیش‌فرض بگذار** (فقط Next بزن)، چون پیش‌فرض‌ها درست‌اند.
2. بعد از نصب، پوشه‌ای را در File Explorer باز کن، کلیک راست ← **Open Git Bash here** (یا PowerShell). دستورها را همان‌جا بزن.
3. یک‌بار هویتت را معرفی کن (ایمیل noreply بخش ۱):

```bash
git config --global user.name "نام یا نام کاربری تو"
git config --global user.email "12345+YOUR_USERNAME@users.noreply.github.com"
```

## ۳. ساخت مخزن (Repository) خالی

1. در GitHub، بالا سمت راست **+ ← New repository**.
2. Repository name: `aegis-planner` (یا هر نام دلخواه).
3. Description: «Offline encrypted planner for Windows (Persian, Jalali calendar)».
4. **Public** را انتخاب کن (برای اینکه مردم کد و فایل exe را ببینند و Actions رایگان باشد).
5. **هیچ‌کدام** از «Add a README file»، «.gitignore» و «license» را تیک نزن؛ این فایل‌ها داخل زیپ هستند.
6. **Create repository** را بزن. صفحه‌ای با آدرس `https://github.com/YOUR_USERNAME/aegis-planner.git` نشان می‌دهد.

## ۴. آپلود کد

آپلود از طریق وب‌سایت برای این پروژه مناسب نیست (محدودیت ۱۰۰ فایل در هر بار)؛ از Git استفاده کن.

۱. زیپ `aegis-planner-2.11.10-github.zip` را **Extract All** کن. پوشهٔ بیرون‌آمده را باز کن (جایی که `README.md` و `LICENSE` هست).
۲. داخل آن پوشه Git Bash را باز کن و آدرس مخزن را در فایل‌ها جایگزین کن:

```bash
python tools/set_repo.py YOUR_USERNAME
```

(اگر نام مخزن را عوض کردی: `python tools/set_repo.py YOUR_USERNAME/نام-مخزن`. اگر `python` شناخته نشد، آن را از python.org نصب کن یا فایل‌های `sepehrkhasto/aegis-planner` را در README.md، README.fa.md، CONTRIBUTING.md، docs/BUILD.md و aegis_desktop/__init__.py با دست ویرایش کن.)

۳. مخزن محلی بساز و اولین کامیت را بزن:

```bash
git init -b main
git add .
git status
```

در خروجی `git status` باید فقط فایل‌های پروژه را ببینی. اگر فایلی مثل `vault.aegis`، `prefs.json`، `*.pfx` یا `backups/` دیدی، **متوقف شو**؛ `.gitignore` باید آن‌ها را کنار بگذارد و هرگز نباید داخل مخزن عمومی بروند. اگر درست بود:

```bash
git commit -m "Initial release 2.11.10"
git remote add origin https://github.com/YOUR_USERNAME/aegis-planner.git
git push -u origin main
```

۴. هنگام `git push` یک پنجرهٔ ورود (Git Credential Manager) باز می‌شود؛ **Sign in with your browser** را بزن و تأیید کن. (رمز حساب را در ترمینال نمی‌پذیرد؛ از همین مرورگر یا Personal Access Token استفاده می‌شود.)

۵. صفحهٔ مخزن را تازه کن: README با تصاویر باید نمایش داده شود.

> هشدارهای `LF will be replaced by CRLF` در ویندوز عادی هستند.

## ۵. تنظیمات مخزن (یک‌بار)

در صفحهٔ مخزن:

- **About** (چرخ‌دنده کنار About): توضیح کوتاه و Topics مثل `planner`, `pyqt6`, `jalali`, `persian`, `encryption`, `offline`, `windows`.
- **Settings ← Code security** (یا Advanced Security) ← **Private vulnerability reporting: Enable**، تا گزارش‌های امنیتی خصوصی برسند (SECURITY.md به آن اشاره می‌کند).
- **Settings ← Actions ← General ← Workflow permissions**: اگر گزینه‌ها دیدی، **Read and write permissions** را انتخاب و Save کن (برای ساخت Release لازم است).
- تب **Actions**: workflow با نام `tests` پس از push خودکار اجرا می‌شود (چند دقیقه). تیک سبز یعنی همهٔ تست‌ها در ویندوز GitHub گذشته‌اند.

## ۶. انتشار برنامه (exe) کنار کد

دو راه دارد. راه خودکار پیشنهاد می‌شود.

### راه الف (خودکار، پیشنهادی)

نسخه‌ی داخل کد `2.11.10` است؛ برچسب (tag) باید دقیقاً `v2.11.10` باشد.

```bash
git tag v2.11.10
git push origin v2.11.10
```

- به تب **Actions** برو؛ workflow `release` شروع می‌شود (۱۵ تا ۳۰ دقیقه): تست ← PyInstaller ← Inno Setup ← فایل‌ها ← SHA256.
- بعد از موفقیت، در صفحهٔ اصلی مخزن، ستون راست، بخش **Releases** نسخهٔ `Aegis Planner 2.11.10` با این فایل‌ها ظاهر می‌شود:
  - `AegisPlanner-Setup-2.11.10.exe` (نصب‌کننده)
  - `AegisPlanner-portable-2.11.10.zip` (بدون نصب)
  - `SHA256SUMS.txt` (و هش‌ها در توضیحات)
- کاربر با کلیک روی همین فایل‌ها دانلود می‌کند. لینک ثابت «آخرین نسخه»: `https://github.com/YOUR_USERNAME/aegis-planner/releases/latest`.

اگر workflow قرمز شد: روی اجرای ناموفق کلیک کن، گام قرمز را باز کن و متن خطا را برای من بفرست.

### راه ب (دستی)

1. روی ویندوز، `build_windows.bat` را اجرا کن؛ فایل `installer_output\AegisPlanner-Setup-2.11.10.exe` ساخته می‌شود.
2. هش را بگیر: `Get-FileHash .\installer_output\AegisPlanner-Setup-2.11.10.exe -Algorithm SHA256`
3. در GitHub: **Releases ← Draft a new release** ← در Choose a tag بنویس `v2.11.10` و Create new tag ← عنوان بنویس ← فایل exe را به کادر «Attach binaries» **بکش و رها کن** ← هش را در توضیحات بگذار ← **Publish release**.

## ۷. انتشار نسخهٔ بعدی (هر بار)

۱. نسخه را در همهٔ جاها عوض کن (فهرست در `docs/BUILD.md` بخش «Releasing a new version»)، تست‌ها را بگیر.
۲. `CHANGELOG.md` را به‌روز کن.
۳. دستورها:

```bash
git add .
git commit -m "Release 2.11.11"
git push
git tag v2.11.11
git push origin v2.11.11
```

۴. صبر کن تا workflow تمام شود؛ Release تازه خودکار ساخته می‌شود. اگر بررسی به‌روزرسانی را در برنامه روشن کرده باشند، خبر نسخهٔ جدید را می‌گیرند.

## ۸. نکته‌های مهم

- **هرگز** فایل ولت، پشتیبان، رمز، کلید بازیابی یا گواهی امضا (`.pfx`) را commit نکن. اگر اشتباه رفت، فقط حذف فایل کافی نیست (در تاریخچه می‌ماند)؛ رمز را عوض کن و از من بپرس چطور تاریخچه پاک شود.
- فایل exe را داخل خود مخزن commit نکن؛ جایش **Releases** است (حجم مخزن بالا نمی‌رود).
- هشدار SmartScreen برای فایل بدون امضا طبیعی است و در README توضیح داده شده است.
- لایسنس GPL‑3.0 یعنی هر کسی می‌تواند کد را استفاده، تغییر و منتشر کند، به شرط اینکه نسخهٔ تغییریافته را هم با GPL و همراه سورس منتشر کند.

</div>
