# Generated by Django 4.2.18 on 2025-02-14 05:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wallet", "0012_alter_token_options_token_is_recommended"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="token_info",
            field=models.JSONField(blank=True, null=True, verbose_name="代币信息"),
        ),
    ]
