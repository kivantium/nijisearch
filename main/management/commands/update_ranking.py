from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware

from ...models import ImageEntry, Status

import datetime
import tweepy
import time
import pytz
import requests

def get_twitter_api():
    consumer_key = settings.SOCIAL_AUTH_TWITTER_KEY
    consumer_secret = settings.SOCIAL_AUTH_TWITTER_SECRET
    access_token = settings.SOCIAL_AUTH_ACCESS_TOKEN
    access_secret = settings.SOCIAL_AUTH_ACCESS_SECRET

    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(access_token, access_secret)
    return tweepy.API(auth)

api = get_twitter_api()

class Command(BaseCommand):
    def handle(self, *args, **options):
        now = make_aware(datetime.datetime.now())
        td = datetime.timedelta(hours=24)
        start = now - td
        statuses = Status.objects.filter(created_at__range=(start, now))
        for status_entry in statuses:
            try:
                status = api.get_status(status_entry.status_id)
                if status_entry.like_count < 100 and status.favorite_count > 100:
                    image_entries = ImageEntry.objects.filter(status=status_entry)
                    for image in image_entries:
                        if not image.is_trimmed:
                            image.collection = True
                            image.save()
                status_entry.like_count = status.favorite_count
                status_entry.retweet_count = status.retweet_count
                status_entry.save()
            except (tweepy.errors.NotFound, tweepy.errors.Forbidden) as e:
                image_entries = ImageEntry.objects.filter(status=status_entry)
                for image in image_entries:
                    image.is_deleted = True
                    image.collection = False
                    image.save()
            time.sleep(1)
