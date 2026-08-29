from django.urls import path

from . import views


urlpatterns = [
    path("", views.chatbot, name="chatbot"),
    path("chat/", views.chat, name="chat"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("ping/", views.ping, name="ping"),
    path("api/history/", views.get_chat_history, name="chat_history"),
    path("api/clear-history/", views.clear_chat_history, name="clear_history"),
    path("api/delete/<int:chat_id>/", views.delete_chat, name="delete_chat"),
    path("api/search/", views.search_chats, name="search_chats"),
    path("api/upload/", views.upload_document, name="upload_document"),
    path("api/documents/clear/", views.clear_documents, name="clear_documents"),
    path("api/documents/<int:document_id>/remove/", views.remove_document, name="remove_document"),
    path("api/voice-commands/", views.voice_commands, name="voice_commands"),
]
