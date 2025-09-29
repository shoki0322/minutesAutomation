全体スケジュール（JST）

会議当日 16:00 … 議事録取り込み → タスク抽出 → Slack 親投稿（振り返り）

会議 2 日前 10:00 … ヒアリング投下（人別@で同スレ）

毎朝 09:00 … スレ返信収集 → スプシ保存 → 未返信者へやさしく催促

会議前日 16:00 … 合体アジェンダ生成 → Slack 最終投稿

0. 前提（Secrets/固定値）

GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN

SLACK_BOT_TOKEN

DEFAULT_TIMEZONE=Asia/Tokyo

（任意）PRIMARY_SHEET_ID, DEFAULT_CHANNEL_ID, MEETING_KEY（例: AI 基盤 MTG）

1. 会議当日 16:00 JST（after_meeting_ingest）
   目的

Drive から対象 Docs を自動で特定し、本文を取得して Sheets に永続化

議事録本文からタスク（actions）抽出し items に登録

Slack に親投稿（振り返り）を流し、その TS を保存

手順（処理の粒度）

Drive→Docs 特定（docs_ingest.py）

入力：

MEETING_KEY（例「AI 基盤 MTG」）

日付（今日）

Docs の保存フォルダ（固定名やフォルダ ID で検索）

処理：

Drive API でフォルダ内ファイルを更新日降順で探索

タイトル or パスに MEETING_KEY ＋日付パターン一致の Docs を最新 1 件特定

Docs API で本文テキスト抽出（段落要素を連結・改行最小）

meeting_id=doc_id, title, date, doc_id を meetings に upsert

既にあれば上書き（idempotent）

元テキストは必要に応じて別シート or Drive にアーカイブ

出力：

meetings に 1 行（meeting_id, meeting_key, date, title, doc_id）

参加者名寄せ（任意・calendar_participants.py）

カレンダーから attendees.email[] を取得 → mappings と突き合わせ

不足は users.lookupByEmail で Slack ID を補完し mappings を更新

meetings.participant_emails に格納

アクション抽出 → items 追記（action_extract.py）

入力：議事録本文

処理：Gemini で JSON 抽出 → [{task, assignee_email, due(YYYY-MM-DD|null), links[]}]

正規化：

assignee_email から assignee_slack_id を mappings で引く（なければ lookup→ 保存）

dedupe_key = {date}:{assignee_email}:{hash(task)} を生成

出力：items に idempotent upsert（status=pending 初期値）

Slack 親投稿（振り返り）（post_retrospective.py）

入力：items を人別に集約

投稿先：mappings.meeting_key → channel_id（無ければ DEFAULT_CHANNEL_ID）

本文（例）：

今週の振り返り & NextAction

- <@Uxxx> : Task A (due: 2025-09-30)
- <@Uyyy> : Task B (due: …)

出力：

Slack レスポンス ts を meetings.parent_ts に保存

slack_posts（任意）にも記録

2. 会議 2 日前 10:00 JST（two_days_before_hearing）
   目的

親スレに人別@ヒアリングテンプレを自動で投下し、トラッキング

手順

人別スレ投稿（post_hearing.py）

入力：meetings.parent_ts, participant_emails → slack_ids

本文テンプレ：

<@Uxxx> 今回のヒアリング

1. 前回 ToDo の状況
2. 今回の報告（1〜3 点）
3. ブロッカー/依頼
4. リンク

出力：

hearing_prompts に 1 行/人（meeting_id, channel_id, parent_ts, assignee_slack_id, prompt_ts, due_to_reply）

3. 毎朝 09:00 JST（daily_sweep）
   目的

スレッドの返信を全収集 →4 項目にパース →Sheets 保存

未返信者にやさしく催促

手順

スレ収集（collect_replies.py）

入力：meetings.parent_ts（最近 N 件でも可）

処理：conversations.replies を取得 → User 毎に直近の本人返信を抽出

パース： 1. 2. の番号付き、箇条書き、コロン区切り等にロバスト

4 項目 todo_status / reports / blockers / links に正規化

出力：hearing_responses へ upsert（meeting_id + user + reply_ts）

未返信者抽出 → 催促（同スレ or DM）

hearing_prompts.sent − hearing_responses.user の差集合

ヒアリング期限超過なら軽めのメンションリマインド

4. 会議前日 16:00 JST（day_before_agenda）
   目的

前回議事録（未決タスク）× 今週の報告 を一本化して読めるアジェンダに整形

Slack に最終投稿

手順

統合素材作成（build_agenda.py）

未決タスク：items から status≠done 抽出 → 期限/担当でソート

人別ハイライト：hearing_responses を 1–2 行で要約

ブロッカー/依頼：一覧化

Top3 自動抽出：期限の近さ＋ブロッカー重み＋件数でスコアリング

出力：agendas.body_md（Markdown）に保存

最終アジェンダ投稿（post_agenda.py）

投稿先：親（新規）またはスレ先頭（運用方針）

出力：agendas.posted_ts を記録
