import json

from flask import Flask, render_template, flash, jsonify, request, Blueprint
from apscheduler.schedulers.background import BackgroundScheduler

import config
from database import init_db, get_db
from auth.microsoft import microsoft_auth_bp
from mail_scanner.microsoft_scanner import get_microsoft_folders
from mail_scanner.scanner import scan_all_accounts

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
init_db()

# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------
app.register_blueprint(microsoft_auth_bp)

# Placeholder for future Google auth
google_auth_bp = Blueprint("google_auth", __name__, url_prefix="/auth/google")
app.register_blueprint(google_auth_bp)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def tasks():
    db = get_db()
    task_list = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template("tasks.html", tasks=task_list)


@app.route("/settings")
def settings():
    db = get_db()
    accounts = db.execute("SELECT * FROM email_accounts WHERE is_active = 1").fetchall()
    db.close()
    ms_accounts = [a for a in accounts if a["account_type"] == "microsoft"]
    google_accounts = [a for a in accounts if a["account_type"] == "google"]
    return render_template("settings.html", ms_accounts=ms_accounts, google_accounts=google_accounts)


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/api/microsoft/folders/<int:account_id>")
def microsoft_folders(account_id):
    folders = get_microsoft_folders(account_id)
    return jsonify(folders)


@app.route("/api/microsoft/folders/<int:account_id>/save", methods=["POST"])
def save_microsoft_folders(account_id):
    data = request.get_json()
    folders = data.get("folders", ["Inbox"])
    db = get_db()
    db.execute(
        "UPDATE email_accounts SET folders_to_scan = ? WHERE id = ? AND account_type = 'microsoft'",
        (json.dumps(folders), account_id),
    )
    db.commit()
    db.close()
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        scan_all_accounts,
        "interval",
        minutes=config.SCAN_INTERVAL_MINUTES,
        id="email_scan",
    )
    scheduler.start()

    app.run(debug=True, port=8080)
