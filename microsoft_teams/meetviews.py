# adsync/views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.core.mail import EmailMessage
from django.conf import settings
from .graph_service import GraphService
import traceback
import requests 

class CreateTeamsMeetingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        mode = data.get('mode', 'onlineMeeting')
        subject = data.get('subject', 'Teams Meeting')
        start = data.get('start')
        end = data.get('end')
        attendees = data.get('attendees', [])
        send_email = data.get('send_email', False)
        to_emails = data.get('to_emails', [])
        cc_emails = data.get('cc_emails', [])
        email_message = data.get('email_message', '')

        gs = GraphService()

        try:
            if mode == 'onlineMeeting':
                user_object_id = data.get('user_object_id')
                if not user_object_id:
                    return Response({'error': 'user_object_id is required for onlineMeeting mode'}, status=status.HTTP_400_BAD_REQUEST)
                resp = gs.create_online_meeting_as_app(user_object_id, subject, start, end)
                join_url = resp.get('joinWebUrl') or resp.get('joinUrl') or resp.get('conferenceId')
                result = {'mode': 'onlineMeeting', 'graph_response': resp}

            else:  # calendarEvent
                user_principal_name = data.get('user_principal_name')
                if not user_principal_name:
                    return Response({'error': 'user_principal_name is required for calendarEvent mode'}, status=status.HTTP_400_BAD_REQUEST)
                resp = gs.create_calendar_event_with_teams(user_principal_name, subject, start, end, attendees)
                # join url may be at resp['onlineMeeting']['joinUrl'] or resp['onlineMeeting']['joinUrl'] in some tenants
                join_url = None
                if isinstance(resp, dict):
                    om = resp.get('onlineMeeting') or resp.get('onlineMeeting')
                    if om and isinstance(om, dict):
                        join_url = om.get('joinUrl') or om.get('joinWebUrl')
                    # fallback common place:
                    join_url = join_url or resp.get('onlineMeetingUrl') or resp.get('onlineMeeting', {}).get('joinUrl')
                result = {'mode': 'calendarEvent', 'graph_response': resp}

            # if still not found, try common field names
            if not join_url:
                # attempt a few common keys
                join_url = (resp.get('joinWebUrl') if isinstance(resp, dict) else None) \
                           or (resp.get('joinUrl') if isinstance(resp, dict) else None) \
                           or (resp.get('onlineMeeting', {}).get('joinUrl') if isinstance(resp, dict) else None)

            # Send email if requested
            if send_email and to_emails:
                if not join_url:
                    # include graph response if no join url
                    email_body = f"{email_message}\n\nMeeting created but join url not found. Graph response:\n\n{resp}"
                else:
                    email_body = f"{email_message}\n\nJoin Teams Meeting: {join_url}\n\nRegards,"
                try:
                    email = EmailMessage(
                        subject=subject,
                        body=email_body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=to_emails,
                        cc=cc_emails
                    )
                    email.send(fail_silently=False)
                    result['email_sent'] = True
                except Exception as e:
                    result['email_sent'] = False
                    result['email_error'] = str(e)

            # return clean response
            result['join_url'] = join_url
            return Response(result)

        except requests.HTTPError as e:
            tb = traceback.format_exc()
            return Response({'error': 'graph_http_error', 'detail': str(e), 'trace': tb}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            tb = traceback.format_exc()
            return Response({'error': 'unexpected_error', 'detail': str(e), 'trace': tb}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
