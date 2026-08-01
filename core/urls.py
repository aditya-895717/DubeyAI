from django.urls import path

from . import views

app_name = "control_panel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", views.site_settings_view, name="site_settings"),
    path("content/", views.content_list, name="content_list"),
    path("content/new/", views.content_create, name="content_create"),
    path("content/<int:pk>/edit/", views.content_edit, name="content_edit"),
    path("content/<int:pk>/delete/", views.content_delete, name="content_delete"),
    path("ai-providers/", views.ai_provider_list, name="ai_provider_list"),
    path("ai-providers/new/", views.ai_provider_create, name="ai_provider_create"),
    path("ai-providers/<int:pk>/edit/", views.ai_provider_edit, name="ai_provider_edit"),
    path("ai-providers/<int:pk>/delete/", views.ai_provider_delete, name="ai_provider_delete"),
    path("ai-providers/<int:pk>/activate/", views.ai_provider_activate, name="ai_provider_activate"),
    path("users/", views.user_list, name="user_list"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
]
