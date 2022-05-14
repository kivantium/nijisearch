from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.core import serializers
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Count, Q

from .utils import register_status
from .models import Status, ImageEntry, I2VTag, HashTag, Character

import collections
import requests
import threading
import itertools
import json
from urllib.parse import urlparse, quote

def index(request):
    status_list = Status.objects.filter(contains_illust=True).order_by('-pk')[:120]
    status_count = Status.objects.count()
    character_count = Character.objects.count()
    return render(request, 'main/index.html', {
        'status_list': status_list,
        'status_count': status_count,
        'character_count': character_count})

def translate(request):
    page = int(request.GET.get('page', default='0'))
    characters = Character.objects.all().annotate(count=Count('characters')).order_by('-count')[100*page:100*(page+1)]
    return render(request, 'main/translate.html', {'characters': characters, 'page': page})

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

    return render(request, 'main/status.html', {
        'registered': True,
        'status_id': status_id,
        'screen_name': screen_name,
        'hashtags': hashtags,
        'number': number})

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
            "characters": characters})
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
    keywords = request.GET.get('keyword')
    character = request.GET.get('character')
    only_confirmed = request.GET.get('confirmed', default='f')
    page = request.GET.get('page', default='1')
    page = int(page)
    order = request.GET.get('order', default='created_at')
    safe = request.GET.get('safe', default='t')
    safe = True if safe == 't' else False
    only_confirmed = True if only_confirmed == 't' else False

    images = ImageEntry.objects.all()
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
    if character is not None:
        query += f"&character={quote(character)}"
        try:
            chara_tag = Character.objects.get(name_ja=character)
        except Character.DoesNotExist:
            try:
                chara_tag = Character.objects.get(name_en=character)
            except Character.DoesNotExist:
                return render(request, 'main/search.html', {'character': character, 'notfound': True})
        if only_confirmed:
            images = images.filter(characters=chara_tag)
        else:
            images = images.filter(Q(characters=chara_tag) | Q(similar_characters=chara_tag))

    images_per_page = 120
    images_count = images.count()
    last_page = -(-images_count // images_per_page)  # round up
    prev_page = request.path + f'?{query}&page={page-1}' if page != 1 else None
    next_page = request.path + f'?{query}&page={page+1}' if page != last_page else None

    images = images.order_by('-pk')[images_per_page*(page-1):images_per_page*page]

    return render(request, 'main/search.html', 
            {'images': images, 'images_count': images_count,
             'i2vtags': i2vtags, 'character': character,
             'prev_page': prev_page, 'next_page': next_page})

@csrf_exempt
@require_POST
def register_character(request):
    data = json.loads(request.body)
    if "name_ja" in data:
        character, _ = Character.objects.get_or_create(name_ja=data['name_ja'])
    elif "name_en" in data:
        character, _ = Character.objects.get_or_create(name_en=data['name_en'])
    else:
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
    image_entry.confirmed = False
    image_entry.save()
    return JsonResponse({ "success": True, })
