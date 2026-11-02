# Media Enhancer

[English](#english) | [فارسی](#فارسی)

---

## English

Media Enhancer makes photos and videos look better with AI. You give it a picture or a clip and it
upscales it (2x or 4x), cleans up noise and blur, can fix faces, and for videos it can double the
frame rate so motion looks smoother.

It comes in two parts that share the same accounts and coins:

- **A website** (Django). People sign up, upload a file, and the server's GPU does the work.
- **A Windows app**. People log in with the same account and the file is processed on their own
  NVIDIA graphics card. Nothing gets uploaded, so it's faster for them and cheaper (by default the
  app costs half of the website price).

The interface is in English and Persian, English by default. There's a language button on the site
and in the app.

### What it can do

- Upscale images and videos 2x or 4x (Real-ESRGAN)
- Two modes: **fast** (light model, good for most videos) and **high quality** (slower, more detail)
- Restore faces in blurry or old photos (GFPGAN v1.4)
- Smooth motion: create in-between frames, e.g. 30 → 60 FPS (RIFE 4.26)
- Keep the audio of videos, with correct colours
- Reduce video noise and the frame-to-frame "flicker" that per-frame AI tends to cause
- Before/after comparison slider
- Coins: sign-up bonus, referral links, price per job, refunds when a job fails or is cancelled
- Admin panel for users, coins, prices, limits, jobs and the desktop app

### How it works

```
             ┌──────────── website (Django) ────────────┐
 browser ──► │ accounts · uploads · wallet · admin      │ ──► SQLite database
             │ /api/app/  (login, charge, refund)       │        ▲
             └──────────────────────────────────────────┘        │
                     ▲                                            │
                     │ same accounts and coins                    │
 Windows app ────────┘                                            │
   └─ runs mecore on the user's own GPU                           │
                                                                  │
 worker (manage.py run_worker) ── runs mecore on the server GPU ──┘
```

- **`mecore/`** is the AI engine. The website's worker and the Windows app both use it, so a fix
  there fixes both. It doesn't depend on Django.
- **The worker** takes queued website jobs one by one. If it isn't running, jobs just wait.
- **The Windows app** never sends files to the server. It only asks the server to log in, to charge
  coins before a job starts, and to refund them if the job fails or is cancelled.
- Uploaded files and results on the website live in `storage/`, which isn't public. Every download
  goes through a view that checks the file belongs to whoever is asking.

A video is processed like this: ffmpeg decodes the frames → light temporal denoise → the AI model
upscales each frame (in tiles, so it fits in GPU memory) → faces are restored if asked → RIFE adds
in-between frames if asked → temporal smoothing → ffmpeg encodes H.264 (NVENC when available) and
copies the audio.

#### About GPU errors

Some GPUs, especially overclocked or very hot ones, now and then compute garbage in half precision.
In a video that shows up as black dots or striped blocks. Every tile is checked after it's computed
(scaled back down, it has to match its input) and redone in full precision if it doesn't. The log
says how many tiles were repaired. If that number is high, run the GPU at stock clocks, or set
`AI_PRECISION=fp32` (slower, but no half precision at all).

### Requirements

- Windows (Linux works for the website), Python 3.10+
- An NVIDIA GPU with a recent driver. I use an RTX 3070 Laptop with 8 GB. It runs on CPU too, but
  very slowly.
- ffmpeg and ffprobe on the PATH

### Setting up the website

```bash
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
copy .env.example .env
```

Open `.env`, set at least `SECRET_KEY` and the `ADMIN_*` lines, then:

```bash
python manage.py migrate
python manage.py compile_translations
python manage.py collectstatic --noinput
python manage.py download_models
python manage.py ensure_admin
```

`download_models` fetches about 650 MB of models the first time. `ensure_admin` creates the admin
account from `.env`; run it again whenever you want to change the admin password. After that you
can delete the password from `.env`.

### Running the website

Two processes, two terminals (or just double-click `start.bat`):

```bash
waitress-serve --listen=127.0.0.1:8000 --threads=8 config.wsgi:application
```

```bash
python manage.py run_worker
```

- Site: http://127.0.0.1:8000
- Admin panel: http://127.0.0.1:8000/manage/

The Windows app only needs the first one (the website), the worker is for website jobs.

### The Windows app

Run it from source:

```bash
python -m desktop.main
```

Or build the installer: one self-extracting `.exe` (about 2 GB) with Python, the AI libraries, the
models and ffmpeg inside, so users don't need to install anything else:

```bash
pyinstaller desktop\MediaEnhancer.spec --noconfirm
powershell -ExecutionPolicy Bypass -File tools\build_installer.ps1
```

The result is `dist\MediaEnhancer-1.0.0-Windows.exe`. It asks where to extract, then you run
`MediaEnhancer.exe`. On the first start it offers to create a desktop shortcut.

The server address is under "Advanced settings" on the login screen (default
`http://127.0.0.1:8000`). Once the website is online, users put its address there. The login is
remembered (encrypted with Windows' own per-user encryption), so they don't have to log in every time.

Keep in mind that the app runs on the user's computer, so it can't be made tamper-proof. The server
decides the price and charges before the job starts, but someone determined could modify the app.

### Admin panel

Most things live in **Site settings**:

- every price (images and videos, fast/high, 4x, faces, smooth motion)
- sign-up and referral bonuses
- limits: file size, video length, output resolution, jobs per user, how long files are kept
- video noise reduction (off / light / medium / strong)
- the desktop app: allow it, its price as a percentage of the website price (0 = free) and the
  download link shown on the website
- an announcement banner, closing registration, pausing new jobs

Coins can be changed for one user (on their page), for selected users, or for everyone at once. Every
change goes into a ledger that can't be edited. Website jobs, app jobs and app logins are all listed,
and an app login can be revoked by deleting it.

### Pricing

- Images: a base price for the mode, plus extra for 4x and for face restoration.
- Videos: the same, but per started 10 seconds.
- Desktop app: the website price × the app percentage, rounded up.
- Coins are taken when a job starts and returned automatically if it fails or is cancelled.

### Why does a short video take so long?

Every frame is an image that goes through the AI. A 13-second clip at 60 FPS is 803 images. In high
quality at 4K, each one takes a few seconds on a laptop GPU, plus faces and the extra frames for
smooth motion. Rough times on my RTX 3070 Laptop:

| Job | Time |
| --- | --- |
| Photo, 4x, high quality | a few seconds |
| 12.7 s video, 480×834 → 2x, high quality, 60 FPS | ~3 min |
| 13.4 s video, 720p 60 FPS → 4K, fast | ~6 min |
| same, fast + faces + smooth motion | ~25 min |
| same, high quality | ~1.5 hours |
| same, high quality + faces + smooth motion | ~2 hours |

The fast mode is several times quicker and usually fine for video. Other programs using the same GPU
(games, animated wallpapers like Wallpaper Engine) slow it down a lot.

### Settings in `.env`

| Setting | What it does |
| --- | --- |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | usual Django settings |
| `SECURE_COOKIES` | set to `True` once the site runs on HTTPS |
| `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | used by `ensure_admin` |
| `AI_DEVICE` | `cuda` or `cpu` |
| `AI_TILE_SIZE` | lower it if you run out of GPU memory |
| `AI_PRECISION` | `auto` (recommended) or `fp32` |
| `VIDEO_ENCODER` | `auto`, `nvenc` or `libx264` |
| `FFMPEG_BIN`, `FFPROBE_BIN` | if ffmpeg isn't on the PATH |

### Security

- Uploads are checked by actually decoding them, not by their extension.
- Users can only see and download their own files.
- CSRF protection, Django's password hashing and validators, login throttling, a limit on sign-ups
  per IP, a strict Content-Security-Policy.
- Coin changes are atomic and logged; a balance can't go negative.
- Desktop-app tokens are random, stored only as a hash on the server, and expire after 90 days of
  not being used.

To put it on the internet: `DEBUG=False`, a real `SECRET_KEY`, proper `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS`, HTTPS, and `SECURE_COOKIES=True`.

### Project layout

```
config/       Django settings and URLs
accounts/     users, coin ledger, sign-up / login / wallet pages
enhancer/     website jobs, site settings, pages, admin, worker.py
appapi/       JSON API for the Windows app
mecore/       the AI engine (no Django): models, GPU-error guard, image/video pipeline
desktop/      the Windows app (PySide6) and its PyInstaller spec
tools/        i18n_sync.py (translation file), build_installer.ps1
templates/, static/, locale/fa/   website pages, styles, Persian translation
```

### Translations

Texts are written in English in the code and translated in `locale/fa/LC_MESSAGES/django.po`. After
changing texts, run `python tools/i18n_sync.py --write`, fill in the new Persian lines and run
`python manage.py compile_translations`. GNU gettext isn't needed. The Windows app keeps its texts in
`desktop/i18n.py`.

### Tests

```bash
python manage.py test
```

### Credits

The real work is done by these projects:

- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)
- [GFPGAN](https://github.com/TencentARC/GFPGAN) and [facexlib](https://github.com/xinntao/facexlib)
- [RIFE](https://github.com/hzwer/Practical-RIFE), through [ccvfi](https://github.com/EutropicAI/ccvfi)
- [spandrel](https://github.com/chaiNNer-org/spandrel) for loading the models
- [FFmpeg](https://ffmpeg.org/) for video, [PySide6](https://doc.qt.io/qtforpython-6/) for the app

Check their licenses before using the models commercially. The installer bundles an ffmpeg build,
which comes with its own (GPL) license.

---

## فارسی

بهساز رسانه کیفیت عکس و ویدیو رو با هوش مصنوعی بالا می‌بره. یک عکس یا ویدیو بهش می‌دی و وضوحش رو
۲ یا ۴ برابر می‌کنه، نویز و تاری رو کم می‌کنه، می‌تونه چهره‌ها رو بازسازی کنه و برای ویدیو می‌تونه
فریم‌ریت رو دو برابر کنه تا حرکت روان‌تر دیده بشه.

دو بخش داره که حساب‌ها و سکه‌هاشون مشترکه:

- **سایت** (جنگو): کاربر ثبت‌نام می‌کنه، فایل رو آپلود می‌کنه و کارت گرافیک سرور پردازش رو انجام می‌ده.
- **برنامه ویندوز**: کاربر با همون حساب وارد می‌شه و فایل روی کارت گرافیک NVIDIA خودش پردازش می‌شه.
  چیزی آپلود نمی‌شه، پس براش سریع‌تر و ارزون‌تره (به طور پیش‌فرض نصف قیمت سایت).

رابط کاربری به انگلیسی و فارسیه و پیش‌فرض انگلیسیه. هم در سایت و هم در برنامه دکمه تغییر زبان هست.

### امکانات

- بزرگ‌نمایی ۲ یا ۴ برابر عکس و ویدیو (Real-ESRGAN)
- دو حالت: **سریع** (مدل سبک، برای بیشتر ویدیوها کافیه) و **کیفیت بالا** (کندتر، با جزئیات بیشتر)
- بازسازی چهره در عکس‌های تار یا قدیمی (GFPGAN نسخه 1.4)
- حرکت روان: ساختن فریم‌های میانی، مثلاً از ۳۰ به ۶۰ فریم (RIFE 4.26)
- حفظ صدای ویدیو با رنگ‌های درست
- کاهش نویز ویدیو و لرزشی که پردازش جداگانه هر فریم معمولاً ایجاد می‌کنه
- اسلایدر مقایسه قبل و بعد
- سکه: هدیه ثبت‌نام، لینک دعوت، قیمت برای هر پردازش، برگشت سکه وقتی پردازش خطا بده یا لغو بشه
- پنل مدیریت برای کاربرها، سکه‌ها، قیمت‌ها، محدودیت‌ها، پردازش‌ها و برنامه ویندوز

### چطور کار می‌کنه

- **`mecore/`** موتور هوش مصنوعیه. ورکر سایت و برنامه ویندوز هر دو از همین استفاده می‌کنن، پس هر
  اصلاحی اینجا هر دو رو درست می‌کنه. به جنگو وابسته نیست.
- **ورکر** (`manage.py run_worker`) پردازش‌های سایت رو یکی‌یکی از صف برمی‌داره. اگه خاموش باشه، پردازش‌ها
  توی صف منتظر می‌مونن.
- **برنامه ویندوز** هیچ فایلی به سرور نمی‌فرسته. فقط برای ورود، کم کردن سکه قبل از شروع و برگردوندن سکه
  در صورت خطا یا لغو به سرور وصل می‌شه (از طریق `/api/app/`).
- فایل‌های آپلودی و نتیجه‌ها در سایت توی پوشه `storage/` هستن که عمومی نیست؛ هر دانلود از یک view رد
  می‌شه که چک می‌کنه فایل مال همون کاربر باشه.

مراحل پردازش ویدیو: ffmpeg فریم‌ها رو باز می‌کنه ← کاهش نویز ملایم ← مدل هوش مصنوعی هر فریم رو تکه‌تکه
بزرگ‌نمایی می‌کنه (تا در حافظه کارت گرافیک جا بشه) ← در صورت انتخاب، بازسازی چهره ← در صورت انتخاب،
ساخت فریم‌های میانی با RIFE ← صاف کردن لرزش بین فریم‌ها ← ffmpeg ویدیو رو با H.264 ذخیره می‌کنه
(با NVENC اگه در دسترس باشه) و صدا رو هم کپی می‌کنه.

#### درباره خطاهای کارت گرافیک

بعضی کارت‌ها، مخصوصاً اگه اورکلاک شده یا خیلی داغ باشن، گاهی در حالت نیم‌دقت محاسبه رو اشتباه انجام
می‌دن. نتیجه‌اش در ویدیو نقطه‌های سیاه یا بلوک‌های خط‌خطیه. هر تکه بعد از پردازش چک می‌شه (وقتی دوباره
کوچیک بشه باید شبیه ورودی باشه) و اگه نباشه با دقت کامل دوباره ساخته می‌شه. تعداد تکه‌های درست‌شده در
لاگ نوشته می‌شه. اگه زیاد بود، کارت گرافیک رو روی تنظیمات کارخانه برگردون یا `AI_PRECISION=fp32` بذار
(کندتره ولی کلاً از نیم‌دقت استفاده نمی‌کنه).

### پیش‌نیازها

- ویندوز (سایت روی لینوکس هم اجرا می‌شه)، پایتون 3.10 یا بالاتر
- کارت گرافیک NVIDIA با درایور جدید. خودم با RTX 3070 لپ‌تاپی ۸ گیگ کار می‌کنم. روی CPU هم اجرا
  می‌شه ولی خیلی کنده.
- ffmpeg و ffprobe که توی PATH باشن

### نصب سایت

```bash
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
copy .env.example .env
```

فایل `.env` رو باز کن و حداقل `SECRET_KEY` و خط‌های `ADMIN_*` رو پر کن. بعد:

```bash
python manage.py migrate
python manage.py compile_translations
python manage.py collectstatic --noinput
python manage.py download_models
python manage.py ensure_admin
```

`download_models` بار اول حدود ۶۵۰ مگ مدل دانلود می‌کنه. `ensure_admin` حساب ادمین رو از روی `.env`
می‌سازه و هر وقت خواستی رمز ادمین رو عوض کنی دوباره اجراش کن. بعدش می‌تونی رمز رو از `.env` پاک کنی.

### اجرای سایت

دو برنامه در دو ترمینال (یا فقط `start.bat` رو اجرا کن):

```bash
waitress-serve --listen=127.0.0.1:8000 --threads=8 config.wsgi:application
```

```bash
python manage.py run_worker
```

- سایت: http://127.0.0.1:8000
- پنل مدیریت: http://127.0.0.1:8000/manage/

برنامه ویندوز فقط به اولی (خود سایت) نیاز داره؛ ورکر برای پردازش‌های سایته.

### برنامه ویندوز

اجرا از روی سورس:

```bash
python -m desktop.main
```

یا ساخت فایل نصب: یک فایل exe حدود ۲ گیگابایتی که پایتون، کتابخونه‌های هوش مصنوعی، مدل‌ها و ffmpeg
داخلشه و کاربر لازم نیست چیز دیگه‌ای نصب کنه:

```bash
pyinstaller desktop\MediaEnhancer.spec --noconfirm
powershell -ExecutionPolicy Bypass -File tools\build_installer.ps1
```

خروجی `dist\MediaEnhancer-1.0.0-Windows.exe` هست. موقع اجرا می‌پرسه کجا باز بشه، بعد `MediaEnhancer.exe`
رو اجرا کن. بار اول پیشنهاد ساخت میان‌بر روی دسکتاپ رو می‌ده.

آدرس سرور در صفحه ورود، زیر «تنظیمات پیشرفته» هست (پیش‌فرض `http://127.0.0.1:8000`). وقتی سایت آنلاین
شد، کاربرها آدرسش رو اونجا می‌ذارن. ورود ذخیره می‌شه (با رمزنگاری خود ویندوز برای هر کاربر)، پس لازم نیست
هر بار وارد بشن.

یادت باشه برنامه روی کامپیوتر خود کاربر اجرا می‌شه، پس نمی‌شه جلوی دستکاری‌اش رو صددرصد گرفت. قیمت رو
سرور تعیین می‌کنه و قبل از شروع کم می‌کنه، ولی کسی که بخواد می‌تونه برنامه رو تغییر بده.

### پنل مدیریت

بیشتر تنظیمات در **تنظیمات سایت** هست:

- همه قیمت‌ها (عکس و ویدیو، سریع/کیفیت بالا، ۴ برابر، چهره، حرکت روان)
- هدیه ثبت‌نام و دعوت
- محدودیت‌ها: حجم فایل، طول ویدیو، وضوح خروجی، تعداد پردازش هر کاربر، مدت نگهداری فایل‌ها
- کاهش نویز ویدیو (خاموش / ملایم / متوسط / قوی)
- برنامه ویندوز: مجاز بودن، قیمتش به درصد از قیمت سایت (۰ یعنی رایگان) و لینک دانلود در سایت
- اطلاعیه بالای سایت، بستن ثبت‌نام، توقف پردازش‌های جدید

سکه رو می‌شه برای یک کاربر (از صفحه خودش)، برای چند کاربر انتخاب‌شده یا برای همه با هم تغییر داد. هر
تغییر در دفتری ثبت می‌شه که قابل ویرایش نیست. پردازش‌های سایت، پردازش‌های برنامه و ورودهای برنامه همه
دیده می‌شن و هر ورود برنامه رو می‌شه با پاک کردنش باطل کرد.

### قیمت‌گذاری

- عکس: قیمت پایه هر حالت، به اضافه هزینه ۴ برابر و بازسازی چهره.
- ویدیو: همین، ولی برای هر ۱۰ ثانیه (یا کمتر).
- برنامه ویندوز: قیمت سایت × درصد برنامه، رو به بالا گرد می‌شه.
- سکه موقع شروع کم می‌شه و اگه پردازش خطا بده یا لغو بشه خودکار برمی‌گرده.

### چرا یک ویدیوی کوتاه این‌قدر طول می‌کشه؟

هر فریم یک عکسه که باید از هوش مصنوعی رد بشه. یک ویدیوی ۱۳ ثانیه‌ای با ۶۰ فریم در ثانیه یعنی ۸۰۳ عکس.
در حالت کیفیت بالا و خروجی 4K هر کدوم روی کارت گرافیک لپ‌تاپ چند ثانیه طول می‌کشه، به اضافه چهره‌ها و
فریم‌های اضافه برای حرکت روان. زمان‌های تقریبی روی RTX 3070 لپ‌تاپی خودم:

| کار | زمان |
| --- | --- |
| عکس، ۴ برابر، کیفیت بالا | چند ثانیه |
| ویدیوی ۱۲.۷ ثانیه‌ای، 480×834 به ۲ برابر، کیفیت بالا، ۶۰ فریم | حدود ۳ دقیقه |
| ویدیوی ۱۳.۴ ثانیه‌ای 720p با ۶۰ فریم به 4K، سریع | حدود ۶ دقیقه |
| همون، سریع + چهره + حرکت روان | حدود ۲۵ دقیقه |
| همون، کیفیت بالا | حدود ۱.۵ ساعت |
| همون، کیفیت بالا + چهره + حرکت روان | حدود ۲ ساعت |

حالت سریع چند برابر سریع‌تره و برای ویدیو معمولاً کافیه. برنامه‌های دیگه‌ای که از همون کارت گرافیک
استفاده می‌کنن (بازی‌ها، والپیپرهای متحرک مثل Wallpaper Engine) سرعت رو خیلی پایین میارن.

### تنظیمات فایل `.env`

| تنظیم | کارش |
| --- | --- |
| `SECRET_KEY`، `DEBUG`، `ALLOWED_HOSTS`، `CSRF_TRUSTED_ORIGINS` | تنظیمات معمول جنگو |
| `SECURE_COOKIES` | وقتی سایت روی HTTPS رفت، `True` بذار |
| `ADMIN_USERNAME`، `ADMIN_EMAIL`، `ADMIN_PASSWORD` | برای دستور `ensure_admin` |
| `AI_DEVICE` | `cuda` یا `cpu` |
| `AI_TILE_SIZE` | اگه حافظه کارت گرافیک کم آورد، کمترش کن |
| `AI_PRECISION` | `auto` (پیشنهادی) یا `fp32` |
| `VIDEO_ENCODER` | `auto`، `nvenc` یا `libx264` |
| `FFMPEG_BIN`، `FFPROBE_BIN` | اگه ffmpeg توی PATH نیست |

### امنیت

- فایل‌های آپلودی با باز کردن واقعی‌شون چک می‌شن، نه از روی پسوند.
- هر کاربر فقط فایل‌های خودش رو می‌بینه و دانلود می‌کنه.
- محافظت CSRF، هش و اعتبارسنجی رمز جنگو، محدودیت تلاش ورود، محدودیت ساخت حساب از یک IP و
  Content-Security-Policy سخت‌گیرانه.
- تغییر سکه اتمیک انجام و ثبت می‌شه و موجودی منفی نمی‌شه.
- توکن‌های برنامه ویندوز تصادفی هستن، روی سرور فقط هش‌شون نگه داشته می‌شه و بعد از ۹۰ روز استفاده
  نشدن باطل می‌شن.

برای گذاشتن روی اینترنت: `DEBUG=False`، یک `SECRET_KEY` واقعی، `ALLOWED_HOSTS` و `CSRF_TRUSTED_ORIGINS`
درست، HTTPS و `SECURE_COOKIES=True`.

### ساختار پروژه

```
config/       تنظیمات و آدرس‌های جنگو
accounts/     کاربرها، دفتر سکه، صفحه‌های ثبت‌نام / ورود / کیف سکه
enhancer/     پردازش‌های سایت، تنظیمات سایت، صفحه‌ها، پنل مدیریت، worker.py
appapi/       API برنامه ویندوز
mecore/       موتور هوش مصنوعی (بدون جنگو): مدل‌ها، محافظ خطای کارت گرافیک، پردازش عکس و ویدیو
desktop/      برنامه ویندوز (PySide6) و فایل ساخت PyInstaller
tools/        i18n_sync.py (فایل ترجمه)، build_installer.ps1
templates/, static/, locale/fa/   صفحه‌ها، استایل‌ها و ترجمه فارسی سایت
```

### ترجمه‌ها

متن‌ها در کد انگلیسی نوشته شدن و ترجمه فارسی در `locale/fa/LC_MESSAGES/django.po` هست. بعد از تغییر
متن‌ها `python tools/i18n_sync.py --write` رو اجرا کن، خط‌های جدید فارسی رو پر کن و
`python manage.py compile_translations` رو بزن. به GNU gettext نیازی نیست. متن‌های برنامه ویندوز در
`desktop/i18n.py` هستن.

### تست‌ها

```bash
python manage.py test
```

### منابع

کار اصلی رو این پروژه‌ها انجام می‌دن:

- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)
- [GFPGAN](https://github.com/TencentARC/GFPGAN) و [facexlib](https://github.com/xinntao/facexlib)
- [RIFE](https://github.com/hzwer/Practical-RIFE) از طریق [ccvfi](https://github.com/EutropicAI/ccvfi)
- [spandrel](https://github.com/chaiNNer-org/spandrel) برای لود مدل‌ها
- [FFmpeg](https://ffmpeg.org/) برای ویدیو و [PySide6](https://doc.qt.io/qtforpython-6/) برای برنامه

قبل از استفاده تجاری از مدل‌ها، لایسنس‌شون رو چک کن. فایل نصب یک نسخه ffmpeg داخلش داره که لایسنس
خودش (GPL) رو داره.
