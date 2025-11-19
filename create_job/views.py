from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import Skills
from .serializers import  SkillsSerializer


# -------------------- SKILLS API --------------------
class SkillsAPIView(APIView):
    def get(self, request, pk=None):
        if pk:
            skill = get_object_or_404(Skills, pk=pk)
            serializer = SkillsSerializer(skill)
        else:
            skills = Skills.objects.all()
            serializer = SkillsSerializer(skills, many=True)
        return Response({"status": "success", "data": serializer.data})

    def post(self, request):
        serializer = SkillsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"status": "success", "message": "Skill created", "data": serializer.data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        skill = get_object_or_404(Skills, pk=pk)
        serializer = SkillsSerializer(skill, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success", "message": "Skill updated", "data": serializer.data})
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        skill = get_object_or_404(Skills, pk=pk)
        skill.delete()
        return Response({"status": "success", "message": "Skill deleted"})



from .models import Question, add_job
from .serializers import QuestionSerializer

class JobQuestionsAPIView(APIView):
    def get(self, request, job_id):
        # return Response({"status": "success", "message": "Fetching job questions"}, status=status.HTTP_200_OK)
        try:
            job = add_job.objects.get(id=job_id)
        except add_job.DoesNotExist:
            return Response(
                {"error": "Job/Role does not exist"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        questions = Question.objects.filter(jobs=job).order_by("order")

        serializer = QuestionSerializer(questions, many=True)
        return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)
 
