import uuid
from datetime import datetime, timezone

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from flask import Blueprint, redirect, request, session, flash, url_for

import config
from database import get_db
from token_crypto import encrypt_token

google_auth_bp = Blueprint("google_auth", __name__, url_prefix="/auth/google")

REDIRECT_URI = config.REDIRECT_BASE + "/auth/google/callback"


def _build_flow():
    client_config = {
        "web": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=config.GOOGLE_SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return flow


@google_auth_bp.route("/connect")
def connect():
    flow = _build_flow()
    state = str(uuid.uuid4())
    session["google_auth_state"] = state

    auth_url, _ = flow.authorization_url(
        state=state,
        access_type="offline",
        prompt="consent",
    )
    return redirect(auth_url)


@google_auth_bp.route("/callback")
def callback():
    # Validate state
    expected_state = session.pop("google_auth_state", None)
    received_state = request.args.get("state")
    if not expected_state or expected_state != received_state:
        flash("Authentication failed: invalid state.", "error")
        return redirect(url_for("settings"))

    # Check for errors
    if "error" in request.args:
        flash(f"Authentication error: {request.args['error']}", "error")
        return redirect(url_for("settings"))

    code = request.args.get("code")
    if not code:
        flash("Authentication failed: no authorization code received.", "error")
        return redirect(url_for("settings"))

    # Exchange code for credentials
    flow = _build_flow()
    flow.fetch_token(code=code)
    credentials = flow.credentials

    access_token = credentials.token
    refresh_token = credentials.refresh_token or ""

    # Get user profile via Gmail API
    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute()
    email_address = profile.get("emailAddress", "")

    # Calculate token expiry
    if credentials.expiry:
        token_expiry = credentials.expiry.timestamp()
    else:
        token_expiry = datetime.now(timezone.utc).timestamp() + 3600

    # Save to database
    db = get_db()
    existing = db.execute(
        "SELECT id FROM email_accounts WHERE email_address = ? AND account_type = 'google'",
        (email_address,),
    ).fetchone()

    if existing:
        db.execute(
            """UPDATE email_accounts
               SET access_token = ?, refresh_token = ?, token_expiry = ?,
                   is_active = 1
               WHERE id = ?""",
            (encrypt_token(access_token), encrypt_token(refresh_token),
             token_expiry, existing["id"]),
        )
    else:
        db.execute(
            """INSERT INTO email_accounts
               (account_type, email_address, display_name, access_token,
                refresh_token, token_expiry, is_active, folders_to_scan)
               VALUES ('google', ?, ?, ?, ?, ?, 1, '["INBOX"]')""",
            (email_address, email_address, encrypt_token(access_token),
             encrypt_token(refresh_token), token_expiry),
        )

    db.commit()
    db.close()

    flash(f"Gmail account {email_address} connected successfully!", "success")
    return redirect(url_for("settings"))


@google_auth_bp.route("/disconnect/<int:account_id>", methods=["POST"])
def disconnect(account_id):
    db = get_db()
    db.execute("DELETE FROM email_accounts WHERE id = ? AND account_type = 'google'", (account_id,))
    db.commit()
    db.close()
    flash("Gmail account disconnected.", "success")
    return redirect(url_for("settings"))
