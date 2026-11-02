"""Persian / English text for the desktop app."""

_language = "en"

TEXT = {
    "app_title": ("بهساز رسانه", "Media Enhancer"),
    "tagline": ("افزایش کیفیت عکس و ویدیو با هوش مصنوعی، روی کارت گرافیک خودتان",
                "AI photo & video enhancement on your own graphics card"),
    # login
    "login_title": ("ورود به حساب", "Log in"),
    "username": ("نام کاربری یا ایمیل", "Username or email"),
    "password": ("رمز عبور", "Password"),
    "login": ("ورود", "Log in"),
    "logging_in": ("در حال ورود...", "Logging in..."),
    "server": ("آدرس سرور", "Server address"),
    "advanced": ("تنظیمات پیشرفته", "Advanced settings"),
    "no_account": ("حساب ندارید؟ در سایت ثبت‌نام کنید", "No account? Sign up on the website"),
    "fill_login": ("نام کاربری و رمز عبور را وارد کنید.", "Enter your username and password."),
    # main window
    "coins": ("سکه", "coins"),
    "balance": ("موجودی: {n} سکه", "Balance: {n} coins"),
    "logout": ("خروج", "Log out"),
    "refresh": ("به‌روزرسانی موجودی", "Refresh balance"),
    "drop_here": ("فایل را اینجا رها کنید یا کلیک کنید", "Drop a file here or click to choose"),
    "drop_hint": ("عکس: JPG، PNG، WEBP — ویدیو: MP4، MOV، MKV، WEBM", "Images: JPG, PNG, WEBP — Videos: MP4, MOV, MKV, WEBM"),
    "choose_file": ("انتخاب فایل", "Choose a file"),
    "file_filter": ("عکس و ویدیو", "Images and videos"),
    "unsupported": ("این نوع فایل پشتیبانی نمی‌شود.", "This file type is not supported."),
    "unreadable": ("فایل قابل خواندن نیست. ممکن است خراب باشد.", "The file could not be read. It may be damaged."),
    "image": ("عکس", "Image"),
    "video": ("ویدیو", "Video"),
    "seconds": ("ثانیه", "s"),
    "mode": ("حالت", "Mode"),
    "fast": ("سریع", "Fast"),
    "fast_hint": ("نتیجه سریع، مناسب بیشتر ویدیوها", "Quick result, good for most videos"),
    "high": ("کیفیت بالا", "High quality"),
    "high_hint": ("کندتر، با بیشترین جزئیات", "Slower, the best detail"),
    "upscale": ("بزرگ‌نمایی", "Upscale"),
    "x2": ("۲ برابر", "2x"),
    "x4": ("۴ برابر", "4x"),
    "fps_value": ("{n} فریم در ثانیه", "{n} FPS"),
    "seconds_value": ("{n} ثانیه", "{n} s"),
    "mb_value": ("{n} مگابایت", "{n} MB"),
    "x2_hint": ("دو برابر شدن وضوح", "Double the resolution"),
    "x4_hint": ("بیشترین وضوح", "Maximum resolution"),
    "extras": ("امکانات بیشتر", "Extras"),
    "faces": ("بازسازی چهره", "Restore faces"),
    "smooth": ("حرکت روان (دو برابر فریم، فقط ویدیو)", "Smooth motion (double FPS, video only)"),
    "output_folder": ("پوشه خروجی", "Output folder"),
    "same_folder": ("کنار فایل اصلی", "Next to the original file"),
    "change": ("تغییر", "Change"),
    "cost": ("هزینه: {n} سکه", "Cost: {n} coins"),
    "cost_note": ("({p}٪ قیمت سایت)", "({p}% of the website price)"),
    "percent": ("{n}٪", "{n}%"),
    "free": ("رایگان", "Free"),
    "not_enough": ("سکه کافی ندارید.", "You do not have enough coins."),
    "start": ("شروع افزایش کیفیت", "Enhance now"),
    "cancel": ("لغو", "Cancel"),
    "cancel_confirm": ("پردازش لغو شود؟ سکه‌ها برگردانده می‌شوند.", "Cancel the job? Your coins will be returned."),
    "choose_first": ("ابتدا یک فایل انتخاب کنید.", "Choose a file first."),
    # engine / gpu
    "engine_loading": ("در حال آماده‌سازی موتور هوش مصنوعی...", "Preparing the AI engine..."),
    "gpu_ok": ("کارت گرافیک: {name}", "Graphics card: {name}"),
    "gpu_missing": ("کارت گرافیک NVIDIA پیدا نشد. پردازش روی CPU بسیار کند خواهد بود.",
                    "No NVIDIA graphics card found. Processing on the CPU will be very slow."),
    "engine_error": ("موتور هوش مصنوعی اجرا نشد: {err}", "The AI engine could not start: {err}"),
    # progress stages
    "stage_charging": ("در حال ثبت پردازش...", "Registering the job..."),
    "stage_loading": ("در حال آماده‌سازی مدل‌ها", "Loading AI models"),
    "stage_upscaling": ("در حال بهبود جزئیات", "Enhancing details"),
    "stage_faces": ("در حال بازسازی چهره‌ها", "Restoring faces"),
    "stage_encoding": ("در حال ذخیره نتیجه", "Saving the result"),
    "time_left": ("زمان باقی‌مانده: {t}", "Time left: {t}"),
    # results
    "done": ("انجام شد! فایل ذخیره شد.", "Done! The file was saved."),
    "done_time": ("زمان پردازش: {t}", "Processing time: {t}"),
    "open_file": ("باز کردن فایل", "Open file"),
    "open_folder": ("نمایش در پوشه", "Show in folder"),
    "before": ("قبل", "Before"),
    "after": ("بعد", "After"),
    "failed": ("پردازش ناموفق بود و سکه‌ها برگردانده شد.\n{err}", "Processing failed and your coins were returned.\n{err}"),
    "cancelled": ("پردازش لغو شد و سکه‌ها برگردانده شد.", "The job was cancelled and your coins were returned."),
    "busy_close": ("یک پردازش در جریان است. اگر برنامه را ببندید لغو می‌شود. ادامه می‌دهید؟",
                   "A job is running. Closing the app will cancel it. Continue?"),
    # errors
    "network_error": ("اتصال به سرور برقرار نشد. اینترنت یا آدرس سرور را بررسی کنید.",
                      "Could not reach the server. Check your connection or the server address."),
    "server_error": ("خطای سرور ({status}). کمی بعد دوباره تلاش کنید.", "Server error ({status}). Please try again later."),
    "session_expired": ("نشست شما منقضی شده. دوباره وارد شوید.", "Your session has expired. Please log in again."),
    "language": ("English", "فارسی"),
    "settings": ("تنظیمات", "Settings"),
    "save": ("ذخیره", "Save"),
    "yes": ("بله", "Yes"),
    "no": ("خیر", "No"),
    "shortcut_q": ("میان‌بر برنامه روی دسکتاپ ساخته شود؟", "Create a desktop shortcut for the app?"),
}


def set_language(lang: str):
    global _language
    _language = "fa" if lang == "fa" else "en"


def language() -> str:
    return _language


def is_rtl() -> bool:
    return _language == "fa"


_FA_DIGITS = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")


def num(value, fmt="{}") -> str:
    """A number for display: Persian digits in Persian mode."""
    text = fmt.format(value)
    return text.translate(_FA_DIGITS) if _language == "fa" else text


def ltr(text: str) -> str:
    """Keep a left-to-right fragment (sizes, file names, GPU names) in order inside Persian text."""
    return f"⁦{text}⁩"


def tr(key: str, **kwargs) -> str:
    """Translated text. int/float arguments are shown with the right digits for the language."""
    fa, en = TEXT.get(key, (key, key))
    text = en if _language == "en" else fa
    if not kwargs:
        return text
    values = {k: num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v for k, v in kwargs.items()}
    return text.format(**values)


def format_duration(seconds) -> str:
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return ltr(num(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"))
