from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import Skills , Country , State
from .serializers import  SkillsSerializer , CountryWithStatesSerializer

from rest_framework.parsers import MultiPartParser
from .utils.extractors import extract_text_from_pdf, extract_text_from_docx
from .utils.parser import parse_resume
import json
from .utils.prompt_builder import build_resume_prompt
from .utils.llm_gemini import call_gemini_llm

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
 
class ResumeParserView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("resume")
        if not file:
            return Response({"error": "No file uploaded"}, status=400)

        ext = file.name.split(".")[-1].lower()
        if ext == "pdf":
            text, diag = extract_text_from_pdf(file)
            parsed = {"raw_text": text[:4000]}
        elif ext in ("docx", "doc"):
            text, diag = extract_text_from_docx(file)
            parsed = {"raw_text": text[:4000]}
        else:
            return Response({"error": "Unsupported file type"}, status=400)
        
        parsed_data = parse_resume(text)

        return Response({"response": parsed_data})

class ResumeAIParserView(APIView):
    def post(self, request):
        file = request.FILES.get("resume")
        if not file:
            return Response({"error": "No file uploaded"}, status=400)

        ext = file.name.split(".")[-1].lower()
        file.seek(0)

        if ext == "pdf":
            text, diag = extract_text_from_pdf(file)
        elif ext == "docx":
            text, diag = extract_text_from_docx(file)
        else:
            return Response({"error": "Only PDF and DOCX supported"}, status=400)

        if not isinstance(text, str) or not text.strip():
            return Response({"error": "Could not extract text"}, status=500)

        prompt = build_resume_prompt(text)

        raw_output = call_gemini_llm(prompt)
        print("Gemini Raw Output:", raw_output)


        if isinstance(raw_output, dict) and "error" in raw_output:
            return Response({"error": raw_output["error"]}, status=500)

        raw_text = raw_output  # Gemini returns a plain string

        cleaned = (
            raw_text.replace("```json", "")
                    .replace("```", "")
                    .strip()
        )

        try:
            parsed_json = json.loads(cleaned)
        except Exception as e:
            return Response({
                "error": "Failed to parse JSON",
                "exception": str(e),
                "raw_output": raw_text
            }, status=500)

        return Response({"parsed": parsed_json}, status=200)



class CountryStateListAPI(APIView):
    def get(self, request):
        search_query = request.GET.get('search', None)

        countries = Country.objects.prefetch_related('states').all()

        if search_query:
            countries = countries.filter(Q(country_name__icontains=search_query) |Q(states__state_name__icontains=search_query)).distinct()
        serializer = CountryWithStatesSerializer(countries, many=True).data
        if search_query:
            for country in serializer:
                country["states"] = [
                    st for st in country["states"]
                    if search_query.lower() in st["state_name"].lower()
                ] or country["states"]
        return Response(serializer)