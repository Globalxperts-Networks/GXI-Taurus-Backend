from django.urls import path
from .views import SyncTeamsMembersAPIView
from .meetviews import  CreateOnlineMeetingAPIView, CreateEventAPIView , teams_user

urlpatterns = [
    path("data_sync/", SyncTeamsMembersAPIView.as_view()),
    path('create_teams_meeting/', CreateOnlineMeetingAPIView.as_view(), name='create-teams-meeting'),
    path('create_event/', CreateEventAPIView.as_view(), name='create-event'),
    path('teams_user/', teams_user.as_view(), name='teams-user'),

]
