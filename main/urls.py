from django.urls import path
import django.contrib.auth.views

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('ranking/', views.ranking, name='ranking'),
    path('settings/', views.user_settings, name='settings'),
    path('register/<int:status_id>/', views.register, name='register'),
    path('author/<str:screen_name>/', views.author, name='author'),
    path('update_author/', views.update_author, name='update_author'),
    path('search/', views.search, name='search'),
    path('unlisted/', views.unlisted, name='unlisted'),
    path('translate/', views.translate, name='translate'),
    path('translate_request/', views.translate_request, name='translate_request'),
    path('status/<int:status_id>/', views.status, name='status'),
    path('get_images/<int:status_id>/', views.get_images, name='get_images'),
    path('get_similar_images/', views.get_similar_images, name='get_similar_images'),
    path('report/', views.report, name='report'),
    path('register_character/', views.register_character, name='register_character'),
    path('delete_character/', views.delete_character, name='delete_character'),
    path('suggest_character/', views.suggest_character, name='suggest_character'),
    path('logout/', django.contrib.auth.views.LogoutView.as_view(template_name = 'main/logout.html'),
         name='logout'),
]
