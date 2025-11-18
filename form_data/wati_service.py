# wati_service.py
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class WatiService:
    BASE_URL = "https://live-mt-server.wati.io"

    def __init__(self):
        self.tenant_id = getattr(settings, "TENANT_ID", "").strip()
        self.token = getattr(settings, "WATI_API_TOKEN", "").strip()

    def _make_request(self, method, endpoint, params=None, json=None):
        """
        Generic request wrapper. Returns dict:
        { "success": bool, "status": int_or_none, "response": parsed_json_or_text_or_none, "error": str_or_none }
        """
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
            try:
                body = response.json()
            except ValueError:
                body = response.text
            return {"success": True, "status": response.status_code, "response": body, "error": None}
        except requests.exceptions.RequestException as e:
            details = None
            try:
                details = e.response.text
            except Exception:
                details = None
            logger.exception("Wati request failed: %s %s %s", method, endpoint, str(e))
            return {"success": False, "status": getattr(e.response, "status_code", None), "response": details, "error": str(e)}

    def send_template_message(self, phone, template_name, parameters, broadcast_name=""):
        """
        Send a template message.
        phone: normalized phone string (no '+', include country code if needed)
        parameters: expected to be a list/dict as your WATI template requires
        """

        phone_s = str(phone).lstrip("+")  # clean phone number

        endpoint = "api/v1/sendTemplateMessage"  # endpoint without phone in path

        params = {
            "whatsappNumber": phone_s  # phone as query param
        }

        payload = {
            "template_name": template_name,
            "broadcast_name": broadcast_name,
            "parameters": parameters,
        }

        return self._make_request(
            method="POST",
            endpoint=endpoint,
            params=params,
            json=payload
        )

    # -----------------------------------------------------------
    # SESSION MESSAGE  (24 hr user initiated window)
    # -----------------------------------------------------------

    def send_session_message(self, phone, message_text):
        """
        Correct URL:
        https://live-mt-server.wati.io/<tenantId>/api/v1/sendSessionMessage/91<phone>?messageText=Hello
        """
        phone_s = str(phone).lstrip("+")

        # Session API requires number in the PATH (WATI rule)
        endpoint = f"api/v1/sendSessionMessage/91{phone_s}"

        params = {"messageText": message_text}

        return self._make_request(
            method="POST",
            endpoint=endpoint,
            params=params
        )

    # -----------------------------------------------------------
    # GET MESSAGE HISTORY
    # -----------------------------------------------------------

    def get_messages(self, phone):
        """
        Get all messages for phone. Returns whatever WATI returns under 'response'.
        """
        phone_s = str(phone).lstrip("+")

        endpoint = f"api/v1/getMessages/{phone_s}"

        return self._make_request("GET", endpoint)
