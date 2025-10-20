"""
新仕様の議事録管理用リポジトリ
スプレッドシートの各シート（事業部ごと）を管理
"""
import os
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dateutil import tz
from .google_clients import sheets as sheets_client

PRIMARY_SHEET_ID = os.getenv("PRIMARY_SHEET_ID", "").strip()
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Tokyo")

# 想定される列名（スプレッドシートのヘッダー順と一致）
EXPECTED_COLUMNS = [
    "meeting_key",
    "title",
    "date",
    "date_display",
    "next_meeting_date",
    "next_meeting_date_display",
    "participants",
    "doc_url",
    "summary",
    "formatted_minutes",
    "final_minutes",
    "decisions",
    "open_issues",
    "hearing_responses01",
    "hearing_responses02",
    "hearing_responses03",
    "hearing_responses04",
    "next_agenda",
    "channel_id",
    "minutes_posted",
    "minutes_thread_ts",
    "final_minutes_thread_ts",
    "hearing_thread_ts",
    "updated_at",
    "status",
    "remarks",
]


def _sheets_service():
    if not PRIMARY_SHEET_ID:
        raise RuntimeError("PRIMARY_SHEET_ID is required.")
    return sheets_client().spreadsheets()


def get_all_sheet_names() -> List[str]:
    """スプレッドシート内の全シート名を取得（事業部ごと）"""
    svc = _sheets_service()
    meta = svc.get(spreadsheetId=PRIMARY_SHEET_ID).execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def read_sheet_rows(sheet_name: str) -> List[Dict[str, str]]:
    """指定シートの全行を辞書のリストで取得"""
    svc = _sheets_service()
    result = svc.values().get(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{sheet_name}!A:Z"
    ).execute()
    
    values = result.get("values", [])
    if not values:
        return []
    
    headers = values[0]
    rows = []
    for i, row in enumerate(values[1:], start=2):  # start=2 for row number
        d = {headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers))}
        d["_row_number"] = i  # 実際の行番号を保持
        rows.append(d)
    
    return rows


def update_row(sheet_name: str, row_number: int, updates: Dict[str, str]) -> None:
    """指定行の特定列を更新"""
    svc = _sheets_service()
    
    # まず現在のヘッダーを取得
    result = svc.values().get(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{sheet_name}!A1:Z1"
    ).execute()
    
    headers = result.get("values", [[]])[0]
    if not headers:
        print(f"[minutes_repo] No headers found in sheet {sheet_name}")
        return
    
    # 現在の行を取得
    current_row_result = svc.values().get(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{sheet_name}!A{row_number}:Z{row_number}"
    ).execute()
    
    current_row = current_row_result.get("values", [[]])[0] if current_row_result.get("values") else []
    
    # 現在の値をディクショナリに変換
    row_dict = {headers[i]: (current_row[i] if i < len(current_row) else "") for i in range(len(headers))}
    
    # 更新を適用
    row_dict.update(updates)
    
    # 新しい行データを作成
    new_row = [row_dict.get(h, "") for h in headers]
    
    # 更新
    svc.values().update(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{sheet_name}!A{row_number}",
        valueInputOption="RAW",
        body={"values": [new_row]}
    ).execute()
    
    print(f"[minutes_repo] Updated row {row_number} in sheet {sheet_name}")


def append_row(sheet_name: str, row_data: Dict[str, str]) -> None:
    """新しい行を追加"""
    svc = _sheets_service()
    
    # ヘッダーを取得
    result = svc.values().get(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{sheet_name}!A1:Z1"
    ).execute()
    
    headers = result.get("values", [[]])[0]
    if not headers:
        print(f"[minutes_repo] No headers found in sheet {sheet_name}")
        return
    
    # 行データを作成
    new_row = [row_data.get(h, "") for h in headers]
    
    # 追加
    svc.values().append(
        spreadsheetId=PRIMARY_SHEET_ID,
        range=f"{sheet_name}!A:Z",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [new_row]}
    ).execute()
    
    print(f"[minutes_repo] Appended new row to sheet {sheet_name}")


def now_jst() -> datetime:
    """現在のJST時刻を取得"""
    tzinfo = tz.gettz(DEFAULT_TIMEZONE)
    return datetime.now(tzinfo)


def now_jst_str() -> str:
    """現在のJST時刻を文字列で取得"""
    return now_jst().strftime("%Y-%m-%d %H:%M:%S")


def date_plus_days(date_str: str, days: int) -> str:
    """日付文字列にN日追加"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        new_dt = dt + timedelta(days=days)
        return new_dt.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"[minutes_repo] Error parsing date {date_str}: {e}")
        return date_str

