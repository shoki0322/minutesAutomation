"""
Drive監視スクリプト
指定フォルダ内の新規Google Docsを検知し、シートに追加
"""
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .google_clients import drive, docs
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    append_row,
    now_jst_str,
    date_plus_days,
)

DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo")


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
        print("[drive_monitor] DRIVE_FOLDER_ID not set. Skipping.")
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
        
        # 各シート（事業部）に追加
        # 実際の運用では、どのシートに追加するかのロジックが必要
        # ここでは全シートに追加しないよう、1つ目のシートのみに追加
        # TODO: タイトルやフォルダ構造から適切なシートを判断するロジックを追加
        
        target_sheet = None
        for sheet_name in sheet_names:
            # システムシート以外を対象（例：「mappings」などは除外）
            if sheet_name.lower() in ["mappings", "meetings", "items", "agendas", "archives"]:
                continue
            target_sheet = sheet_name
            break
        
        if not target_sheet:
            print(f"[drive_monitor] No valid target sheet found for {title}")
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
            "hearing_thread_ts": "",
            "minutes_posted": "",
        }
        
        # シートに追加
        append_row(target_sheet, new_row)
        print(f"[drive_monitor] Added new doc to {target_sheet}: {title}")


if __name__ == "__main__":
    monitor_and_update_sheets()

