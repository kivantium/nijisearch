from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.core import serializers
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db.models import Count
from django.contrib.auth.decorators import login_required
from django.utils.timezone import make_aware
from social_django.models import UserSocialAuth

from .utils import register_status, get_twitter_api
from .models import Author, Status, ImageEntry, I2VTag, HashTag, Character, UserProfile

import collections
import datetime
import requests
import threading
import itertools
import json
import logging
import os
from urllib.parse import urlparse, quote
import urllib.request

def log_info(msg):
    logger = logging.getLogger('command')
    logger.info(msg)

def index(request):
    images = ImageEntry.objects.filter(collection=True, image_number=0)
    now = make_aware(datetime.datetime.now())
    td = datetime.timedelta(hours=24)
    start = now - td
    ranking_images = ImageEntry.objects.filter(status__created_at__range=(start, now)).filter(collection=True, image_number=0)
    editor = False
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not profile.show_nsfw:
            images = images.filter(is_nsfw=False)
            ranking_images = ranking_images.filter(is_nsfw=False)
        if profile.editor:
            editor = True
    else:
        images = images.filter(is_nsfw=False)
        ranking_images = ranking_images.filter(is_nsfw=False)
    names = []
    for entry in images[:500]:
        names.extend([c.name_en for c in entry.characters.all()])
    count = collections.Counter(names)
    freq_index = [(-count[name], names.index(name), name) for name in set(names)]
    en_names = [c[2] for c in sorted(freq_index)][:20]
    characters = []
    for name in en_names:
        character = Character.objects.get(name_en=name)
        characters.append({"name_en": name, "name_ja": character.name_ja if character.name_ja else name})
    images = images.order_by('-pk')[:24]
    ranking_images = ranking_images.order_by('-status__like_count')[:12]

    return render(request, 'main/index.html',
            {'images': images, 'ranking_images': ranking_images, 'editor': editor, 'characters': characters})

def about(request):
    return render(request, 'main/about.html')

def reduce_pages(pages, current_page):
    page_size = len(pages)
    if page_size > 6:
        if current_page <= 3:
            pages = pages[:4] + [None] + pages[-1:]
        elif current_page > 1000:
            if current_page >= page_size:
                pages = pages[:1] + [None] + pages[-2:]
            else:
                pages = pages[current_page-2:current_page+1]
        elif current_page > 100:
            if current_page >= page_size - 1:
                pages = pages[:1] + [None] + pages[-3:]
            else: 
                pages = pages[current_page-3:current_page+2]
        else:
            if current_page >= page_size - 3:
                pages = pages[:1] + [None] + pages[-5:]
            else: 
                pages = pages[current_page-4:current_page+3]
    return pages

def ranking(request):
    page = request.GET.get('page', default='1')
    page = int(page)
    now = make_aware(datetime.datetime.now())
    td = datetime.timedelta(hours=24)
    start = now - td
    images = ImageEntry.objects.filter(status__created_at__range=(start, now)).filter(collection=True, image_number=0)
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not profile.show_nsfw:
            images = images.filter(is_nsfw=False)
    else:
        images = images.filter(is_nsfw=False)
    images = images.order_by('-status__like_count')

    images_per_page = 120
    images_count = images.count()
    page_size = -(-images_count // images_per_page)  # round up
    url = request.path
    if images_count > images_per_page:
        pages = [{"url": f'{url}?page={p+1}', "n": p+1} for p in range(page_size)]
        images = images[images_per_page*(page-1):images_per_page*page]
        pages = reduce_pages(pages, page)
    else:
        pages = None
    prev_page = url + f'?page={page-1}' if page != 1 else None
    next_page = url + f'?page={page+1}' if page != page_size and page_size != 0 else None

    editor = False
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile = UserProfile.objects.get(user=user)
        if profile.editor:
            editor = True
    return render(request, 'main/ranking.html', {'images': images, 'pages': pages, 'current_page': page, 'prev_page': prev_page, 'next_page': next_page, 'editor': editor})

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
    if 'name_ja' in data:
        character.name_ja = data['name_ja']
    elif 'hashtags' in data:
        for hashtag in data['hashtags'].split(','):
            hashtag, _ = HashTag.objects.get_or_create(name=data['hashtags'])
            hashtag.characters.add(character)
    character.save()
    return JsonResponse({ "success": True, "message": character.name_en + " is succesfully translated: " + character.name_ja })

def update_author_info(screen_name, author=None):
    api = get_twitter_api()
    try:
        user = api.get_user(screen_name=screen_name)
    except:
        return None
    if author is None:
        author, _ = Author.objects.get_or_create(author_id=user.id)
        author.screen_name = screen_name
    if user.default_profile_image:
        author.profile_image_url = 'https://abs.twimg.com/sticky/default_profile_images/default_profile.png'
    else:
        author.profile_image_url = user.profile_image_url_https.replace('_normal', '')
    if 'にじさーち削除依頼' in user.description:
        author.is_blocked = True
        images = ImageEntry.objects.filter(author=author)
        for image in images:
            image.collection = False
            image.save()
    author.is_protected = user.protected
    author.save()
    return author

@require_POST
def update_author(request):
    data = json.loads(request.body)
    screen_name = data['screen_name']
    author, _ = Author.objects.get_or_create(screen_name=screen_name)
    res = update_author_info(screen_name)
    if res is not None:
        return JsonResponse({"success": True})
    else:
        return JsonResponse({"success": False, "reason": "User not found"})

def author(request, screen_name):
    order = request.GET.get('order', default='created_at')
    page = request.GET.get('page', default='1')
    page = int(page)
    show_unlisted = request.GET.get('show_unlisted', default='f')
    show_unlisted = True if show_unlisted == 't' else False
    try:
        author = Author.objects.get(screen_name=screen_name)
        if author.profile_image_url == "":
            update_author_info(screen_name, author)
    except:
        author = update_author_info(screen_name)
        if author is None:
            return render(request, 'main/author.html', { 'notFound': True, 'screen_name': screen_name })
    if author.is_blocked:
        return render(request, 'main/author.html', { 'author': author, 'blocked': True })
    if author.is_protected:
        return render(request, 'main/author.html', { 'author': author, 'protected': True })
    images = ImageEntry.objects.filter(author=author)
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not profile.show_nsfw:
            safe = I2VTag.objects.get(name='safe')
            images = images.filter(i2vtags=safe)
    else:
        safe = I2VTag.objects.get(name='safe')
        images = images.filter(i2vtags=safe)

    if not show_unlisted:
        images = images.filter(collection=True).exclude(is_duplicated=True)

    if order == 'like':
        images = images.order_by('-status__like_count', 'image_number')
    elif order == 'id':
        images = images.order_by('-pk', 'image_number')
    else:
        images = images.order_by('-status__created_at', 'image_number')
    images_count = images.count()

    images_per_page = 60
    page_size = -(-images_count // images_per_page)  # round up
    url = request.path + f'?order={order}'
    if show_unlisted:
     url = request.path + f'?order={order}'
    if show_unlisted:
        url += '&show_unlisted=t'
    if images_count > images_per_page:
        pages = [{"url": f'{url}&page={p+1}', "n": p+1} for p in range(page_size)]
        images = images[images_per_page*(page-1):images_per_page*page]
        pages = reduce_pages(pages, page)
    else:
        pages = None
    prev_page = url + f'&page={page-1}' if page != 1 else None
    next_page = url + f'&page={page+1}' if page != page_size and page_size != 0 else None

    return render(request, 'main/author.html', {
        'author': author, 'order': order, 'show_unlisted': show_unlisted,
        'pages': pages, 'current_page': page,
        'prev_page': prev_page, 'next_page': next_page,
        'image_entry_list': images,
        'images_count': images_count})

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

    if status.author.is_blocked:
        return render(request, 'main/status.html', {'blocked': True})
    if status.author.is_protected:
        return render(request, 'main/status.html', {'protected': True})

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
            "diff": entry.is_trimmed,
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
            try:
                entry = ImageEntry.objects.get(media_url=media_url)
                names.extend([chara.name_en for chara in entry.characters.all()])
                similar_images.append({"status_url": f"/status/{status_id}/?n={entry.image_number}",
                                       "media_url": f"{media_url}:small"})
            except:
                similar_images.append({"status_url": f"/status/{status_id}/",
                                       "media_url": f"{media_url}:small"})
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
    only_confirmed = request.GET.get('confirmed', default='t')
    page = request.GET.get('page', default='1')
    page = int(page)
    order = request.GET.get('order', default='created_at')
    only_confirmed = True if only_confirmed == 't' else False

    editor = False
    if request.user.is_authenticated:
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        profile = UserProfile.objects.get(user=user)
        if profile.editor:
            editor = True

    images = ImageEntry.objects.filter(collection=True).exclude(is_duplicated=True)
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
        hashtags = hashtags.split(';')
        for tag_name in hashtags:
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
    related_hashtags = None
    if character is not None:
        query += f"&character={quote(character)}"
        try:
            character_tag = Character.objects.get(name_en=character)
        except Character.DoesNotExist:
            try:
                character_tag = Character.objects.get(name_ja=character)
            except Character.DoesNotExist:
                return render(request, 'main/search.html', {'character': character, 'notfound': True})
        images = images.filter(characters=character_tag)
        if only_confirmed:
            images = images.filter(confirmed=True)
        related_hashtags = HashTag.objects.filter(characters=character_tag)
        related_hashtags = ','.join([tag.name for tag in related_hashtags])

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
    page_size = -(-images_count // images_per_page)  # round up
    url = request.path + f'?{query}'
    if not only_confirmed:
        url += '&confirmed=f'

    if order == 'like':
        images = images.order_by('-status__like_count', 'image_number')
        url += '&order=like'
    elif order == 'id':
        images = images.order_by('-pk', 'image_number')
        url += '&order=id'
    else:
        images = images.order_by('-status__created_at', 'image_number')

    if images_count > images_per_page:
        pages = [{"url": f'{url}&page={p+1}', "n": p+1} for p in range(page_size)]
        images = images[images_per_page*(page-1):images_per_page*page]
        pages = reduce_pages(pages, page)
    else:
        pages = None

    prev_page = url + f'&page={page-1}' if page != 1 else None
    next_page = url + f'&page={page+1}' if page != page_size and page_size != 0 else None

    return render(request, 'main/search.html', 
            {'images': images, 'images_count': images_count, 'order': order,
            'only_confirmed': only_confirmed, 'editor': editor, 'keyword': keyword,
             'i2vtags': i2vtags, 'character': character_tag, 'hashtags': hashtags,
             'related_hashtags': related_hashtags, 'pages': pages, 'current_page': page,
             'prev_page': prev_page, 'next_page': next_page})


def unlisted(request):
    page = request.GET.get('page', default='1')
    page = int(page)
    now = make_aware(datetime.datetime.now())
    td = datetime.timedelta(hours=72)
    start = now - td
    images = ImageEntry.objects.filter(collection=False).exclude(author__is_blocked=True)
    images = images.exclude(is_duplicated=True).exclude(is_trimmed=True)
    images = images.filter(status__registered_at__range=(start, now)).order_by('-status__like_count')
    images = images.order_by('-status__like_count')

    images_per_page = 120
    images_count = images.count()
    page_size = -(-images_count // images_per_page)  # round up
    url = request.path
    if images_count > images_per_page:
        pages = [{"url": f'{url}?page={p+1}', "n": p+1} for p in range(page_size)]
        images = images[images_per_page*(page-1):images_per_page*page]
        pages = reduce_pages(pages, page)
    else:
        pages = None
    prev_page = url + f'?page={page-1}' if page != 1 else None
    next_page = url + f'?page={page+1}' if page != page_size and page_size != 0 else None

    return render(request, 'main/ranking.html', {'images': images, 'pages': pages, 'current_page': page, 'prev_page': prev_page, 'next_page': next_page, 'unlisted': True, 'editor': True})

@csrf_exempt
@require_POST
def report(request):
    data = json.loads(request.body)
    try:
        status = Status.objects.get(status_id=data['status_id'])
        image = ImageEntry.objects.get(status=status, image_number=data['image_number'])
        if data['report_type'] == 'not_illust':
            image.collection = False
            try:
                filename = os.path.basename(urlparse(image.media_url).path)
                filename = os.path.join(os.path.dirname(__file__), '../false_positive', filename)
                urllib.request.urlretrieve(image.media_url + ':small', filename)
            except:
                pass
        elif data['report_type'] == 'is_illust':
            image.collection = True
            try:
                filename = os.path.basename(urlparse(image.media_url).path)
                filename = os.path.join(os.path.dirname(__file__), '../false_negative', filename)
                urllib.request.urlretrieve(image.media_url + ':small', filename)
            except:
                pass
        elif data['report_type'] == 'safe':
            image.is_nsfw = False
        elif data['report_type'] == 'not_safe':
            image.is_nsfw = True
        elif data['report_type'] == 'deleted':
            image.is_deleted = True
            image.collection = False
        elif data['report_type'] == 'diff':
            image.is_trimmed = True
            image.collection = False
        elif data['report_type'] == 'not_diff':
            image.is_trimmed = False
            image.collection = True
        image.save()
        status.contains_illust = any([img.collection for img in ImageEntry.objects.filter(status=status)])
        status.save()
    except Exception as e:
        return JsonResponse({ "success": False, })
    return JsonResponse({ "success": True, })

@csrf_exempt
@require_POST
@login_required
def register_character(request):
    data = json.loads(request.body)
    if "name_en" in data:
        try:
            character = Character.objects.get(name_en=data['name_en'])
        except:
            user = UserSocialAuth.objects.get(user_id=request.user.id)
            if user.access_token['screen_name'] == 'kivantium':
                character = Character.objects.create(name_en=data['name_en'])
            else:
                return JsonResponse({ "success": False, })
    else:
        return JsonResponse({ "success": False, })
    try:
        status = Status.objects.get(status_id=int(data['status_id']))
        image_entry = ImageEntry.objects.get(status=status, image_number=data['image_number'])
        image_entry.characters.add(character)
        image_entry.confirmed = True
        image_entry.save()
        identical_images = ImageEntry.objects.filter(imagehash=image_entry.imagehash, author=image_entry.author)
        for entry in identical_images:
            if entry == image_entry:
                continue
            entry.characters.clear()
            entry.characters.add(*image_entry.characters.all())
            entry.confirmed = True
            entry.save()
        user = UserSocialAuth.objects.get(user_id=request.user.id)
        log_info(f"Register {data['name_en']} to status {data['status_id']} (n={data['image_number']}) by {user.access_token['screen_name']}")
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
        return JsonResponse({ "success": False, })
    status = Status.objects.get(status_id=int(data['status_id']))
    image_entry = ImageEntry.objects.get(status=status, image_number=data['image_number'])
    image_entry.characters.remove(character)
    if image_entry.characters.count() == 0:
        image_entry.confirmed = False
    else:
        image_entry.confirmed = True
    image_entry.save()
    identical_images = ImageEntry.objects.filter(imagehash=image_entry.imagehash, author=image_entry.author)
    for entry in identical_images:
        if entry == image_entry:
            continue
        entry.characters.clear()
        entry.characters.add(*image_entry.characters.all())
        entry.confirmed = image_entry.confirmed
        entry.save()
    user = UserSocialAuth.objects.get(user_id=request.user.id)
    log_info(f"Delete {data['name']} from status {data['status_id']} (n={data['image_number']}) by {user.access_token['screen_name']}")
    return JsonResponse({ "success": True, })

@csrf_exempt
@require_POST
def suggest_character(request):
    data = json.loads(request.body)
    characters = Character.objects.filter(name_en__contains=data['content'])
    return JsonResponse({"success": True, "names": [c.name_en for c in characters]})
