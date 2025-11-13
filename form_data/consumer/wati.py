# consumers.py
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from django.conf import settings
from ..wati_service import WatiService
from ..models import FormData

logger = logging.getLogger(__name__)
@sync_to_async
def _call_send_session(phone, message_text):
    svc = WatiService()
    return svc.send_session_message(phone=phone, message_text=message_text)

@sync_to_async
def _call_send_template(phone, template_name, parameters, broadcast_name):
    svc = WatiService()
    return svc.send_template_message(phone=phone, template_name=template_name, parameters=parameters, broadcast_name=broadcast_name)

@sync_to_async
def _get_form_submission(form_id):
    try:
        f = FormData.objects.get(id=form_id)
        return f.submission_data or {}
    except Exception:
        return None

def normalize_phone(phone, default_cc="91"):
    if phone is None:
        return None
    s = str(phone).strip()
    for ch in ["+", " ", "-", "(", ")"]:
        s = s.replace(ch, "")
    if len(s) == 10:
        return default_cc + s
    return s

class WatiRealtimeConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        await self.send_json({"type": "connected", "message": "Connected to WATI realtime socket"})

    async def disconnect(self, code):
        logger.debug("WS disconnected: %s", code)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            payload = json.loads(text_data or "{}")
        except Exception as e:
            await self.send_json({"success": False, "error": "Invalid JSON", "details": str(e)})
            return

        action = payload.get("action")
        if action == "send_session":
            await self._handle_send_session(payload)
        elif action == "send_template":
            await self._handle_send_template(payload)
        else:
            await self.send_json({"success": False, "error": "Unknown action", "action": action})

    async def _handle_send_session(self, payload):
        phone = payload.get("phone")
        form_id = payload.get("form_id")
        message_text = payload.get("message") or payload.get("message_text")
        if not phone and form_id:
            submission = await _get_form_submission(form_id)
            if submission:
                phone = submission.get("Phone") or submission.get("phone") or submission.get("mobile")
        if not phone:
            await self.send_json({"success": False, "error": "Missing phone or form_id"})
            return
        if not message_text:
            await self.send_json({"success": False, "error": "Missing message_text"})
            return

        phone_norm = normalize_phone(phone)
        try:
            result = await _call_send_session(phone_norm, message_text)
            await self.send_json({"action": "send_session_result", "phone": phone_norm, **result})
        except Exception as e:
            logger.exception("Error in send_session")
            await self.send_json({"success": False, "error": "Exception when sending session message", "details": str(e)})

    async def _handle_send_template(self, payload):
        phone = payload.get("phone")
        form_id = payload.get("form_id")
        template_name = payload.get("template_name")
        parameters = payload.get("parameters") or []
        broadcast_name = payload.get("broadcast_name") or ""
        if not phone and form_id:
            submission = await _get_form_submission(form_id)
            if submission:
                phone = submission.get("Phone") or submission.get("phone") or submission.get("mobile")
        if not phone:
            await self.send_json({"success": False, "error": "Missing phone or form_id"})
            return
        if not template_name:
            await self.send_json({"success": False, "error": "Missing template_name"})
            return

        phone_norm = normalize_phone(phone)
        try:
            result = await _call_send_template(phone_norm, template_name, parameters, broadcast_name)
            await self.send_json({"action": "send_template_result", "phone": phone_norm, "template_name": template_name, **result})
        except Exception as e:
            logger.exception("Error in send_template")
            await self.send_json({"success": False, "error": "Exception when sending template message", "details": str(e)})

    # convenience
    async def send_json(self, data):
        await self.send(text_data=json.dumps(data))
