from flask import Flask, render_template, flash, Blueprint
from apscheduler.schedulers.background import BackgroundScheduler
import config
from database import init_db, get_db

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ---------------------------------------------------------------------------
# Blueprint placeholders
# ---------------------------------------------------------------------------
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
email_bp = Blueprint("email", __name__, url_prefix="/email")

app.register_blueprint(auth_bp)
app.register_blueprint(email_bp)

# ---------------------------------------------------------------------------
# Placeholder scan function
# ---------------------------------------------------------------------------

def scan_emails():
    """Placeholder – will be implemented in a later phase."""
    pass

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

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        scan_emails,
        "interval",
        minutes=config.SCAN_INTERVAL_MINUTES,
        id="email_scan",
    )
    scheduler.start()

    app.run(debug=True, port=5000)
