from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Team, Member
from .graph_service import GraphService
from django.conf import settings

class SyncTeamsMembersAPIView(APIView):
    def get(self, request):
        graph = GraphService(
            settings.AZURE_TENANT_ID,
            settings.AZURE_CLIENT_ID,
            settings.AZURE_CLIENT_SECRET
        )

        token = graph.get_token()

        teams_data = graph.get_teams(token).get("value", [])

        all_synced = []

        for t in teams_data:
            team_obj, created = Team.objects.update_or_create(
                ad_id=t["id"],
                defaults={"name": t["displayName"]}
            )

            members_data = graph.get_team_members(token, t["id"]).get("value", [])

            for m in members_data:
                Member.objects.update_or_create(
                    ad_id=m["id"],
                    defaults={
                        "display_name": m.get("displayName", ""),
                        "email": m.get("mail", None),
                        "team": team_obj
                    }
                )

            all_synced.append(team_obj.name)

        return Response({
            "status": "success",
            "total_teams_synced": len(all_synced),
            "teams": all_synced
        })
