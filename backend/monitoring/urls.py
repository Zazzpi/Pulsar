from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("clients/", views.clients),
    path("clients/<int:client_id>/summary/", views.summary),
    path("clients/<int:client_id>/notes/", views.notes),
    path("clients/<int:client_id>/metrics/", views.metrics),
    path("clients/<int:client_id>/<str:resource>/", views.detail),
    path("watches/", views.watches),
    path("watches/<int:watch_id>/", views.watch),
]
