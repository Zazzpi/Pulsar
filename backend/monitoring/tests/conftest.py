import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import Client

from accounts.models import ApiToken


@pytest.fixture(autouse=True)
def isolated_cache(settings):
    settings.WMS_MODE = "mock"
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    cache.clear()
    caches["login_limits"].clear()
    yield
    cache.clear()
    caches["login_limits"].clear()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="sales_a", password="A-test-passphrase-218")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="sales_b", password="B-test-passphrase-219")


@pytest.fixture
def api(user):
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = "Bearer " + ApiToken.issue(user)
    return client


@pytest.fixture
def other_api(other_user):
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = "Bearer " + ApiToken.issue(other_user)
    return client
