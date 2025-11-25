# meetviews.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from .graph_service import GraphService, GraphAPIError
from .models import Meeting , TeamsUser
from .serializers import MeetingSerializer , TeamsUserSerializer

logger = logging.getLogger(__name__)

class CreateOnlineMeetingAPIView(APIView):
    def post(self, request):
        try:
            organizer = request.data.get("organizer")
            start = request.data.get("start")
            end = request.data.get("end")
            subject = request.data.get("subject", "Scheduled via API")
            meeting_options = request.data.get("meeting_options", None)

            if not organizer or not start or not end:
                return Response({"error": "organizer, start and end are required"}, status=status.HTTP_400_BAD_REQUEST)

            graph = GraphService()
            token = graph.get_app_token()
            result = graph.create_online_meeting_app(token, organizer, start, end, subject=subject, meeting_options=meeting_options)

            # Save to Meeting model (optional)
            try:
                Meeting.objects.create(
                    organizer_ad_id=organizer,
                    subject=subject,
                    start=start,
                    end=end,
                    graph_response=result
                )
            except Exception as e:
                logger.warning("Could not save Meeting model: %s", e)

            return Response({"status": "success", "meeting": result}, status=status.HTTP_201_CREATED)

        except GraphAPIError as gee:
            logger.exception("Graph API error creating online meeting")
            return Response({"status": "error", "graph_status": gee.status_code, "graph_body": gee.body}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            logger.exception("Unexpected error")
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CreateEventAPIView(APIView):
    def post(self, request):
        try:
            organizer = request.data.get("organizer")
            event_payload = request.data.get("event") or request.data

            if not organizer:
                return Response({"error": "organizer (user email or id) is required"}, status=status.HTTP_400_BAD_REQUEST)
            if not event_payload:
                return Response({"error": "event payload is required"}, status=status.HTTP_400_BAD_REQUEST)

            graph = GraphService()
            token = graph.get_app_token()
            result = graph.create_event_for_user_app(token, organizer, event_payload)

            # Save to Meeting model (optional) - extract dates if provided
            try:
                start_iso = None
                end_iso = None
                # event_payload may include nested dict start.dateTime or start/dateTime; handle common shapes
                s = event_payload.get("start", {})
                e = event_payload.get("end", {})
                start_iso = s.get("dateTime") if isinstance(s, dict) else s
                end_iso = e.get("dateTime") if isinstance(e, dict) else e

                Meeting.objects.create(
                    organizer_ad_id=organizer,
                    subject=event_payload.get("subject", ""),
                    start=start_iso,
                    end=end_iso,
                    graph_response=result
                )
            except Exception as e:
                logger.warning("Could not save Meeting model: %s", e)

            return Response({"status": "success", "event": result}, status=status.HTTP_201_CREATED)

        except GraphAPIError as gee:
            logger.exception("Graph API error creating event")
            return Response({"status": "error", "graph_status": gee.status_code, "graph_body": gee.body}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            logger.exception("Unexpected error creating event: %s", exc)
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        


from django.db import transaction
class teams_user(APIView):
    def get(self, request):
        if GraphService is None:
            logger.error("GraphService not available; ensure graph_service.py is importable from this app.")
            return Response({"status": "error", "detail": "GraphService not available"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        graph = GraphService()
        try:
            token = graph.get_app_token()
            top_q = request.query_params.get("top", "500")
            try:
                top = int(top_q)
            except (TypeError, ValueError):
                top = 500
            fetch_all_q = request.query_params.get("fetch_all", "false").lower()
            fetch_all = fetch_all_q in ("1", "true", "yes", "y")
            user_info = graph.user_list(token=token, top=top, fetch_all=fetch_all)
            users = user_info.get("value", []) if isinstance(user_info, dict) else []
            if not users:
                return Response({
                    "status": "success",
                    "message": "No users returned from Graph",
                    "created": 0, "updated": 0, "skipped": 0, "total_fetched": 0
                }, status=status.HTTP_200_OK)

            now = timezone.now()
            incoming_by_id = {}
            incoming_ids = []
            for u in users:
                gid = u.get("id")
                if not gid:
                    continue
                incoming_by_id[gid] = u
                incoming_ids.append(gid)
            existing_qs = TeamsUser.objects.filter(graph_id__in=incoming_ids)
            existing_map = {t.graph_id: t for t in existing_qs}

            to_create = []
            to_update = []
            skipped = 0

            for gid, payload in incoming_by_id.items():
                defaults = {
                    "display_name": payload.get("displayName"),
                    "given_name": payload.get("givenName"),
                    "surname": payload.get("surname"),
                    "job_title": payload.get("jobTitle"),
                    "mail": payload.get("mail"),
                    "mobile_phone": payload.get("mobilePhone"),
                    "office_location": payload.get("officeLocation"),
                    "preferred_language": payload.get("preferredLanguage"),
                    "user_principal_name": payload.get("userPrincipalName"),
                    "business_phones": payload.get("businessPhones") or [],
                    "raw_graph": payload,
                    "updated_at": now
                }

                existing = existing_map.get(gid)
                if existing:
                    changed = False
                    for field, val in defaults.items():
                        if getattr(existing, field) != val:
                            setattr(existing, field, val)
                            changed = True
                    if changed:
                        to_update.append(existing)
                    else:
                        skipped += 1
                else:
                    obj = TeamsUser(graph_id=gid, **defaults)
                    to_create.append(obj)

            created_count = 0
            updated_count = 0
            try:
                with transaction.atomic():
                    if to_create:
                        TeamsUser.objects.bulk_create(to_create, batch_size=50)
                        created_count = len(to_create)
                    if to_update:
                        TeamsUser.objects.bulk_update(
                            to_update,
                            fields=[
                                "display_name", "given_name", "surname", "job_title", "mail",
                                "mobile_phone", "office_location", "preferred_language",
                                "user_principal_name", "business_phones", "raw_graph", "updated_at"
                            ],
                            batch_size=50
                        )
                        updated_count = len(to_update)
            except Exception:
                # If bulk operations fail for any DB/back-end reason, fall back to per-record upserts
                logger.exception("Bulk upsert failed; falling back to per-record update_or_create")
                created_count = 0
                updated_count = 0
                for gid, payload in incoming_by_id.items():
                    defaults = {
                        "display_name": payload.get("displayName"),
                        "given_name": payload.get("givenName"),
                        "surname": payload.get("surname"),
                        "job_title": payload.get("jobTitle"),
                        "mail": payload.get("mail"),
                        "mobile_phone": payload.get("mobilePhone"),
                        "office_location": payload.get("officeLocation"),
                        "preferred_language": payload.get("preferredLanguage"),
                        "user_principal_name": payload.get("userPrincipalName"),
                        "business_phones": payload.get("businessPhones") or [],
                        "raw_graph": payload,
                        "updated_at": now
                    }
                    obj, created = TeamsUser.objects.update_or_create(graph_id=gid, defaults=defaults)
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                # recalc skipped count
                skipped = max(0, len(incoming_by_id) - created_count - updated_count)

            # Respond with summary
            return Response({
                "status": "success",
                "created": created_count,
                "updated": updated_count,
                "skipped": skipped,
                "total_fetched": len(users)
            }, status=status.HTTP_200_OK)

        except GraphAPIError as gee:
            logger.exception("Graph API error fetching user info")
            # GraphAPIError expected to have .status_code and .body attributes in your code
            return Response(
                {"status": "error", "graph_status": getattr(gee, "status_code", None), "graph_body": getattr(gee, "body", str(gee))},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            logger.exception("Unexpected error fetching user info: %s", exc)
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        


from django.core.paginator import Paginator
from django.db.models import Q
class meeting_list(APIView):
    def get(self, request):
        # --- SINGLE MEETING by id ---
        meeting_id = request.GET.get("meeting_id")
        if meeting_id:
            try:
                meeting = Meeting.objects.get(pk=meeting_id)
            except Meeting.DoesNotExist:
                return Response({"detail": "Meeting not found"}, status=status.HTTP_404_NOT_FOUND)

            serializer = MeetingSerializer(meeting, many=False)
            return Response({"result": serializer.data}, status=status.HTTP_200_OK)

        # --- LIST view ---
        qs = Meeting.objects.all().order_by('-created_at')

        # --------------------
        # Filters
        # --------------------
        search = request.GET.get("search")
        subject = request.GET.get("subject")
        organizer = request.GET.get("organizer")
        email = request.GET.get("email")
        name = request.GET.get("name")
        date = request.GET.get("date")   # expected format: YYYY-MM-DD

        # TEXT SEARCH (subject & attendees)
        if search:
            qs = qs.filter(
                Q(subject__icontains=search) |
                Q(graph_response__attendees__icontains=search)
            )

        # SUBJECT filter
        if subject:
            qs = qs.filter(subject__icontains=subject)

        # ORGANIZER filter
        if organizer:
            qs = qs.filter(organizer_ad_id__icontains=organizer)

        # FILTER by attendee email (best-effort: JSON contains or plain icontains)
        if email:
            qs = qs.filter(
                Q(graph_response__attendees__icontains=email) |
                Q(graph_response__attendees__contains=[{"emailAddress": {"address": email}}])
            )

        # FILTER by attendee name
        if name:
            qs = qs.filter(
                graph_response__attendees__icontains=name
            )

        # FILTER by DATE (start of meeting)
        if date:
            qs = qs.filter(start__date=date)

        # --------------------
        # Pagination (safe conversion)
        # --------------------
        try:
            page = int(request.GET.get("page", 1))
            if page < 1:
                page = 1
        except (ValueError, TypeError):
            page = 1

        try:
            page_size = int(request.GET.get("page_size", 20))
            if page_size < 1:
                page_size = 20
        except (ValueError, TypeError):
            page_size = 20

        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page)

        # serializer must receive the page object list (not the Paginator page wrapper)
        serializer = MeetingSerializer(page_obj.object_list, many=True)

        return Response({
            "total": paginator.count,
            "page": page_obj.number,
            "page_size": page_size,
            "total_pages": paginator.num_pages,
            "results": serializer.data
        }, status=status.HTTP_200_OK)
     


from django.utils import timezone
from datetime import timezone as dt_timezone
from django.utils.dateparse import parse_datetime

class RescheduleMeetingAPIView(APIView):
    def post(self, request, meeting_id):
        start_iso = request.data.get("start")
        end_iso = request.data.get("end")
        subject = request.data.get("subject", None)

        if not start_iso or not end_iso:
            return Response({"error": "start and end ISO datetimes required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            meeting = Meeting.objects.get(pk=meeting_id)
        except Meeting.DoesNotExist:
            return Response({"error": "meeting not found"}, status=status.HTTP_404_NOT_FOUND)

        # Pull organizer and event id from saved graph_response
        graph_resp = meeting.graph_response or {}
        graph_id = graph_resp.get("id")
        if not graph_id:
            return Response({"error": "no graph id stored for meeting (cannot reschedule)"}, status=status.HTTP_400_BAD_REQUEST)

        organizer = meeting.organizer_ad_id
        graph = GraphService()
        token = graph.get_app_token()

        # Try to update as calendar event first (most common)
        updated_obj = None
        try:
            updated_obj = graph.reschedule_event(token, organizer, graph_id, start_iso, end_iso, subject=subject)
            if updated_obj is None:
                # Graph returned 204: fetch the updated resource
                updated_obj = graph.get_event_for_user(token, organizer, graph_id)
        except GraphAPIError as gee:
            # If 404 for event, maybe this is an onlineMeeting — try onlineMeetings endpoint
            if getattr(gee, "status_code", None) == 404:
                try:
                    updated_obj = graph.reschedule_online_meeting(token, organizer, graph_id, start_iso, end_iso, subject=subject)
                    if updated_obj is None:
                        updated_obj = graph.get_online_meeting(token, organizer, graph_id)
                except GraphAPIError as gee2:
                    logger.exception("Graph error rescheduling onlineMeeting: %s", gee2.body)
                    return Response({"status": "error", "graph_status": gee2.status_code, "graph_body": gee2.body}, status=status.HTTP_502_BAD_GATEWAY)
            else:
                logger.exception("Graph error rescheduling event: %s", gee.body)
                return Response({"status": "error", "graph_status": gee.status_code, "graph_body": gee.body}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            logger.exception("Unexpected error rescheduling: %s", exc)
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # At this point updated_obj should be the latest graph object
        if not updated_obj:
            return Response({"status": "error", "message": "Could not retrieve updated object after patch"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Update Meeting model: graph_response, start, end, subject if present
        try:
            # try to get start/end using common shapes
            s = updated_obj.get("start") or {}
            e = updated_obj.get("end") or {}
            # Graph event shape: start: {"dateTime": "...", "timeZone": "..."}
            start_val = s.get("dateTime") if isinstance(s, dict) else s
            end_val = e.get("dateTime") if isinstance(e, dict) else e

            # If onlineMeeting, check common fields used earlier
            if not start_val:
                # some onlineMeeting resources have startDateTime
                start_val = updated_obj.get("startDateTime") or updated_obj.get("start_time") or start_iso
            if not end_val:
                end_val = updated_obj.get("endDateTime") or updated_obj.get("end_time") or end_iso

            # Parse datetimes to timezone-aware fields for Meeting model
            parsed_start = parse_datetime(start_val) if start_val else None
            parsed_end = parse_datetime(end_val) if end_val else None

            if parsed_start and not timezone.is_aware(parsed_start):
                parsed_start = timezone.make_aware(parsed_start, dt_timezone.utc)

            if parsed_end and not timezone.is_aware(parsed_end):
                parsed_end = timezone.make_aware(parsed_end, dt_timezone.utc)

            meeting.graph_response = updated_obj
            if parsed_start:
                meeting.start = parsed_start
            if parsed_end:
                meeting.end = parsed_end
            if subject:
                meeting.subject = subject
            else:
                # try to update from returned object
                if updated_obj.get("subject"):
                    meeting.subject = updated_obj.get("subject")
            meeting.save()
        except Exception as e:
            logger.exception("Failed to persist updated meeting: %s", e)
            # still return success from Graph but report DB save failed
            return Response({"status": "warning", "message": "rescheduled in Graph but failed saving locally", "graph_updated": updated_obj, "save_error": str(e)}, status=status.HTTP_200_OK)

        return Response({"status": "ok", "graph_updated": updated_obj}, status=status.HTTP_200_OK)
    



class MeetingRecordingFetchAPIView(APIView):
    def get(self, request):
        organizer_email = request.query_params.get("organizer_email")
        meeting_id = request.query_params.get("meeting_id")
        if not organizer_email or not meeting_id:
            return Response({"error": "organizer_email & meeting_id required"}, status=400)

        graph = GraphService()
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr and auth_hdr.lower().startswith("bearer "):
            token = auth_hdr.split(" ", 1)[1].strip()
        else:
            try:
                token = graph.get_app_token()
            except Exception as e:
                return Response({"error": "Failed to get app token", "details": str(e)}, status=500)

        try:
            data = graph.call_recording(token=token, organizer_email=organizer_email, meeting_id=meeting_id)
            return Response({"status": "success", "data": data})
        except GraphAPIError as ge:
            body = getattr(ge, "body", None) or str(ge)
            if isinstance(body, dict) and body.get("error", {}).get("code", "").lower().startswith("invalidauth"):
                return Response({
                    "status": "error",
                    "graph_status": getattr(ge, "status_code", 502),
                    "graph_body": body,
                    "hint": "Token rejected. Check client secret / certificate validity, ensure token 'aud' == 'https://graph.microsoft.com', and that token is not expired. Try get_app_token(force_refresh=True)."
                }, status=502)
            return Response({"status": "error", "graph_status": getattr(ge, "status_code", 502), "graph_body": body}, status=502)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=500)