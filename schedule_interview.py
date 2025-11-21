import os
import json
import uuid
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request


# =====================================================
# 🔹 CONFIGURATION (EDIT THESE VALUES ONLY)
# =====================================================

# ---- HR Google Account OAuth Token (from DB or file) ----
GOOGLE_TOKEN_FILE = "google_token.json"         # This contains HR's OAuth token
GOOGLE_CLIENT_SECRET = "credentials/client_secret.json"

# ---- HR SMTP Email Credentials ----
HR_EMAIL = "shubhsingh1515@gmail.com"                  # HR Gmail
HR_APP_PASSWORD = "kfze xwml vrzn wwal"           # 16-digit app password

# ---- Candidate Details ----
CANDIDATE_EMAIL = "vandanaiec3093@gmail.com"
CANDIDATE_NAME = "Vandana Prakash"

# ---- CC Emails ----
CC_EMAILS = ["vinod.sharma@gxinetworks.com", "vandanaprakash.3093@gmail.com"]

# ---- Interview Schedule ----
INTERVIEW_DATE = "2025-03-12"
START_TIME = "10:00"
END_TIME = "10:30"

TIMEZONE = "Asia/Kolkata"



# =====================================================
# 🔹 LOAD GOOGLE CREDENTIALS
# =====================================================

def load_google_credentials():
    if not os.path.exists(GOOGLE_TOKEN_FILE):
        raise Exception("Google OAuth token file not found. Run OAuth login first.")

    with open(GOOGLE_TOKEN_FILE, "r") as f:
        data = json.load(f)

    creds = Credentials.from_authorized_user_info(data)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save new token
        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds



# =====================================================
# 🔹 CREATE GOOGLE MEET LINK (Calendar API)
# =====================================================

def create_meet_link():
    print("📅 Creating Google Meet event...")

    creds = load_google_credentials()
    service = build("calendar", "v3", credentials=creds)

    start_dt = datetime.strptime(f"{INTERVIEW_DATE} {START_TIME}", "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(f"{INTERVIEW_DATE} {END_TIME}", "%Y-%m-%d %H:%M")

    event = {
        "summary": f"Interview - {CANDIDATE_NAME}",
        "description": "Interview Meeting",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
        "attendees": [{"email": CANDIDATE_EMAIL}] + [{"email": x} for x in CC_EMAILS],
        "conferenceData": {
            "createRequest": {
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
                "requestId": f"gxihiring-{uuid.uuid4()}"
            }
        }
    }

    created_event = service.events().insert(
        calendarId="primary",
        body=event,
        conferenceDataVersion=1
    ).execute()

    meet_link = created_event.get("hangoutLink")
    print("✅ Meet link created:", meet_link)

    return meet_link



# =====================================================
# 🔹 SEND EMAIL WITH MEET LINK
# =====================================================

def send_email(meet_link):
    print("📤 Sending email to candidate...")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Interview Scheduled for {CANDIDATE_NAME}"
    msg["From"] = HR_EMAIL
    msg["To"] = CANDIDATE_EMAIL
    msg["Cc"] = ", ".join(CC_EMAILS)

    recipients = [CANDIDATE_EMAIL] + CC_EMAILS

    html_body = f"""
        <p>Dear {CANDIDATE_NAME},</p>
        <p>Your interview has been scheduled.</p>
        <p><strong>Date:</strong> {INTERVIEW_DATE}</p>
        <p><strong>Time:</strong> {START_TIME} - {END_TIME}</p>
        <p><strong>Google Meet Link:</strong> <a href="{meet_link}">{meet_link}</a></p>
        <br>
        <p>Regards,<br>HR Team</p>
    """

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(HR_EMAIL, HR_APP_PASSWORD)
        server.sendmail(HR_EMAIL, recipients, msg.as_string())

    print("✅ Email sent successfully!")



# =====================================================
# 🔹 MAIN FUNCTION
# =====================================================

if __name__ == "__main__":
    print("🚀 Running Interview Scheduler Script")

    try:
        meet_link = create_meet_link()
        send_email(meet_link)

    except Exception as e:
        print("❌ Error:", e)

    print("🎉 Script completed!")