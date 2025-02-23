from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0021_merge_20250218_0008'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentpassword',
            name='is_biometric_enabled',
            field=models.BooleanField(default=False, verbose_name='是否启用生物密码'),
        ),
        migrations.AddField(
            model_name='paymentpassword',
            name='biometric_verified_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='最后生物密码验证时间'),
        ),
    ]