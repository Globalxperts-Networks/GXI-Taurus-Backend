import requests
from urllib.parse import urlencode
from django.conf import settings


class WatiService:
    BASE_URL = "https://live-mt-server.wati.io"

    def __init__(self):
        self.tenant_id = settings.TENANT_ID
        self.token = settings.WATI_API_TOKEN

    def _make_request(self, method, endpoint, params=None, json=None):
        url = f"{self.BASE_URL}/{self.tenant_id}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                timeout=15,
            )
            response.raise_for_status()
            return {"success": True, "status": response.status_code, "response": response.json()}
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "details": getattr(e.response, "text", None),
            }

    def send_template_message(self, phone, template_name, parameters, broadcast_name):
        url_path = f"api/v1/sendTemplateMessage"
        params = {"whatsappNumber": str(phone).replace("+", "")}
        headers_patch = {"Content-Type": "application/json-patch+json"}

        payload = {
            "template_name": template_name,
            "broadcast_name": broadcast_name,
            "parameters": parameters,
        }

        return self._make_request("POST", url_path, params=params, json=payload)

    def send_session_message(self, phone, message_text):
        phone = str(phone).replace("+", "")
        url_path = f"api/v1/sendSessionMessage/91{phone}"
        params = {"messageText": message_text}
        return self._make_request("POST", url_path, params=params)

    def get_messages(self, phone):
        phone = str(phone).replace("+", "")
        url_path = f"api/v1/getMessages/{phone}"
        return self._make_request("GET", url_path)
