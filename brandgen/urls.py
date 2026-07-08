from django.urls import path

from brandgen import views

urlpatterns = [
    path("", views.home, name="home"),
    path("brands/<uuid:brand_id>/", views.brand_detail, name="brand_detail"),
    path("posts/<uuid:post_id>/", views.post_detail, name="post_detail"),
    path("posts/<uuid:post_id>/action/", views.post_action, name="post_action"),
    path("slides/<uuid:slide_id>/download/", views.slide_download, name="slide_download"),
    path("api-key/set/", views.api_key_set, name="api_key_set"),
    path("api-key/clear/", views.api_key_clear, name="api_key_clear"),
    path("jobs/<uuid:job_id>/", views.job_progress, name="job_progress"),
    path("api/jobs/<uuid:job_id>/", views.job_progress_api, name="job_progress_api"),
    path("usage/", views.usage_dashboard, name="usage_dashboard"),
]
