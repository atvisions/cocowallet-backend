from django.core.management.base import BaseCommand
from wallet.models import Wallet, PaymentPassword, encrypt_string, decrypt_string
import base64, base58
from cryptography.fernet import Fernet
import os

class Command(BaseCommand):
    help = '使用新的加密方式重新加密所有钱包的私钥'

    def format_private_key(self, private_key, chain):
        """格式化私钥为正确的格式"""
        if chain == 'SOL':
            try:
                # 如果是十六进制格式，转换为 Base58
                if len(private_key) == 64 and all(c in '0123456789abcdefABCDEF' for c in private_key):
                    return base58.b58encode(bytes.fromhex(private_key)).decode('ascii')
                # 如果是 Base64 格式，先解码再转换为 Base58
                try:
                    decoded = base64.b64decode(private_key)
                    if len(decoded) == 32:
                        return base58.b58encode(decoded).decode('ascii')
                except:
                    pass
                # 如果已经是 Base58 格式，直接返回
                return private_key
            except Exception as e:
                raise ValueError(f"格式化私钥失败: {str(e)}")
        else:
            # EVM 链使用十六进制格式
            if private_key.startswith('0x'):
                return private_key[2:]
            return private_key

    def decrypt_old_private_key(self, encrypted_key):
        """使用旧的方式解密私钥"""
        try:
            # 第一层解密
            key = os.getenv('ENCRYPTION_KEY', '').encode()
            f = Fernet(base64.urlsafe_b64encode(key.ljust(32)[:32]))
            
            # 解密第一层
            first_decrypted = f.decrypt(base64.b64decode(encrypted_key))
            
            # 尝试解密第二层
            try:
                second_decrypted = f.decrypt(first_decrypted)
                # 如果是 Base64 编码的，继续解码
                try:
                    third_decrypted = base64.b64decode(second_decrypted)
                    # 如果是十六进制格式，转换为 Base58
                    if len(third_decrypted) == 32:
                        return base58.b58encode(third_decrypted).decode('ascii')
                    return third_decrypted.decode('utf-8')
                except:
                    return second_decrypted.decode('utf-8')
            except:
                pass
            
            # 如果第二层解密失败，返回第一层解密结果
            return first_decrypted.decode('utf-8')
        except Exception as e:
            raise ValueError(f"解密失败: {str(e)}")

    def handle(self, *args, **options):
        # 获取所有钱包
        wallets = Wallet.objects.all()
        
        # 重新加密私钥
        for wallet in wallets:
            try:
                # 使用旧的方式解密私钥
                original_private_key = self.decrypt_old_private_key(wallet.encrypted_private_key)
                
                # 格式化私钥
                formatted_private_key = self.format_private_key(original_private_key, wallet.chain)
                
                # 使用新的方式重新加密
                wallet.encrypted_private_key = encrypt_string(formatted_private_key)
                wallet.save()
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'重新加密钱包 {wallet.address} 的私钥成功，'
                        f'原始私钥: {original_private_key}, '
                        f'格式化后: {formatted_private_key}'
                    )
                )
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'重新加密钱包 {wallet.address} 的私钥失败: {str(e)}'))
        
        self.stdout.write(self.style.SUCCESS('所有钱包私钥已重新加密')) 