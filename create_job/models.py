from django.db import models
from django.core.validators import MinValueValidator
from django.conf import settings
from django.core.exceptions import ValidationError
from superadmin.models import UserProfile  # just for role constants
from microsoft_teams.models import TeamsUser


# Optional reusable timestamp mixin (left as-is per your code)
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class Location(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'locations'
        ordering = ["name"]


class Skills(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'skills'
        ordering = ["name"]


class Department(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    # Renamed field variable for clarity, keeps your table and relation intact
    Location_types = models.ManyToManyField(
        Location,
        related_name='departments',
        blank=True
    )

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'Departments'
        ordering = ["name"]


class Teams(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    department_types = models.ForeignKey(
        'Department',
        on_delete=models.CASCADE,
        db_index=True,
        null=True,
        blank=True,
        related_name='teams'
    )

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'Teams'
        ordering = ["name"]


class Job_types(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True, db_index=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'Job_types'
        ordering = ["name"]


class add_job(TimeStampedModel):
    title = models.CharField(max_length=255, db_index=True)
    job_id = models.CharField(max_length=20, unique=True, db_index=True, editable=False)
    Description = models.TextField()
    Salary_range = models.CharField(max_length=100, db_index=True)
    Experience_required = models.CharField(max_length=100, db_index=True)
    no_opening = models.PositiveIntegerField(validators=[MinValueValidator(1)], db_index=True)
    skills_required = models.ManyToManyField(Skills, related_name='jobs', blank=True)
    last_hiring_date = models.DateField(null=True, blank=True, db_index=True)
    teams = models.ForeignKey(Teams,on_delete=models.CASCADE,null=True,blank=True,related_name='jobs',db_index=True)
    posted_by = models.ForeignKey(TeamsUser,on_delete=models.SET_NULL,null=True,blank=True,related_name='posted_jobs',db_index=True)
    employments_types = models.ForeignKey(Job_types,on_delete=models.CASCADE,null=True,blank=True,related_name='jobs',db_index=True)
    manager = models.ForeignKey(TeamsUser,on_delete=models.SET_NULL,null=True,blank=True,related_name='jobs_managed',db_index=True)
    hiring_manager = models.ForeignKey(TeamsUser,on_delete=models.SET_NULL,null=True,blank=True,related_name='jobs_as_hiring_manager',db_index=True)
    hr_team_members = models.ManyToManyField(TeamsUser,related_name='jobs_as_hr')
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    def save(self, *args, **kwargs):
        if not self.job_id:
            last_job = add_job.objects.all().order_by('-id').first()
            if last_job and last_job.job_id:
                try:
                    last_number = int(last_job.job_id.replace('GXI', ''))
                except ValueError:
                    last_number = 1000
                new_number = last_number + 1
            else:
                new_number = 1001

            self.job_id = f"GXI{new_number}"

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.job_id})"

    class Meta:
        db_table = 'add_job'
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=['title', 'is_active']),
            models.Index(fields=['job_id', 'is_active']),
            models.Index(fields=['teams', 'is_active']),
            models.Index(fields=['employments_types', 'is_active']),
            models.Index(fields=['Salary_range', 'Experience_required']),
            models.Index(fields=['created_at', 'updated_at']),
            models.Index(fields=['manager', 'is_active']),
            models.Index(fields=['hiring_manager', 'is_active']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['job_id'], name='unique_job_id_constraint'),
        ]

class JobSkillPreference(models.Model):
    job = models.ForeignKey("add_job", on_delete=models.CASCADE,related_name="skill_preferences")
    skill = models.ForeignKey("Skills", on_delete=models.CASCADE)
    must = models.BooleanField(default=False)
    good = models.BooleanField(default=False)
    rating = models.PositiveIntegerField(null=True, blank=True)  # only if good

    def __str__(self):
        return self.skill.name


class Question(models.Model):

    QUESTION_TYPES = [
        ("text", "Text Input"),
        ("textarea", "Textarea"),
        ("number", "Number Input"),
        ("radio", "Radio Options"),
        ("select", "Dropdown Select"),
        ("multiselect", "Multiselect"),
        ("slider", "Slider"),
        ("checkbox", "Checkbox"),
        ("file", "File Upload"),
    ]

    label = models.CharField(max_length=255)
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    options = models.JSONField(null=True, blank=True)
    required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)
    jobs = models.ManyToManyField(add_job, related_name="questions")
    section = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.label



class Country(models.Model):
    country_code = models.CharField(max_length=10,)
    country_name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.country_name
    
    class meta:
        verbose_name = "Country"
        verbose_name_plural = "Countries"
        ordering = ["country_name"]


class State(models.Model):
    state_name = models.CharField(max_length=100)
    country = models.ForeignKey(Country, related_name='states', on_delete=models.CASCADE)
    short_name = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.state_name} ({self.country.country_name})"
    

    class meta:
        verbose_name = "State"
        verbose_name_plural = "States"
        ordering = ["state_name"]