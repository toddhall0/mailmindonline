import uuid
from datetime import datetime, timezone

import msal
import requests
from flask import Blueprint, redirect, request, session, flash, url_for

import config
from database import get_db
from token_crypto import encrypt_token

microsoft_auth_bp = Blueprint("microsoft_auth", __name__, url_prefix="/auth/microsoft")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _build_msal_app():
    return msal.ConfidentialClientApplication(
        client_id=config.MICROSOFT_CLIENT_ID,
        client_credential=config.MICROSOFT_CLIENT_SECRET,
        authority=config.MICROSOFT_AUTHORITY,
    )


@microsoft_auth_bp.route("/connect")
def connect():
    app = _build_msal_app()
    state = str(uuid.uuid4())
    session["ms_auth_state"] = state

    # MSAL handles offline_access automatically; only pass non-reserved scopes
    auth_scopes = [s for s in config.MICROSOFT_SCOPES if s.lower() != "offline_access"]
    auth_url = app.get_authorization_request_url(
        scopes=auth_scopes,
        state=state,
        redirect_uri=config.REDIRECT_BASE + "/auth/microsoft/callback",
    )
    return redirect(auth_url)


@microsoft_auth_bp.route("/callback")
def callback():
    # Validate state
    expected_state = session.pop("ms_auth_state", None)
    received_state = request.args.get("state")
    if not expected_state or expected_state != received_state:
        flash("Authentication failed: invalid state.", "error")
        return redirect(url_for("settings"))

    # Check for errors from Microsoft
    if "error" in request.args:
        flash(f"Authentication error: {request.args.get('error_description', request.args['error'])}", "error")
        return redirect(url_for("settings"))

    code = request.args.get("code")
    if not code:
        flash("Authentication failed: no authorization code received.", "error")
        return redirect(url_for("settings"))

    # Exchange code for tokens
    app = _build_msal_app()
    auth_scopes = [s for s in config.MICROSOFT_SCOPES if s.lower() != "offline_access"]
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=auth_scopes,
        redirect_uri=config.REDIRECT_BASE + "/auth/microsoft/callback",
    )

    if "error" in result:
        flash(f"Token error: {result.get('error_description', result['error'])}", "error")
        return redirect(url_for("settings"))

    access_token = result["access_token"]
    refresh_token = result.get("refresh_token", "")

    # Get user profile from Graph API
    headers = {"Authorization": f"Bearer {access_token}"}
    me_resp = requests.get(f"{GRAPH_BASE}/me", headers=headers, timeout=10)
    if me_resp.status_code != 200:
        flash("Failed to retrieve user profile from Microsoft Graph.", "error")
        return redirect(url_for("settings"))

    profile = me_resp.json()
    email_address = profile.get("mail") or profile.get("userPrincipalName", "")
    display_name = profile.get("displayName", "")

    # Calculate token expiry
    expires_in = result.get("expires_in", 3600)
    token_expiry = datetime.now(timezone.utc).timestamp() + expires_in

    # Save to database
    db = get_db()
    # Check if account already exists
    existing = db.execute(
        "SELECT id FROM email_accounts WHERE email_address = ? AND account_type = 'microsoft'",
        (email_address,),
    ).fetchone()

    if existing:
        db.execute(
            """UPDATE email_accounts
               SET access_token = ?, refresh_token = ?, token_expiry = ?,
                   display_name = ?, is_active = 1
               WHERE id = ?""",
            (encrypt_token(access_token), encrypt_token(refresh_token),
             token_expiry, display_name, existing["id"]),
        )
    else:
        db.execute(
            """INSERT INTO email_accounts
               (account_type, email_address, display_name, access_token,
                refresh_token, token_expiry, is_active)
               VALUES ('microsoft', ?, ?, ?, ?, ?, 1)""",
            (email_address, display_name, encrypt_token(access_token),
             encrypt_token(refresh_token), token_expiry),
        )

    db.commit()
    db.close()

    flash(f"Microsoft account {email_address} connected successfully!", "success")
    return redirect(url_for("settings"))


@microsoft_auth_bp.route("/disconnect/<int:account_id>", methods=["POST"])
def disconnect(account_id):
    db = get_db()
    db.execute("DELETE FROM email_accounts WHERE id = ? AND account_type = 'microsoft'", (account_id,))
    db.commit()
    db.close()
    flash("Microsoft account disconnected.", "success")
    return redirect(url_for("settings"))
