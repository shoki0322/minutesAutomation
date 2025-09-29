import os
import hashlib
from typing import List, Dict, Optional, Tuple
import time
from datetime import datetime
from dateutil import tz
from googleapiclient.errors import HttpError
from .google_clients import sheets as sheets_client

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo")
PRIMARY_SHEET_ID = os.getenv("PRIMARY_SHEET_ID")

HEADERS: Dict[str, List[str]] = {
    "mappings": ["meeting_key", "slack_channel_id", "email", "slack_user_id", "display_name"],
    "meetings": ["meeting_id", "meeting_key", "date", "title", "doc_id", "participant_emails", "channel_id", "parent_ts"],
    "items": ["date", "meeting_id", "task", "assignee_email", "assignee_slack_id", "due", "links", "status", "dedupe_key"],
    "hearing_prompts": ["meeting_id", "channel_id", "parent_ts", "assignee_slack_id", "prompt_ts", "due_to_reply", "status"],
    "hearing_responses": ["meeting_id", "assignee_slack_id", "reply_ts", "todo_status", "reports", "blockers", "links", "raw_text"],
    "agendas": ["meeting_id", "channel_id", "thread_ts", "body_md", "posted_ts"],
    "archives": ["meeting_id", "date", "title", "doc_id", "body_text"],
}

def _sheets_service():
    if not PRIMARY_SHEET_ID:
        raise RuntimeError("PRIMARY_SHEET_ID is required.")
    return sheets_client().spreadsheets()

def _get_sheet_titles() -> List[str]:
    svc = _sheets_service()
    last_err = None
    for i in range(3):
        try:
            meta = svc.get(spreadsheetId=PRIMARY_SHEET_ID).execute()
            return [s["properties"]["title"] for s in meta.get("sheets", [])]
        except Exception as e:
            last_err = e
            # naive backoff for quota errors
            time.sleep(1 + i * 2)
    raise last_err

def ensure_tab(tab: str) -> None:
    titles = _get_sheet_titles()
    if tab not in titles:
        print(f"[sheets] Creating sheet tab: {tab}")
        svc = _sheets_service()
        body = {"requests": [{"addSheet": {"properties": {"title": tab}}}]}
        svc.batchUpdate(spreadsheetId=PRIMARY_SHEET_ID, body=body).execute()
        # Insert header row
        svc.values().update(
            spreadsheetId=PRIMARY_SHEET_ID,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS[tab]]},
        ).execute()

def read_rows(tab: str) -> List[Dict[str, str]]:
    ensure_tab(tab)
    svc = _sheets_service()
    result = svc.values().get(spreadsheetId=PRIMARY_SHEET_ID, range=f"{tab}!A:Z").execute()
    values = result.get("values", [])
    if not values:
        # write header row
        svc.values().update(
            spreadsheetId=PRIMARY_SHEET_ID,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS[tab]]},
        ).execute()
        return []
    headers = values[0]
    rows = []
    for row in values[1:]:
        d = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        rows.append(d)
    return rows

def _write_row_at_index(tab: str, headers: List[str], row_dict: Dict[str, str], data_index_1_based: int) -> None:
    # data_index_1_based: 2 means second row (first data row)
    values = [[row_dict.get(h, "") for h in headers]]
    svc = _sheets_service()
    svc.values().update(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{tab}!A{data_index_1_based}",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

def upsert_by_keys(tab: str, row_dict: Dict[str, str], key_fields: List[str]) -> int:
    ensure_tab(tab)
    headers = HEADERS[tab]
    rows = read_rows(tab)
    # find existing
    for idx, r in enumerate(rows):
        if all(str(r.get(k, "")) == str(row_dict.get(k, "")) for k in key_fields):
            # update at row number = idx+2
            data_index = idx + 2
            _write_row_at_index(tab, headers, {**r, **row_dict}, data_index)
            return data_index
    # append
    values = [[row_dict.get(h, "") for h in headers]]
    svc = _sheets_service()
    svc.values().append(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{tab}!A:Z",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()
    # return new index (best-effort)
    rows2 = read_rows(tab)
    return len(rows2) + 1  # header + all rows => next index (best-effort)

def get_channel_for_meeting_key(meeting_key: str) -> Optional[str]:
    rows = read_rows("mappings")
    for r in rows:
        if r.get("meeting_key") == meeting_key and r.get("slack_channel_id"):
            return r["slack_channel_id"]
    return os.getenv("DEFAULT_CHANNEL_ID")

def get_slack_id_for_email(email: str) -> Optional[str]:
    rows = read_rows("mappings")
    for r in rows:
        if r.get("email") == email and r.get("slack_user_id"):
            return r["slack_user_id"]
    return None

def resolve_contact_by_name(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve (email, slack_user_id) by display_name loose match from mappings.
    Matching rules: case-insensitive, ignore spaces, substring match in either direction.
    """
    target = (name or "").strip().lower().replace(" ", "")
    if not target:
        return None, None
    rows = read_rows("mappings")
    best_email, best_sid = None, None
    for r in rows:
        disp = (r.get("display_name") or "").strip().lower().replace(" ", "")
        if not disp:
            continue
        if target in disp or disp in target:
            if r.get("email"):
                best_email = r["email"].strip().lower()
            if r.get("slack_user_id"):
                best_sid = r["slack_user_id"].strip()
            # Prefer exact normalized match
            if target == disp:
                return best_email, best_sid
    return best_email, best_sid

def save_email_slack_mapping(email: str, slack_user_id: str, display_name: str = ""):
    # upsert on email
    row = {"meeting_key": "", "slack_channel_id": "", "email": email, "slack_user_id": slack_user_id, "display_name": display_name}
    upsert_by_keys("mappings", row, ["email"])

def upsert_meeting(meeting_id: str, meeting_key: str, date_str: str, title: str, doc_id: str, participant_emails: str = "", channel_id: str = "", parent_ts: str = ""):
    row = {
        "meeting_id": meeting_id,
        "meeting_key": meeting_key,
        "date": date_str,
        "title": title,
        "doc_id": doc_id,
        "participant_emails": participant_emails,
        "channel_id": channel_id,
        "parent_ts": parent_ts,
    }
    upsert_by_keys("meetings", row, ["meeting_id"])

def set_meeting_parent_ts(meeting_id: str, parent_ts: str):
    rows = read_rows("meetings")
    for r in rows:
        if r.get("meeting_id") == meeting_id:
            row = {**r, "parent_ts": parent_ts}
            upsert_by_keys("meetings", row, ["meeting_id"])
            return
    print(f"[sheets] meeting_id not found for parent_ts: {meeting_id}")

def get_latest_meeting(meeting_key: Optional[str] = None) -> Optional[Dict[str, str]]:
    rows = read_rows("meetings")
    # Filter by meeting_key if provided
    if meeting_key:
        rows = [r for r in rows if r.get("meeting_key") == meeting_key]
    def date_key(r):
        try:
            return r.get("date") or ""
        except Exception:
            return ""
    rows = sorted(rows, key=date_key, reverse=True)
    return rows[0] if rows else None

def find_meeting_by_title_contains(substr: str, meeting_key: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Return the most recent meeting whose title contains the given substring.
    If meeting_key is provided, filter by it first.
    """
    rows = read_rows("meetings")
    if meeting_key:
        rows = [r for r in rows if r.get("meeting_key") == meeting_key]
    s = (substr or "").strip()
    if not s:
        return None
    rows = [r for r in rows if s in (r.get("title") or "")]
    rows = sorted(rows, key=lambda r: (r.get("date") or "", r.get("title") or ""), reverse=True)
    return rows[0] if rows else None

def get_previous_meeting(meeting_key: str, current_date: str) -> Optional[Dict[str, str]]:
    rows = [r for r in read_rows("meetings") if r.get("meeting_key") == meeting_key]
    rows = [r for r in rows if r.get("date") and r.get("date") < (current_date or "")]
    rows = sorted(rows, key=lambda r: r.get("date") or "", reverse=True)
    return rows[0] if rows else None

def upsert_item(date_str: str, meeting_id: str, task: str, assignee_email: str, assignee_slack_id: str, due: str, links: str, status: str):
    dedupe_key = f"{date_str}:{assignee_email}:{hashlib.sha1(task.strip().lower().encode('utf-8')).hexdigest()[:10]}"
    row = {
        "date": date_str,
        "meeting_id": meeting_id,
        "task": task,
        "assignee_email": assignee_email,
        "assignee_slack_id": assignee_slack_id,
        "due": due,
        "links": links,
        "status": status,
        "dedupe_key": dedupe_key,
    }
    upsert_by_keys("items", row, ["dedupe_key"])

def list_items_for_meeting(meeting_id: str) -> List[Dict[str, str]]:
    rows = read_rows("items")
    return [r for r in rows if r.get("meeting_id") == meeting_id]

def upsert_hearing_prompt(meeting_id: str, channel_id: str, parent_ts: str, assignee_slack_id: str, prompt_ts: str, due_to_reply: str, status: str):
    row = {
        "meeting_id": meeting_id,
        "channel_id": channel_id,
        "parent_ts": parent_ts,
        "assignee_slack_id": assignee_slack_id,
        "prompt_ts": prompt_ts,
        "due_to_reply": due_to_reply,
        "status": status,
    }
    upsert_by_keys("hearing_prompts", row, ["meeting_id", "assignee_slack_id"])

def upsert_hearing_response(meeting_id: str, assignee_slack_id: str, reply_ts: str, todo_status: str, reports: str, blockers: str, links: str, raw_text: str):
    row = {
        "meeting_id": meeting_id,
        "assignee_slack_id": assignee_slack_id,
        "reply_ts": reply_ts,
        "todo_status": todo_status,
        "reports": reports,
        "blockers": blockers,
        "links": links,
        "raw_text": raw_text,
    }
    upsert_by_keys("hearing_responses", row, ["meeting_id", "assignee_slack_id", "reply_ts"])

def latest_parent_thread() -> Optional[Tuple[str, str]]:
    # returns (meeting_id, parent_ts) for latest meeting with parent_ts
    rows = read_rows("meetings")
    rows = [r for r in rows if r.get("parent_ts")]
    rows = sorted(rows, key=lambda r: r.get("date", ""), reverse=True)
    if rows:
        return rows[0].get("meeting_id"), rows[0].get("parent_ts")
    return None

def upsert_agenda(meeting_id: str, channel_id: str, thread_ts: str, body_md: str, posted_ts: str = ""):
    row = {
        "meeting_id": meeting_id,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "body_md": body_md,
        "posted_ts": posted_ts,
    }
    upsert_by_keys("agendas", row, ["meeting_id", "thread_ts"])

def set_agenda_posted_ts(meeting_id: str, thread_ts: str, posted_ts: str):
    rows = read_rows("agendas")
    for r in rows:
        if r.get("meeting_id") == meeting_id and r.get("thread_ts") == thread_ts:
            row = {**r, "posted_ts": posted_ts}
            upsert_by_keys("agendas", row, ["meeting_id", "thread_ts"])
            return

def now_date_str() -> str:
    tzinfo = tz.gettz(DEFAULT_TIMEZONE)
    return datetime.now(tzinfo).strftime("%Y-%m-%d")

def upsert_archive(meeting_id: str, date_str: str, title: str, doc_id: str, body_text: str):
    row = {
        "meeting_id": meeting_id,
        "date": date_str,
        "title": title,
        "doc_id": doc_id,
        "body_text": body_text,
    }
    upsert_by_keys("archives", row, ["meeting_id"]) 
