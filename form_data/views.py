import json
import logging
from functools import reduce
from operator import or_
import json

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils.html import strip_tags

from .models import FormData
from .serializers import FormDataSerializer
from rest_framework.parsers import MultiPartParser, FormParser
from django.core.files.storage import FileSystemStorage

logger = logging.getLogger(__name__)


class FormDataAPIView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    def send_status_email(self, candidate_email, candidate_name, current_status, phase=None,
                          interview_date=None, interview_time=None, joining_date=None, is_new_candidate=False):
        if not candidate_email:
            return

        if is_new_candidate:
            template_name = "application_welcome.html"
            subject = "Thank You For Applying - GXI Networks"
        else:
            template_name = "application_status.html"
            subject = f"Update: Your Application Status - {current_status}"

        context = {
            "candidate_name": candidate_name,
            "current_status": current_status,
            "phase": phase,
            "interview_date": interview_date,
            "interview_time": interview_time,
            "joining_date": joining_date,
        }

        html_message = render_to_string(template_name, context)
        text_message = strip_tags(html_message) if html_message else "Your application status has been updated."

        try:
            send_mail(
                subject=subject,
                message=text_message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "",
                recipient_list=[candidate_email],
                html_message=html_message,
                fail_silently=False,
            )
        except Exception as e:
            # Log error; do not raise to keep API flow stable
            logger.exception("Failed to send status email to %s: %s", candidate_email, str(e))

    def get(self, request, pk=None):
        try:
            if pk:
                form = FormData.objects.filter(id=pk).first()
                if not form:
                    return Response({"status": "error", "message": "Record not found"},
                                    status=status.HTTP_404_NOT_FOUND)
                serializer = FormDataSerializer(form)
                return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

            search_query = request.query_params.get('search', None)
            form_name = request.query_params.get('form_name', None)
            sort_by = request.query_params.get('sort_by', '-submitted_at')

            role_type_param = request.query_params.get('role_type')  # comma separated
            role_type_exact = request.query_params.get('role_type_exact', 'false').lower() in ('1', 'true', 'yes')

            forms = FormData.objects.all()

            if form_name:
                forms = forms.filter(form_name__icontains=form_name)

            if search_query:
                forms = forms.filter(
                    Q(form_name__icontains=search_query) |
                    Q(submission_data__icontains=search_query)
                )

            # -------------------------------------
            # ROLE TYPE FILTER (CASE-INSENSITIVE)
            # -------------------------------------
            if role_type_param:
                role_types = [rt.strip() for rt in role_type_param.split(',') if rt.strip()]

                if role_types:
                    if role_type_exact:
                        # CASE-INSENSITIVE EXACT MATCH
                        conds = [
                            Q(submission_data__Role_Type__iexact=rt)
                            for rt in role_types
                        ]
                    else:
                        # CASE-INSENSITIVE CONTAINS MATCH
                        conds = [
                            Q(submission_data__Role_Type__icontains=rt)
                            for rt in role_types
                        ]

                    forms = forms.filter(reduce(or_, conds))

            valid_sort_fields = ['form_name', 'submitted_at']
            if sort_by.lstrip('-') not in valid_sort_fields:
                sort_by = '-submitted_at'
            forms = forms.order_by(sort_by)

            page = request.query_params.get('page', 1)
            page_size = int(request.query_params.get('page_size', 25))
            paginator = Paginator(forms, page_size)

            try:
                forms_page = paginator.page(page)
            except PageNotAnInteger:
                forms_page = paginator.page(1)
            except EmptyPage:
                forms_page = paginator.page(paginator.num_pages)

            serializer = FormDataSerializer(forms_page, many=True)

            return Response({
                "status": "success",
                "total_records": paginator.count,
                "total_pages": paginator.num_pages,
                "current_page": forms_page.number,
                "page_size": page_size,
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("GET FormData error: %s", str(e))
            return Response({"status": "error", "message": f"An error occurred: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    # ================================
    # POST METHOD
    # ================================
    def post(self, request):
        submission_data_raw = request.data.get("submission_data")
       

        # Convert JSON string from multipart form
        if isinstance(submission_data_raw, str):
            try:
                submission_data = json.loads(submission_data_raw)
            except Exception as e:
                return Response(
                    {"error": "Invalid JSON in submission_data", "details": str(e)},
                    status=400
                )
        elif isinstance(submission_data_raw, dict):
            submission_data = submission_data_raw
        else:
            submission_data = {}

        data = request.data.copy()

        # 🔥 Convert dict → JSON string for serializer
        data["submission_data"] = json.dumps(submission_data)

        serializer = FormDataSerializer(data=data)

        if serializer.is_valid():
            candidate_email = submission_data.get("Email")
            is_new = not FormData.objects.filter(
                submission_data__Email=candidate_email
            ).exists()

            form_obj = serializer.save()
            submission = form_obj.submission_data  # Python dict (auto parsed)

            self.send_status_email(
                candidate_email=submission.get("Email"),
                candidate_name=submission.get("Name"),
                current_status=submission.get("status", "Applied"),
                phase=submission.get("phase"),
                interview_date=submission.get("interview_time"),
                interview_time=submission.get("interview_time"),
                joining_date=submission.get("joining_date"),
                is_new_candidate=is_new
            )

            return Response({
                "status": "success",
                "message": "Form data saved successfully",
                "data": serializer.data
            }, status=201)

        return Response({
            "status": "error",
            "errors": serializer.errors
        }, status=400)

    # ================================
    # PUT METHOD (update status / notes)
    # ================================
    def put(self, request, pk):
        new_status = request.data.get("status")
        reject_reason = request.data.get("reject_reason")
        interview_date = request.data.get("interview_date")
        interview_time = request.data.get("interview_time")
        offer_letter_date = request.data.get("offer_letter_date")
        joining_date = request.data.get("joining_date")
        phase = request.data.get("phase")
        note = request.data.get("note")

        ts = timezone.now().isoformat()

        with transaction.atomic():
            try:
                form = FormData.objects.select_for_update().get(pk=pk)
            except FormData.DoesNotExist:
                return Response({"status": "error", "message": "Record not found"}, status=status.HTTP_404_NOT_FOUND)

            submission_data = form.submission_data or {}
            old_status = submission_data.get("status", "Scouting")

            candidate_name = submission_data.get("Name")
            candidate_email = submission_data.get("Email")

            # === NOTES: Always allow adding/updating notes regardless of status ===
            note_was_added = False
            if note:
                submission_data.setdefault("notes_history", []).append({
                    "note": note,
                    "updated_at": ts
                })
                submission_data["note"] = note
                note_was_added = True

            # If either no status provided, or same as current => save note only (if any) and return
            if (new_status is None) or (new_status == old_status):
                form.submission_data = submission_data
                form.save()
                serializer = FormDataSerializer(form)
                return Response({
                    "status": "success",
                    "message": f"Update saved (status unchanged: {submission_data.get('status')}).",
                    "data": serializer.data
                }, status=status.HTTP_200_OK)

            # Disallow changes after Reject/Hired
            if old_status == "Reject":
                return Response({"status": "error", "message": "Cannot change status after rejection."},
                                status=status.HTTP_400_BAD_REQUEST)
            if old_status == "Hired":
                return Response({"status": "error", "message": "Candidate already hired. No further changes allowed."},
                                status=status.HTTP_400_BAD_REQUEST)

            # Now process transitions
            # === SCOUTING ===
            if old_status == "Scouting":
                if new_status == "Reject":
                    if not reject_reason:
                        return Response({"status": "error", "message": "Reject reason required when rejecting from Scouting."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    submission_data.setdefault("status_history", []).append({
                        "from": old_status,
                        "to": "Reject",
                        "reason": reject_reason,
                        "updated_at": ts
                    })
                    submission_data["status"] = "Reject"
                    submission_data["reject_reason"] = reject_reason

                    self.send_status_email(candidate_email, candidate_name, "Reject")

                elif new_status == "Ongoing":
                    if not (interview_date or interview_time):
                        return Response({"status": "error", "message": "Interview date and/or time required to move to Ongoing."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    submission_data.setdefault("status_history", []).append({
                        "from": old_status,
                        "to": "Ongoing",
                        "phase": phase or "First Round",
                        "interview_date": interview_date,
                        "interview_time": interview_time,
                        "updated_at": ts
                    })
                    submission_data["status"] = "Ongoing"
                    submission_data["phase"] = phase or "First Round"
                    if interview_date:
                        submission_data["interview_date"] = interview_date
                    if interview_time:
                        submission_data["interview_time"] = interview_time

                    self.send_status_email(candidate_email, candidate_name, "Ongoing", phase, interview_date, interview_time)

                else:
                    return Response({"status": "error", "message": "Invalid transition from Scouting. Must be 'Ongoing' or 'Reject'."},
                                    status=status.HTTP_400_BAD_REQUEST)

            # === ONGOING ===
            elif old_status == "Ongoing":
                if new_status == "Hired":
                    if not (offer_letter_date and joining_date):
                        return Response({"status": "error", "message": "Offer letter date and joining date required to mark as Hired."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    submission_data.setdefault("status_history", []).append({
                        "from": "Ongoing",
                        "to": "Hired",
                        "offer_letter_date": offer_letter_date,
                        "joining_date": joining_date,
                        "updated_at": ts
                    })
                    submission_data["status"] = "Hired"
                    submission_data["offer_letter_date"] = offer_letter_date
                    submission_data["joining_date"] = joining_date
                    submission_data["phase"] = "Final Selection"

                    self.send_status_email(candidate_email, candidate_name, "Hired", "Final Selection", joining_date=joining_date)

                elif new_status == "Reject":
                    if not reject_reason:
                        return Response({"status": "error", "message": "Reject reason required when rejecting from Ongoing."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    submission_data.setdefault("status_history", []).append({
                        "from": "Ongoing",
                        "to": "Reject",
                        "reason": reject_reason,
                        "updated_at": ts
                    })
                    submission_data["status"] = "Reject"
                    submission_data["reject_reason"] = reject_reason

                    self.send_status_email(candidate_email, candidate_name, "Reject")

                elif new_status == "Ongoing":
                    # Update schedule/phase while keeping status the same
                    history_entry = {
                        "from": "Ongoing",
                        "to": "Ongoing",
                        "phase": phase or submission_data.get("phase", "Next Round"),
                        "updated_at": ts
                    }
                    if interview_date:
                        submission_data["interview_date"] = interview_date
                        history_entry["interview_date"] = interview_date
                    if interview_time:
                        submission_data["interview_time"] = interview_time
                        history_entry["interview_time"] = interview_time

                    submission_data.setdefault("status_history", []).append(history_entry)
                    submission_data["status"] = "Ongoing"
                    submission_data["phase"] = phase or submission_data.get("phase", "Next Round")

                    self.send_status_email(candidate_email, candidate_name, "Ongoing", phase, interview_date, interview_time)

                else:
                    return Response({"status": "error", "message": f"Invalid transition from Ongoing to {new_status}."},
                                    status=status.HTTP_400_BAD_REQUEST)

            else:
                return Response({"status": "error", "message": f"Unhandled current status: {old_status}."},
                                status=status.HTTP_400_BAD_REQUEST)

            # Persist changes
            form.submission_data = submission_data
            form.save()

            serializer = FormDataSerializer(form)
            return Response({
                "status": "success",
                "message": f"Status updated successfully (current: {submission_data.get('status')}, phase: {submission_data.get('phase')})",
                "data": serializer.data
            }, status=status.HTTP_200_OK)




from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.core.mail import send_mail
from .serializers import FormDataSerializer
from .utils import create_teams_meeting

class ScheduleInterviewAPIView(APIView):
    def post(self, request):
        serializer = FormDataSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data

            candidate_email = data.get("candidate_email")
            interviewer_email = data.get("interviewer_email")
            start_time = data.get("meeting_start").isoformat()
            end_time = data.get("meeting_end").isoformat()

            try:
                meeting = create_teams_meeting(
                    subject=f"Interview - {data.get('form_name')}",
                    start_time=start_time,
                    end_time=end_time,
                    organizer_email=interviewer_email
                )

                meeting_link = meeting["joinWebUrl"]

                form_instance = serializer.save(submission_data=data, form_name=data.get('form_name'))

                # Send meeting link to both candidate and interviewer
                subject = "Microsoft Teams Interview Scheduled"
                message = (
                    f"Dear Candidate,\n\n"
                    f"Your interview has been scheduled.\n"
                    f"Join via Microsoft Teams using the link below:\n\n"
                    f"{meeting_link}\n\n"
                    f"Meeting Time: {start_time} to {end_time}\n\n"
                    f"Regards,\nHR Team"
                )

                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [candidate_email, interviewer_email]
                )

                return Response({
                    "message": "Meeting created successfully!",
                    "meeting_link": meeting_link
                }, status=status.HTTP_201_CREATED)

            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from django.shortcuts import get_object_or_404
from .wati_service import WatiService

class SendWhatsappMessageAPIView(APIView):

    wati = WatiService()

    def post(self, request, form_id):
        form_data = get_object_or_404(FormData, id=form_id)
        serializer = FormDataSerializer(form_data)
        submission = serializer.data["submission_data"]

        phone = submission.get("Phone")
        name = submission.get("Name", "there")
        role_taurus = submission.get("Role_Type", "N/A")
        status_taurus = submission.get("status", "N/A")

        parameters = [
            {"name": "name", "value": name},
            {"name": "role_taurus", "value": role_taurus},
            {"name": "status_taurus", "value": status_taurus},
        ]

        result = self.wati.send_template_message(
            phone=phone,
            template_name="candidate_application_status_taurus_testing_phase",
            parameters=parameters,
            broadcast_name="candidate_application_status_taurus_testing_phase_131120251013",
        )

        if result["success"]:
            return Response(
                {
                    "message": "WhatsApp message sent successfully!",
                    "wati_response": result["response"],
                    "data": serializer.data
                },
                status=status.HTTP_200_OK
            )
        else:
            return Response(
                {
                    "message": "Failed to send WhatsApp message",
                    "error": result["error"],
                    "detail": result.get("details")
                },
                status=status.HTTP_200_OK
            )

    def get(self, request):
        phone = request.query_params.get("phone")
        if not phone:
            return Response(
                {"error": "Missing 'phone' query parameter."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = self.wati.get_messages(phone)
        if result["success"]:
            return Response(
                {
                    "message": "Messages fetched successfully.",
                    "data": result["response"],
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {
                    "message": "Failed to fetch WhatsApp messages.",
                    "error": result["error"],
                    "details": result.get("details"),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )


class SendSessionMessageAPIView(APIView):
    wati = WatiService()
    def post(self, request, form_id):
        form_data = get_object_or_404(FormData, id=form_id)
        serializer = FormDataSerializer(form_data)
        submission = serializer.data["submission_data"]

        phone = submission.get("Phone")
        message_text = request.data.get("message")

        if not phone or not message_text:
            return Response(
                {"error": "Missing phone or message"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = self.wati.send_session_message(phone, message_text)
        return Response(
            result if result["success"] else {"message": "Failed to send", **result},
            status=status.HTTP_200_OK if result["success"] else status.HTTP_502_BAD_GATEWAY,
        )

def send_composed_email(to_email, cc_emails, subject, message):
    try:
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email='',
            to=[to_email],
            cc=cc_emails,
        )

        email.content_subtype = "html"   # if message contains HTML tags
        email.send()
        return True

    except Exception as e:
        print(f"⚠️ Email sending failed: {e}")
        return False


class ComposeMailAPIView(APIView):
    def post(self, request, pk):
        cc_emails = request.data.get("cc_emails", "")
        message = request.data.get("message")
        attachment_file = request.FILES.get("attachment")
 
        cc_list = [email.strip() for email in cc_emails.split(",") if email.strip()]
 
        # Fetch FormData using pk from URL
        try:
            form_obj = FormData.objects.get(pk=pk)
        except FormData.DoesNotExist:
            return Response(
                {"status": "error", "message": "Record not found"},
                status=status.HTTP_404_NOT_FOUND
            )
 
        submission = form_obj.submission_data
        candidate_email = submission.get("Email")
        role = submission.get("Role_Type", "Not Provided")
        current_status = submission.get("status", "Unknown")
 
        # Replace placeholders dynamically in message
        subject = f"Role: {role} | Status: {current_status}"
        message = message.format(
            candidate_name=submission.get("Name"),
            status=current_status,
            phone=submission.get("Phone"),
            role=submission.get("Role_Type")
        )
        saved_file_path = None
 
        if attachment_file:
            fs = FileSystemStorage(location='media/email_attachments/')
            saved_name = fs.save(attachment_file.name, attachment_file)
            saved_file_path = f"email_attachments/{saved_name}"  # relative path to media
 
        # =============================================
        # ⭐ UPDATE submission_data JSON STRUCTURE
        # =============================================
        email_log = {
            "subject": subject,
            "message": message,
            "cc": cc_list,
            "attachments": [saved_file_path] if saved_file_path else []
        }
        if "email_message" not in submission or not isinstance(submission["email_message"], list):
            submission["email_message"] = []
 
        # Append new email message entry
        submission["email_message"].append(email_log)
 
       
        # SAVE MESSAGE IN DATABASE
        form_obj.submission_data = submission
        form_obj.save()
        # Send email
        send_composed_email(
            to_email=candidate_email,
            cc_emails=cc_list,
            subject=subject,
            message=message,
            attachment_file=attachment_file,
        )
 
        return Response({"message": "Email sent successfully!"})
    
    
    def put(self, request, pk):

        cc_emails = request.data.get("cc_emails", "")
        message = request.data.get("message")

        # Build CC list
        cc_list = [email.strip() for email in cc_emails.split(",") if email.strip()]

        # Fetch FormData record
        try:
            form_obj = FormData.objects.get(pk=pk)
        except FormData.DoesNotExist:
            return Response(
                {"status": "error", "message": "Record not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        submission = form_obj.submission_data

        # Extract fields
        role = submission.get("Role_Type", "")
        current_status = submission.get("status", "")
        name = submission.get("Name", "")
        email = submission.get("Email", "")

        # Dynamic subject
        subject = f"Role: {role} | Status: {current_status}"

        # Replace message placeholders
        message = message.format(
            candidate_name=name,
            status=current_status,
            role=role,
            phone=submission.get("Phone")
        )

        # Send email
        send_composed_email(
            to_email=email,
            cc_emails=cc_list,
            subject=subject,
            message=message
        )

        return Response({"message": "Email updated successfully "})
    


from .resume_parser import parse_resume

class ResumeParseAPIView(APIView):
    def post(self, request):
        f = request.FILES.get("resume")
        if not f:
            return Response({"error": "Please upload a file under the key 'resume'."}, status=status.HTTP_400_BAD_REQUEST)

        max_mb = 10
        if getattr(f, "size", 0) > max_mb * 1024 * 1024:
            return Response({"error": f"File too large. Max {max_mb} MB allowed."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = parse_resume(f, f.name)
            return Response({"success": True, "response": result}, status=status.HTTP_200_OK)
        except Exception as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from .csv_reader import get_or_create_job_by_title
from create_job.models import add_job
from django.db import transaction
from .csv_reader import read_uploaded_file

BATCH_SIZE = 100


class UploadCandidatesCSVAPIView(APIView):
    def post(self, request):
        csv_file = request.FILES.get("file")
        if not csv_file:
            return Response({"error": "Please upload a file under key 'file'."}, status=status.HTTP_400_BAD_REQUEST)

        if not (csv_file.name.lower().endswith(".csv") or csv_file.name.lower().endswith(".xlsx") or csv_file.name.lower().endswith(".xls")):
            return Response({"error": "Only CSV, XLSX, and XLS files allowed."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            rows = read_uploaded_file(csv_file)
        except Exception as e:
            return Response({"error": f"Error reading CSV: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        created = 0
        errors = []

        job_cache = {}

        batch_objects = []

        for idx, row in enumerate(rows, start=2):
            try:
                job_title = (row.get("Job Title") or row.get("job title") or "").strip()

                if job_title not in job_cache:
                    job_cache[job_title] = get_or_create_job_by_title(job_title)

                job_instance = job_cache[job_title]

                submission_json = {
                    k: v for k, v in row.items()
                    if k.lower() != "job title"
                }

                submission_json["Role_Type"] = job_title
                submission_json["job_id"] = job_instance.job_id if job_instance else None
                submission_json["job_title"] = job_instance.title if job_instance else None

                batch_objects.append(
                    FormData(
                        form_name="gxi_form",
                        submission_data=submission_json
                    )
                )

                if len(batch_objects) >= BATCH_SIZE:
                    FormData.objects.bulk_create(batch_objects)
                    created += len(batch_objects)
                    batch_objects = []

            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")

        if batch_objects:
            FormData.objects.bulk_create(batch_objects)
            created += len(batch_objects)

        return Response({
            "message": "File uploaded successfully!",
            "total_rows": len(rows),
            "created": created,
            "failed": len(errors),
            "errors": errors[:20],
        }, status=status.HTTP_200_OK)




# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Count, Q
from django.core.cache import cache   # optional: requires Django cache configured

class RoleTypeCountAPIView(APIView):
    CACHE_KEY = "role_type_counts_v1"
    CACHE_TIMEOUT = 600

    def get(self, request):
        try:
            cached = cache.get(self.CACHE_KEY)
            if cached is not None:
                return Response({"status": "success", "role_type_counts": cached}, status=status.HTTP_200_OK)
            qs = (
                FormData.objects
                .exclude(Q(submission_data__Role_Type__isnull=True) | Q(submission_data__Role_Type__exact=''))
                .values('submission_data__Role_Type')
                .annotate(count=Count('id'))
            )

            role_type_counts = {item['submission_data__Role_Type']: item['count'] for item in qs}

            # Optional: cache the result
            try:
                cache.set(self.CACHE_KEY, role_type_counts, timeout=self.CACHE_TIMEOUT)
            except Exception:
                # caching is best-effort — don't fail the request if cache isn't configured
                pass

            return Response({"status": "success", "role_type_counts": role_type_counts}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("RoleTypeCountAPIView error: %s", str(e))
            return Response({"status": "error", "message": "An error occurred"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
