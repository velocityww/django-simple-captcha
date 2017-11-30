from captcha.conf import settings as captcha_settings
from mongoengine import Document, StringField, DateTimeField
from django.utils import timezone
from django.utils.encoding import python_2_unicode_compatible
from django.utils.encoding import smart_text
import datetime
import hashlib
import logging
import random
import time


# Heavily based on session key generation in Django
# Use the system (hardware-based) random number generator if it exists.
if hasattr(random, 'SystemRandom'):
    randrange = random.SystemRandom().randrange
else:
    randrange = random.randrange
MAX_RANDOM_KEY = 18446744073709551616     # 2 << 63

logger = logging.getLogger(__name__)


@python_2_unicode_compatible
class CaptchaStore(Document):
    challenge = StringField(required=True, max_length=32, db_field='c')
    response = StringField(required=True, max_length=32, db_field='r')
    hashkey = StringField(required=True, max_length=40, db_field='h', unique=True)
    expiration = DateTimeField(required=True, db_field='e')

    def save(self, *args, **kwargs):
        self.response = self.response.lower()
        if not self.expiration:
            self.expiration = timezone.now() + datetime.timedelta(minutes=int(captcha_settings.CAPTCHA_TIMEOUT))
        if not self.hashkey:
            key_ = (
                smart_text(randrange(0, MAX_RANDOM_KEY)) +
                smart_text(time.time()) +
                smart_text(self.challenge, errors='ignore') +
                smart_text(self.response, errors='ignore')
            ).encode('utf8')
            self.hashkey = hashlib.sha1(key_).hexdigest()
            del(key_)
        super(CaptchaStore, self).save(*args, **kwargs)

    def __str__(self):
        return self.challenge

    def remove_expired(cls):
        cls.objects.filter(expiration__lte=timezone.now()).delete()
    remove_expired = classmethod(remove_expired)

    @classmethod
    def generate_key(cls, generator=None):
        challenge, response = captcha_settings.get_challenge(generator)()
        store = cls.objects.create(challenge=challenge, response=response)
        logger.debug("Created a captcha doc in MongoDB %r", store)

        return store.hashkey

    @classmethod
    def pick(cls):
        if not captcha_settings.CAPTCHA_GET_FROM_POOL:
            return cls.generate_key()

        def fallback():
            logger.error("Couldn't get a captcha from pool, generating")
            return cls.generate_key()

        # Pick up a random item from pool
        minimum_expiration = timezone.now() + datetime.timedelta(minutes=int(captcha_settings.CAPTCHA_GET_FROM_POOL_TIMEOUT))
        store = cls.objects.filter(expiration__gt=minimum_expiration).order_by('?').first()

        return (store and store.hashkey) or fallback()

    @classmethod
    def create_pool(cls, count=1000):
        assert count > 0
        while count > 0:
            cls.generate_key()
            count -= 1
