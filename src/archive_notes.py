import os
from typing import Optional, Dict, Any
from .google_clients import docs as docs_client
import os
from .sheets_repo import get_latest_meeting, upsert_archive, find_meeting_by_title_contains

MEETING_KEY = os.getenv("MEETING_KEY")
MEETING_TITLE_CONTAINS = os.getenv("MEETING_TITLE_CONTAINS", "").strip()

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
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = None
    if MEETING_TITLE_CONTAINS:
        meeting = find_meeting_by_title_contains(MEETING_TITLE_CONTAINS, MEETING_KEY)
    if not meeting:
        meeting = get_latest_meeting(MEETING_KEY)
    if not meeting:
        raise RuntimeError("No meeting found. Run docs_ingest first.")
    meeting_id = meeting["meeting_id"]
    date_str = meeting["date"]
    title = meeting.get("title", "")
    doc_id = meeting["doc_id"]
    text = _extract_text_from_doc(doc_id)
    upsert_archive(meeting_id=meeting_id, date_str=date_str, title=title, doc_id=doc_id, body_text=text)
    print(f"[archive_notes] Archived doc to Sheets: meeting_id={meeting_id}, chars={len(text)}")

if __name__ == "__main__":
    main()
