"""کمکی‌های نمایش فارسی: رقم‌های فارسی، قالب‌بندی زمان و تاریخ."""

from __future__ import annotations

from datetime import date, datetime

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(value: object) -> str:
    """عدد یا متن را با رقم‌های فارسی برمی‌گرداند."""
    return str(value).translate(FA_DIGITS)


def duration(seconds: float | int | None) -> str:
    """ثانیه را به «د:ثث» فارسی تبدیل می‌کند."""
    if seconds is None:
        return "—"
    total = max(0, int(round(float(seconds))))
    minutes, secs = divmod(total, 60)
    return fa(f"{minutes}:{secs:02d}")


def clock_time(timestamp: float) -> str:
    """ساعت محلی از یک timestamp."""
    return fa(datetime.fromtimestamp(timestamp).strftime("%H:%M"))


def when(timestamp: float) -> str:
    """«امروز ۱۱:۲۰» / «دیروز ۲۱:۰۵» / «۲۰۲۶-۱۱-۱۸ ۲۱:۰۵»."""
    moment = datetime.fromtimestamp(timestamp)
    today = date.today()
    delta = (today - moment.date()).days
    if delta == 0:
        prefix = "امروز"
    elif delta == 1:
        prefix = "دیروز"
    else:
        prefix = fa(moment.strftime("%Y-%m-%d"))
    return f"{prefix} {clock_time(timestamp)}"
