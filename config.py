import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
MICROSOFT_TENANT = os.getenv("MICROSOFT_TENANT", "common")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "5"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "mailmind.db")

MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/" + MICROSOFT_TENANT
MICROSOFT_SCOPES = ["Mail.Read", "offline_access", "User.Read"]
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT_BASE = "http://localhost:8080"
