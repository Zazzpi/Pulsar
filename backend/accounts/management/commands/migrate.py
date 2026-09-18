from django.core.management.base import CommandError
from django.core.management.commands.migrate import Command as DjangoMigrateCommand


class Command(DjangoMigrateCommand):
    """Refuse before Django's migration recorder can try creating a WMS table."""

    def handle(self, *args, **options):
        if options.get("database", "default") != "default":
            raise CommandError("Migrations are allowed only on the application's default database")
        return super().handle(*args, **options)
