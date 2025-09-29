import os
from datetime import datetime, timedelta
from dateutil import parser as dateparser
from typing import List, Dict
from .google_clients import calendar as calendar_client

DEFAULT_CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")

def fetch_attendees_for_date(date_str: str, meeting_key: str, calendar_id: str = None) -> List[str]:
    cal_id = calendar_id or DEFAULT_CALENDAR_ID
    svc = calendar_client().events()
    # Search a window around the date
    base = dateparser.isoparse(date_str).date()
    time_min = datetime.combine(base - timedelta(days=3), datetime.min.time()).isoformat() + "Z"
    time_max = datetime.combine(base + timedelta(days=4), datetime.max.time()).isoformat() + "Z"
    events_resp = svc.list(calendarId=cal_id, timeMin=time_min, timeMax=time_max, singleEvents=True, orderBy="startTime").execute()
    events = events_resp.get("items", [])
    # Filter by summary contains meeting_key (fallback: take first)
    filtered = [e for e in events if meeting_key in (e.get("summary") or "")]
    target = filtered[0] if filtered else (events[0] if events else None)
    emails: List[str] = []
    if target:
        attendees = target.get("attendees") or []
        for a in attendees:
            mail = a.get("email")
            if mail:
                emails.append(mail)
    return sorted(list({e.strip().lower() for e in emails if e}))

