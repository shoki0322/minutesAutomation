"""
ヒアリング回答収集スクリプト
Slackスレッドから回答を収集し、シートのhearing_responses01-04に格納
締切：next_meeting_dateの1日前09:00、時間が早い順に最大4件
"""
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from .slack_client import SlackClient
from .minutes_repo import (
    get_all_sheet_names,
    read_sheet_rows,
    update_row,
    now_jst,
    now_jst_str,
)

DEFAULT_CHANNEL_ID = os.getenv("DEFAULT_CHANNEL_ID")


def should_collect_responses(next_meeting_date_str: str) -> bool:
    """
    ヒアリング回答を収集すべきかどうか判定
    next_meeting_dateの1日前09:00に実行される想定
    現在時刻が1日前の09:00~10:00の範囲内ならTrue
    """
    if not next_meeting_date_str:
        return False
    
    try:
        # next_meeting_dateをパース
        meeting_date = datetime.strptime(next_meeting_date_str, "%Y-%m-%d")
        
        # 1日前
        target_date = meeting_date - timedelta(days=1)
        
        # 現在のJST時刻
        now = now_jst()
        
        # 同じ日付で、09:00~10:00の間
        if now.date() == target_date.date() and 9 <= now.hour < 10:
            return True
        
        return False
    
    except Exception as e:
        print(f"[collect_hearing_responses] Error parsing date {next_meeting_date_str}: {e}")
        return False


def parse_slack_timestamp(ts: str) -> float:
    """Slack timestamp (e.g., "1234567890.123456") を floatに変換"""
    try:
        return float(ts)
    except Exception:
        return 0.0


def collect_thread_responses(slack_client: SlackClient, channel_id: str, thread_ts: str) -> List[str]:
    """
    Slackスレッドから返信を収集
    最初の投稿（親メッセージ）とヒアリング依頼メッセージを除く、時間順で最大4件を返す
    """
    replies = slack_client.fetch_thread_replies(channel_id, thread_ts)
    
    if not replies:
        return []
    
    # 親メッセージを除外（thread_tsと同じtsのもの）
    responses = [r for r in replies if r.get("ts") != thread_ts]
    
    # ヒアリング依頼メッセージを除外（「次回会議のヒアリング項目」で始まるもの）
    responses = [r for r in responses if not r.get("text", "").startswith("次回会議のヒアリング項目")]
    
    # 時間順でソート
    responses.sort(key=lambda r: parse_slack_timestamp(r.get("ts", "0")))
    
    # 最大4件
    top_responses = responses[:4]
    
    # テキストのみ抽出
    texts = [r.get("text", "") for r in top_responses]
    
    return texts


def collect_responses_for_sheet(sheet_name: str, slack_client: SlackClient):
    """1つのシートに対してヒアリング回答収集を実行"""
    print(f"[collect_hearing_responses] Checking sheet: {sheet_name}")
    
    rows = read_sheet_rows(sheet_name)
    
    for row in rows:
        next_meeting_date = row.get("next_meeting_date", "").strip()
        hearing_thread_ts = row.get("hearing_thread_ts", "").strip()
        
        # hearing_thread_tsがない場合はスキップ
        if not hearing_thread_ts:
            continue
        
        # 収集すべきか判定
        if not should_collect_responses(next_meeting_date):
            continue
        
        # 既に収集済みかチェック（hearing_responses01が既に入っていたらスキップ）
        # ※運用に応じて調整（毎回上書きする場合はこのチェックを外す）
        if row.get("hearing_responses01", "").strip():
            print(f"[collect_hearing_responses] Already collected for: {row.get('title')}")
            continue
        
        # チャンネルID取得
        channel_id = row.get("channel_id", "").strip() or DEFAULT_CHANNEL_ID
        if not channel_id:
            print(f"[collect_hearing_responses] No channel_id for: {row.get('title')}")
            continue
        
        title = row.get("title", "無題")
        
        # スレッドから回答を収集
        print(f"[collect_hearing_responses] Collecting responses for: {title}")
        responses = collect_thread_responses(slack_client, channel_id, hearing_thread_ts)
        
        if not responses:
            print(f"[collect_hearing_responses] No responses found for: {title}")
            continue
        
        # シートに格納
        updates = {
            "updated_at": now_jst_str(),
        }
        
        for i, response_text in enumerate(responses, start=1):
            col_name = f"hearing_responses{i:02d}"
            updates[col_name] = response_text
        
        row_number = row.get("_row_number")
        if row_number:
            update_row(sheet_name, row_number, updates)
            print(f"[collect_hearing_responses] Collected {len(responses)} responses and updated row {row_number}")


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
            collect_responses_for_sheet(sheet_name, slack_client)
        except Exception as e:
            print(f"[collect_hearing_responses] Error processing sheet {sheet_name}: {e}")
            continue


if __name__ == "__main__":
    main()

