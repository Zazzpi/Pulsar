import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a demo account from DEMO_USERNAME/DEMO_PASSWORD (mock mode only)."

    def handle(self, *args, **options):
        if settings.WMS_MODE != "mock":
            raise CommandError("Demo accounts can only be created in mock mode")
        username = os.getenv("DEMO_USERNAME", "")
        password = os.getenv("DEMO_PASSWORD", "")
        if not username or not password:
            raise CommandError("Set DEMO_USERNAME and DEMO_PASSWORD")
        if len(username) > 150:
            raise CommandError("DEMO_USERNAME exceeds 150 characters")
        user_model = get_user_model()
        if user_model.objects.filter(username=username).exists():
            self.stdout.write("Demo account already exists; password unchanged.")
            return
        candidate = user_model(username=username)
        try:
            validate_password(password, candidate)
        except ValidationError:
            raise CommandError("DEMO_PASSWORD does not satisfy password policy") from None
        user_model.objects.create_user(username=username, password=password)
        self.stdout.write(self.style.SUCCESS("Demo account created."))
