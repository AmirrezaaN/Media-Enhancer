from django.urls import path

from . import views

app_name = "appapi"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("me/", views.me, name="me"),
    path("jobs/", views.start_job, name="start_job"),
    path("jobs/<uuid:pk>/finish/", views.finish_job, name="finish_job"),
]
