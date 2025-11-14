from unittest import result
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from django.core.mail import send_mail
from .models import FormData
from .serializers import FormDataSerializer
import requests
from functools import reduce
from operator import or_
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.utils.html import strip_tags

class FormDataAPIView(APIView):
    
    def send_status_email(self, candidate_email, candidate_name, current_status, phase=None,
                      interview_date=None, interview_time=None, joining_date=None):

        if not candidate_email:
            return

        subject = f"Update: Your Application Status - {current_status}"

        context = {
            "candidate_name": candidate_name,
            "current_status": current_status,
            "phase": phase,
            "interview_date": interview_date,
            "interview_time": interview_time,
            "joining_date": joining_date,
        }

        # Generate HTML email
        html_message = render_to_string("application_status.html", context)

        # You can still send a simple text fallback (optional)
        text_message = "Your application status has been updated."

        try:
            send_mail(
                subject=subject,
                message=text_message,      # plain text fallback
                from_email='',              # DEFAULT_FROM_EMAIL or your email
                recipient_list=[candidate_email],
                html_message=html_message,  # Load HTML template
                fail_silently=False,
            )
        except Exception as e:
            print(f"⚠️ Email send failed to {candidate_email}: {e}")

    # ================================
    # GET METHOD
    # ================================
    def get(self, request, pk=None):
        try:
            if pk:
                form = FormData.objects.filter(id=pk).first()
                if not form:
                    return Response(
                        {"status": "error", "message": "Record not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )
                serializer = FormDataSerializer(form)
                return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

            search_query = request.query_params.get('search', None)
            form_name = request.query_params.get('form_name', None)
            sort_by = request.query_params.get('sort_by', '-submitted_at')

            # NEW: role_type filters
            role_type_param = request.query_params.get('role_type')  # e.g., "SDET" or "Software...,SDET"
            role_type_exact = request.query_params.get('role_type_exact', 'false').lower() in ('1', 'true', 'yes')

            forms = FormData.objects.all()

            if form_name:
                forms = forms.filter(form_name__icontains=form_name)

            # existing search across name + JSON text
            if search_query:
                forms = forms.filter(
                    Q(form_name__icontains=search_query) |
                    Q(submission_data__icontains=search_query)
                )

            # NEW: Role_Type inside submission_data (top-level key)
            # Works on PostgreSQL natively; on SQLite it will still work for icontains via JSONField text casting.
            if role_type_param:
                role_types = [rt.strip() for rt in role_type_param.split(',') if rt.strip()]
                if role_types:
                    if role_type_exact:
                        conds = [Q(submission_data__Role_Type__iexact=rt) for rt in role_types]
                    else:
                        conds = [Q(submission_data__Role_Type__icontains=rt) for rt in role_types]
                    # OR all role conditions together
                    forms = forms.filter(reduce(or_, conds))

            valid_sort_fields = ['form_name', 'submitted_at']
            if sort_by.lstrip('-') not in valid_sort_fields:
                sort_by = '-submitted_at'
            forms = forms.order_by(sort_by)

            page = request.query_params.get('page', 1)
            page_size = int(request.query_params.get('page_size', 10))
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
            return Response(
                {"status": "error", "message": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ================================
    # POST METHOD
    # ================================
    
    
    

    def post(self, request):
        serializer = FormDataSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save() 
            return Response({
                "status": "success",
                "message": "Form data saved successfully",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            "status": "error",
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    # ================================
    # PUT METHOD (UPDATED)
    # ================================
    def put(self, request, pk):
        try:
            form = FormData.objects.get(pk=pk)
        except FormData.DoesNotExist:
            return Response(
                {"status": "error", "message": "Record not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        submission_data = form.submission_data or {}
        old_status = submission_data.get("status", "Scouting")

        # Input parameters
        new_status = request.data.get("status")
        reject_reason = request.data.get("reject_reason")
        interview_date = request.data.get("interview_date")
        interview_time = request.data.get("interview_time")
        offer_letter_date = request.data.get("offer_letter_date")
        joining_date = request.data.get("joining_date")
        phase = request.data.get("phase")
        note = request.data.get("note")

        candidate_name = submission_data.get("Name")
        candidate_email = submission_data.get("Email")

        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

        if not old_status:
            submission_data["status"] = "Scouting"

        # === SCOUTING ===
        if old_status == "Scouting":
            if new_status == "Reject":
                if not reject_reason:
                    return Response(
                        {"status": "error", "message": "Reject reason required when rejecting from Scouting."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                submission_data.setdefault("status_history", []).append({
                    "from": old_status,
                    "to": "Reject",
                    "reason": reject_reason,
                    "updated_at": timestamp
                })
                submission_data["status"] = "Reject"
                submission_data["reject_reason"] = reject_reason

                self.send_status_email(candidate_email, candidate_name, "Reject")

            elif new_status == "Ongoing":
                if not interview_date or not interview_time:
                    return Response(
                        {"status": "error", "message": "Interview date and time required to move from Scouting to Ongoing."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                submission_data.setdefault("status_history", []).append({
                    "from": old_status,
                    "to": "Ongoing",
                    "phase": phase or "First Round",
                    "interview_date": interview_date,
                    "interview_time": interview_time,
                    "updated_at": timestamp
                })
                submission_data["status"] = "Ongoing"
                submission_data["phase"] = phase or "First Round"

                self.send_status_email(candidate_email, candidate_name, "Ongoing", phase, interview_date, interview_time)

            else:
                return Response(
                    {"status": "error", "message": "Invalid transition from Scouting. Must be 'Ongoing' or 'Reject'."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # === ONGOING ===
        elif old_status == "Ongoing":
            if new_status == "Hired":
                if not offer_letter_date or not joining_date:
                    return Response(
                        {"status": "error", "message": "Offer letter release date and joining date required to mark as Hired."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                submission_data.setdefault("status_history", []).append({
                    "from": "Ongoing",
                    "to": "Hired",
                    "offer_letter_date": offer_letter_date,
                    "joining_date": joining_date,
                    "updated_at": timestamp
                })
                submission_data["status"] = "Hired"
                submission_data["offer_letter_date"] = offer_letter_date
                submission_data["joining_date"] = joining_date
                submission_data["phase"] = "Final Selection"

                self.send_status_email(candidate_email, candidate_name, "Hired", "Final Selection", joining_date=joining_date)

            else:
                history_entry = {
                    "from": "Ongoing",
                    "to": new_status or "Ongoing",
                    "phase": phase or "Next Round",
                    "updated_at": timestamp
                }
                if interview_date:
                    history_entry["interview_date"] = interview_date
                if interview_time:
                    history_entry["interview_time"] = interview_time

                submission_data.setdefault("status_history", []).append(history_entry)
                submission_data["status"] = "Ongoing"
                submission_data["phase"] = phase or "Next Round"

                self.send_status_email(candidate_email, candidate_name, "Ongoing", phase, interview_date, interview_time)

        elif old_status == "Reject":
            return Response(
                {"status": "error", "message": "Cannot change status after rejection."},
                status=status.HTTP_400_BAD_REQUEST
            )

        elif old_status == "Hired":
            return Response(
                {"status": "error", "message": "Candidate already hired. No further changes allowed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # === Notes ===
        if note:
            submission_data.setdefault("notes_history", []).append({
                "note": note,
                "updated_at": timestamp
            })
            submission_data["note"] = note

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
    """
    Send custom email with TO, CC, SUBJECT, and message body (NO TEMPLATE)
    """

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
        submission["message"]=message
        
        # SAVE MESSAGE IN DATABASE
        form_obj.submission_data = submission
        form_obj.save()
        # Send email
        send_composed_email(
            to_email=candidate_email,
            cc_emails=cc_list,
            subject=subject,
            message=message
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
        submission["message"]=message
        
        # SAVE MESSAGE IN DATABASE
        form_obj.submission_data = submission
        form_obj.save()
        # Send email
        send_composed_email(
            to_email=email,
            cc_emails=cc_list,
            subject=subject,
            message=message
        )

        return Response({"message": "Email updated successfully "})