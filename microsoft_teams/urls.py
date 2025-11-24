from django.urls import path
from .views import SyncTeamsMembersAPIView
from .meetviews import  CreateOnlineMeetingAPIView, CreateEventAPIView , teams_user , meeting_list , RescheduleMeetingAPIView

urlpatterns = [
    path("data_sync/", SyncTeamsMembersAPIView.as_view()),
    path('create_teams_meeting/', CreateOnlineMeetingAPIView.as_view(), name='create-teams-meeting'),
    path('create_event/', CreateEventAPIView.as_view(), name='create-event'),
    path('teams_user/', teams_user.as_view(), name='teams-user'),
    path('meetings/', meeting_list.as_view(), name='meeting-list'),
    path('reschedule_meeting/<int:meeting_id>/', RescheduleMeetingAPIView.as_view(), name='reschedule-meeting'),

]
