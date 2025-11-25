
import time
import requests
import base64
import json
from django.conf import settings
from typing import Optional, Dict, Any, List
import logging
from typing import Optional

logger = logging.getLogger(__name__)

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
    def _is_token_valid(self):
        return _token_cache["access_token"] and time.time() < _token_cache["expiry_time"] - 10

    def _store_token(self, token, expires_in):
        _token_cache["access_token"] = token
        _token_cache["expiry_time"] = time.time() + int(expires_in)

    def get_app_token(self, force_refresh=False):
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


    def user_list(self, token: str, top: int = 500, fetch_all: bool = False, timeout: int = 20) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        params = {"$top": str(top)}

        url = f"{self.GRAPH_BASE}/users"
        try:
            # initial GET
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        except requests.RequestException as re:
            logger.exception("Network error while calling Graph /users")
            raise

        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)

        data = resp.json()
        if fetch_all:
            users: List[Dict[str, Any]] = []
            if "value" in data and isinstance(data["value"], list):
                users.extend(data["value"])

            next_link = data.get("@odata.nextLink")
            while next_link:
                try:
                    resp = requests.get(next_link, headers=headers, timeout=timeout)
                except requests.RequestException as re:
                    logger.exception("Network error while following @odata.nextLink")
                    raise

                if resp.status_code >= 400:
                    try:
                        body = resp.json()
                    except ValueError:
                        body = resp.text
                    raise GraphAPIError(resp.status_code, body)

                page = resp.json()
                if "value" in page and isinstance(page["value"], list):
                    users.extend(page["value"])
                next_link = page.get("@odata.nextLink")

            return {"value": users}
        return data


    def reschedule_event(self, token: str, organizer_user_id: str, event_id: str, start_iso: str, end_iso: str, subject: Optional[str] = None):
        url = f"{self.GRAPH_BASE}/users/{organizer_user_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "start": {"dateTime": start_iso, "timeZone": "UTC"},
            "end": {"dateTime": end_iso, "timeZone": "UTC"},
        }
        if subject:
            payload["subject"] = subject

        resp = requests.patch(url, headers=headers, json=payload, timeout=20)

        if resp.status_code >= 400:
            # Try to include JSON body if present
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)

        # Success: either 200 with body or 204 no content
        if resp.status_code == 204:
            return None
        try:
            return resp.json()
        except ValueError:
            return None


    def get_event_for_user(self, token: str, organizer_user_id: str, event_id: str) -> dict:
        url = f"{self.GRAPH_BASE}/users/{organizer_user_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)
        return resp.json()


    def reschedule_online_meeting(self, token: str, organizer_user_id: str, meeting_id: str, start_iso: str, end_iso: str, subject: Optional[str] = None):
        url = f"{self.GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{meeting_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "startDateTime": start_iso,
            "endDateTime": end_iso
        }
        if subject:
            payload["subject"] = subject

        resp = requests.patch(url, headers=headers, json=payload, timeout=20)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)
        if resp.status_code == 204:
            return None
        try:
            return resp.json()
        except ValueError:
            return None


    def get_online_meeting(self, token: str, organizer_user_id: str, meeting_id: str) -> dict:
        url = f"{self.GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{meeting_id}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)
        return resp.json()
