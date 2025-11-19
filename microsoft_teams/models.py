from django.db import models

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
