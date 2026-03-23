import json
from datetime import datetime, timezone

import msal
import requests

import config
from database import get_db
from token_crypto import decrypt_token, encrypt_token

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _refresh_token_if_needed(account):
    """Check token expiry and refresh if needed. Returns a valid access token."""
    token_expiry = account["token_expiry"] or 0
    now = datetime.now(timezone.utc).timestamp()

    access_token = decrypt_token(account["access_token"])

    # Refresh if token expires within 5 minutes
    if now >= token_expiry - 300:
        refresh_token = decrypt_token(account["refresh_token"])
        app = msal.ConfidentialClientApplication(
            client_id=config.MICROSOFT_CLIENT_ID,
            client_credential=config.MICROSOFT_CLIENT_SECRET,
            authority=config.MICROSOFT_AUTHORITY,
        )

        result = app.acquire_token_by_refresh_token(
            refresh_token, scopes=config.MICROSOFT_SCOPES
        )

        if "error" in result:
            raise RuntimeError(
                f"Token refresh failed for account {account['id']}: "
                f"{result.get('error_description', result['error'])}"
            )

        access_token = result["access_token"]
        new_refresh = result.get("refresh_token", refresh_token)
        new_expiry = now + result.get("expires_in", 3600)

        db = get_db()
        db.execute(
            """UPDATE email_accounts
               SET access_token = ?, refresh_token = ?, token_expiry = ?
               WHERE id = ?""",
            (encrypt_token(access_token), encrypt_token(new_refresh),
             new_expiry, account["id"]),
        )
        db.commit()
        db.close()

    return access_token


def _get_folder_id_by_name(access_token, folder_name):
    """Resolve a folder display name to its Graph API id."""
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(
        f"{GRAPH_BASE}/me/mailFolders",
        headers=headers,
        params={"$top": "100"},
        timeout=15,
    )
    if resp.status_code != 200:
        return None

    for folder in resp.json().get("value", []):
        if folder["displayName"].lower() == folder_name.lower():
            return folder["id"]
    return None


def scan_microsoft_account(account_id):
    """Scan a Microsoft email account for new messages."""
    db = get_db()
    account = db.execute(
        "SELECT * FROM email_accounts WHERE id = ? AND account_type = 'microsoft'",
        (account_id,),
    ).fetchone()

    if not account:
        db.close()
        return

    try:
        access_token = _refresh_token_if_needed(account)
    except RuntimeError as e:
        print(f"[scanner] {e}")
        db.close()
        return

    headers = {"Authorization": f"Bearer {access_token}"}

    # Determine folders to scan
    folders_to_scan = json.loads(account["folders_to_scan"] or '["Inbox"]')
    last_scan_at = account["last_scan_at"]

    new_count = 0

    for folder_name in folders_to_scan:
        folder_id = _get_folder_id_by_name(access_token, folder_name)
        if not folder_id:
            print(f"[scanner] Folder '{folder_name}' not found for account {account_id}")
            continue

        # Build query params
        params = {
            "$select": "id,subject,from,receivedDateTime,conversationId,body",
            "$orderby": "receivedDateTime desc",
            "$top": "50",
        }
        if last_scan_at:
            params["$filter"] = f"receivedDateTime ge {last_scan_at}"

        resp = requests.get(
            f"{GRAPH_BASE}/me/mailFolders/{folder_id}/messages",
            headers=headers,
            params=params,
            timeout=30,
        )

        if resp.status_code != 200:
            print(f"[scanner] Failed to fetch messages from '{folder_name}': {resp.status_code}")
            continue

        messages = resp.json().get("value", [])

        for msg in messages:
            message_id = msg["id"]

            # Skip if already scanned
            existing = db.execute(
                "SELECT id FROM scanned_emails WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if existing:
                continue

            sender_info = msg.get("from", {}).get("emailAddress", {})
            sender = sender_info.get("address", "")

            db.execute(
                """INSERT INTO scanned_emails
                   (message_id, account_id, subject, sender, received_at,
                    thread_id, was_processed)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    message_id,
                    account_id,
                    msg.get("subject", ""),
                    sender,
                    msg.get("receivedDateTime", ""),
                    msg.get("conversationId", ""),
                ),
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

    print(f"[scanner] Scanned account {account_id}: {new_count} new emails found")
    return new_count


def get_microsoft_folders(account_id):
    """Fetch the list of mail folders for a Microsoft account."""
    db = get_db()
    account = db.execute(
        "SELECT * FROM email_accounts WHERE id = ? AND account_type = 'microsoft'",
        (account_id,),
    ).fetchone()
    db.close()

    if not account:
        return []

    try:
        access_token = _refresh_token_if_needed(account)
    except RuntimeError:
        return []

    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(
        f"{GRAPH_BASE}/me/mailFolders",
        headers=headers,
        params={"$top": "100"},
        timeout=15,
    )

    if resp.status_code != 200:
        return []

    return [
        {"id": f["id"], "displayName": f["displayName"],
         "totalItemCount": f.get("totalItemCount", 0)}
        for f in resp.json().get("value", [])
    ]
