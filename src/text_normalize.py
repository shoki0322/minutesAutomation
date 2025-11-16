import re


_JAPANESE_EMOJI_ALIAS_TO_UNICODE = {
    ":電球:": "💡",
    ":メモ:": "📝",
    ":警告:": "⚠️",
    ":チェック:": "✅",
    ":チェック済み:": "✅",
    ":拍手:": "👏",
    ":目:": "👀",
    ":火:": "🔥",
    ":OK:": "🆗",
    ":下向き二重矢印:": "⏬",
    ":鉛筆_2:": "✏️",
}


def normalize_slack_shortcodes(text: str) -> str:
    """
    日本語のエイリアス表記（例: :電球:）をUnicode絵文字へ変換。
    未知のコードはそのまま残す。
    """
    if not text:
        return text
    def _replace(m: re.Match) -> str:
        token = m.group(0)
        return _JAPANESE_EMOJI_ALIAS_TO_UNICODE.get(token, token)
    # :...: を検出して置換
    return re.sub(r"(:[^:\s]{1,32}:)", _replace, text)


