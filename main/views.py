from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.core import serializers
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Count, Q
from django.contrib.auth.decorators import login_required
from social_django.models import UserSocialAuth

from .utils import register_status
from .models import Author, Status, ImageEntry, I2VTag, HashTag, Character, UserProfile

import collections
import requests
import threading
import itertools
import json
from urllib.parse import urlparse, quote

def index(request):
    images = ImageEntry.objects.filter(collection=True)
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not profile.show_nsfw:
            safe = I2VTag.objects.get(name='safe')
            images = images.filter(i2vtags=safe)
    else:
        safe = I2VTag.objects.get(name='safe')
        images = images.filter(i2vtags=safe)
    images = images.order_by('-pk')[:36]
    return render(request, 'main/index.html', {'images': images})

def translate(request):
    page = int(request.GET.get('page', default='0'))
    characters = Character.objects.all().annotate(count=Count('characters')).order_by('-count')[100*page:100*(page+1)]
    return render(request, 'main/translate.html', {'characters': characters, 'page': page})

@login_required
def user_settings(request):
    user = UserSocialAuth.objects.get(user_id=request.user.id)
    profile = UserProfile.objects.get(user=user)
    if request.method == 'POST':
        profile.show_nsfw = True if request.POST.get('show_nsfw', 'off') == 'on' else False
        profile.editor = True if request.POST.get('editor', 'off') == 'on' else False
        profile.save()
        return render(request, 'main/settings.html', {'user': user, 'profile': profile, 'saved': True})
    else:
        return render(request, 'main/settings.html', {'user': user, 'profile': profile})

@csrf_exempt
@require_POST
def translate_request(request):
    data = json.loads(request.body)
    character = Character.objects.get(pk=data['pk'])
    character.name_ja = data['name_ja']
    character.save()
    return JsonResponse({ "success": True, "message": character.name_en + " is succesfully transtaled: " + character.name_ja })

def about(request):
    return HttpResponse('About')

def author(request, screen_name):
    try:
        author = Author.objects.get(screen_name=screen_name)
    except:
        return HttpResponse('Not found')
    images = ImageEntry.objects.filter(author=author, collection=True)
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not profile.show_nsfw:
            safe = I2VTag.objects.get(name='safe')
            images = images.filter(i2vtags=safe)
    else:
        safe = I2VTag.objects.get(name='safe')
        images = images.filter(i2vtags=safe)
    image_count = images.count()
    return render(request, 'main/author.html', {
        'author': author,
        'image_entry_list': images,
        'image_count': image_count})

def register(request, status_id):
    res = register_status(status_id)
    return JsonResponse(res)

def status(request, status_id):
    number = int(request.GET.get('n', default='0'))
    try:
        status = Status.objects.get(status_id=status_id)
        screen_name = status.author.screen_name
        hashtags = status.hashtags.all()
    except Status.DoesNotExist:
        t = threading.Thread(target=register_status, args=(status_id, ))
        t.start()
        return render(request, 'main/status.html', {'registered': False, 'status_id': status_id})

    editor = False
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile = UserProfile.objects.get(user=user)
        if profile.editor:
            editor = True

    return render(request, 'main/status.html', {
        'registered': True,
        'status_id': status_id,
        'screen_name': screen_name,
        'hashtags': hashtags,
        'number': number,
        'editor': editor})

def get_images(request, status_id):
    try:
        status = Status.objects.get(status_id=status_id)
        image_entries = ImageEntry.objects.filter(status=status).order_by('image_number')
    except:
        return JsonResponse({"success": False})
    data = []
    for entry in image_entries:
        rating = entry.i2vtags.get(tag_type='RA')
        i2vtags = [tag.name for T in ['GE', 'CO', 'CH'] for tag in entry.i2vtags.filter(tag_type=T)]
        characters = [{"name_ja": c.name_ja, "name_en": c.name_en} for c in entry.characters.all()]

        data.append({
            "media_url": entry.media_url,
            "rating": rating.name,
            "i2vtags": i2vtags,
            "characters": characters,
            "confirmed": entry.confirmed,
            "duplicated": entry.is_duplicated,
            "parent_id": str(entry.parent.status.status_id) if entry.parent else None,
            "parent_number": entry.parent.image_number if entry.parent else None,
            "is_nsfw": entry.is_nsfw,
	    "collection": entry.collection})

    return JsonResponse({
        "success": True, 
        "image_data": data})

@csrf_exempt
@require_POST
def get_similar_images(request):
    data = json.loads(request.body)
    media_url = data['media_url']
    res = requests.post(f'http://{settings.IMAGE_SEARCH_SERVER_IP}/search/', json={"media_url": media_url}).json()
    if res['success']:
        similar_images = []
        names = []
        indices = res['indices']
        media_urls = res['media_urls']
        for status_id, media_url in zip(indices, media_urls):
            similar_images.append({"status_url": f"/status/{status_id}",
                                    "media_url": media_url})
            try:
                entry = ImageEntry.objects.get(media_url=media_url)
                names.extend([chara.name_en for chara in entry.characters.all()])
            except:
                pass
        count = collections.Counter(names)
        freq_index = [(-count[name], names.index(name), name) for name in set(names)]
        similar_characters = [c[2] for c in sorted(freq_index)]
        return JsonResponse({"success": True, "similar_images": similar_images,
                             "similar_characters": similar_characters})
    else:
        return JsonResponse({"success": False})

def search(request):
    i2vtags = request.GET.get('i2vtags')
    hashtags = request.GET.get('hashtags')
    keyword = request.GET.get('keyword')
    character = request.GET.get('character')
    only_confirmed = request.GET.get('confirmed', default='f')
    page = request.GET.get('page', default='1')
    page = int(page)
    order = request.GET.get('order', default='created_at')
    only_confirmed = True if only_confirmed == 't' else False

    images = ImageEntry.objects.filter(collection=True)
    query = ""
    if i2vtags is not None:
        query += f"&i2vtags={quote(i2vtags)}"
        i2vtags = i2vtags.split(';')
        for tag_name in i2vtags:
            try:
                tag = I2VTag.objects.get(name=tag_name)
            except I2VTag.DoesNotExist:
                return render(request, 'main/search.html', {'i2vtags': i2vtags, 'notfound': True})
            images = images.filter(i2vtags=tag)
    if hashtags is not None:
        query += f"&hashtags={quote(hashtags)}"
        status_list = Status.objects.all()
        for tag_name in hashtags.split(';'):
            try:
                tag = HashTag.objects.get(name=tag_name)
            except HashTag.DoesNotExist:
                return render(request, 'main/search.html', {'notfound': True})
            status_list = status_list.filter(hashtags=tag)
        images = images.filter(status__in=status_list)
    if keyword is not None:
        query += f"&keyword={quote(keyword)}"
        status_list = Status.objects.filter(text__contains=keyword)
        images = images.filter(status__in=status_list)
    character_tag = None
    if character is not None:
        query += f"&character={quote(character)}"
        try:
            character_tag = Character.objects.get(name_en=character)
        except Character.DoesNotExist:
            try:
                character_tag = Character.objects.get(name_ja=character)
            except Character.DoesNotExist:
                return render(request, 'main/search.html', {'character': character, 'notfound': True})
        if only_confirmed:
            images = images.filter(Q(characters=character_tag) & Q(confirmed=True))
        else:
            images = images.filter(Q(characters=character_tag))

    images = images.distinct()
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not profile.show_nsfw:
            safe = I2VTag.objects.get(name='safe')
            images = images.filter(i2vtags=safe)
    else:
        safe = I2VTag.objects.get(name='safe')
        images = images.filter(i2vtags=safe)
    images_per_page = 120
    images_count = images.count()
    last_page = -(-images_count // images_per_page)  # round up
    prev_page = request.path + f'?{query}&page={page-1}' if page != 1 else None
    next_page = request.path + f'?{query}&page={page+1}' if page != last_page and last_page != 0 else None

    images = images.order_by('-pk')[images_per_page*(page-1):images_per_page*page]

    return render(request, 'main/search.html', 
            {'images': images, 'images_count': images_count,
             'i2vtags': i2vtags, 'character': character_tag,
             'prev_page': prev_page, 'next_page': next_page})

def unlisted(request):
    page = request.GET.get('page', default='1')
    page = int(page)
    images = ImageEntry.objects.filter(collection=False)
    images_per_page = 120
    images_count = images.count()
    last_page = -(-images_count // images_per_page)  # round up
    prev_page = request.path + f'?page={page-1}' if page != 1 else None
    next_page = request.path + f'?page={page+1}' if page != last_page else None

    images = images.order_by('-pk')[images_per_page*(page-1):images_per_page*page]

    return render(request, 'main/search.html', 
            {'images': images, 'images_count': images_count, 'unlisted': True, 
             'prev_page': prev_page, 'next_page': next_page})

@csrf_exempt
@require_POST
def report(request):
    data = json.loads(request.body)
    try:
        status = Status.objects.get(status_id=data['status_id'])
        image = ImageEntry.objects.get(status=status, image_number=data['image_number'])
        if data['report_type'] == 'not_illust':
            image.collection = False
        elif data['report_type'] == 'is_illust':
            image.collection = True
        elif data['report_type'] == 'safe':
            image.is_nsfw = False
        elif data['report_type'] == 'not_safe':
            image.is_nsfw = True
        elif data['report_type'] == 'deleted':
            image.is_deleted = True
            image.collection = False
        image.save()
        status.contains_illust = any([img.collection for img in ImageEntry.objects.filter(status=status)])
        status.save()
    except Exception as e:
        return JsonResponse({ "success": False, })
    return JsonResponse({ "success": True, })

@csrf_exempt
@require_POST
def register_character(request):
    data = json.loads(request.body)
    if "name_ja" in data:
        character, _ = Character.objects.get_or_create(name_ja=data['name_ja'])
    elif "name_en" in data:
        try:
            character = Character.objects.get(name_en=data['name_en'])
        except:
            return JsonResponse({ "success": False, })
    try:
        status = Status.objects.get(status_id=int(data['status_id']))
        image_entry = ImageEntry.objects.get(status=status, image_number=data['image_number'])
        image_entry.characters.add(character)
        image_entry.confirmed = True
        image_entry.save()
        return JsonResponse({ "success": True, })
    except:
        return JsonResponse({ "success": False, })

@csrf_exempt
@require_POST
def delete_character(request):
    data = json.loads(request.body)
    try:
        character = Character.objects.get(name_en=data['name'])
    except Character.DoesNotExist:
        try:
            character = Character.objects.get(name_ja=data['name'])
        except Character.DoesNotExist:
            return JsonResponse({ "success": False, })
    status = Status.objects.get(status_id=int(data['status_id']))
    image_entry = ImageEntry.objects.get(status=status, image_number=data['image_number'])
    image_entry.characters.remove(character)
    image_entry.confirmed = True
    image_entry.save()
    return JsonResponse({ "success": True, })

@csrf_exempt
@require_POST
def suggest_character(request):
    data = json.loads(request.body)
    characters = Character.objects.filter(name_en__contains=data['content'])
    return JsonResponse({"success": True, "names": [c.name_en for c in characters]})
