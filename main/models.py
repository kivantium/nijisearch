from django.db import models

class I2VTag(models.Model):
    TAG_TYPES = (
        ('CO', 'copyright'),
        ('GE', 'general'),
        ('CH', 'character'),
        ('RA', 'rating'),
    )
    name = models.CharField(max_length=40)
    tag_type = models.CharField(max_length=2, choices=TAG_TYPES)
    def __str__(self):
        return self.name

class HashTag(models.Model):
    name = models.CharField(max_length=140)
    def __str__(self):
        return self.name

class Character(models.Model):
    name_ja = models.TextField()
    name_en = models.TextField()

    def __str__(self):
        return self.name_ja


class Author(models.Model):
    author_id = models.BigIntegerField()
    screen_name = models.CharField(max_length=32)
    is_blocked = models.BooleanField(default=False)

    def __str__(self):
        return f"@{self.screen_name} ({self.author_id})"

class Status(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    status_id = models.BigIntegerField()
    contains_illust = models.BooleanField(default=False)
    text = models.TextField()
    hashtags = models.ManyToManyField(HashTag)
    retweet_count = models.IntegerField(default=0)
    like_count = models.IntegerField(default=0)
    created_at = models.DateTimeField()
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    thumbnail = models.IntegerField(default=0)
    thumbnail_url = models.URLField()

    def __str__(self):
        return f"@{self.author.screen_name} ({self.author_id})"

class ImageEntry(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    status = models.ForeignKey(Status, on_delete=models.CASCADE)
    image_number = models.IntegerField()
    media_url = models.URLField()
    collection = models.BooleanField()
    confirmed = models.BooleanField(default=False)
    is_nsfw = models.BooleanField(default=False)
    is_duplicated = models.BooleanField(default=False)
    is_trimmed = models.BooleanField(default=False)
    i2vtags = models.ManyToManyField(I2VTag)
    characters = models.ManyToManyField(Character, related_name='characters')
    similar_characters = models.ManyToManyField(Character, related_name='similars')
    thumbnail = models.FilePathField()

    def __str__(self):
        return "{} (by @{})".format(self.media_url, self.author.screen_name)

