from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("rules", views.rules, name="rules"),
    path("geocode", views.geocode, name="geocode"),
    path("plan", views.plan, name="plan"),
    path("heatmap", views.heatmap, name="heatmap"),
]
