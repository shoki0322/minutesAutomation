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
LOOKBACK_HOURS = int(os.getenv("DRIVE_LOOKBACK_HOURS", "3") or "3")
DEFAULT_TARGET_SHEET = os.getenv("DEFAULT_TARGET_SHEET", "").strip()


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
    # RFC3339（UTC）に正規化
    cutoff_str = cutoff_time.isoformat(timespec='seconds').replace('+00:00', 'Z')
    
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
    print(f"[drive_monitor] Using cutoff createdTime > {cutoff_str} (UTC), hours_ago={hours_ago}")
    print(f"[drive_monitor] Found {len(files)} new docs in folder {folder_id}")
    
    return files


def _lookup_calendar_event_and_attendees(keyword: str, target_date_str: str) -> (Optional[str], List[str]):
    """同日のカレンダーから対象イベントを特定し、開始日時（ISO文字列）と出席者メールを返す。
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
        # キーワード（ベースタイトル）一致の候補を抽出
        def normalize(s: str) -> str:
            return (s or "").replace("\u3000", " ").strip()
        base_title = None
        for ch in ["-", "－", "–", "—"]:
            if ch in keyword:
                base_title = keyword.split(ch, 1)[0]
                break
        if base_title is None:
            base_title = keyword
        base_title = normalize(base_title)

        candidates = []
        for ev in items:
            if base_title and base_title in normalize(ev.get("summary", "")):
                candidates.append(ev)
        if not candidates:
            candidates = items

        # 17:00に最も近い開始時刻のイベントを選択
        def start_minutes(ev) -> int:
            st = ev.get("start", {})
            v = st.get("dateTime") or st.get("date")
            if not v:
                return 0
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(tz)
            except Exception:
                try:
                    dt = tz.localize(datetime.strptime(v, "%Y-%m-%d"))
                except Exception:
                    return 0
            return dt.hour * 60 + dt.minute

        target = min(candidates, key=lambda ev: abs(start_minutes(ev) - (17 * 60)))
        # 開始日時の正規化（dateTime優先。なければ 00:00 固定で補完）
        start = target.get("start", {})
        start_dt = start.get("dateTime") or start.get("date")
        if start_dt:
            if "T" in start_dt:
                start_iso = start_dt
            else:
                # 終日予定など date の場合は 00:00 を補完（JST）
                start_iso = f"{start_dt}T00:00:00+09:00"
        else:
            start_iso = f"{target_date_str}T00:00:00+09:00"
        # 出席者メール
        attendees = [a.get("email", "") for a in (target.get("attendees") or []) if a.get("email")]
        # ワークスペースドメインでフィルタ
        if WORKSPACE_DOMAINS:
            attendees = [e for e in attendees if any(e.endswith(f"@{dom}") for dom in WORKSPACE_DOMAINS)]
        return start_iso, attendees
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
    if DEFAULT_TARGET_SHEET:
        print(f"[drive_monitor] DEFAULT_TARGET_SHEET: {DEFAULT_TARGET_SHEET}")
    
    # 直近の新規Docsを取得（環境変数 DRIVE_LOOKBACK_HOURS で調整可能）
    new_docs = list_docs_in_folder(DRIVE_FOLDER_ID, hours_ago=LOOKBACK_HOURS)
    
    if not new_docs:
        print("[drive_monitor] No new documents found.")
        return
    
    # 全シート名を取得
    sheet_names = get_all_sheet_names()
    print(f"[drive_monitor] Found {len(sheet_names)} sheets: {sheet_names}")
    
    # 各新規Docsに対して処理
    for doc_file in new_docs:
        doc_id = doc_file["id"]
        doc_url = doc_file.get("webViewLink", f"https://docs.google.com/document/d/{doc_id}/edit")
        title = doc_file.get("name", "無題")
        created_time = doc_file.get("createdTime", "")
        
        # 作成日の初期値
        try:
            created_dt = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
            date_str = created_dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = now_jst_str()[:10]
        
        print(f"[drive_monitor] Processing: {title} ({doc_url})")
        
        # Docsの本文を取得
        summary = get_doc_text_content(doc_id)

        # カレンダーから当日イベントを照会して、正確な日付と参加者を補完
        # 例: タイトルに「AI基盤」などのキーワードが含まれていれば、そのイベントを優先
        event_start_iso, attendees = _lookup_calendar_event_and_attendees(title, date_str)
        date_display = ""
        if event_start_iso:
            # date列は時刻付きISOに（下流で日付だけ必要な箇所はスライスして使用）
            date_str = event_start_iso
            try:
                dt = datetime.fromisoformat(event_start_iso.replace("Z", "+00:00"))
                dow = "月火水木金土日"[dt.weekday()]
                date_display = f"{dt.month}月{dt.day}日（{dow}）{dt.strftime('%H:%M')}~{(dt + timedelta(hours=1)).strftime('%H:%M')}"
            except Exception:
                date_display = ""
        
        # next_meeting_date = date + 7日（ベースは日付部）
        next_meeting_date = date_plus_days(date_str[:10], 7)
        # 表示用の next_meeting_date_display（開始+7日，同じ時刻帯を仮適用）
        next_display = ""
        try:
            dt0 = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            dt1 = dt0 + timedelta(days=7)
            dow1 = "月火水木金土日"[dt1.weekday()]
            next_display = f"{dt1.month}月{dt1.day}日（{dow1}）{dt1.strftime('%H:%M')}~{(dt1 + timedelta(hours=1)).strftime('%H:%M')}"
        except Exception:
            next_display = ""
        
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
            if DEFAULT_TARGET_SHEET and DEFAULT_TARGET_SHEET in sheet_names:
                target_sheet = DEFAULT_TARGET_SHEET
                print(f"[drive_monitor] No matching sheet. Falling back to DEFAULT_TARGET_SHEET='{DEFAULT_TARGET_SHEET}'")
            else:
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
            "date_display": date_display,
            "next_meeting_date": next_meeting_date,
            "next_meeting_date_display": next_display,
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
            "participants": ", ".join(attendees) if attendees else "",
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

