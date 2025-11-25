# views.py
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import TeamsUser
from .serializers import TeamsUserSerializer
from django.shortcuts import get_object_or_404
from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = getattr(settings, "TEAMS_DEFAULT_PAGE_SIZE", 25)
    page_size_query_param = "page_size"
    max_page_size = getattr(settings, "TEAMS_MAX_PAGE_SIZE", 1000)


class user_list(APIView):
    pagination_class = StandardResultsSetPagination
    def get(self, request, pk=None):
        if pk:
            user_obj = get_object_or_404(TeamsUser, pk=pk)
            serializer = TeamsUserSerializer(user_obj)
            return Response({"status": "success", "data": serializer.data}, status=status.HTTP_200_OK)

        qs = TeamsUser.objects.all().order_by("-id")
        mail = request.query_params.get("mail")
        display_name = request.query_params.get("display_name")
        upn = request.query_params.get("user_principal_name")
        if mail:
            qs = qs.filter(mail__icontains=mail)

        if display_name:
            qs = qs.filter(display_name__icontains=display_name)

        if upn:
            qs = qs.filter(user_principal_name__icontains=upn)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)

        serializer = TeamsUserSerializer(page, many=True)

        return paginator.get_paginated_response({
            "status": "success",
            "count": qs.count(),
            "data": serializer.data
        })