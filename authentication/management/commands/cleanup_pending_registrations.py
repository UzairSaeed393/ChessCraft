from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from authentication.models import PendingRegistration


class Command(BaseCommand):
    help = "Delete unverified pending registrations older than N days (default: 7)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Delete PendingRegistration records created more than N days ago.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print how many records would be deleted.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]

        if days < 1:
            self.stderr.write(self.style.ERROR("--days must be >= 1"))
            return

        cutoff = timezone.now() - timedelta(days=days)
        qs = PendingRegistration.objects.filter(created_at__lt=cutoff)
        count = qs.count()

        if dry_run:
            self.stdout.write(f"Would delete {count} pending registration(s) older than {days} day(s).")
            return

        deleted_count, _ = qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_count} pending registration(s) older than {days} day(s)."
            )
        )
