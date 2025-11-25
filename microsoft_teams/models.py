from django.db import models

try:
    from django.db.models import JSONField
except Exception:
    from django.contrib.postgres.fields import JSONField

class Team(models.Model):
    ad_id = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class Member(models.Model):
    ad_id = models.CharField(max_length=200, unique=True)
    display_name = models.CharField(max_length=200)
    email = models.EmailField(null=True, blank=True)
    team = models.ForeignKey(Team, related_name="members", on_delete=models.CASCADE)

    def __str__(self):
        return self.display_name




class Meeting(models.Model):
    organizer_ad_id = models.CharField(max_length=128)   # AD object id of organizer
    subject = models.CharField(max_length=255, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    graph_response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.subject} ({self.organizer_ad_id}) {self.start.isoformat()}"
    


class TeamsUser(models.Model):
    graph_id = models.CharField(max_length=100, unique=True, help_text="Microsoft Graph 'id'")
    display_name = models.CharField(max_length=255, blank=True, null=True)
    given_name = models.CharField(max_length=100, blank=True, null=True)
    surname = models.CharField(max_length=100, blank=True, null=True)
    job_title = models.CharField(max_length=255, blank=True, null=True)
    mail = models.EmailField(max_length=254, blank=True, null=True)
    mobile_phone = models.CharField(max_length=50, blank=True, null=True)
    office_location = models.CharField(max_length=255, blank=True, null=True)
    preferred_language = models.CharField(max_length=50, blank=True, null=True)
    user_principal_name = models.CharField(max_length=254, blank=True, null=True, db_index=True)
    business_phones = JSONField(blank=True, null=True, help_text="Array of phone numbers")
    raw_graph = JSONField(blank=True, null=True, help_text="Full original Graph JSON payload")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Teams User"
        verbose_name_plural = "Teams Users"
        ordering = ["display_name"]
        indexes = [
            models.Index(fields=["user_principal_name"]),
        ]

    def __str__(self):
        return self.display_name or self.user_principal_name or self.graph_id
    