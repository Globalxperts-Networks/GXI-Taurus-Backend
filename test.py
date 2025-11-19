import os
import sys
import argparse
import requests
import json
import smtplib
from email.message import EmailMessage
from typing import List, Optional

# ----------------------
# Config (from env)
# ----------------------
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "b6bc0503-84d4-4cab-9502-058795a1a3ce")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "bb5aa073-9901-4f94-8935-dc3aa37b5855")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "pXW8Q~NBTAUAaMRy9TH52LNv_TX1AuxADDyWLbDO")  # must set securely

GRAPH_TOKEN_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = "noreply@gxinetworks.com"
SMTP_PASSWORD ="August@082024"

DEFAULT_FROM = SMTP_USER or "noreply@example.com"

# ----------------------
# Defaults (user provided)
# ----------------------
DEFAULT_TO = ["jaijhavats32@gmail.com"]
DEFAULT_CC = ["jaijhavats95@gmail.com"]
DEFAULT_SUBJECT = "Meeting for Python"

# ----------------------
# Helpers
# ----------------------
def get_app_token() -> str:
    if not AZURE_CLIENT_SECRET:
        raise RuntimeError("AZURE_CLIENT_SECRET is not set in environment. Set it before running.")
    data = {
        "client_id": AZURE_CLIENT_ID,
        "client_secret": AZURE_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    r = requests.post(GRAPH_TOKEN_URL, data=data, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Token request failed ({r.status_code}): {r.text}")
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in token response: {r.text}")
    return token

def get_user_object_id_by_upn(token: str, upn: str) -> Optional[str]:
    """
    Lookup user object id from UPN (email). Returns objectId or None.
    """
    url = f"{GRAPH_BASE}/users/{upn}"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200:
        return r.json().get("id")
    # return None and log message
    print(f"Warning: unable to lookup user {upn}. Status: {r.status_code}. Body: {r.text}", file=sys.stderr)
    return None

def create_online_meeting(token: str, user_object_id: str, subject: str, start: str, end: str) -> dict:
    url = f"{GRAPH_BASE}/users/{user_object_id}/onlineMeetings"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"startDateTime": start, "endDateTime": end, "subject": subject}
    r = requests.post(url, headers=headers, json=body, timeout=20)
    if r.status_code not in (200, 201):
        # surface Graph error
        raise RuntimeError(f"create_online_meeting failed ({r.status_code}): {r.text}")
    return r.json()

def create_calendar_event(token: str, organizer_upn: str, subject: str, start: str, end: str, attendees: List[str]) -> dict:
    url = f"{GRAPH_BASE}/users/{organizer_upn}/events"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    attendees_payload = []
    for a in attendees:
        if a:
            attendees_payload.append({"emailAddress": {"address": a, "name": ""}, "type": "required"})
    body = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness",
        "attendees": attendees_payload,
    }
    r = requests.post(url, headers=headers, json=body, timeout=20)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create_calendar_event failed ({r.status_code}): {r.text}")
    return r.json()

def extract_join_url(resp: dict) -> Optional[str]:
    if not isinstance(resp, dict):
        return None
    # common fields
    for key in ("joinWebUrl", "joinUrl", "onlineMeetingUrl"):
        if resp.get(key):
            return resp.get(key)
    om = resp.get("onlineMeeting")
    if isinstance(om, dict):
        return om.get("joinUrl") or om.get("joinWebUrl")
    return None

def send_email(smtp_user: str, smtp_pass: str, to_list: List[str], cc_list: List[str], subject: str, body: str):
    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP_USER or SMTP_PASSWORD not set in environment.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = DEFAULT_FROM
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg.set_content(body)
    # send
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)

# ----------------------
# CLI / Main
# ----------------------
def parse_args():
    p = argparse.ArgumentParser(description="Create Teams meeting and email link")
    p.add_argument("--mode", choices=["onlineMeeting", "calendarEvent"], default="calendarEvent",
                   help="onlineMeeting (standalone) or calendarEvent (recommended)")
    p.add_argument("--organizer-upn", help="Organizer UPN / email (for calendarEvent or lookup).")
    p.add_argument("--organizer-object-id", help="Organizer AAD object id (for onlineMeeting). If not provided for onlineMeeting, the script tries to lookup by --organizer-upn.")
    p.add_argument("--subject", default=DEFAULT_SUBJECT)
    p.add_argument("--start", required=True, help="Start ISO datetime, e.g. 2025-11-20T10:00:00Z")
    p.add_argument("--end", required=True, help="End ISO datetime, e.g. 2025-11-20T11:00:00Z")
    p.add_argument("--attendees", default="", help="Comma-separated attendee emails (for calendar event)")
    p.add_argument("--to", default=",".join(DEFAULT_TO), help="Comma-separated To emails for notification email")
    p.add_argument("--cc", default=",".join(DEFAULT_CC), help="Comma-separated CC emails for notification email")
    p.add_argument("--send-email", action="store_true", help="Send email notification with join link")
    return p.parse_args()

def main():
    args = parse_args()
    attendees = [x.strip() for x in args.attendees.split(",") if x.strip()]
    to_list = [x.strip() for x in args.to.split(",") if x.strip()]
    cc_list = [x.strip() for x in args.cc.split(",") if x.strip()]

    # Basic env checks
    if not AZURE_CLIENT_SECRET:
        print("ERROR: AZURE_CLIENT_SECRET must be set as an environment variable.", file=sys.stderr)
        sys.exit(1)
    if args.send_email and (not SMTP_USER or not SMTP_PASSWORD):
        print("ERROR: SMTP_USER and SMTP_PASSWORD must be set in environment to send email.", file=sys.stderr)
        sys.exit(1)

    try:
        print("Requesting app token...")
        token = get_app_token()
        print("Token acquired.")

        resp = None
        join_url = None

        if args.mode == "onlineMeeting":
            user_obj = args.organizer_object_id
            if not user_obj:
                if not args.organizer_upn:
                    raise RuntimeError("For onlineMeeting mode provide --organizer-object-id or --organizer-upn (to lookup).")
                print(f"Looking up object id for {args.organizer_upn} ...")
                user_obj = get_user_object_id_by_upn(token, args.organizer_upn)
                if not user_obj:
                    raise RuntimeError(f"Could not find object id for {args.organizer_upn}.")
            print(f"Creating onlineMeeting for object id: {user_obj} ...")
            resp = create_online_meeting(token, user_obj, args.subject, args.start, args.end)

        else:  # calendarEvent
            if not args.organizer_upn:
                raise RuntimeError("For calendarEvent mode provide --organizer-upn (user email).")
            print(f"Creating calendar event for {args.organizer_upn} ...")
            resp = create_calendar_event(token, args.organizer_upn, args.subject, args.start, args.end, attendees)

        print("Graph response (truncated):")
        print(json.dumps(resp, indent=2)[:4000] + ("\n... (truncated)" if len(json.dumps(resp))>4000 else ""))

        join_url = extract_join_url(resp)
        if join_url:
            print("\nJoin URL:", join_url)
        else:
            print("\nWARNING: join URL not found in Graph response. Inspect response above.")

        if args.send_email and to_list:
            email_body = f"{args.subject}\n\nPlease join the Teams meeting:\n\n{join_url or 'JOIN LINK NOT FOUND'}\n\nRegards,"
            print("Sending email notification...")
            send_email(SMTP_USER, SMTP_PASSWORD, to_list, cc_list, args.subject, email_body)
            print("Email sent to:", to_list, "cc:", cc_list)

        print("\nDone.")

    except Exception as e:
        print("ERROR:", str(e), file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
