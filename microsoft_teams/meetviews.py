# meetviews.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from .graph_service import GraphService, GraphAPIError
from .models import Meeting
from .serializers import MeetingSerializer

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
        

class teams_user(APIView):
    def get(self, request):
        graph = GraphService()
        try:
            token = graph.get_app_token()

            # read query params (safe parsing)
            top_q = request.query_params.get("top", "200")
            try:
                top = int(top_q)
            except (TypeError, ValueError):
                top = 200

            fetch_all_q = request.query_params.get("fetch_all", "false").lower()
            fetch_all = fetch_all_q in ("1", "true", "yes", "y")

            user_info = graph.user_list(token=token, top=top, fetch_all=fetch_all)

            return Response({"status": "success", "user": user_info}, status=status.HTTP_200_OK)

        except GraphAPIError as gee:
            logger.exception("Graph API error fetching user info")
            return Response(
                {"status": "error", "graph_status": gee.status_code, "graph_body": gee.body},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            logger.exception("Unexpected error fetching user info: %s", exc)
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        


class meeting_list(APIView):
    def get(self, request):
        meetings = Meeting.objects.all().order_by('-created_at')[:50]
        serializer = MeetingSerializer(meetings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)