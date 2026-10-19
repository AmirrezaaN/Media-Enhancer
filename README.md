# Media Enhancer

[English](#english) | [فارسی](#فارسی)

---

## English

A small web app for making photos and videos look better with AI. You upload a picture or a clip,
pick how much time you want to spend on it, and the server upscales it, cleans up noise and blur,
fixes faces and (for videos) can double the frame rate.

It's built with Django and runs the models on your own NVIDIA GPU. There's a user system with
coins, so each job costs a few coins, and an admin panel where you can hand out coins, change
prices and keep an eye on the queue. The UI is in Persian and English.

### What it can do

- Upscale images and videos 2x or 4x (Real-ESRGAN)
- Two modes: **fast** (a light model, fine for most videos) and **high quality** (slower, more detail)
- Restore faces in blurry or old photos (GFPGAN v1.4)
- Smooth motion: generate in-between frames, e.g. 30 → 60 FPS (RIFE 4.26)
- Keeps the audio track of videos
- Before / after slider on the result page
- Sign-up bonus and referral links (both amounts are set by the admin)
- Admin panel: users, coins, prices, limits, jobs, announcements

### How it works

There are two processes:

1. **The website** – accounts, uploads, wallet, job pages and the admin panel.
2. **The worker** (`manage.py run_worker`) – picks jobs from the queue and runs them on the GPU, one
   at a time. If it's not running, jobs just wait in the queue.

They share a SQLite database. Uploaded files and results go to `storage/`, which isn't public;
every download goes through a view that checks who owns the file.

### Requirements

- Python 3.10+
- An NVIDIA GPU with a recent driver (I use an RTX 3070 Laptop with 8 GB). It technically works on
  CPU but it's painfully slow.
- ffmpeg and ffprobe on your PATH

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # on Linux: source .venv/bin/activate

pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt

copy .env.example .env          # on Linux: cp .env.example .env
```

Open `.env` and at least set `SECRET_KEY` and the `ADMIN_*` values. Then:

```bash
python manage.py migrate
python manage.py compile_translations
python manage.py collectstatic --noinput
python manage.py download_models     # ~600 MB, only the first time
python manage.py ensure_admin
```

`ensure_admin` creates the admin account from `.env`. After that you can remove the password from
the file. Running it again later updates the password/email.

### Running

You need both processes running, so use two terminals:

```bash
waitress-serve --listen=127.0.0.1:8000 config.wsgi:application
```

```bash
python manage.py run_worker
```

On Windows you can just double-click `start.bat`.

- Site: http://127.0.0.1:8000
- Admin panel: http://127.0.0.1:8000/manage/

### Admin panel

Most of the settings live in **Site settings**: every price, sign-up and referral bonuses, max file
size / video length / resolution, how many jobs a user can queue, how long files are kept, an
announcement banner, and switches to close registration or pause new jobs.

For coins you can change one user from their page, select a few users and use the action, or use
the "Add / remove coins for all users" button. Every change is logged and the log can't be edited.

### Pricing

- Images: a base price for the mode, plus extra for 4x and for face restoration.
- Videos: the same idea, but charged per started 10 seconds.

Coins are taken when the job is submitted. If a job fails or gets cancelled, they're returned
automatically.

### Speed

Rough numbers from my laptop (RTX 3070 Laptop, 8 GB):

| Job | Time |
| --- | --- |
| Photo 480×300, 4x, high quality | ~3 s |
| 2 s video, 720p → 4K, fast | ~17 s |
| 2 s video, 720p → 4K, high quality + faces + 60 FPS | ~280 s |

High quality on video is slow, about 4 seconds per 720p frame, and that's just the model itself.
For videos the fast mode is usually the better deal. You can limit video length and set prices in
the admin panel to keep the queue under control.

### Security

- Uploads are checked by actually decoding them (Pillow / ffprobe), not by the file extension.
- Users can only see and download their own files.
- CSRF protection, Django's password hashing and validators, login throttling, a limit on sign-ups
  per IP, and a strict Content-Security-Policy.
- Coin balance changes are atomic, so a balance can't go negative.

If you put it on the internet: `DEBUG=False`, a real `SECRET_KEY`, proper `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS`, HTTPS, and `SECURE_COOKIES=True`.

### Tests

```bash
python manage.py test
```

### Project layout

```
config/       settings and urls
accounts/     users, coin ledger, sign-up / login / wallet
enhancer/     jobs, site settings, views, admin
  engine/     the AI part: models, image/video pipeline, model downloads
  worker.py   queue handling
templates/    html
static/       css, js
locale/fa/    Persian translation
```

### Credits

The heavy lifting is done by these projects:

- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)
- [GFPGAN](https://github.com/TencentARC/GFPGAN) and [facexlib](https://github.com/xinntao/facexlib)
- [RIFE](https://github.com/hzwer/Practical-RIFE), used through [ccvfi](https://github.com/EutropicAI/ccvfi)
- [spandrel](https://github.com/chaiNNer-org/spandrel) for loading the models

Check their licenses before using their weights commercially.

---

## فارسی

یک وب‌اپ کوچیک برای بالا بردن کیفیت عکس و ویدیو با هوش مصنوعی. عکس یا ویدیو رو آپلود می‌کنی،
انتخاب می‌کنی سریع باشه یا با کیفیت بیشتر، و سرور وضوحش رو بالا می‌بره، نویز و تاری رو کم می‌کنه،
چهره‌ها رو بازسازی می‌کنه و برای ویدیو می‌تونه فریم‌ریت رو دو برابر کنه.

با Django نوشته شده و مدل‌ها روی کارت گرافیک NVIDIA خود سیستم اجرا می‌شن. سیستم کاربری و سکه داره،
یعنی هر پردازش چند تا سکه خرج داره. یک پنل مدیریت هم هست که از اونجا می‌شه به کاربرها سکه داد،
قیمت‌ها رو عوض کرد و صف پردازش رو دید. سایت دو زبانه‌ست (فارسی و انگلیسی).

### امکانات

- بزرگ‌نمایی ۲ یا ۴ برابر عکس و ویدیو (Real-ESRGAN)
- دو حالت: **سریع** (مدل سبک، برای بیشتر ویدیوها کافیه) و **کیفیت بالا** (کندتر، با جزئیات بیشتر)
- بازسازی چهره در عکس‌های تار یا قدیمی (GFPGAN نسخه 1.4)
- روان کردن حرکت: ساختن فریم‌های میانی، مثلاً از ۳۰ به ۶۰ فریم (RIFE 4.26)
- صدای ویدیو حفظ می‌شه
- اسلایدر مقایسه قبل و بعد
- سکه هدیه ثبت‌نام و لینک دعوت (مقدارش رو ادمین تعیین می‌کنه)
- پنل مدیریت برای کاربرها، سکه‌ها، قیمت‌ها، محدودیت‌ها، پردازش‌ها و اطلاعیه

### چطور کار می‌کنه

دو تا برنامه کنار هم اجرا می‌شن:

1. **سایت**: حساب کاربری، آپلود، کیف سکه، صفحه پردازش‌ها و پنل مدیریت.
2. **ورکر** (`manage.py run_worker`): پردازش‌ها رو از صف برمی‌داره و یکی‌یکی روی GPU اجرا می‌کنه.
   اگه خاموش باشه، پردازش‌ها توی صف منتظر می‌مونن.

هر دو از یک دیتابیس SQLite استفاده می‌کنن. فایل‌ها توی پوشه `storage/` ذخیره می‌شن که عمومی نیست؛
هر دانلود از یک view رد می‌شه که چک می‌کنه فایل مال همون کاربر باشه.

### پیش‌نیازها

- پایتون 3.10 یا بالاتر
- کارت گرافیک NVIDIA با درایور جدید (خودم با RTX 3070 لپ‌تاپی ۸ گیگ تست کردم). روی CPU هم اجرا
  می‌شه ولی خیلی کنده.
- ffmpeg و ffprobe که توی PATH باشن

### نصب

```bash
python -m venv .venv
.venv\Scripts\activate

pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt

copy .env.example .env
```

فایل `.env` رو باز کن و حداقل `SECRET_KEY` و مقدارهای `ADMIN_*` رو پر کن. بعد:

```bash
python manage.py migrate
python manage.py compile_translations
python manage.py collectstatic --noinput
python manage.py download_models
python manage.py ensure_admin
```

دستور `download_models` حدود ۶۰۰ مگ مدل دانلود می‌کنه و فقط بار اول لازمه. `ensure_admin` اکانت
ادمین رو از روی `.env` می‌سازه. بعدش می‌تونی رمز رو از فایل پاک کنی؛ هر وقت هم دوباره اجراش کنی،
رمز و ایمیل ادمین به‌روز می‌شه.

### اجرا

باید هر دو برنامه روشن باشن، پس دو تا ترمینال باز کن:

```bash
waitress-serve --listen=127.0.0.1:8000 config.wsgi:application
```

```bash
python manage.py run_worker
```

روی ویندوز می‌تونی فقط `start.bat` رو اجرا کنی.

- سایت: http://127.0.0.1:8000
- پنل مدیریت: http://127.0.0.1:8000/manage/

### پنل مدیریت

بیشتر تنظیمات توی **تنظیمات سایت** هست: همه قیمت‌ها، سکه هدیه ثبت‌نام و دعوت، حداکثر حجم فایل و
طول ویدیو و وضوح، تعداد پردازش همزمان هر کاربر، مدت نگهداری فایل‌ها، اطلاعیه بالای سایت، و
گزینه‌هایی برای بستن ثبت‌نام یا متوقف کردن پردازش‌های جدید.

برای سکه می‌شه از صفحه هر کاربر موجودیش رو تغییر داد، چند کاربر رو انتخاب کرد و از اکشن استفاده
کرد، یا با دکمه «افزودن / کم کردن سکه برای همه کاربران» به همه سکه داد. همه تغییرها ثبت می‌شن و
قابل ویرایش نیستن.

### قیمت‌گذاری

- عکس: یک قیمت پایه برای هر حالت، به اضافه هزینه ۴ برابر و بازسازی چهره.
- ویدیو: همین منطق، ولی برای هر ۱۰ ثانیه (یا کمتر) حساب می‌شه.

سکه موقع ثبت پردازش کم می‌شه و اگه پردازش خطا بده یا لغو بشه، خودکار برمی‌گرده.

### سرعت

اعداد تقریبی روی لپ‌تاپ خودم (RTX 3070 لپ‌تاپی، ۸ گیگ):

| کار | زمان |
| --- | --- |
| عکس 480×300، ۴ برابر، کیفیت بالا | حدود ۳ ثانیه |
| ویدیوی ۲ ثانیه‌ای، 720p به 4K، سریع | حدود ۱۷ ثانیه |
| ویدیوی ۲ ثانیه‌ای، 720p به 4K، کیفیت بالا + چهره + ۶۰ فریم | حدود ۲۸۰ ثانیه |

حالت کیفیت بالا برای ویدیو کنده، حدود ۴ ثانیه برای هر فریم 720p، و این زمانِ خود مدله. برای ویدیو
معمولاً حالت سریع به‌صرفه‌تره. از پنل مدیریت می‌شه طول ویدیو رو محدود کرد و قیمت‌ها رو طوری گذاشت
که صف شلوغ نشه.

### امنیت

- فایل‌های آپلودی با باز کردن واقعی‌شون (Pillow و ffprobe) چک می‌شن، نه فقط از روی پسوند.
- هر کاربر فقط فایل‌های خودش رو می‌بینه و دانلود می‌کنه.
- محافظت CSRF، هش و اعتبارسنجی رمز جنگو، محدودیت تلاش ورود، محدودیت ساخت حساب از یک IP و
  Content-Security-Policy سخت‌گیرانه.
- تغییر موجودی سکه اتمیک انجام می‌شه و منفی نمی‌شه.

اگه روی اینترنت می‌ذاریش: `DEBUG=False`، یک `SECRET_KEY` واقعی، `ALLOWED_HOSTS` و
`CSRF_TRUSTED_ORIGINS` درست، HTTPS و `SECURE_COOKIES=True`.

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

قبل از استفاده تجاری از مدل‌ها، لایسنس‌شون رو چک کن.
