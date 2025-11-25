
import time
import requests
import base64
import json
from django.conf import settings
from typing import Optional, Dict, Any, List
import logging
from typing import Optional
import os

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

    _cached_token = None
    _cached_token_expires_at = 0

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

    def get_app_token(self, force_refresh: bool = False) -> str:
        now = int(time.time())
        if not force_refresh and self._cached_token and now < self._cached_token_expires_at - 30:
            return self._cached_token

        client_id = os.getenv("AZURE_CLIENT_ID") or getattr(settings, "AZURE_CLIENT_ID", None)
        client_secret = os.getenv("AZURE_CLIENT_SECRET") or getattr(settings, "AZURE_CLIENT_SECRET", None)
        tenant_id = os.getenv("AZURE_TENANT_ID") or getattr(settings, "AZURE_TENANT_ID", None)

        if not client_id or not client_secret or not tenant_id:
            raise Exception("Azure AD app credentials not configured (AZURE_CLIENT_ID/SECRET/TENANT_ID)")

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": client_id,
            "scope": "https://graph.microsoft.com/.default",
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }

        resp = requests.post(token_url, data=data, timeout=20)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            # include body so you can see Azure's error in logs
            raise Exception(f"Failed to get app token: {resp.status_code} {body}")

        j = resp.json()
        access_token = j.get("access_token")
        expires_in = int(j.get("expires_in", 3600))

        if not access_token:
            raise Exception(f"No access_token in token response: {j}")

        # cache
        self._cached_token = access_token
        self._cached_token_expires_at = int(time.time()) + expires_in
        return access_token

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
    

    def call_recording(self, token: str, organizer_email: str, meeting_id: str, download_content: bool = False, download_dest: str = None) -> Dict[str, Any]:
        if not token:
            raise GraphAPIError(401, "Missing access token")
        if not organizer_email or not meeting_id:
            raise GraphAPIError(400, "organizer_email and meeting_id are required")

        url = f"{self.GRAPH_BASE}/users/{organizer_email}/onlineMeetings/{meeting_id}/recordings"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            # network-level error
            raise GraphAPIError(500, f"Network error while calling Graph recordings endpoint: {str(e)}")

        # Graph-level error
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise GraphAPIError(resp.status_code, body)

        content_type = resp.headers.get("Content-Type", "")
        # If Graph returned JSON metadata (typical)
        if "application/json" in content_type:
            metadata = resp.json()

            # if user asked to download actual content and recording metadata exposes a content URL -> try download
            if download_content:
                # determine download destination folder
                dest_dir = download_dest or "/mnt/data/recordings"
                os.makedirs(dest_dir, exist_ok=True)

                # look for a recording content URL in the metadata
                # common places: value[*].recordingContentUrl or value[*].contentLocation or property names may vary
                rec_item = None
                for v in metadata.get("value", []):
                    # prefer explicit recordingContentUrl field
                    if v.get("recordingContentUrl"):
                        rec_item = v
                        content_url = v.get("recordingContentUrl")
                        break
                    # fallback to contentLocation / contentUrl / downloadUrl
                    for alt in ("contentLocation", "contentUrl", "downloadUrl", "recordingUrl"):
                        if v.get(alt):
                            rec_item = v
                            content_url = v.get(alt)
                            break
                    if rec_item:
                        break
                else:
                    # no break -> no content url found
                    content_url = None

                if content_url:
                    # attempt to fetch binary content (recording)
                    try:
                        dl_headers = {"Authorization": f"Bearer {token}"}  # sometimes no auth needed; safe to include
                        with requests.get(content_url, headers=dl_headers, timeout=60, stream=True) as r:
                            r.raise_for_status()
                            # derive extension from content-type if possible
                            ct = r.headers.get("Content-Type", "")
                            ext = ""
                            if "mp4" in ct.lower():
                                ext = ".mp4"
                            # fallback: try to parse filename from content-disposition
                            fname = None
                            cd = r.headers.get("content-disposition", "")
                            if cd and "filename=" in cd:
                                try:
                                    fname = cd.split("filename=")[1].strip(' ";')
                                except Exception:
                                    fname = None
                            if not fname:
                                # sanitize meeting_id for filesystem
                                safe_mid = meeting_id.replace("/", "_").replace(":", "_")
                                fname = f"meeting_{safe_mid}{ext or '.bin'}"

                            saved_path = os.path.join(dest_dir, fname)
                            # write stream to file
                            with open(saved_path, "wb") as wf:
                                total = 0
                                for chunk in r.iter_content(chunk_size=8192):
                                    if chunk:
                                        wf.write(chunk)
                                        total += len(chunk)

                        # attach download info to metadata
                        return {
                            "metadata": metadata,
                            "downloaded": True,
                            "saved_path": saved_path,
                            "download_size": total,
                            "content_type": ct
                        }
                    except requests.RequestException as re:
                        # return metadata but mark download failed
                        return {
                            "metadata": metadata,
                            "downloaded": False,
                            "download_error": str(re)
                        }
                else:
                    # metadata present but no content URL
                    return {
                        "metadata": metadata,
                        "downloaded": False,
                        "download_error": "No recordingContentUrl / contentUrl found in metadata"
                    }

            # not downloading, just return metadata
            return metadata

        # If Graph returned binary directly
        return {
            "content_bytes": resp.content,
            "content_type": content_type,
            "size": len(resp.content)
        }
