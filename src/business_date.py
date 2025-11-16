from datetime import date, timedelta


def business_days_before(target: date, days: int) -> date:
    """
    指定日の「営業日前」を返す（祝日は考慮せず、土日を除外）。
    例: 月曜の1営業日前は前週の金曜。
    - target: 基準となる日付（datetime.date）
    - days: さかのぼる営業日数（0ならtargetを返す）
    """
    if days <= 0:
        return target

    d = target
    remaining = days
    while remaining > 0:
        d = d - timedelta(days=1)
        # 月=0 ... 日=6。土日(5,6)はスキップ
        if d.weekday() < 5:
            remaining -= 1
    return d

import os
from datetime import datetime, timedelta, date
from functools import lru_cache
import pytz
from .google_clients import calendar as calendar_client

JST = pytz.timezone(os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo"))
HOLIDAY_CALENDAR_ID = os.getenv(
    "HOLIDAY_CALENDAR_ID",
    "ja.japanese#holiday@group.v.calendar.google.com"  # Japan public holidays
).strip()


def _jst_range_for_date(d: date) -> tuple[str, str]:
    start = JST.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def is_weekend(d: date) -> bool:
    # Monday=0 ... Sunday=6
    return d.weekday() >= 5


@lru_cache(maxsize=512)
def is_public_holiday(d: date) -> bool:
    """Check if given date is a public holiday via Google Calendar."""
    try:
        if not HOLIDAY_CALENDAR_ID:
            return False
        svc = calendar_client()
        time_min, time_max = _jst_range_for_date(d)
        items = svc.events().list(
            calendarId=HOLIDAY_CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=5,
        ).execute().get("items", [])
        return len(items) > 0
    except Exception:
        # Fail-open: if API fails, do not block by treating as business day
        return False


def is_business_day(d: date) -> bool:
    return (not is_weekend(d)) and (not is_public_holiday(d))


def previous_business_day(d: date) -> date:
    """Return the most recent business day strictly before d."""
    cur = d - timedelta(days=1)
    while not is_business_day(cur):
        cur -= timedelta(days=1)
    return cur


def business_days_before(d: date, n: int) -> date:
    """Return the date that is n business days before d."""
    if n <= 0:
        return d
    cur = d
    for _ in range(n):
        cur = previous_business_day(cur)
    return cur


