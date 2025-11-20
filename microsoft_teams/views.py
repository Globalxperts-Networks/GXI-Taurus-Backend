# views.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from .graph_service import GraphService, GraphAPIError
from .models import Team, Member

logger = logging.getLogger(__name__)

class SyncTeamsMembersAPIView(APIView):
    """
    Sync Teams and Members from Microsoft Graph into local Team/Member models.
    """

    def get(self, request):
        try:
            # Option A: let GraphService read settings internally (recommended)
            graph = GraphService()

            # Option B: explicit (also supported)
            # graph = GraphService(settings.AZURE_TENANT_ID, settings.AZURE_CLIENT_ID, settings.AZURE_CLIENT_SECRET)

            # Get token (cached by GraphService)
            token = graph.get_token()

            # Debug: log token claims (safe to log claims; never log client_secret)
            claims = graph.decode_jwt_no_verify(token)
            logger.info("Graph token claims: %s", claims)

            # Fetch all teams (teams are groups whose resourceProvisioningOptions contains 'Team')
            teams_resp = graph.get_teams(token)
            teams_data = teams_resp.get("value", [])

            synced = []
            for t in teams_data:
                # Defensive access to fields
                ad_id = t.get("id")
                display_name = t.get("displayName", "") or t.get("display_name", "")
                if not ad_id:
                    logger.warning("Skipping team with missing id: %s", t)
                    continue

                team_obj, created = Team.objects.update_or_create(
                    ad_id=ad_id,
                    defaults={"name": display_name}
                )

                # Get members for this team (handles paging)
                members_resp = graph.get_team_members(token, ad_id)
                members_data = members_resp.get("value", [])

                for m in members_data:
                    member_ad_id = m.get("id")
                    if not member_ad_id:
                        logger.warning("Skipping member missing id: %s", m)
                        continue

                    # Try to pick a reasonable email (mail or userPrincipalName)
                    email = m.get("mail") or m.get("userPrincipalName")
                    display_name = m.get("displayName", "") or m.get("givenName", "")

                    Member.objects.update_or_create(
                        ad_id=member_ad_id,
                        defaults={
                            "display_name": display_name,
                            "email": email,
                            "team": team_obj
                        }
                    )

                synced.append(team_obj.name)

            return Response({
                "status": "success",
                "total_teams_synced": len(synced),
                "teams": synced
            })

        except GraphAPIError as gee:
            # Graph returned non-2xx — capture JSON body and status
            logger.exception("Graph API returned an error: %s", gee.body)
            # return Graph's error body to client for debugging (careful in prod)
            return Response({
                "status": "error",
                "message": "Graph API error",
                "graph_status": gee.status_code,
                "graph_body": gee.body
            }, status=status.HTTP_gee.status_code if hasattr(status, 'HTTP_{}'.format(gee.status_code)) else status.HTTP_502_BAD_GATEWAY)

        except Exception as exc:
            logger.exception("Unexpected error syncing teams/members: %s", exc)
            return Response({
                "status": "error",
                "message": str(exc)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
