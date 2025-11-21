from django.urls import path
from .views import *
from .meetviews import GoogleAuthInit, GoogleAuthCallback, GoogleTokenStatus, CreateMeetView
# from .cvviews import GenerateCVAPIView

urlpatterns = [
    path('formdata/', FormDataAPIView.as_view(), name='formdata'),
    path('formdata/<int:pk>/', FormDataAPIView.as_view(), name='formdata-detail'),
    path('schedule-interview/', ScheduleInterviewAPIView.as_view(), name='schedule-interview'),
    path('send-whatsapp/<int:form_id>/', SendWhatsappMessageAPIView.as_view(), name='send_whatsapp'),
    path("send-whatsapp/", SendWhatsappMessageAPIView.as_view(), name="get_whatsapp_messages"),
    path("auth/", GoogleAuthInit.as_view()),
    path("callback/", GoogleAuthCallback.as_view()),
    path("token-status/", GoogleTokenStatus.as_view()),
    path("create/", CreateMeetView.as_view()),
    path("send-session-message/<int:form_id>/", SendSessionMessageAPIView.as_view(), name="send_session_message"),
    path("compose-email/<int:pk>/", ComposeMailAPIView.as_view()),
    path('update-email/<int:pk>/', ComposeMailAPIView.as_view(),),
    path("email-messages/<int:pk>/", ComposeMailAPIView.as_view()),
    path("fetch-incoming-emails/", FetchIncomingEmails.as_view()),
    path("hr/compose-email/<int:pk>/", HRComposeMailAPIView.as_view(), name="hr-compose-email"),
    path("hr/incoming-mails/<int:pk>/", FetchIncomingMailAPIView.as_view(), name="hr-incoming-mails"),
    path("hr/chat-history/<int:pk>/", ChatHistoryAPIView.as_view(), name="chat-histor"),

    # path("formdata/<int:pk>/generate-cv/", GenerateCVAPIView.as_view(), name="generate-cv"),
]