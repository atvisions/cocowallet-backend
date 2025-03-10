# Generated by Django 4.2.18 on 2025-02-15 12:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wallet", "0013_transaction_token_info"),
    ]

    operations = [
        migrations.AddField(
            model_name="token",
            name="block_number",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="区块高度"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="categories",
            field=models.JSONField(
                blank=True, default=list, null=True, verbose_name="分类"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="circulating_supply",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="流通供应量"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="email",
            field=models.EmailField(
                blank=True, max_length=255, null=True, verbose_name="邮箱"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="fully_diluted_valuation",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="完全稀释估值"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="instagram",
            field=models.URLField(
                blank=True, max_length=500, null=True, verbose_name="Instagram"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="logo_hash",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="Logo哈希"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="market_cap",
            field=models.CharField(
                blank=True, max_length=255, null=True, verbose_name="市值"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="moralis",
            field=models.URLField(
                blank=True, max_length=500, null=True, verbose_name="Moralis"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="thumbnail",
            field=models.URLField(
                blank=True, max_length=500, null=True, verbose_name="缩略图"
            ),
        ),
        migrations.AddField(
            model_name="token",
            name="validated",
            field=models.IntegerField(default=0, verbose_name="验证状态"),
        ),
        migrations.AlterField(
            model_name="token",
            name="reddit",
            field=models.URLField(
                blank=True, max_length=500, null=True, verbose_name="Reddit"
            ),
        ),
    ]
