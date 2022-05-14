from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('about', views.about, name='about'),
    path('register/<int:status_id>', views.register, name='register'),
    path('search/', views.search, name='search'),
    path('translate/', views.translate, name='translate'),
    path('translate_request/', views.translate_request, name='translate_request'),
    path('status/<int:status_id>', views.status, name='status'),
    path('get_images/<int:status_id>/', views.get_images, name='get_images'),
    path('get_similar_images/', views.get_similar_images, name='get_similar_images'),
    path('register_character/', views.register_character, name='register_character'),
    path('delete_character/', views.delete_character, name='delete_character'),
]
