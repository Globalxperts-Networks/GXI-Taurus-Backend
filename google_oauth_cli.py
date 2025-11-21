#!/usr/bin/env python3
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

CLIENT_SECRET_FILE = "credentials/client_secret.json"
TOKEN_FILE = "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def generate_token():
    creds = None

    # Load existing token if exists
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                creds = Credentials.from_authorized_user_info(data, SCOPES)
        except Exception as e:
            print("⚠️ Existing token invalid, creating new one:", e)
            creds = None

    # If no valid token → create new
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("🌐 Opening browser for Google login...")

            # Must be Desktop OAuth (installed)
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE,
                SCOPES
            )

            # Use built-in local server (Google recommended)
            creds = flow.run_local_server(
                port=0,                   # auto-free port
                prompt="consent",
                authorization_prompt_message="Please authorize Google Calendar access"
            )

        # Save token
        print("💾 Saving token to google_token.json...")
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    print("✅ Google OAuth completed successfully!")
    print("👉 You can now run schedule_interview.py")
    return creds


if __name__ == "__main__":
    print("🚀 Google OAuth CLI Started")
    generate_token()
    print("🎉 Done.")
