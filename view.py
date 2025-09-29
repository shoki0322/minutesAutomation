import os, sys, requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# .env 読み込み
load_dotenv(".env.local", override=True)
load_dotenv(".env", override=True)

def get(name, required=False, default=None):
    v = os.getenv(name, default)
    if required and not v:
        raise SystemExit(f"Missing env: {name}")
    return v

def get_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": get("GOOGLE_CLIENT_ID", True),
        "client_secret": get("GOOGLE_CLIENT_SECRET", True),
        "refresh_token": get("GOOGLE_REFRESH_TOKEN", True),
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def build_client(api, version, token):
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    creds = Credentials(
        token=token,
        refresh_token=get("GOOGLE_REFRESH_TOKEN"),
        client_id=get("GOOGLE_CLIENT_ID"),
        client_secret=get("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=scopes,
    )
    return build(api, version, credentials=creds, cache_discovery=False)

def show_env():
    keys = [
        "GOOGLE_CLIENT_ID","GOOGLE_CLIENT_SECRET","GOOGLE_REFRESH_TOKEN",
        "PRIMARY_SHEET_ID","DRIVE_FOLDER_ID","SHARED_DRIVE_ID","CALENDAR_ID",
        "DEFAULT_TIMEZONE","MEETING_KEY"
    ]
    for k in keys:
        v = os.getenv(k)
        if not v:
            print(f"{k}=<not set>")
        elif "SECRET" in k or "REFRESH_TOKEN" in k:
            print(f"{k}={v[:4]}... (hidden)")
        else:
            print(f"{k}={v}")

def show_drive():
    token = get_access_token()
    svc = build_client("drive","v3",token)
    folder = get("DRIVE_FOLDER_ID", required=True)
    meeting_key = get("MEETING_KEY", default="")
    q = f"'{folder}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false"
    if meeting_key:
        q += f" and name contains '{meeting_key}'"
    resp = svc.files().list(
        q=q, orderBy="modifiedTime desc", pageSize=5,
        fields="files(id,name,modifiedTime,owners(displayName,emailAddress))",
    ).execute()
    files = resp.get("files", [])
    if not files:
        print("No Docs found. Check DRIVE_FOLDER_ID / permission / name filter.")
    for f in files:
        print(f"- {f['name']}  ({f['id']})  updated: {f['modifiedTime']}  owner: {f['owners'][0]['emailAddress']}")

def show_docs(doc_id):
    token = get_access_token()
    svc = build_client("docs","v1",token)
    d = svc.documents().get(documentId=doc_id).execute()
    title = d.get("title","(no title)")
    lines = []
    for c in d.get("body",{}).get("content",[]):
        p = c.get("paragraph")
        if not p: continue
        seg = "".join(e.get("textRun",{}).get("content","") for e in p.get("elements",[]) if e.get("textRun"))
        if seg.strip(): lines.append(seg.strip())
    text = "\n".join(lines)
    print(f"# {title}\n")
    print(text[:2000])

def show_sheets(range_a1=None):
    token = get_access_token()
    svc = build_client("sheets","v4",token)
    sid = get("PRIMARY_SHEET_ID", required=True)
    rng = range_a1 or "A1:Z20"
    vals = svc.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute().get("values", [])
    if not vals:
        print(f"(empty range: {rng})"); return
    widths = [max(len(str(x)) for x in col) for col in zip(*([vals[0]] + [row + [""]*(len(vals[0])-len(row)) for row in vals[1:]]))]
    for row in vals:
        cells = row + [""]*(len(widths)-len(row))
        print(" | ".join(str(c).ljust(w) for c,w in zip(cells,widths)))

def show_calendar():
    token = get_access_token()
    svc = build_client("calendar","v3",token)
    cal_id = get("CALENDAR_ID", default="primary")
    JST = timezone(timedelta(hours=9))
    start = datetime.now(JST).replace(hour=0,minute=0,second=0,microsecond=0)
    end   = start + timedelta(days=7)
    items = svc.events().list(
        calendarId=cal_id, timeMin=start.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime"
    ).execute().get("items", [])
    if not items:
        print("No events in next 7 days.")
    for e in items[:10]:
        when = e.get("start",{}).get("dateTime") or e.get("start",{}).get("date")
        atts = [a.get("email") for a in (e.get("attendees") or [])]
        print(f"- {when}  {e.get('summary','(no title)')}  attendees: {', '.join(atts) if atts else '-'}")

def help():
    print("""
Usage:
  python view.py env
  python view.py drive
  python view.py docs <DOC_ID>
  python view.py sheets [SHEET_RANGE]     # e.g. 'meetings!A1:Z20'
  python view.py calendar
""".strip())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        help(); sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "env":        show_env()
    elif cmd == "drive":    show_drive()
    elif cmd == "docs":     show_docs(sys.argv[2] if len(sys.argv)>=3 else sys.exit("need DOC_ID"))
    elif cmd == "sheets":   show_sheets(sys.argv[2] if len(sys.argv)>=3 else None)
    elif cmd == "calendar": show_calendar()
    else:                   help()

