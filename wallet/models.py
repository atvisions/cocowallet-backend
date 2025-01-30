from django.db import models
from django.conf import settings

class Wallet(models.Model):
    """钱包模型"""
    CHAIN_CHOICES = [(key, value['name']) for key, value in settings.SUPPORTED_CHAINS.items()]
    
    device_id = models.CharField(max_length=100, verbose_name='设备ID')
    name = models.CharField(max_length=100, verbose_name='钱包名称')
    chain = models.CharField(max_length=20, verbose_name='区块链')
    address = models.CharField(max_length=100, verbose_name='地址')
    encrypted_private_key = models.TextField(verbose_name='加密私钥', null=True, blank=True)
    avatar = models.ImageField(upload_to='wallet_avatars/', verbose_name='头像', null=True, blank=True)
    is_active = models.BooleanField(default=True, verbose_name='是否激活')
    is_watch_only = models.BooleanField(default=False, verbose_name='是否观察者钱包')
    is_imported = models.BooleanField(default=False, verbose_name='是否导入的钱包')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '钱包'
        verbose_name_plural = '钱包'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.address})"

class MnemonicBackup(models.Model):
    """助记词备份模型"""
    device_id = models.CharField(max_length=100, verbose_name='设备ID')
    encrypted_mnemonic = models.TextField(verbose_name='加密助记词')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '助记词备份'
        verbose_name_plural = '助记词备份'
        ordering = ['-created_at']

    def __str__(self):
        return f"Backup for device {self.device_id}"

class PaymentPassword(models.Model):
    """支付密码模型"""
    device_id = models.CharField(max_length=100, unique=True, verbose_name='设备ID')
    encrypted_password = models.CharField(max_length=255, verbose_name='加密的支付密码')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '支付密码'
        verbose_name_plural = '支付密码'

    def __str__(self):
        return f"Payment password for device {self.device_id}"
