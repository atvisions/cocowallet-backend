from django.core.management.base import BaseCommand
from wallet.models import Wallet
from django.conf import settings
from cryptography.fernet import Fernet
import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '使用新的加密密钥重新加密所有钱包的私钥'

    def add_arguments(self, parser):
        parser.add_argument('--old-key', type=str, required=True, help='旧的加密密钥')

    def handle(self, *args, **options):
        old_key = options['old_key'].encode()
        
        # 生成旧密钥的Fernet实例
        old_key_hash = hashlib.sha256(old_key).digest()
        old_fernet = Fernet(base64.urlsafe_b64encode(old_key_hash))
        
        # 生成新密钥的Fernet实例
        new_key = settings.WALLET_ENCRYPTION_KEY
        new_key_hash = hashlib.sha256(new_key).digest()
        new_fernet = Fernet(base64.urlsafe_b64encode(new_key_hash))
        
        # 获取所有有私钥的钱包
        wallets = Wallet.objects.exclude(encrypted_private_key__isnull=True).exclude(encrypted_private_key='')
        
        success_count = 0
        error_count = 0
        
        for wallet in wallets:
            try:
                # 使用旧密钥解密
                if isinstance(wallet.encrypted_private_key, str):
                    encrypted_bytes = wallet.encrypted_private_key.encode()
                else:
                    encrypted_bytes = wallet.encrypted_private_key
                    
                decrypted = old_fernet.decrypt(encrypted_bytes)
                
                # 使用新密钥加密
                new_encrypted = new_fernet.encrypt(decrypted)
                
                # 保存新的加密私钥
                wallet.encrypted_private_key = new_encrypted.decode()
                wallet.save()
                
                success_count += 1
                self.stdout.write(self.style.SUCCESS(f'成功重新加密钱包 {wallet.address}'))
                
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f'重新加密钱包 {wallet.address} 失败: {str(e)}'))
                logger.error(f'重新加密钱包失败: {str(e)}')
        
        self.stdout.write(self.style.SUCCESS(f'完成重新加密。成功: {success_count}, 失败: {error_count}')) 