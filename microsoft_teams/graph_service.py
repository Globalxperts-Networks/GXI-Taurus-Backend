# graph_service.py  (full file to use — you can replace or merge with your uploaded file)
import time
import requests
import base64
import json
from django.conf import settings

_token_cache = {"access_token": None, "expiry_time": 0}

class GraphAPIError(Exception):
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Graph API {status_code}: {body}")

class GraphService:
    TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, tenant_id=None, client_id=None, client_secret=None):
        self.tenant = tenant_id or getattr(settings, "AZURE_TENANT_ID", None)
        self.client_id = client_id or getattr(settings, "AZURE_CLIENT_ID", None)
        self.client_secret = client_secret or getattr(settings, "AZURE_CLIENT_SECRET", None)
        if not all([self.tenant, self.client_id, self.client_secret]):
            raise ValueError("Azure credentials missing in constructor or settings.")

    # Token logic (app-only)
    def _is_token_valid(self):
        return _token_cache["access_token"] and time.time() < _token_cache["expiry_time"] - 10

    def _store_token(self, token, expires_in):
        _token_cache["access_token"] = token
        _token_cache["expiry_time"] = time.time() + int(expires_in)

    def get_app_token(self, force_refresh=False):
        """
        Acquire app-only token (client_credentials). Uses simple in-process cache.
        """
        if not force_refresh and self._is_token_valid():
            return _token_cache["access_token"]

        url = self.TOKEN_URL.format(tenant=self.tenant)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        resp = requests.post(url, data=data, timeout=15)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)
        body = resp.json()
        token = body.get("access_token")
        expires_in = body.get("expires_in", 3600)
        if not token:
            raise Exception(f"No access_token: {body}")
        self._store_token(token, expires_in)
        return token

    # backward-compatible alias (some of your code called graph.get_token())
    def get_token(self, force_refresh=False):
        return self.get_app_token(force_refresh=force_refresh)

    def decode_jwt_no_verify(self, token):
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return {}
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception as e:
            return {"error": f"decode_failed: {e}"}

    # ---- Create online meeting (app-only) ----
    def create_online_meeting_app(self, token: str, organizer_user_id: str, start_dt: str, end_dt: str, subject: str = None, meeting_options: dict = None):
        """
        Create online meeting using app-only token for a chosen organizer.
        POST /users/{organizer_user_id}/onlineMeetings
        start_dt/end_dt in ISO-8601 UTC e.g. "2025-11-20T10:00:00Z"
        meeting_options: optional dict to pass additional Graph fields.
        """
        url = f"{self.GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "startDateTime": start_dt,
            "endDateTime": end_dt,
            "subject": subject or "Scheduled via API"
        }
        if meeting_options:
            payload.update(meeting_options)

        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)
        return resp.json()

    # ---- Create calendar event for user (app-only) ----
    def create_event_for_user_app(self, token: str, user_identifier: str, event_payload: dict):
        """
        Create a calendar event for a user using app-only token.
        POST /users/{user_identifier}/events
        user_identifier: userPrincipalName (email) or user object id
        event_payload: the JSON body for the event (e.g. the payload you gave)
        """
        url = f"{self.GRAPH_BASE}/users/{user_identifier}/events"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=event_payload, timeout=20)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)
        return resp.json()

    # You can add other helpers like get_teams, get_team_members etc. as needed.
