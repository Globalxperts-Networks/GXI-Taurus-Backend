import requests

class GraphService:
    def __init__(self, tenant_id, client_id, client_secret):
        self.token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = ["https://graph.microsoft.com/.default"]

    def get_token(self):
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default"
        }
        response = requests.post(self.token_url, data=data)
        return response.json()["access_token"]

    def get_teams(self, access_token):
        url = "https://graph.microsoft.com/v1.0/groups?$filter=groupTypes/any(c:c eq 'Unified')"
        headers = {"Authorization": f"Bearer {access_token}"}
        return requests.get(url, headers=headers).json()

    def get_team_members(self, access_token, group_id):
        url = f"https://graph.microsoft.com/v1.0/groups/{group_id}/members"
        headers = {"Authorization": f"Bearer {access_token}"}
        return requests.get(url, headers=headers).json()




# adsync/graph_service.py
import requests
from django.conf import settings

class GraphService:
    TOKEN_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
    GRAPH_BASE = 'https://graph.microsoft.com/v1.0'

    def __init__(self):
        self.tenant = settings.AZURE_TENANT_ID
        self.client_id = settings.AZURE_CLIENT_ID
        self.client_secret = settings.AZURE_CLIENT_SECRET

    def get_app_token(self):
        url = self.TOKEN_URL.format(tenant=self.tenant)
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials',
        }
        r = requests.post(url, data=data, timeout=15)
        r.raise_for_status()
        body = r.json()
        token = body.get('access_token')
        if not token:
            raise Exception(f"No access_token in token response: {body}")
        return token

    def create_online_meeting_as_app(self, user_object_id, subject, start_iso, end_iso):
        """
        Create a standalone online meeting for user (app permissions).
        POST /users/{userId}/onlineMeetings
        Returns the JSON response which contains 'joinWebUrl'.
        NOTE: Requires OnlineMeetings.ReadWrite.All (Application) and application access policy allowing your app to act for the user.
        """
        token = self.get_app_token()
        url = f"{self.GRAPH_BASE}/users/{user_object_id}/onlineMeetings"
        body = {
            "startDateTime": start_iso,
            "endDateTime": end_iso,
            "subject": subject
        }
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        r = requests.post(url, json=body, headers=headers, timeout=20)
        r.raise_for_status()
        return r.json()

    def create_calendar_event_with_teams(self, user_principal_name, subject, start_iso, end_iso, attendees_list):
        """
        Create a calendar event on a user's calendar with Teams meeting link.
        POST /users/{userPrincipalName}/events
        attendees_list: list of dicts -> [{"email":"a@b.com","name":"A"} , ...]
        Returns event JSON which contains onlineMeeting/joinUrl in 'onlineMeeting' or in 'onlineMeeting' fields.
        NOTE: Requires Calendars.ReadWrite (Application).
        """
        token = self.get_app_token()
        url = f"{self.GRAPH_BASE}/users/{user_principal_name}/events"
        attendees_payload = []
        for a in attendees_list:
            attendees_payload.append({
                "emailAddress": {"address": a.get('email'), "name": a.get('name', '')},
                "type": "required"
            })
        body = {
            "subject": subject,
            "start": {"dateTime": start_iso, "timeZone": "UTC"},
            "end": {"dateTime": end_iso, "timeZone": "UTC"},
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
            "attendees": attendees_payload
        }
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        r = requests.post(url, json=body, headers=headers, timeout=20)
        r.raise_for_status()
        return r.json()
