from django.conf import settings
from .models import I2VTag, HashTag, Author, Status, ImageEntry, Character

import tweepy
import os
import sys
import numpy as np
import onnxruntime
import urllib.request
from urllib.parse import urlparse

from PIL import Image
import i2v
import requests
import collections
import imagehash

def get_twitter_api():
    consumer_key = settings.SOCIAL_AUTH_TWITTER_KEY
    consumer_secret = settings.SOCIAL_AUTH_TWITTER_SECRET
    access_token = settings.SOCIAL_AUTH_ACCESS_TOKEN
    access_secret = settings.SOCIAL_AUTH_ACCESS_SECRET

    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(access_token, access_secret)
    return tweepy.API(auth)

def crop_and_resize(img, size):
    width, height = img.size
    crop_size = min(width, height)
    img_crop = img.crop(((width - crop_size) // 2, (height - crop_size) // 2,
                         (width + crop_size) // 2, (height + crop_size) // 2))
    return img_crop.resize((size, size))

def softmax(x):
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum()

img_mean = np.asarray([0.485, 0.456, 0.406])
img_std = np.asarray([0.229, 0.224, 0.225])

illust2vec = i2v.make_i2v_with_onnx(
        os.path.join(os.path.dirname(__file__), "illust2vec_tag_ver200.onnx"),
        os.path.join(os.path.dirname(__file__), "tag_list.json"))

def register_status(status_id):
    api = get_twitter_api()

    try:
        status = api.get_status(status_id, tweet_mode='extended')
    except:
        return {"success": False, "message": f"Failed to retrieve status {status_id}."}

    if hasattr(status, "retweeted_status"):
        status = status.retweeted_status

    if status.author.protected:
        return {"success": False, "message": f"The author {status.author.screen_name} is protected."}

    author_entry, created = Author.objects.get_or_create(author_id=status.author.id)
    if author_entry.is_blocked:
        return {"success": False, "message": f"The author {status.author.screen_name} is blocked."}

    # Update screen name
    if author_entry.screen_name != status.author.screen_name:
        author_entry.screen_name = status.author.screen_name
        author_entry.save()

    if 'media' not in status.entities:
        return {"success": False, "message": f"The status {status_id} has no media."}

    for num, media in enumerate(status.extended_entities['media']):
        if media['type'] == 'video':
            return {"success": False, "message": f"The status {status_id} contains video."}

    status_entry, created = Status.objects.get_or_create(author=author_entry, 
                                                         status_id=status_id,
                                                         created_at=status.created_at)
    # if the status is already registered
    if not created:
        status_entry.retweet_count=status.retweet_count
        status_entry.like_count=status.favorite_count
        status_entry.save()
        return {"success": False, "message": f"The status {status_id} is already registered."}

    try:
        full_text = status.extended_tweet["full_text"]
    except:
        full_text = status.full_text
    hashtags = [tag['text'] for tag in status.entities['hashtags']]

    status_entry.author = author_entry
    status_entry.text = full_text
    for tag in hashtags:
        t, _ = HashTag.objects.get_or_create(name=tag)
        status_entry.hashtags.add(t)
    status_entry.retweet_count = status.retweet_count
    status_entry.like_count = status.favorite_count

    for num, media in enumerate(status.extended_entities['media']):
        media_url = media['media_url_https']
        filename = os.path.basename(urlparse(media_url).path)
        filename = os.path.join('/tmp', filename)
        urllib.request.urlretrieve(media_url, filename)
        img_pil = Image.open(filename).convert('RGB')
        img = crop_and_resize(img_pil, 224)

        img_np = np.asarray(img).astype(np.float32)/255.0
        img_np_normalized = (img_np - img_mean) / img_std
        ort_session = onnxruntime.InferenceSession(
            os.path.join(os.path.dirname(__file__), "model.onnx"))

        # (H, W, C) -> (C, H, W)
        img_np_transposed = img_np_normalized.transpose(2, 0, 1)
        batch_img = [img_np_transposed]
        ort_inputs = {ort_session.get_inputs()[0].name: batch_img}
        ort_outs = ort_session.run(None, ort_inputs)[0]
        probs = softmax(ort_outs[0])
        is_illust = True if probs[1] > 0.3 else False

        # Run Illustration2Vec
        i2vtags = illust2vec.estimate_plausible_tags([img_pil], threshold=0.4)

        img_entry = ImageEntry.objects.create(
                    author = author_entry,
                    status = status_entry,
                    image_number=num,
                    media_url=media_url,
                    collection=is_illust)

        for category, TYPE in [('character', 'CH'), ('copyright', 'CO'), ('general', 'GE')]:
            for tag in i2vtags[0][category]:
                tag_name, tag_prob = tag
                t, _ = I2VTag.objects.get_or_create(name=tag_name, tag_type=TYPE)
                img_entry.i2vtags.add(t)

        rating_name = i2vtags[0]['rating'][0][0]
        rating, _ = I2VTag.objects.get_or_create(name=rating_name, tag_type='RA')
        img_entry.i2vtags.add(rating)

        img_entry.is_nsfw = False if rating_name == 'safe' else True

        names = ['1girl', 'multiple girls', '2girls', '3girls', '4girls']
        has_girl = False
        for tag_name in names:
            t, created = I2VTag.objects.get_or_create(name=tag_name, tag_type='GE')
            if t in img_entry.i2vtags.all():
                has_girl = True
                break
        if not has_girl:
            img_entry.collection = False

        # Reject monochrome image or photo
        names = ['monochrome', 'photo']
        for tag_name in names:
            t, _ = I2VTag.objects.get_or_create(name=tag_name, tag_type='GE')
            if t in img_entry.i2vtags.all():
                img_entry.collection = False

        # Illustration usually contains more than 5 tags.
        if len(img_entry.i2vtags.all()) < 5:
            img_entry.collection = False

        # Add similar characters
        res = requests.post(f'http://{settings.IMAGE_SEARCH_SERVER_IP}/search/', json={"media_url": img_entry.media_url}).json()
        if res['success']:
            characters = []
            indices = res['indices']
            media_urls = res['media_urls']
            for status_id, media_url in zip(indices, media_urls):
                try:
                    entry = ImageEntry.objects.get(media_url=media_url)
                    characters.extend([chara.pk for chara in entry.characters.all()])
                except:
                    pass

            count = collections.Counter(characters)
            for pk in set(characters):
                if count[pk] >= 3:
                    tag = Character.objects.get(pk=pk)
                    img_entry.similar_characters.add(tag)
        img_entry.imagehash = str(imagehash.average_hash(img_pil))
        img_entry.save()

    entries = ImageEntry.objects.filter(status=status_entry)
    status_entry.contains_illust = any([img.collection for img in entries])
    if status_entry.contains_illust:
        img_entry = entries.filter(collection=True).order_by('image_number')[0]
        status_entry.thumbnail_url = img_entry.media_url
    status_entry.save()
    return {"success": True, "message": f"The status {status_id} is registered successfully."}
