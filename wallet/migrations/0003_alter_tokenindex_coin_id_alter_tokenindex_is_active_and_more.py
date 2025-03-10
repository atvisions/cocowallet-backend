# Generated by Django 4.2.18 on 2025-01-31 15:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wallet", "0002_tokenindex"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tokenindex",
            name="coin_id",
            field=models.CharField(max_length=100, unique=True, verbose_name="代币ID"),
        ),
        migrations.AlterField(
            model_name="tokenindex",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="是否激活"),
        ),
        migrations.AlterField(
            model_name="tokenindex",
            name="is_new",
            field=models.BooleanField(default=False, verbose_name="是否新增"),
        ),
    ]
