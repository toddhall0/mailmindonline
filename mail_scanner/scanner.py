from database import get_db
from mail_scanner.microsoft_scanner import scan_microsoft_account
from mail_scanner.gmail_scanner import scan_gmail_account


def process_email(email_id):
    """Placeholder – Claude AI processing will be implemented in Phase 4."""
    pass


def scan_all_accounts():
    """Scan all active email accounts and process new emails."""
    db = get_db()
    accounts = db.execute(
        "SELECT id, account_type FROM email_accounts WHERE is_active = 1"
    ).fetchall()
    db.close()

    for account in accounts:
        if account["account_type"] == "microsoft":
            scan_microsoft_account(account["id"])
        elif account["account_type"] == "google":
            scan_gmail_account(account["id"])

    # Process any unprocessed emails
    db = get_db()
    unprocessed = db.execute(
        "SELECT id FROM scanned_emails WHERE was_processed = 0"
    ).fetchall()
    db.close()

    for email_row in unprocessed:
        process_email(email_row["id"])
