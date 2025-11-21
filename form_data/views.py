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
from django.core.mail import EmailMessage,get_connection
from django.utils.html import strip_tags
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from superadmin.models import UserProfile
from imapclient import IMAPClient
import pyzmail
from datetime import datetime

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

def send_composed_email(to_email, cc_emails, subject, message,attachment_file=None):
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
        if attachment_file:
            email.attach(attachment_file.name, attachment_file.read(), attachment_file.content_type)

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
        attachment_file = request.FILES.get("attachment") 


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
        saved_file_path = None

        if attachment_file:
            fs = FileSystemStorage(location='media/email_attachments/')
            saved_name = fs.save(attachment_file.name, attachment_file)
            saved_file_path = f"email_attachments/{saved_name}"  # relative path to media

        email_log = {
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
            to_email=email,
            cc_emails=cc_list,
            subject=subject,
            message=message,
            attachment_file=attachment_file,
        )

        return Response({"message": "Email updated successfully "})
    
    def get(self, request, pk):

        # Fetch FormData using pk
        try:
            form_obj = FormData.objects.get(pk=pk)
        except FormData.DoesNotExist:
            return Response({"status": "error", "message": "Record not found"}, status=404)

        submission = form_obj.submission_data

        # Get email message list (or empty list if not exists)
        email_logs = submission.get("email_message", [])

        return Response({
            "status": "success",
            "email_messages": email_logs
        })
        
def fetch_emails_and_store():
    import imaplib
    import email
    from email.header import decode_header
    from django.core.files.storage import FileSystemStorage
    from .models import FormData

    imap = imaplib.IMAP4_SSL("outlook.office365.com")
    imap.login("noreply@gxinetworks.com", "August@082024")

    imap.select("INBOX")
    status, messages = imap.search(None, "UNSEEN")
    email_ids = messages[0].split()

    for mail_id in email_ids:
        status, msg_data = imap.fetch(mail_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        # Decode subject safely
        raw_subject, enc = decode_header(msg["Subject"])[0]
        if isinstance(raw_subject, bytes):
            subject = raw_subject.decode(enc or "utf-8", errors="ignore")
        else:
            subject = raw_subject

        sender = msg.get("From")
        body = ""
        saved_attachments = []

        # Walk through email parts
        for part in msg.walk():

            # TEXT BODY
            if part.get_content_type() == "text/plain":
                body += part.get_payload(decode=True).decode(errors="ignore")

            # ATTACHMENTS
            if part.get("Content-Disposition"):
                filename = part.get_filename()
                file_data = part.get_payload(decode=True)

                # Save to media
                fs = FileSystemStorage(location="media/incoming_attachments/")
                saved_name = fs.save(filename, file_data)
                saved_path = "incoming_attachments/" + saved_name

                saved_attachments.append(saved_path)

        # 🟢 Find correct FormData based on email sender
        try:
            form_obj = FormData.objects.get(submission_data__Email__icontains=sender)
        except:
            form_obj = FormData.objects.first() 

        # 🟢 Append email inside JSON
        incoming = form_obj.submission_data.get("incoming_emails", [])

        incoming.append({
            "subject": subject,
            "sender": sender,
            "body": body,
            "attachments": saved_attachments
        })

        form_obj.submission_data["incoming_emails"] = incoming
        form_obj.save()

    imap.close()
    imap.logout()

    return True

class FetchIncomingEmails(APIView):
    def get(self, request):
        success = fetch_emails_and_store()
        return Response({"status": "ok", "message": "Emails fetched successfully"})
    
class HREmailSender:

    def __init__(self, user):
        if user.role != UserProfile.ROLE_HR:
            raise PermissionError("Only HR can send emails")

        if not hasattr(user, "email_config"):
            raise ValueError("HR has not configured email settings")

        self.user = user
        self.config = user.email_config

        self.connection = get_connection(
            host=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            username=self.config.email_host_user,
            password=self.config.email_host_password,
            use_tls=settings.EMAIL_USE_TLS,
            use_ssl=getattr(settings, "EMAIL_USE_SSL", False)
        )

    def send_composed(self, to_email, cc_emails, subject, message, attachment_file=None):
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=self.config.email_host_user,
            to=[to_email],
            cc=cc_emails,
            connection=self.connection,
        )

        email.content_subtype = "html"

        if attachment_file:
            email.attach(
                attachment_file.name,
                attachment_file.read(),
                attachment_file.content_type
            )

        return email.send()
    
class HRComposeMailAPIView(APIView):
    # permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user

        # Only HR allowed
        if user.role != UserProfile.ROLE_HR:
            return Response({"error": "Only HR can send emails"}, status=403)

        cc_emails = request.data.get("cc_emails", "")
        message = request.data.get("message")
        attachment_file = request.FILES.get("attachment")

        if not message:
            return Response({"error": "message is required"}, status=400)

        # Convert comma-separated CC into list
        cc_list = [email.strip() for email in cc_emails.split(",") if email.strip()]

        # ============================
        # Fetch Candidate FormData
        # ============================
        try:
            form_obj = FormData.objects.get(pk=pk)
        except FormData.DoesNotExist:
            return Response({"error": "Record not found"}, status=404)

        submission = form_obj.submission_data
        candidate_email = submission.get("Email")
        role = submission.get("Role_Type", "Not Provided")
        current_status = submission.get("status", "Unknown")

        # Subject
        subject = f"Role: {role} | Status: {current_status}"

        # Replace placeholders dynamically
        message = message.format(
            candidate_name=submission.get("Name"),
            status=current_status,
            phone=submission.get("Phone"),
            role=submission.get("Role_Type")
        )

        # ============================
        # Save Attachment to MEDIA
        # ============================
        saved_file_path = None

        if attachment_file:
            fs = FileSystemStorage(location='media/email_attachments/')
            saved_name = fs.save(attachment_file.name, attachment_file)
            saved_file_path = f"email_attachments/{saved_name}"

        # ============================
        # SAVE EMAIL LOG IN DB
        # ============================
        email_log = {
            "message": message,
            "cc": cc_list,
            "attachments": [saved_file_path] if saved_file_path else []
        }

        if "email_message" not in submission or not isinstance(submission["email_message"], list):
            submission["email_message"] = []

        submission["email_message"].append(email_log)

        form_obj.submission_data = submission
        form_obj.save()

        # ============================
        # SEND EMAIL USING HR SMTP
        # ============================
        try:
            sender = HREmailSender(user)
            sender.send_composed(
                to_email=candidate_email,
                cc_emails=cc_list,
                subject=subject,
                message=message,
                attachment_file=attachment_file
            )

        except Exception as e:
            return Response({"error": str(e)}, status=500)

        return Response({"message": "Email sent successfully!"})
    
def extract_clean_body(msg):
    # Prefer plain text part
    if msg.text_part:
        try:
            return msg.text_part.get_payload().decode(msg.text_part.charset)
        except:
            pass

    # If no text version, remove HTML tags
    if msg.html_part:
        try:
            import re
            html = msg.html_part.get_payload().decode(msg.html_part.charset)
            clean_text = re.sub('<[^<]+?>', '', html)  # remove HTML tags
            return clean_text.strip()
        except:
            return ""
    
    return ""


def fetch_dynamic_emails(imap_host, imap_port, email_user, email_pass, candidate_email=None):
    try:
        with IMAPClient(imap_host, port=imap_port, ssl=True, timeout=10) as client:

            client.login(email_user, email_pass)
            client.select_folder("INBOX")

            # ⭐ Always fetch all emails from candidate (read + unread)
            if candidate_email:
                messages = client.search(["FROM", candidate_email])
            else:
                messages = client.search(["ALL"])

            # ⭐ Limit for speed
            messages = messages[-20:]

            email_list = []

            for msgid, data in client.fetch(messages, ["BODY[]", "ENVELOPE"]).items():
                msg = pyzmail.PyzMessage.factory(data[b"BODY[]"])

                from_email = msg.get_addresses("from")[0][1]
                subject = msg.get_subject()
                body = extract_clean_body(msg)

                email_list.append({
                    "from": from_email,
                    "subject": subject,
                    "body": body
                })

            return email_list

    except Exception as e:
        print("IMAP Error:", e)
        return []

    
class FetchIncomingMailAPIView(APIView):
    def get(self, request, pk):
        user = request.user
        if user.role != UserProfile.ROLE_HR:
            return Response({"error": "Only HR can fetch incoming emails"}, status=403)

        config = user.email_config

        try:
            form_obj = FormData.objects.get(pk=pk)
        except FormData.DoesNotExist:
            return Response({"error": "Record not found"}, status=404)

        candidate_email = form_obj.submission_data.get("Email")

        emails = fetch_dynamic_emails(
            imap_host=settings.IMAP_DEFAULT_HOST,
            imap_port=settings.IMAP_DEFAULT_PORT,
            email_user=config.email_host_user,
            email_pass=config.email_host_password,
            candidate_email=candidate_email
        )

        return Response({"emails": emails})
    
class ChatHistoryAPIView(APIView):
    def get(self, request, pk):
        user = request.user
        if user.role != UserProfile.ROLE_HR:
            return Response({"error": "Only HR can view chat"}, status=403)

        # Candidate FormData
        try:
            form_obj = FormData.objects.get(pk=pk)
        except FormData.DoesNotExist:
            return Response({"error": "Candidate not found"}, status=404)

        submission = form_obj.submission_data
        candidate_email = submission.get("Email")

        # 1️⃣ Sent Messages (DB)
        sent_messages = submission.get("email_message", [])

        # Force type=sent and remove timestamp if exists
        clean_sent = []
        for msg in sent_messages:
            msg.pop("timestamp", None)
            msg["type"] = "sent"
            clean_sent.append(msg)

        # 2️⃣ Received Messages
        config = user.email_config
        received_messages = fetch_dynamic_emails(
            imap_host=settings.IMAP_DEFAULT_HOST,
            imap_port=settings.IMAP_DEFAULT_PORT,
            email_user=config.email_host_user,
            email_pass=config.email_host_password,
            candidate_email=candidate_email
        )

        # Force type=received and remove timestamp
        clean_received = []
        for msg in received_messages:
            msg.pop("timestamp", None)
            msg["type"] = "received"
            clean_received.append(msg)

        # 3️⃣ Merge directly WITHOUT sorting
        full_chat = clean_sent + clean_received

        return Response({"chat": full_chat})
