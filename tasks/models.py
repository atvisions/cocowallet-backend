from django.db import models
from django.utils import timezone
from django.conf import settings
from cryptography.fernet import Fernet
import json

def encrypt_string(text):
    """使用 Fernet 对称加密方法加密字符串"""
    if not text:
        return None
    f = Fernet(settings.ENCRYPTION_KEY.encode())
    return f.encrypt(text.encode()).decode()

def decrypt_string(encrypted_text):
    """使用 Fernet 对称加密方法解密字符串"""
    if not encrypted_text:
        return None
    f = Fernet(settings.ENCRYPTION_KEY.encode())
    return f.decrypt(encrypted_text.encode()).decode()

class Task(models.Model):
    """任务模型"""
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField()
    points = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

class TaskHistory(models.Model):
    """任务完成历史记录"""
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    device_id = models.CharField(max_length=100)
    completed_at = models.DateTimeField(auto_now_add=True)
    points_awarded = models.IntegerField(default=0)

    class Meta:
        unique_together = ['task', 'device_id', 'completed_at']

    def __str__(self):
        return f"{self.device_id} completed {self.task.name}"

class UserPoints(models.Model):
    """用户积分"""
    device_id = models.CharField(max_length=100, unique=True)
    total_points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_or_create_user_points(cls, device_id):
        """获取或创建用户积分记录"""
        points, created = cls.objects.get_or_create(device_id=device_id)
        return points

    def add_points(self, points, action_type, description, related_device_id=None):
        """添加积分"""
        self.total_points += points
        self.save()

        # 记录积分历史
        PointsHistory.objects.create(
            device_id=self.device_id,
            points=points,
            action_type=action_type,
            description=description,
            related_device_id=related_device_id
        )

    def __str__(self):
        return f"{self.device_id}: {self.total_points} points"

class PointsHistory(models.Model):
    """积分历史记录"""
    ACTION_TYPES = (
        ('DAILY_CHECK_IN', '每日签到'),
        ('TASK_COMPLETION', '完成任务'),
        ('SHARE_TASK', '分享任务'),
        ('REFERRAL', '推荐奖励')
    )

    device_id = models.CharField(max_length=100)
    points = models.IntegerField()
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    description = models.TextField()
    related_device_id = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.device_id} earned {self.points} points from {self.get_action_type_display()}"

class ShareTaskToken(models.Model):
    """分享任务代币"""
    token = models.ForeignKey('wallet.Token', on_delete=models.CASCADE)
    points = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Share task for {self.token.symbol}"

class ReferralLink(models.Model):
    """推荐链接模型"""
    device_id = models.CharField(max_length=100, help_text='设备ID')
    code = models.CharField(max_length=20, unique=True, help_text='推荐码')
    clicks = models.IntegerField(default=0, help_text='点击次数')
    is_active = models.BooleanField(default=True, help_text='是否激活')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    updated_at = models.DateTimeField(auto_now=True, help_text='更新时间')

    class Meta:
        db_table = 'referral_link'
        verbose_name = '推荐链接'
        verbose_name_plural = '推荐链接'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.device_id} - {self.code}"

    @classmethod
    def get_or_create_link(cls, device_id):
        """获取或创建推荐链接"""
        link, created = cls.objects.get_or_create(
            device_id=device_id,
            defaults={'code': cls.generate_code()}
        )
        return link

    @staticmethod
    def generate_code():
        """生成推荐码"""
        import random
        import string
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        while ReferralLink.objects.filter(code=code).exists():
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return code

    def increment_clicks(self):
        """增加点击次数"""
        self.clicks += 1
        self.save()

    def get_full_link(self):
        """获取完整的推荐链接"""
        from django.conf import settings
        base_url = settings.REFERRAL_BASE_URL
        return f"{base_url}?code={self.code}"

class ReferralRelationship(models.Model):
    """推荐关系模型"""
    referrer_device_id = models.CharField(max_length=100, help_text='推荐人设备ID')
    referred_device_id = models.CharField(max_length=100, help_text='被推荐人设备ID')
    download_completed = models.BooleanField(default=False, help_text='是否完成下载')
    wallet_created = models.BooleanField(default=False, help_text='是否创建钱包')
    download_points_awarded = models.BooleanField(default=False, help_text='是否已发放下载奖励')
    wallet_points_awarded = models.BooleanField(default=False, help_text='是否已发放钱包创建奖励')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    updated_at = models.DateTimeField(auto_now=True, help_text='更新时间')

    class Meta:
        db_table = 'referral_relationship'
        verbose_name = '推荐关系'
        verbose_name_plural = '推荐关系'
        ordering = ['-created_at']
        unique_together = [['referrer_device_id', 'referred_device_id']]

    def __str__(self):
        return f"{self.referrer_device_id} -> {self.referred_device_id}" 