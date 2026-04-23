from django.db import migrations, models
from django.db.models import F
from django.utils import timezone


def backfill_game_fetched_at(apps, schema_editor):
    Game = apps.get_model('user', 'Game')

    # Best-effort backfill for older rows.
    # If date_played exists, use it as an approximation; otherwise use 'now'.
    Game.objects.filter(fetched_at__isnull=True, date_played__isnull=False).update(
        fetched_at=F('date_played')
    )
    Game.objects.filter(fetched_at__isnull=True, date_played__isnull=True).update(
        fetched_at=timezone.now()
    )


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0003_game_unique_user_game_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='fetched_at',
            field=models.DateTimeField(auto_now_add=True, blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_game_fetched_at, reverse_code=migrations.RunPython.noop),
    ]
