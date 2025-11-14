# wati.py (WebSocket consumer) — separated tasks for send_template, send_session, get_messages
import json
import logging
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from django.conf import settings
from ..wati_service import WatiService
from ..models import FormData

logger = logging.getLogger(__name__)

# Blocking calls wrapped to run in threadpool
@sync_to_async
def _call_send_session(phone, message_text):
    svc = WatiService()
    return svc.send_session_message(phone=phone, message_text=message_text)

@sync_to_async
def _call_send_template(phone, template_name, parameters, broadcast_name):
    svc = WatiService()
    return svc.send_template_message(phone=phone, template_name=template_name, parameters=parameters, broadcast_name=broadcast_name)

@sync_to_async
def _call_get_messages(phone):
    svc = WatiService()
    return svc.get_messages(phone=phone)

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
    """
    Actions:
      - start_poller / stop_poller: control automatic get_messages polling
      - send_session: fire-and-forget session message (returns result when done)
      - send_template: fire-and-forget template message (returns result when done)
      - get_messages_once: immediate single fetch (doesn't affect poller)
      - cancel_task: cancel a running task by id (optional)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.poll_task = None                 # dedicated poller (get_messages every interval)
        self.poll_phone = None
        self._poll_interval = getattr(settings, "WATI_POLL_INTERVAL_SECONDS", 1)  # default 1s as requested
        self.running_tasks = {}               # map task_id -> asyncio.Task for send operations
        self._task_counter = 0
        self._lock = asyncio.Lock()           # protect task bookkeeping

    async def connect(self):
        await self.accept()
        await self.send_json({"connected": True, "message": "WebSocket connected. Use actions to control operations."})

    async def disconnect(self, code):
        # Cancel poller and any running tasks
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass

        # cancel send tasks
        async with self._lock:
            for tid, t in list(self.running_tasks.items()):
                if not t.done():
                    t.cancel()
            self.running_tasks.clear()

        logger.info("WS disconnected")

    async def receive(self, text_data=None, bytes_data=None):
        try:
            payload = json.loads(text_data or "{}")
        except Exception as e:
            await self.send_json({"success": False, "error": "Invalid JSON", "details": str(e)})
            return

        action = payload.get("action")

        if action == "start_poller":
            await self._start_poller(payload)
        elif action == "stop_poller":
            await self._stop_poller_action(payload)
        elif action == "send_session":
            await self._start_send_session(payload)
        elif action == "send_template":
            await self._start_send_template(payload)
        elif action == "get_messages_once":
            await self._get_messages_once(payload)
        elif action == "cancel_task":
            await self._cancel_task(payload)
        else:
            await self.send_json({"success": False, "error": "Unknown action", "action": action})

    # convenience
    async def send_json(self, data):
        await self.send(text_data=json.dumps(data))

    # ---------------------------
    # Poller: runs get_messages every interval (independent task)
    # ---------------------------
    async def _start_poller(self, payload):
        phone = payload.get("phone")
        form_id = payload.get("form_id")

        if not phone and form_id:
            submission = await _get_form_submission(form_id)
            if submission:
                phone = submission.get("Phone") or submission.get("phone") or submission.get("mobile")

        if not phone:
            await self.send_json({"success": False, "error": "Missing phone or form_id for start_poller"})
            return

        phone_norm = normalize_phone(phone)

        # if poller already running for same phone, ignore
        if self.poll_task and not self.poll_task.done() and self.poll_phone == phone_norm:
            await self.send_json({"action": "start_poller_ack", "phone": phone_norm, "message": "Poller already running for this phone"})
            return

        # stop existing poller if different phone
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass

        self.poll_phone = phone_norm
        self.poll_task = asyncio.create_task(self._poller_loop(phone_norm))
        await self.send_json({"action": "start_poller_ack", "phone": phone_norm, "message": f"Started poller every {self._poll_interval}s"})

    async def _stop_poller_action(self, payload):
        await self._stop_poller()
        await self.send_json({"action": "stop_poller_ack", "message": "Poller stopped"})

    async def _stop_poller(self):
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        self.poll_task = None
        self.poll_phone = None

    async def _poller_loop(self, phone):
        """
        Dedicated poller that runs get_messages every poll interval.
        This runs independently from send tasks.
        """
        logger.info("Poller started for phone %s (interval=%s)", phone, self._poll_interval)
        last_marker = None
        try:
            while True:
                try:
                    result = await _call_get_messages(phone)
                except Exception as e:
                    logger.exception("Error in poller get_messages")
                    await self.send_json({"action": "poll_error", "phone": phone, "error": str(e)})
                    await asyncio.sleep(self._poll_interval)
                    continue

                # Always forward the result as messages_update; client can decide how to handle delta
                try:
                    await self.send_json({"action": "messages_update", "phone": phone, "result": result})
                except Exception:
                    logger.exception("Failed to send poller update to client")

                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            logger.info("Poller cancelled for phone %s", phone)
            return
        except Exception as e:
            logger.exception("Unexpected poller error")
            await self.send_json({"action": "poll_fatal_error", "phone": phone, "error": str(e)})

    # ---------------------------
    # Send operations - run as independent background tasks
    # ---------------------------
    async def _start_send_session(self, payload):
        phone = payload.get("phone")
        form_id = payload.get("form_id")
        message_text = payload.get("message") or payload.get("message_text")
        if not phone and form_id:
            submission = await _get_form_submission(form_id)
            if submission:
                phone = submission.get("Phone") or submission.get("phone") or submission.get("mobile")
        if not phone:
            await self.send_json({"success": False, "error": "Missing phone or form_id for send_session"})
            return
        if not message_text:
            await self.send_json({"success": False, "error": "Missing message_text"})
            return

        phone_norm = normalize_phone(phone)
        task_id = await self._create_task(self._run_send_session(phone_norm, message_text))
        await self.send_json({"action": "send_session_started", "task_id": task_id, "phone": phone_norm})

    async def _start_send_template(self, payload):
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
            await self.send_json({"success": False, "error": "Missing phone or form_id for send_template"})
            return
        if not template_name:
            await self.send_json({"success": False, "error": "Missing template_name"})
            return

        phone_norm = normalize_phone(phone)
        task_id = await self._create_task(self._run_send_template(phone_norm, template_name, parameters, broadcast_name))
        await self.send_json({"action": "send_template_started", "task_id": task_id, "phone": phone_norm, "template_name": template_name})

    # Background runner wrappers
    async def _run_send_session(self, phone, message_text):
        """
        Runs in background: calls _call_send_session and delivers result back to client.
        """
        try:
            result = await _call_send_session(phone, message_text)
            await self.send_json({"action": "send_session_result", "phone": phone, "result": result})
        except asyncio.CancelledError:
            await self.send_json({"action": "send_session_cancelled", "phone": phone})
            raise
        except Exception as e:
            logger.exception("Error in background send_session")
            await self.send_json({"action": "send_session_error", "phone": phone, "error": str(e)})

    async def _run_send_template(self, phone, template_name, parameters, broadcast_name):
        try:
            result = await _call_send_template(phone, template_name, parameters, broadcast_name)
            await self.send_json({"action": "send_template_result", "phone": phone, "template_name": template_name, "result": result})
        except asyncio.CancelledError:
            await self.send_json({"action": "send_template_cancelled", "phone": phone, "template_name": template_name})
            raise
        except Exception as e:
            logger.exception("Error in background send_template")
            await self.send_json({"action": "send_template_error", "phone": phone, "template_name": template_name, "error": str(e)})

    # Utility: create and track a background task, return generated task id
    async def _create_task(self, coro):
        async with self._lock:
            self._task_counter += 1
            task_id = f"task-{self._task_counter}"
            task = asyncio.create_task(coro)
            # store it
            self.running_tasks[task_id] = task

            # add done callback to cleanup mapping when finished
            def _done_cb(t, tid=task_id):
                # schedule cleanup in event loop
                try:
                    # use create_task to call async cleanup
                    asyncio.create_task(self._cleanup_task(tid))
                except Exception:
                    logger.exception("Failed to schedule cleanup task callback")

            task.add_done_callback(_done_cb)
            return task_id

    async def _cleanup_task(self, task_id):
        async with self._lock:
            self.running_tasks.pop(task_id, None)

    # cancel task by id
    async def _cancel_task(self, payload):
        task_id = payload.get("task_id")
        if not task_id:
            await self.send_json({"success": False, "error": "Missing task_id for cancel_task"})
            return
        async with self._lock:
            task = self.running_tasks.get(task_id)
            if not task:
                await self.send_json({"success": False, "error": "No such task", "task_id": task_id})
                return
            task.cancel()
        await self.send_json({"action": "cancel_task_ack", "task_id": task_id})

    # Immediate one-off fetch (doesn't affect poller)
    async def _get_messages_once(self, payload):
        phone = payload.get("phone")
        form_id = payload.get("form_id")
        if not phone and form_id:
            submission = await _get_form_submission(form_id)
            if submission:
                phone = submission.get("Phone") or submission.get("phone") or submission.get("mobile")
        if not phone:
            await self.send_json({"success": False, "error": "Missing phone or form_id for get_messages_once"})
            return

        phone_norm = normalize_phone(phone)
        try:
            result = await _call_get_messages(phone_norm)
            await self.send_json({"action": "get_messages_once_result", "phone": phone_norm, "result": result})
        except Exception as e:
            logger.exception("Error in get_messages_once")
            await self.send_json({"action": "get_messages_once_error", "phone": phone_norm, "error": str(e)})
