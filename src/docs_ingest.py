import os
from dateutil import tz, parser as dateparser
from typing import Optional, Dict, Any
from .google_clients import drive as drive_client, docs as docs_client
from .sheets_repo import upsert_meeting, now_date_str

DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
MEETING_KEY = os.getenv("MEETING_KEY")
MEETING_TITLE_CONTAINS = os.getenv("MEETING_TITLE_CONTAINS", "").strip()

def _search_latest_doc(folder_id: str, meeting_key: str) -> Optional[Dict[str, Any]]:
    svc = drive_client().files()
    conds = [
        f"'{folder_id}' in parents",
        "mimeType='application/vnd.google-apps.document'",
        "trashed=false",
    ]
    if meeting_key:
        conds.append(f"name contains '{meeting_key}'")
    if MEETING_TITLE_CONTAINS:
        conds.append(f"name contains '{MEETING_TITLE_CONTAINS}'")
    query = " and ".join(conds)
    res = svc.list(q=query, orderBy="modifiedTime desc", fields="files(id,name,modifiedTime,parents)", pageSize=10).execute()
    files = res.get("files", [])
    return files[0] if files else None

def _extract_text_from_doc(doc_id: str) -> str:
    document = docs_client().documents().get(documentId=doc_id).execute()
    def walk(elements):
        text = ""
        for e in elements:
            if "paragraph" in e:
                for el in e["paragraph"].get("elements", []):
                    text += el.get("textRun", {}).get("content", "")
            if "table" in e:
                for row in e["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        text += walk(cell.get("content", []))
            if "tableOfContents" in e:
                text += walk(e["tableOfContents"].get("content", []))
        return text
    return walk(document.get("body", {}).get("content", []))

def main():
    if not (DRIVE_FOLDER_ID and MEETING_KEY):
        raise RuntimeError("DRIVE_FOLDER_ID and MEETING_KEY are required.")
    latest = _search_latest_doc(DRIVE_FOLDER_ID, MEETING_KEY)
    if not latest and MEETING_TITLE_CONTAINS:
        # Relax to title-only search within the folder
        print(f"[docs_ingest] No match with MEETING_KEY; retrying with title contains only: '{MEETING_TITLE_CONTAINS}'")
        svc = drive_client().files()
        q = (
            f"'{DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false and name contains '{MEETING_TITLE_CONTAINS}'"
        )
        res = svc.list(q=q, orderBy="modifiedTime desc", fields="files(id,name,modifiedTime,parents)", pageSize=10).execute()
        files = res.get("files", [])
        latest = files[0] if files else None
    if not latest:
        raise RuntimeError("No matching Google Doc found in the folder for MEETING_KEY.")
    doc_id = latest["id"]
    title = latest["name"]
    modified = latest.get("modifiedTime")
    tzinfo = tz.gettz(DEFAULT_TIMEZONE)
    date_str = now_date_str()
    if modified:
        try:
            dt = dateparser.isoparse(modified).astimezone(tzinfo)
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    text = _extract_text_from_doc(doc_id)
    meeting_id = doc_id
    upsert_meeting(meeting_id=meeting_id, meeting_key=MEETING_KEY, date_str=date_str, title=title, doc_id=doc_id, participant_emails="", channel_id="", parent_ts="")
    print(f"[docs_ingest] Upserted meeting: {meeting_id} {title} {date_str} (chars={len(text)})")

if __name__ == "__main__":
    main()
