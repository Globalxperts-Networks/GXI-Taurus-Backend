# serializers.py
from rest_framework import serializers
from .models import Meeting

class CreateMeetingSerializer(serializers.Serializer):
    # for app-only: organizer_object_id required
    organizer_object_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    subject = serializers.CharField(required=False, allow_blank=True)
    # optional flag whether to use app-only or delegated (if delegated, pass Authorization header)
    mode = serializers.ChoiceField(choices=("app", "delegated"), default="app")



class MeetingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Meeting
        fields = '__all__'