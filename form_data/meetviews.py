import os
import json
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

BASE_DIR = getattr(settings, "BASE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TOKEN_DIR = os.path.join(BASE_DIR, ".google")
os.makedirs(TOKEN_DIR, exist_ok=True)
TOKEN_PATH = os.path.join(TOKEN_DIR, "token.json")
GOOGLE_CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "credentials_2.json")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# MUST match your OAuth client "Authorized redirect URIs" EXACTLY.
# If you prefer https, ensure your dev server actually serves HTTPS.
REDIRECT_URI = "http://127.0.0.1:8000/api/form_data/callback/"

# -------------------------------
# Views
# -------------------------------

class GoogleAuthInit(APIView):
    """
    Step 1: Get the Google OAuth consent URL.
    Open the returned 'auth_url' in a browser and grant access.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        flow = Flow.from_client_secrets_file(
            GOOGLE_CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        # offline + prompt=consent ensures we get a refresh_token
        auth_url, _ = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            include_granted_scopes="true",
        )
        return Response({"auth_url": auth_url})


class GoogleAuthCallback(APIView):
    """
    Step 2: OAuth redirect target. Saves token to TOKEN_PATH.
    You should see has_refresh_token = true on first successful grant.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        code = request.GET.get("code")
        if not code:
            return Response({"error": "Missing ?code"}, status=400)

        flow = Flow.from_client_secrets_file(
            GOOGLE_CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

        return Response({
            "message": "Google authorization successful!",
            "token_file": TOKEN_PATH,
            "has_refresh_token": bool(creds.refresh_token)
        })


class GoogleTokenStatus(APIView):
    """
    (Optional) Quick diagnostic endpoint to check token presence/health.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        exists = os.path.exists(TOKEN_PATH)
        info = {"exists": exists, "path": TOKEN_PATH}
        if exists:
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
                info.update({
                    "valid": bool(creds and creds.valid),
                    "has_refresh_token": bool(getattr(creds, "refresh_token", None)),
                    "scopes": list(creds.scopes or []),
                })
            except Exception as e:
                info.update({"error": str(e)})
        return Response(info)


class CreateMeetView(APIView):
    """
    Step 3: Create a Calendar event with a Google Meet link.
    POST the JSON body shown below. Returns meet_link + event_id.
    """
    def post(self, request):
        try:
            # 1) Ensure we have a token
            if not os.path.exists(TOKEN_PATH):
                return Response(
                    {"error": "User not authorized with Google (no token.json)", "looking_for": TOKEN_PATH},
                    status=401
                )

            # 2) Load credentials
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

            # 3) Refresh if expired and refresh_token present
            if not creds.valid and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(TOKEN_PATH, "w") as f:
                        f.write(creds.to_json())
                except Exception as e:
                    return Response({"error": "Failed to refresh token", "details": str(e)}, status=401)

            # If still invalid, we can't proceed
            if not creds.valid:
                return Response(
                    {"error": "Invalid/expired credentials and no refresh_token", "token_path": TOKEN_PATH},
                    status=401
                )

            service = build("calendar", "v3", credentials=creds)

            # 4) Build event body
            event = {
                "summary": request.data.get("summary", "Team Meeting"),
                "description": request.data.get("description", "Google Meet discussion"),
                "start": {
                    "dateTime": request.data.get("start_time", "2025-11-10T15:00:00+05:30"),
                    "timeZone": "Asia/Kolkata",
                },
                "end": {
                    "dateTime": request.data.get("end_time", "2025-11-10T16:00:00+05:30"),
                    "timeZone": "Asia/Kolkata",
                },
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"meet-{os.getpid()}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
                "attendees": [{"email": email} for email in (request.data.get("attendees") or [])],
            }

            # 5) Create event (conferenceDataVersion=1 required for Meet link)
            event = service.events().insert(
                calendarId="primary",
                body=event,
                conferenceDataVersion=1
            ).execute()

            # 6) Extract Meet URL
            meet_link = event.get("hangoutLink")
            if not meet_link:
                conf = event.get("conferenceData", {}) or {}
                eps = conf.get("entryPoints") or []
                meet_link = next((ep.get("uri") for ep in eps if ep.get("entryPointType") == "video"), None)

            return Response({
                "meet_link": meet_link,
                "event_id": event.get("id"),
                "debug": {"token_path": TOKEN_PATH}
            })

        except HttpError as he:
            try:
                details = json.loads(he.content.decode())
            except Exception:
                details = str(he)
            return Response({"error": "Google API error", "details": details}, status=he.status_code)
        except Exception as e:
            return Response({"error": str(e)}, status=500)
