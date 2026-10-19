from django.urls import path

from . import views

app_name = "enhancer"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("jobs/", views.job_list, name="job_list"),
    path("jobs/new/", views.create_job, name="create_job"),
    path("jobs/<uuid:pk>/", views.job_detail, name="job_detail"),
    path("jobs/<uuid:pk>/status/", views.job_status, name="job_status"),
    path("jobs/<uuid:pk>/file/<str:kind>/", views.job_file, name="job_file"),
    path("jobs/<uuid:pk>/cancel/", views.job_cancel, name="job_cancel"),
    path("jobs/<uuid:pk>/delete/", views.job_delete, name="job_delete"),
]
