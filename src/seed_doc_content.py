import os
from typing import List
from datetime import datetime, timedelta
from .google_clients import docs as docs_client
from .sheets_repo import get_latest_meeting
from .calendar_participants import fetch_attendees_for_date

MEETING_KEY = os.getenv("MEETING_KEY")

FALLBACK_EMAILS = [
    "shoki.kanno@nexx-inc.jp",
    "kota.nakajima@initialbrain.jp",
    "sota.suzuki@initialbrain.jp",
]

def build_seed_block(emails: List[str]) -> str:
    today = datetime.utcnow().date()
    due1 = (today + timedelta(days=7)).isoformat()
    due2 = (today + timedelta(days=10)).isoformat()
    lines = []
    lines.append("\n## 次アクション (seed)\n")
    if emails:
        # Assign simple dummy tasks per person
        for i, em in enumerate(emails):
            if i % 3 == 0:
                lines.append(f"- [ ] ダミータスクA 担当: {em} 期限: {due1}\n")
            elif i % 3 == 1:
                lines.append(f"- [ ] ダミータスクB 担当: {em} 期限: {due2} https://example.com\n")
            else:
                lines.append(f"- [ ] ダミータスクC 担当: {em}\n")
    else:
        lines.append("- [ ] ダミータスク 担当: someone@example.com 期限: %s\n" % due1)
    lines.append("\n## 振り返り (seed)\n")
    if emails:
        for em in emails:
            lines.append(f"- {em}: 今週のハイライト（ダミー）\n")
    else:
        lines.append("- someone@example.com: 今週のハイライト（ダミー）\n")
    return "".join(lines)

def main():
    if not MEETING_KEY:
        raise RuntimeError("MEETING_KEY required.")
    meeting = get_latest_meeting(MEETING_KEY)
    if not meeting:
        raise RuntimeError("No meeting found. Run docs_ingest first.")
    doc_id = meeting["doc_id"]
    date_str = meeting.get("date") or datetime.utcnow().date().isoformat()
    emails = fetch_attendees_for_date(date_str, MEETING_KEY)
    if not emails:
        emails = FALLBACK_EMAILS
    block = build_seed_block(emails)

    # Append to end of document
    svc = docs_client().documents()
    svc.batchUpdate(documentId=doc_id, body={
        "requests": [
            {"insertText": {"endOfSegmentLocation": {}, "text": "\n" + block}}
        ]
    }).execute()
    print(f"[seed_doc_content] Seeded content for {len(emails)} people into doc {doc_id}")

if __name__ == "__main__":
    main()

