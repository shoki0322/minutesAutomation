import re
from typing import Tuple


# ヘッダー定義（詳細・参照資料系）
DETAIL_HEADERS = [
    "_:detail: 決定事項の詳細_",
    "_:shosai: 決定事項の詳細_",
]

ATTACHMENT_HEADERS = [
    "添付ファイル",
    "参照資料",
    "_:sankou:",
    "_:sankou_link:",
]


def split_main_and_thread(text: str) -> Tuple[str, str]:
    """
    指定ヘッダー行(DETAIL_HEADERS)以降をスレッド投稿に回し、それ以前を親メッセージとする。
    - 詳細ヘッダー直前の境界線（例: "━━━━━━━━━━" 等）が存在する場合は、境界線もスレッド側に含める。
    - 該当ヘッダーがなければ全体を親メッセージとして返し、スレッドは空文字。
    """
    lines = text.splitlines()
    idx = None

    # 1) 詳細ヘッダーを最優先で検出
    for i, line in enumerate(lines):
        if any(h in line for h in DETAIL_HEADERS):
            idx = i
            break

    # 2) キーワードフォールバック（詳細）
    if idx is None:
        for i, line in enumerate(lines):
            if "決定事項の詳細" in line:
                idx = i
                break

    # 3) 参照資料/添付系ヘッダー
    if idx is None:
        for i, line in enumerate(lines):
            if any(h in line for h in ATTACHMENT_HEADERS):
                idx = i
                break

    # 4) 最終フォールバック（語ベース）
    if idx is None:
        for i, line in enumerate(lines):
            if "参照資料" in line or "添付ファイル" in line:
                idx = i
                break

    if idx is None:
        return text, ""

    # 境界線が直前にあれば、そこからスレッド側に含める
    start_idx = idx

    def _is_border(line: str) -> bool:
        s = line.strip()
        if len(s) < 5:
            return False
        return re.match(r"^[━─—－ー＝=_~\-]{5,}$", s) is not None

    if idx > 0 and _is_border(lines[idx - 1]):
        start_idx = idx - 1

    main_part = "\n".join(lines[:start_idx]).rstrip()
    thread_part = "\n".join(lines[start_idx:]).lstrip("\n")
    return main_part, thread_part


