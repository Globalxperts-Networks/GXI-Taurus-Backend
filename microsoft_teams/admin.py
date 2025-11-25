from django.contrib import admin
from .models import Team, Member , Meeting , TeamsUser

# Register your models here.
admin.site.register(Team)
admin.site.register(Member)
admin.site.register(Meeting)
admin.site.register(TeamsUser)
