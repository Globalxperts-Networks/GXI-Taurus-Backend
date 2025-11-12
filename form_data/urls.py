from django.urls import path
from .views import FormDataAPIView  , ScheduleInterviewAPIView, SendWhatsappMessageAPIView
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
    # path("formdata/<int:pk>/generate-cv/", GenerateCVAPIView.as_view(), name="generate-cv"),
]