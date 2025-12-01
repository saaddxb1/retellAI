
from django.contrib import admin
from django.urls import path
from retellAPI.views.API import API  # Fixed import

urlpatterns = [
    path('retellAPI/', API.as_view(), name='retellAPI'),
]