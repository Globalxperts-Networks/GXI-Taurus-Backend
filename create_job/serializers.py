# serializers.py
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import Skills, Department, Job_types, Location, Teams, add_job, Question , Country , State,JobSkillPreference
from superadmin.models import UserProfile  # role constants
from microsoft_teams.models import TeamsUser
from microsoft_teams.serializers import TeamsUserSerializer

User = get_user_model()


# ---------- Basic serializers ----------
class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name"]


class SkillsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skills
        fields = ["id", "name"]
        

class Job_typesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job_types
        fields = ["id", "name"]


# ---------- Department (w/ M2M: Location) ----------
class DepartmentSerializer(serializers.ModelSerializer):
    # write-only ids
    location_ids = serializers.PrimaryKeyRelatedField(
        source="Location_types",
        many=True,
        queryset=Location.objects.all(),
        write_only=True,
        required=False,
    )
    # read-only nested
    locations = LocationSerializer(source="Location_types", many=True, read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "locations", "location_ids"]

    def _collect_location_objs(self, validated_data):
        # Case 1: via location_ids (already objects)
        loc_objs = validated_data.pop("Location_types", None)
        if loc_objs is not None:
            return list(loc_objs)

        # Case 2: legacy key Location_types: [ids]
        raw_ids = self.initial_data.get("Location_types", None)
        if raw_ids is None:
            return None

        if not isinstance(raw_ids, (list, tuple)):
            raise serializers.ValidationError({"Location_types": "Must be a list of IDs."})

        qs = Location.objects.filter(id__in=raw_ids).only("id")
        found = list(qs)
        if len(found) != len(set(raw_ids)):
            found_ids = {o.id for o in found}
            missing = [i for i in raw_ids if i not in found_ids]
            raise serializers.ValidationError({"Location_types": f"Invalid IDs: {missing}"})
        return found

    def validate_name(self, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise serializers.ValidationError("Name cannot be empty or whitespace.")
        return normalized

    @transaction.atomic
    def create(self, validated_data):
        loc_objs = self._collect_location_objs(validated_data)
        dept = Department.objects.create(**validated_data)
        if loc_objs is not None:
            dept.Location_types.set(loc_objs)
        return dept

    @transaction.atomic
    def update(self, instance, validated_data):
        loc_objs = self._collect_location_objs(validated_data)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if loc_objs is not None:
            instance.Location_types.set(loc_objs)
        return instance


# ---------- Teams (people fields removed) ----------
class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teams
        fields = [
            "id",
            "name",
            "department_types",
        ]


# ---------- Lightweight user serializer (works with custom user model) ----------
class LiteUserSerializer(serializers.ModelSerializer):
    display = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "display"]

    def get_display(self, obj):
        return str(obj)


# ---------- add_job ----------
class addjobSerializer(serializers.ModelSerializer):
    # --- write-only input fields (IDs) pointing to TeamsUser ---
    teams = serializers.PrimaryKeyRelatedField(
        queryset=Teams.objects.all(), required=False, allow_null=True, write_only=True
    )

    # ✔ back to PK based lookup (integer or UUID PK)
    employments_types = serializers.PrimaryKeyRelatedField(
        queryset=Job_types.objects.all(),
        required=False,
        allow_null=True,
        write_only=True
    )

    posted_by = serializers.PrimaryKeyRelatedField(read_only=True)
    skill_preferences = serializers.ListField(required=False, write_only=True)


    skills_required = serializers.PrimaryKeyRelatedField(
        queryset=Skills.objects.all(), many=True, required=False, write_only=True
    )

    # TeamsUser relations using graph_id Slug
    manager = serializers.SlugRelatedField(
        slug_field='graph_id',
        queryset=TeamsUser.objects.all(),
        allow_null=True, required=False, write_only=True
    )
    hiring_manager = serializers.SlugRelatedField(
        slug_field='graph_id',
        queryset=TeamsUser.objects.all(),
        allow_null=True, required=False, write_only=True
    )
    hr_team_members = serializers.SlugRelatedField(
        slug_field='graph_id',
        queryset=TeamsUser.objects.all(),
        many=True, required=False, write_only=True
    )

    # --- read-only detail fields ---
    teams_detail = serializers.SerializerMethodField()
    employments_types_detail = serializers.SerializerMethodField()
    posted_by_detail = serializers.SerializerMethodField()

    manager_detail = TeamsUserSerializer(source="manager", read_only=True)
    hiring_manager_detail = TeamsUserSerializer(source="hiring_manager", read_only=True)
    hr_team_members_detail = TeamsUserSerializer(source="hr_team_members", many=True, read_only=True)

    skills_details = serializers.SerializerMethodField()
    



    class Meta:
        model = add_job
        fields = "__all__"
        read_only_fields = ("job_id", "created_at", "updated_at", "posted_by")

    # ---------- simple getters ----------
    def get_teams_detail(self, obj):
        if obj.teams:
            return {"id": obj.teams.id, "name": getattr(obj.teams, "name", None)}
        return None

    def get_employments_types_detail(self, obj):
        if obj.employments_types:
            return {"id": obj.employments_types.id, "name": getattr(obj.employments_types, "name", None)}
        return None

    def get_posted_by_detail(self, obj):
        if obj.posted_by:
            u = obj.posted_by
            return {"id": u.id, "email": getattr(u, "email", None), "name": getattr(u, "name", None)}
        return None

    # def get_skills_details(self, obj):
    #     return [
    #         {"id": s.id, "name": getattr(s, "name", None)}
    #         for s in obj.skills_required.all()
    #     ]
    def get_skills_details(self, obj):
        return [
            {
                "id": p.skill.id,
                "name": p.skill.name,
                "must": p.must,
                "good": p.good,
                "rating": p.rating
            }
            for p in obj.skill_preferences.all()
        ]

    # ---------- create / update ----------
    # def create(self, validated_data):
    #     req = self.context.get("request")
    #     if req and getattr(req, "user", None) and req.user.is_authenticated:
    #         validated_data["posted_by"] = req.user
    #     return super().create(validated_data)
    
    def create(self, validated_data):
        skill_pref_list = validated_data.pop("skill_preferences", [])
        m2m_skills = validated_data.pop("skills_required", [])

        req = self.context.get("request")
        if req and req.user.is_authenticated:
            validated_data["posted_by"] = req.user

        job = super().create(validated_data)

        # Save M2M normally
        if m2m_skills:
            job.skills_required.set(m2m_skills)

        # Save skill preferences
        for pref in skill_pref_list:
            JobSkillPreference.objects.create(
                job=job,
                skill=Skills.objects.get(id=pref["skill"]),
                must=pref.get("must", False),
                good=pref.get("good", False),
                rating=pref.get("rating"),
            )

        return job


    def update(self, instance, validated_data):
        validated_data.pop("job_id", None)
        return super().update(instance, validated_data)

    

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = [
            "id",
            "label",
            "question_type",
            "options",
            "required",
            "order",
            "section"
        ]    



class StateListSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ['id', 'state_name', 'short_name']   # added short_name


class CountryWithStatesSerializer(serializers.ModelSerializer):
    states = StateListSerializer(many=True)

    class Meta:
        model = Country
        fields = ['id', 'country_code', 'country_name', 'short_name', 'states'] 