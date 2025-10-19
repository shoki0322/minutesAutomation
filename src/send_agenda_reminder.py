"""
議題共有リマインダー
next_meeting_dateの前日18:00（JST）にSlackへ次回議題を投稿
"""
import os
from datetime import datetime, timedelta
from .slack_client import SlackClient
from .google_clients import docs as docs_client, drive as drive_client, calendar as calendar_client
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    update_row,
    now_jst,
    now_jst_str,
)

DEFAULT_CHANNEL_ID = os.getenv("DEFAULT_CHANNEL_ID", "").strip()


def create_google_doc(title: str, content: str) -> str:
    """
    Google Docsを作成して、URLを返す
    """
    try:
        # 新しいドキュメントを作成
        doc_service = docs_client()
        doc = doc_service.documents().create(body={'title': title}).execute()
        doc_id = doc.get('documentId')
        
        # 内容を挿入
        requests = [
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': content
                }
            }
        ]
        
        doc_service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': requests}
        ).execute()
        
        # ドキュメントのURLを生成
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        
        print(f"[create_google_doc] Created document: {doc_url}")
        
        return doc_url
    
    except Exception as e:
        print(f"[create_google_doc] Error creating document: {e}")
        return ""


def should_send_agenda_reminder(next_meeting_date_str: str) -> bool:
    """
    議題共有リマインダーを送信すべきかどうか判定
    next_meeting_dateの前日18:00に実行される想定
    現在時刻が前日の18:00~19:00の範囲内ならTrue
    """
    if not next_meeting_date_str:
        return False
    
    try:
        # next_meeting_dateをパース
        meeting_date = datetime.strptime(next_meeting_date_str, "%Y-%m-%d")
        
        # 前日
        target_date = meeting_date - timedelta(days=1)
        
        # 現在のJST時刻
        now = now_jst()
        
        # 同じ日付で、18:00以降
        # GitHub Actionsは毎時00分実行なので、18:00以降ならOK
        # remarksのagenda_sentフラグで重複防止されているので何度実行しても安全
        if now.date() == target_date.date() and now.hour >= 18:
            return True
        
        return False
    
    except Exception as e:
        print(f"[send_agenda_reminder] Error parsing date {next_meeting_date_str}: {e}")
        return False


def create_agenda_message(title: str, next_meeting_date: str, next_agenda: str, 
                         mentions: str = "") -> str:
    """議題共有メッセージを生成（メンション＋テキスト本文のみ）"""
    parts = []
    
    # メンション
    if mentions:
        parts.append(mentions)
    
    # タイトルと日付
    parts.append(f"明日の議題共有（{next_meeting_date} 開催）")

    # 議題本文をそのまま載せる（テキストのみ）
    if next_agenda:
        parts.append("")
        parts.append(next_agenda)
    
    return "\n".join(parts)


def _find_event_on_date(cal_svc, calendar_id: str, date_str: str, title: str) -> dict:
    """指定日付のイベントからタイトル一致（部分可）を優先して1件返す。無ければ最初のイベント。無ければNone。"""
    from datetime import datetime, timedelta
    import pytz
    tz = pytz.timezone(os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo"))
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    dt = tz.localize(dt)
    time_min = dt.isoformat()
    time_max = (dt + timedelta(days=1)).isoformat()
    items = cal_svc.events().list(calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
                                  singleEvents=True, orderBy="startTime").execute().get("items", [])
    if not items:
        return None
    # 完全一致
    for ev in items:
        if ev.get("summary", "") == title:
            return ev
    # 部分一致
    for ev in items:
        sm = ev.get("summary", "")
        if title in sm or sm in title:
            return ev
    return items[0]


def _append_doc_url_to_event_description(cal_svc, calendar_id: str, event: dict, doc_url: str) -> bool:
    """イベントのdescription末尾にDoc URLを追記。更新成功でTrue。"""
    if not event:
        return False
    desc = (event.get("description") or "").strip()
    append_line = f"\n\n次回議題: {doc_url}"
    if doc_url in desc:
        return True  # 既に含まれていればOK扱い
    new_desc = (desc + append_line) if desc else f"次回議題: {doc_url}"
    patched = {"description": new_desc}
    cal_svc.events().patch(calendarId=calendar_id, eventId=event.get("id"), body=patched).execute()
    return True


def send_agenda_for_sheet(sheet_name: str, slack_client: SlackClient):
    """1つのシートに対して議題共有送信チェック"""
    print(f"[send_agenda_reminder] Checking sheet: {sheet_name}")
    
    rows = read_sheet_rows(sheet_name)
    
    for row in rows:
        next_meeting_date = row.get("next_meeting_date", "").strip()
        next_agenda = row.get("next_agenda", "").strip()
        
        # 条件: next_agendaが非空
        if not next_agenda:
            continue
        
        # 送信すべきか判定
        if not should_send_agenda_reminder(next_meeting_date):
            continue
        
        # 重複送信防止: remarksに "agenda_sent:YYYY-MM-DD" が含まれていたらスキップ
        remarks = row.get("remarks", "")
        sent_marker = f"agenda_sent:{next_meeting_date}"
        if sent_marker in remarks:
            print(f"[send_agenda_reminder] Already sent for {next_meeting_date}: {row.get('title')}")
            continue
        
        # チャンネルID取得
        channel_id = row.get("channel_id", "").strip() or DEFAULT_CHANNEL_ID
        if not channel_id:
            print(f"[send_agenda_reminder] No channel_id for: {row.get('title')}")
            continue
        
        title = row.get("title", "無題")
        
        # 参加者メンションを生成
        participants_str = row.get("participants", "").strip()
        mentions = ""
        if participants_str:
            participant_emails = [p.strip() for p in participants_str.split(',') if p.strip()]
            slack_ids = []
            
            for email in participant_emails:
                # メールからSlack IDを取得（ドメイン変換含む）
                slack_id = slack_client.lookup_user_id_by_email(email)
                
                # ドメイン変換: @initialbrain.jp -> @nexx-inc.jp
                if not slack_id and "@initialbrain.jp" in email:
                    converted_email = email.replace("@initialbrain.jp", "@nexx-inc.jp")
                    slack_id = slack_client.lookup_user_id_by_email(converted_email)
                
                if slack_id:
                    slack_ids.append(f"<@{slack_id}>")
            
            if slack_ids:
                mentions = " ".join(slack_ids)
        
        # 次回議題用のGoogle Docsを作成し、カレンダーイベントの説明にURLを追加
        doc_title = f"{title} - 次回議題 ({next_meeting_date})"
        agenda_doc_url = create_google_doc(doc_title, next_agenda)
        if agenda_doc_url:
            try:
                cal_svc = calendar_client()
                calendar_id = os.getenv("CALENDAR_ID", "primary")
                ev = _find_event_on_date(cal_svc, calendar_id, next_meeting_date, title)
                if ev:
                    if _append_doc_url_to_event_description(cal_svc, calendar_id, ev, agenda_doc_url):
                        print(f"[send_agenda_reminder] Appended doc URL to calendar event: {ev.get('summary','')} ({ev.get('id')})")
                else:
                    print(f"[send_agenda_reminder] No calendar event found on {next_meeting_date} for {title}")
            except Exception as e:
                print(f"[send_agenda_reminder] Failed to append doc to calendar: {e}")
        else:
            print(f"[send_agenda_reminder] Failed to create Google Doc for: {title}")

        # Slackにはテキストのみ送る（Docsリンクは含めない）
        message = create_agenda_message(title, next_meeting_date, next_agenda, mentions)
        
        # Slack投稿
        print(f"[send_agenda_reminder] Sending agenda reminder for: {title}")
        ts = slack_client.post_message(channel_id, message)
        
        if ts:
            # 送信成功: remarksに送信済みマークを追記
            row_number = row.get("_row_number")
            if row_number:
                new_remarks = f"{remarks} {sent_marker}".strip()
                update_row(sheet_name, row_number, {
                    "remarks": new_remarks,
                    "updated_at": now_jst_str(),
                })
                print(f"[send_agenda_reminder] Successfully sent and updated row {row_number}")
        else:
            print(f"[send_agenda_reminder] Failed to send agenda for: {title}")


def main():
    """メイン処理"""
    slack_client = SlackClient()
    
    # 全シートをチェック
    sheet_names = get_all_sheet_names()
    
    for sheet_name in sheet_names:
        # システムシートはスキップ
        if sheet_name.lower() in ["mappings", "meetings", "items", "agendas", "archives", "hearing_prompts", "hearing_responses"]:
            continue
        
        try:
            send_agenda_for_sheet(sheet_name, slack_client)
        except Exception as e:
            print(f"[send_agenda_reminder] Error processing sheet {sheet_name}: {e}")
            continue


if __name__ == "__main__":
    main()

