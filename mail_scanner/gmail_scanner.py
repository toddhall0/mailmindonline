import base64
import json
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import config
from database import get_db
from token_crypto import decrypt_token, encrypt_token

GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _build_credentials(account):
    """Build Google credentials from stored tokens, refreshing if needed."""
    access_token = decrypt_token(account["access_token"])
    refresh_token = decrypt_token(account["refresh_token"])
    token_expiry = account["token_expiry"] or 0

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=GMAIL_TOKEN_URI,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
    )

    now = datetime.now(timezone.utc).timestamp()
    if now >= token_expiry - 300:
        creds.refresh(Request())

        # Update stored tokens
        db = get_db()
        new_expiry = creds.expiry.timestamp() if creds.expiry else now + 3600
        db.execute(
            """UPDATE email_accounts
               SET access_token = ?, refresh_token = ?, token_expiry = ?
               WHERE id = ?""",
            (encrypt_token(creds.token),
             encrypt_token(creds.refresh_token or refresh_token),
             new_expiry, account["id"]),
        )
        db.commit()
        db.close()

    return creds


def _extract_header(headers, name):
    """Extract a header value from Gmail message headers."""
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _extract_body(payload):
    """Extract plain text body from Gmail message payload."""
    # Direct body
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart: look for text/plain first
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    # Fallback: try text/html
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    return ""


def scan_gmail_account(account_id):
    """Scan a Gmail account for new messages."""
    db = get_db()
    account = db.execute(
        "SELECT * FROM email_accounts WHERE id = ? AND account_type = 'google'",
        (account_id,),
    ).fetchone()

    if not account:
        db.close()
        return

    try:
        creds = _build_credentials(account)
    except Exception as e:
        print(f"[gmail_scanner] Failed to build credentials for account {account_id}: {e}")
        db.close()
        return

    service = build("gmail", "v1", credentials=creds)

    labels_to_scan = json.loads(account["folders_to_scan"] or '["INBOX"]')
    last_scan_at = account["last_scan_at"]

    new_count = 0

    for label in labels_to_scan:
        # Build query
        query = ""
        if last_scan_at:
            # Convert ISO timestamp to unix for Gmail query
            try:
                dt = datetime.fromisoformat(last_scan_at.replace("Z", "+00:00"))
                query = f"after:{int(dt.timestamp())}"
            except (ValueError, TypeError):
                pass

        try:
            results = service.users().messages().list(
                userId="me",
                labelIds=[label],
                q=query or None,
                maxResults=50,
            ).execute()
        except Exception as e:
            print(f"[gmail_scanner] Failed to list messages for label '{label}': {e}")
            continue

        messages = results.get("messages", [])

        for msg_ref in messages:
            message_id = msg_ref["id"]

            # Skip if already scanned
            existing = db.execute(
                "SELECT id FROM scanned_emails WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if existing:
                continue

            # Fetch full message
            try:
                msg = service.users().messages().get(
                    userId="me", id=message_id, format="full"
                ).execute()
            except Exception as e:
                print(f"[gmail_scanner] Failed to fetch message {message_id}: {e}")
                continue

            headers = msg.get("payload", {}).get("headers", [])
            subject = _extract_header(headers, "Subject")
            sender = _extract_header(headers, "From")
            date_str = _extract_header(headers, "Date")
            thread_id = msg.get("threadId", "")

            # Convert internal date (ms since epoch)
            internal_date = msg.get("internalDate", "0")
            received_at = datetime.fromtimestamp(
                int(internal_date) / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            db.execute(
                """INSERT INTO scanned_emails
                   (message_id, account_id, subject, sender, received_at,
                    thread_id, was_processed)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (message_id, account_id, subject, sender, received_at,
                 thread_id),
            )
            new_count += 1

    # Update last_scan_at
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        "UPDATE email_accounts SET last_scan_at = ? WHERE id = ?",
        (now_iso, account_id),
    )
    db.commit()
    db.close()

    print(f"[gmail_scanner] Scanned account {account_id}: {new_count} new emails found")
    return new_count


def get_gmail_labels(account_id):
    """Fetch the list of Gmail labels for an account."""
    db = get_db()
    account = db.execute(
        "SELECT * FROM email_accounts WHERE id = ? AND account_type = 'google'",
        (account_id,),
    ).fetchone()
    db.close()

    if not account:
        return []

    try:
        creds = _build_credentials(account)
    except Exception:
        return []

    service = build("gmail", "v1", credentials=creds)

    try:
        results = service.users().labels().list(userId="me").execute()
    except Exception:
        return []

    return [
        {"id": label["id"], "name": label["name"], "type": label.get("type", "")}
        for label in results.get("labels", [])
    ]
