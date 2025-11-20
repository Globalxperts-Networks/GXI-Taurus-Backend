# views.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .serializers import CreateMeetingSerializer
from .graph_service import GraphService, GraphAPIError
from .models import Meeting

logger = logging.getLogger(__name__)

class CreateOnlineMeetingAPIView(APIView):
    """
    POST endpoint to create an online meeting.
    Accepts JSON:
    {
      "mode": "app" or "delegated",
      "organizer_object_id": "GUID"  # required for app mode
      "start": "2025-11-20T10:00:00Z",
      "end": "2025-11-20T10:30:00Z",
      "subject": "My meeting"
    }
    For delegated mode include Authorization: Bearer <delegated-token> header.
    """

    def post(self, request):
        serializer = CreateMeetingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        mode = data.get("mode", "app")
        start = data["start"].isoformat()
        end = data["end"].isoformat()
        subject = data.get("subject", "Scheduled via API")

        graph = GraphService()  # uses settings

        try:
            if mode == "app":
                organizer = data.get("organizer_object_id")
                if not organizer:
                    return Response({"status": "error", "message": "organizer_object_id is required for app mode"}, status=status.HTTP_400_BAD_REQUEST)

                # get app token
                token = graph.get_app_token()
                # create meeting for specified organizer
                created = graph.create_online_meeting_app(token, organizer, start, end, subject)
                # save record (optional)
                Meeting.objects.create(
                    organizer_ad_id=organizer,
                    subject=subject,
                    start=data["start"],
                    end=data["end"],
                    graph_response=created
                )
                return Response({"status": "success", "meeting": created})

            else:  # delegated
                # delegated token must be provided in Authorization header
                auth_header = request.headers.get("Authorization") or request.META.get("HTTP_AUTHORIZATION")
                if not auth_header or not auth_header.lower().startswith("bearer "):
                    return Response({"status": "error", "message": "Authorization: Bearer <delegated_token> header required for delegated mode"}, status=status.HTTP_401_UNAUTHORIZED)

                delegated_token = auth_header.split(" ", 1)[1].strip()
                created = graph.create_online_meeting_delegated(delegated_token, start, end, subject)
                # organizer info is from the delegated token (Graph returns organizer info)
                organizer_id = created.get("organizer", {}).get("identity", {}).get("user", {}).get("id")
                Meeting.objects.create(
                    organizer_ad_id=organizer_id or "delegated",
                    subject=subject,
                    start=data["start"],
                    end=data["end"],
                    graph_response=created
                )
                return Response({"status": "success", "meeting": created})

        except GraphAPIError as gee:
            logger.exception("Graph API error: %s", gee.body)
            # return Graph error for debugging (sanitize in prod)
            return Response({"status": "error", "graph_status": gee.status_code, "graph_body": gee.body}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return Response({"status": "error", "message": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
