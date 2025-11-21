from django.contrib import admin
from .models import  UserProfile,EmailConfig

# Register your models here.

admin.site.register(UserProfile)
admin.site.register(EmailConfig)