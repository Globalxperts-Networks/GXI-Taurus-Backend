from django.urls import path
from .views import SyncTeamsMembersAPIView
from .meetviews import CreateTeamsMeetingAPIView

urlpatterns = [
    path("data_sync/", SyncTeamsMembersAPIView.as_view()),
    path('create_teams_meeting/', CreateTeamsMeetingAPIView.as_view(), name='create-teams-meeting'),

]
