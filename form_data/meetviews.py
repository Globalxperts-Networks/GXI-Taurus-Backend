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

REDIRECT_URI = "http://127.0.0.1:8000/api/form_data/callback/"

class GoogleAuthInit(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        flow = Flow.from_client_secrets_file(
            GOOGLE_CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        auth_url, _ = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            include_granted_scopes="true",
        )
        return Response({"auth_url": auth_url})


class GoogleAuthCallback(APIView):
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
    def post(self, request):
        try:
            if not os.path.exists(TOKEN_PATH):
                return Response(
                    {"error": "User not authorized with Google (no token.json)", "looking_for": TOKEN_PATH},
                    status=401
                )
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
            if not creds.valid and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(TOKEN_PATH, "w") as f:
                        f.write(creds.to_json())
                except Exception as e:
                    return Response({"error": "Failed to refresh token", "details": str(e)}, status=401)

            if not creds.valid:
                return Response(
                    {"error": "Invalid/expired credentials and no refresh_token", "token_path": TOKEN_PATH},
                    status=401
                )

            service = build("calendar", "v3", credentials=creds)
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
            event = service.events().insert(
                calendarId="primary",
                body=event,
                conferenceDataVersion=1
            ).execute()

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
