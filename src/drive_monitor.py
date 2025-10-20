"""
Drive監視スクリプト
指定フォルダ内の新規Google Docsを検知し、シートに追加
"""
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .google_clients import drive, docs, calendar
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    append_row,
    now_jst_str,
    date_plus_days,
)

DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo")
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary").strip()
WORKSPACE_DOMAINS = [d.strip() for d in os.getenv("WORKSPACE_DOMAINS", "").split(",") if d.strip()]


def get_doc_text_content(doc_id: str) -> str:
    """Google DocsのIDから本文テキストを取得"""
    try:
        # Docs APIで取得
        doc_service = docs()
        document = doc_service.documents().get(documentId=doc_id).execute()
        
        # テキストを抽出
        content = document.get("body", {}).get("content", [])
        text_parts = []
        
        for element in content:
            if "paragraph" in element:
                paragraph = element["paragraph"]
                for elem in paragraph.get("elements", []):
                    if "textRun" in elem:
                        text_parts.append(elem["textRun"].get("content", ""))
        
        full_text = "".join(text_parts).strip()
        return full_text
    
    except Exception as e:
        print(f"[drive_monitor] Error getting doc content for {doc_id}: {e}")
        return ""


def list_docs_in_folder(folder_id: str, hours_ago: int = 3) -> List[Dict[str, str]]:
    """
    指定フォルダ内のGoogle Docsをリスト（共有ドライブ対応）
    hours_ago: 過去N時間以内に作成されたファイルのみ取得（初回は大きめの値を推奨）
    """
    drive_service = drive()
    
    # 過去N時間以内のファイルを検索
    from datetime import datetime, timezone
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    cutoff_str = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
    
    query = (
        f"'{folder_id}' in parents "
        f"and mimeType='application/vnd.google-apps.document' "
        f"and createdTime > '{cutoff_str}' "
        f"and trashed=false"
    )
    
    # 共有ドライブ対応のパラメータを追加
    results = drive_service.files().list(
        q=query,
        fields="files(id, name, createdTime, webViewLink)",
        orderBy="createdTime desc",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    
    files = results.get("files", [])
    print(f"[drive_monitor] Found {len(files)} new docs in folder {folder_id}")
    
    return files


def _lookup_calendar_event_and_attendees(keyword: str, target_date_str: str) -> (Optional[str], List[str]):
    """同日のカレンダーから対象イベントを特定し、開始日（YYYY-MM-DD）と出席者メールを返す。
    - keyword がタイトルに含まれるイベントを優先
    - 見つからない場合は当日の最初のイベント
    """
    try:
        cal_svc = calendar()
        # 日付範囲（当日）
        from datetime import datetime, timedelta
        import pytz
        tz = pytz.timezone(DEFAULT_TIMEZONE)
        dt = tz.localize(datetime.strptime(target_date_str, "%Y-%m-%d"))
        time_min = dt.isoformat()
        time_max = (dt + timedelta(days=1)).isoformat()
        items = cal_svc.events().list(
            calendarId=CALENDAR_ID or "primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])
        if not items:
            return None, []
        # キーワード一致優先
        target = None
        if keyword:
            for ev in items:
                summary = ev.get("summary", "")
                if keyword in summary:
                    target = ev
                    break
        if not target:
            target = items[0]
        # 開始日の正規化
        start = target.get("start", {})
        start_dt = start.get("dateTime") or start.get("date")
        if start_dt and len(start_dt) >= 10:
            event_date = start_dt[:10]
        else:
            event_date = target_date_str
        # 出席者メール
        attendees = [a.get("email", "") for a in (target.get("attendees") or []) if a.get("email")]
        # ワークスペースドメインでフィルタ
        if WORKSPACE_DOMAINS:
            attendees = [e for e in attendees if any(e.endswith(f"@{dom}") for dom in WORKSPACE_DOMAINS)]
        return event_date, attendees
    except Exception:
        return None, []


def doc_already_exists(sheet_name: str, doc_url: str) -> bool:
    """シート内に既に同じdoc_urlが存在するかチェック"""
    rows = read_sheet_rows(sheet_name)
    for row in rows:
        if row.get("doc_url") == doc_url:
            return True
    return False


def monitor_and_update_sheets():
    """Drive監視メイン処理"""
    if not DRIVE_FOLDER_ID:
        print("[drive_monitor] ERROR: DRIVE_FOLDER_ID not set or empty. Skipping.")
        print(f"[drive_monitor] DEBUG: DRIVE_FOLDER_ID value: '{DRIVE_FOLDER_ID}' (length: {len(DRIVE_FOLDER_ID)})")
        return
    
    print(f"[drive_monitor] Monitoring folder: {DRIVE_FOLDER_ID}")
    
    # 過去3時間以内の新規Docsを取得（2時間に1回実行なので余裕を持たせる）
    new_docs = list_docs_in_folder(DRIVE_FOLDER_ID, hours_ago=3)
    
    if not new_docs:
        print("[drive_monitor] No new documents found.")
        return
    
    # 全シート名を取得
    sheet_names = get_all_sheet_names()
    print(f"[drive_monitor] Found {len(sheet_names)} sheets")
    
    # 各新規Docsに対して処理
    for doc_file in new_docs:
        doc_id = doc_file["id"]
        doc_url = doc_file.get("webViewLink", f"https://docs.google.com/document/d/{doc_id}/edit")
        title = doc_file.get("name", "無題")
        created_time = doc_file.get("createdTime", "")
        
        # 作成日をパース
        try:
            created_dt = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
            date_str = created_dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = now_jst_str()[:10]
        
        print(f"[drive_monitor] Processing: {title} ({doc_url})")
        
        # Docsの本文を取得
        summary = get_doc_text_content(doc_id)
        
        # next_meeting_date = date + 7日
        next_meeting_date = date_plus_days(date_str, 7)
        
        # タイトルにシート名が含まれるかチェックして振り分け
        # 例：「AI基盤MTG」→「AI基盤」シート、「BI基盤MTG」→「BI基盤」シート
        target_sheet = None
        for sheet_name in sheet_names:
            # システムシート以外を対象
            if sheet_name.lower() in ["mappings", "meetings", "items", "agendas", "archives", "hearing_prompts", "hearing_responses"]:
                continue
            
            # タイトルにシート名が含まれているかチェック
            if sheet_name in title:
                target_sheet = sheet_name
                print(f"[drive_monitor] Matched sheet '{sheet_name}' from title: {title}")
                break
        
        if not target_sheet:
            print(f"[drive_monitor] No matching sheet found for title: {title} (skipping)")
            continue
        
        # 重複チェック
        if doc_already_exists(target_sheet, doc_url):
            print(f"[drive_monitor] Doc already exists in {target_sheet}: {doc_url}")
            continue
        
        # 既存行からchannel_idを取得（シートごとに固定）
        existing_rows = read_sheet_rows(target_sheet)
        default_channel_id = ""
        for existing_row in existing_rows:
            existing_channel = existing_row.get("channel_id", "").strip()
            if existing_channel:
                default_channel_id = existing_channel
                break
        
        # 新規行データ
        new_row = {
            "doc_url": doc_url,
            "summary": summary,
            "title": title,
            "date": date_str,
            "next_meeting_date": next_meeting_date,
            "updated_at": now_jst_str(),
            "formatted_minutes": "",
            "decisions": "",
            "open_issues": "",
            "hearing_responses01": "",
            "hearing_responses02": "",
            "hearing_responses03": "",
            "hearing_responses04": "",
            "next_agenda": "",
            "status": "new",
            "remarks": "",
            "meeting_key": "",
            "channel_id": default_channel_id,  # 既存行から自動コピー
            "participants": "",
            "minutes_thread_ts": "",
            "final_minutes_thread_ts": "",
            "hearing_thread_ts": "",
            "minutes_posted": "",
        }
        
        # シートに追加
        append_row(target_sheet, new_row)
        print(f"[drive_monitor] Added new doc to {target_sheet}: {title}")


if __name__ == "__main__":
    monitor_and_update_sheets()

