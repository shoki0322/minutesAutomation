import os
import sys
from typing import Optional
from .slack_client import SlackClient

def main():
    # Args: [channel] [message]
    channel: Optional[str] = None
    text: Optional[str] = None
    if len(sys.argv) > 1 and sys.argv[1] not in (None, "", "None"):
        channel = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] not in (None, "", "None"):
        text = sys.argv[2]
    if not channel:
        channel = os.getenv("TEST_CHANNEL_ID") or os.getenv("DEFAULT_CHANNEL_ID")
    if not text:
        text = "[Test] AI Meeting Autopilot: Slack connection check"
    if not channel:
        print("[test_slack] No channel specified. Pass as arg or set TEST_CHANNEL_ID/DEFAULT_CHANNEL_ID in env.")
        return
    sc = SlackClient()
    ts = sc.post_message(channel=channel, text=text)
    print(f"[test_slack] result ts={ts}")

if __name__ == "__main__":
    main()

