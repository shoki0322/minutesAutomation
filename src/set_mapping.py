import sys
from .sheets_repo import save_email_slack_mapping

def main():
    if len(sys.argv) < 3:
        print("Usage: python -m src.set_mapping <email> <slack_user_id> [display_name]")
        return
    email = sys.argv[1].strip().lower()
    slack_id = sys.argv[2].strip()
    display = sys.argv[3] if len(sys.argv) >= 4 else ""
    save_email_slack_mapping(email, slack_id, display)
    print(f"[set_mapping] mapped {email} -> {slack_id} ({display})")

if __name__ == "__main__":
    main()

