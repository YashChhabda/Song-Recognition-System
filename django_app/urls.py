"""
URL configuration for Song Recognition System Django API.
"""

from django.urls import path
from django_app import views

urlpatterns = [
    path('api/recognize/', views.recognize_view, name='api_recognize'),
    path('api/index/', views.index_view, name='api_index'),
    path('api/catalog/', views.catalog_view, name='api_catalog'),
]
