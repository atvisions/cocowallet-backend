from django.db import models
from django.utils import timezone
from cryptography.fernet import Fernet
import base64
from solana.keypair import Keypair
from eth_account import Account
import json
import os
import logging
import hashlib
import base58

logger = logging.getLogger(__name__)

def encrypt_string(text: str) -> str:
    """使用 Fernet 加密字符串"""
    try:
        # 从环境变量获取密钥
        key = os.getenv('ENCRYPTION_KEY', '').encode()
        if not key:
            raise ValueError("ENCRYPTION_KEY environment variable is not set")
        
        # 确保密钥长度为32字节
        key = key.ljust(32)[:32]
        
        # 创建 Fernet 实例
        f = Fernet(base64.urlsafe_b64encode(key))
        
        # 加密数据
        encrypted = f.encrypt(text.encode())
        return base64.b64encode(encrypted).decode('utf-8')
        
    except Exception as e:
        logger.error(f"加密失败: {str(e)}")
        raise ValueError(f"加密失败: {str(e)}")

def decrypt_string(encrypted_text: str) -> str:
    """使用 Fernet 解密字符串"""
    try:
        # 从环境变量获取密钥
        key = os.getenv('ENCRYPTION_KEY', '').encode()
        if not key:
            raise ValueError("ENCRYPTION_KEY environment variable is not set")
        
        # 确保密钥长度为32字节
        key = key.ljust(32)[:32]
        
        # 创建 Fernet 实例
        f = Fernet(base64.urlsafe_b64encode(key))
        
        # Base64 解码
        encrypted_bytes = base64.b64decode(encrypted_text)
        
        # 解密数据
        decrypted = f.decrypt(encrypted_bytes)
        return decrypted.decode('utf-8')
        
    except Exception as e:
        logger.error(f"解密失败: {str(e)}")
        raise ValueError(f"解密失败: {str(e)}")

class Chain:
    """支持的区块链类型"""
    ETH = 'ETH'  # 以太坊主网
    BSC = 'BSC'  # 币安智能链
    MATIC = 'MATIC'  # Polygon
    SOL = 'SOL'  # Solana
    
    CHOICES = [
        (ETH, 'Ethereum'),
        (BSC, 'BNB Chain'),
        (MATIC, 'Polygon'),
        (SOL, 'Solana'),
    ]
    
    @staticmethod
    def is_evm_chain(chain):
        """判断是否是EVM兼容链"""
        return chain in [Chain.ETH, Chain.BSC, Chain.MATIC]
    
    @staticmethod
    def is_solana_chain(chain):
        """判断是否是Solana链"""
        return chain == Chain.SOL

class Wallet(models.Model):
    """钱包模型"""
    device_id = models.CharField(max_length=100, help_text='设备ID')
    name = models.CharField(max_length=100, help_text='钱包名称')
    chain = models.CharField(max_length=10, choices=Chain.CHOICES, help_text='区块链类型')
    address = models.CharField(max_length=100, help_text='钱包地址')
    encrypted_private_key = models.CharField(max_length=500, help_text='加密后的私钥')
    avatar = models.ImageField(upload_to='wallet_avatars/', null=True, blank=True, help_text='钱包头像')
    is_active = models.BooleanField(default=True, help_text='是否激活')
    is_watch_only = models.BooleanField(default=False, help_text='是否只读')
    is_imported = models.BooleanField(default=False, help_text='是否导入')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    updated_at = models.DateTimeField(auto_now=True, help_text='更新时间')
    
    _payment_password = None
    
    @property
    def payment_password(self):
        return self._payment_password
        
    @payment_password.setter
    def payment_password(self, value):
        self._payment_password = value

    class Meta:
        db_table = 'wallet'
        verbose_name = '钱包'
        verbose_name_plural = '钱包'
        ordering = ['-created_at']
        unique_together = [['device_id', 'address']]
    
    def __str__(self):
        return f"{self.name} ({self.chain})"
    
    def check_device_id(self, device_id: str) -> bool:
        """检查设备ID是否匹配"""
        return self.device_id == device_id
    
    def check_payment_password(self, payment_password: str) -> bool:
        """检查支付密码是否正确"""
        try:
            pwd = PaymentPassword.objects.get(device_id=self.device_id)
            return pwd.check_password(payment_password)
        except PaymentPassword.DoesNotExist:
            return False
    
    def encrypt_private_key(self, private_key, payment_password):
        """加密私钥"""
        try:
            # 确保私钥是字符串类型
            if isinstance(private_key, bytes):
                if self.chain == 'SOL':
                    private_key = base58.b58encode(private_key).decode('ascii')
                else:
                    private_key = '0x' + private_key.hex()
            
            # 使用支付密码作为密钥
            key_bytes = hashlib.sha256(payment_password.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            # 加密数据
            encrypted = f.encrypt(private_key.encode())
            return base64.b64encode(encrypted).decode('utf-8')
                
        except Exception as e:
            logger.error(f"加密私钥失败: {str(e)}")
            raise ValueError(f"加密私钥失败: {str(e)}")

    def decrypt_private_key(self) -> str:
        """解密私钥"""
        if not self.encrypted_private_key:
            logger.error("Wallet does not have a private key")
            raise ValueError("Wallet does not have a private key")
        
        if self.is_watch_only:
            logger.error("Watch-Only wallet does not have a private key")
            raise ValueError("Watch-Only wallet does not have a private key")
            
        try:
            # 获取支付密码
            if not self.payment_password:
                raise ValueError("Payment password not provided")
            
            # 使用 Fernet 解密私钥
            from wallet.views.wallet import WalletViewSet
            wallet_viewset = WalletViewSet()
            
            # 记录解密前的数据
            logger.debug(f"Encrypted private key length: {len(self.encrypted_private_key)}")
            logger.debug(f"Payment password length: {len(self.payment_password)}")
            
            # 解密数据
            decrypted = wallet_viewset.decrypt_data(self.encrypted_private_key, self.payment_password)
            
            # 记录解密后的数据
            logger.debug(f"Decrypted data type: {type(decrypted)}")
            logger.debug(f"Decrypted data length: {len(decrypted) if isinstance(decrypted, (str, bytes)) else 'N/A'}")
            
            # 根据链类型处理私钥
            if self.chain == 'SOL':
                try:
                    # 如果是字节类型，尝试转换为原始格式
                    if isinstance(decrypted, bytes):
                        # 尝试 Base58 编码
                        try:
                            # 验证私钥长度
                            if len(decrypted) != 32:
                                raise ValueError(f"Invalid private key length: {len(decrypted)}")
                            
                            # 验证生成的地址
                            keypair = Keypair.from_seed(decrypted)
                            generated_address = str(keypair.public_key)
                            logger.debug(f"Generated address: {generated_address}")
                            
                            if generated_address != self.address:
                                raise ValueError(f"Private key does not match: Expected={self.address}, Actual={generated_address}")
                            
                            # 返回 Base58 编码的私钥
                            return base58.b58encode(decrypted).decode('ascii')
                        except:
                            # 如果 Base58 编码失败，尝试其他格式
                            pass
                    
                    # 如果是字符串类型，直接返回
                    if isinstance(decrypted, str):
                        # 验证私钥格式
                        try:
                            # 尝试解码为 Base58
                            keypair = Keypair.from_secret_key(base58.b58decode(decrypted))
                            if str(keypair.public_key) != self.address:
                                raise ValueError("Private key does not match address")
                            return decrypted
                        except:
                            # 如果不是 Base58 格式，尝试其他格式
                            pass
                    
                    # 如果以上都失败，尝试十六进制格式
                    try:
                        # 如果是十六进制格式
                        if isinstance(decrypted, str) and decrypted.startswith('0x'):
                            private_key_bytes = bytes.fromhex(decrypted[2:])
                        else:
                            private_key_bytes = bytes.fromhex(decrypted)
                        
                        # 验证私钥长度
                        if len(private_key_bytes) != 32:
                            raise ValueError(f"Invalid private key length: {len(private_key_bytes)}")
                        
                        # 验证生成的地址
                        keypair = Keypair.from_seed(private_key_bytes)
                        if str(keypair.public_key) != self.address:
                            raise ValueError(f"Private key does not match: Expected={self.address}, Actual={str(keypair.public_key)}")
                        
                        # 返回十六进制格式
                        return '0x' + private_key_bytes.hex()
                    except:
                        raise ValueError("Invalid private key format")
                    
                except Exception as e:
                    logger.error(f"Failed to verify SOL private key: {str(e)}")
                    raise ValueError(f"Failed to verify SOL private key: {str(e)}")
                    
            elif self.chain in ["ETH", "BASE", "BNB", "MATIC", "AVAX", "ARBITRUM", "OPTIMISM"]:
                try:
                    # 如果是字节类型，尝试转换为原始格式
                    if isinstance(decrypted, bytes):
                        # 验证私钥长度
                        if len(decrypted) != 32:
                            raise ValueError(f"Invalid private key length: {len(decrypted)}")
                        
                        # 验证私钥是否匹配地址
                        account = Account.from_key(decrypted)
                        if account.address.lower() != self.address.lower():
                            raise ValueError(f"Private key address does not match: Expected {self.address}, Actual {account.address}")
                        
                        # 返回十六进制格式
                        return '0x' + decrypted.hex()
                    
                    # 如果是字符串类型，直接返回
                    if isinstance(decrypted, str):
                        # 验证私钥格式
                        try:
                            # 如果是十六进制格式
                            if decrypted.startswith('0x'):
                                private_key_bytes = bytes.fromhex(decrypted[2:])
                            else:
                                private_key_bytes = bytes.fromhex(decrypted)
                            
                            # 验证私钥长度
                            if len(private_key_bytes) != 32:
                                raise ValueError(f"Invalid private key length: {len(private_key_bytes)}")
                            
                            # 验证私钥是否匹配地址
                            account = Account.from_key(private_key_bytes)
                            if account.address.lower() != self.address.lower():
                                raise ValueError(f"Private key address does not match: Expected {self.address}, Actual {account.address}")
                            
                            return decrypted
                        except:
                            # 如果不是十六进制格式，尝试其他格式
                            pass
                    
                    # 如果以上都失败，尝试 Base58 格式
                    try:
                        private_key_bytes = base58.b58decode(decrypted)
                        
                        # 验证私钥长度
                        if len(private_key_bytes) != 32:
                            raise ValueError(f"Invalid private key length: {len(private_key_bytes)}")
                        
                        # 验证私钥是否匹配地址
                        account = Account.from_key(private_key_bytes)
                        if account.address.lower() != self.address.lower():
                            raise ValueError(f"Private key address does not match: Expected {self.address}, Actual {account.address}")
                        
                        # 返回十六进制格式
                        return '0x' + private_key_bytes.hex()
                    except:
                        raise ValueError("Invalid private key format")
                    
                except Exception as e:
                    logger.error(f"Failed to verify EVM private key: {str(e)}")
                    raise ValueError(f"Failed to verify EVM private key: {str(e)}")
            else:
                raise ValueError(f"Unsupported chain type: {self.chain}")
                
        except Exception as e:
            logger.error(f"Failed to decrypt private key: {str(e)}")
            raise ValueError(f"Failed to decrypt private key: {str(e)}")
    
    def get_evm_private_key(self) -> str:
        """获取EVM私钥（带0x前缀）"""
        if not Chain.is_evm_chain(self.chain):
            raise ValueError(f'Chain {self.chain} is not EVM compatible')
        
        private_key = self.decrypt_private_key()
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key.hex()
        return private_key
    
    def get_solana_keypair(self) -> Keypair:
        """获取Solana密钥对"""
        if not Chain.is_solana_chain(self.chain):
            raise ValueError(f'Chain {self.chain} is not Solana')
        
        private_key = self.decrypt_private_key()
        return Keypair.from_secret_key(private_key)

    def encrypt_data(self, data, key):
        """使用 Fernet 加密数据"""
        try:
            # 确保输入数据是字符串类型
            if not isinstance(data, str):
                data = str(data)
            
            # 确保密钥是字符串类型
            if not isinstance(key, str):
                key = str(key)
            
            # 使用 SHA256 生成固定长度的密钥
            key_bytes = hashlib.sha256(key.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            # 加密数据
            encrypted = f.encrypt(data.encode())
            return base64.b64encode(encrypted).decode('utf-8')
                
        except Exception as e:
            logger.error(f"加密数据失败: {str(e)}")
            raise ValueError(f"加密失败: {str(e)}")

    def decrypt_data(self, encrypted_text, key):
        """使用 Fernet 解密数据"""
        try:
            # 确保密钥是字符串类型
            if not isinstance(key, str):
                key = str(key)
            
            # 使用 SHA256 生成固定长度的密钥
            key_bytes = hashlib.sha256(key.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            try:
                # Base64 解码
                encrypted_bytes = base64.b64decode(encrypted_text)
                
                # 解密数据
                decrypted = f.decrypt(encrypted_bytes)
                return decrypted.decode('utf-8')
                
            except Exception as e:
                logger.error(f"解密失败: {str(e)}")
                raise ValueError(f"解密失败: {str(e)}")
                
        except Exception as e:
            logger.error(f"解密数据失败: {str(e)}")
            raise ValueError(f"解密失败: {str(e)}")

class PaymentPassword(models.Model):
    """支付密码模型"""
    device_id = models.CharField(max_length=100, unique=True, help_text='设备ID')
    encrypted_password = models.CharField(max_length=255, help_text='加密后的支付密码')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    updated_at = models.DateTimeField(auto_now=True, help_text='更新时间')
    
    class Meta:
        db_table = 'payment_password'
        verbose_name = '支付密码'
        verbose_name_plural = '支付密码'
    
    def __str__(self):
        return f"PaymentPassword for {self.device_id}"
    
    def verify_password(self, password):
        """验证密码"""
        try:
            # 使用设备ID作为密钥解密支付密码
            key_bytes = hashlib.sha256(self.device_id.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            # Base64 解码
            encrypted_bytes = base64.b64decode(self.encrypted_password)
            
            # 解密数据
            decrypted = f.decrypt(encrypted_bytes)
            decrypted_password = decrypted.decode('utf-8')
            
            # 直接比较解密后的密码
            return decrypted_password == password
            
        except Exception as e:
            logger.error(f"验证密码失败: {str(e)}")
            return False

    def set_password(self, password):
        """设置密码"""
        try:
            # 使用设备ID作为密钥
            key_bytes = hashlib.sha256(self.device_id.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            # 加密密码
            encrypted = f.encrypt(password.encode())
            
            # Base64 编码存储
            self.encrypted_password = base64.b64encode(encrypted).decode('utf-8')
            self.save()
            
        except Exception as e:
            logger.error(f"设置密码失败: {str(e)}")
            raise ValueError(f"设置密码失败: {str(e)}")

    def encrypt_data(self, data, key):
        """使用 Fernet 加密数据"""
        try:
            # 确保输入数据是字符串类型
            if not isinstance(data, str):
                data = str(data)
            
            # 确保密钥是字符串类型
            if not isinstance(key, str):
                key = str(key)
            
            # 使用 SHA256 生成固定长度的密钥
            key_bytes = hashlib.sha256(key.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            # 加密数据
            encrypted = f.encrypt(data.encode())
            return base64.b64encode(encrypted).decode('utf-8')
                
        except Exception as e:
            logger.error(f"加密数据失败: {str(e)}")
            raise ValueError(f"加密失败: {str(e)}")

    def decrypt_data(self, encrypted_text, key):
        """使用 Fernet 解密数据"""
        try:
            # 确保密钥是字符串类型
            if not isinstance(key, str):
                key = str(key)
            
            # 使用 SHA256 生成固定长度的密钥
            key_bytes = hashlib.sha256(key.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            try:
                # Base64 解码
                encrypted_bytes = base64.b64decode(encrypted_text)
                
                # 解密数据
                decrypted = f.decrypt(encrypted_bytes)
                return decrypted.decode('utf-8')
                
            except Exception as e:
                logger.error(f"解密失败: {str(e)}")
                raise ValueError(f"解密失败: {str(e)}")
                
        except Exception as e:
            logger.error(f"解密数据失败: {str(e)}")
            raise ValueError(f"解密失败: {str(e)}")

class Token(models.Model):
    """代币模型"""
    chain = models.CharField(max_length=10, choices=Chain.CHOICES, help_text='区块链类型')
    address = models.CharField(max_length=100, help_text='代币合约地址')
    name = models.CharField(max_length=100, help_text='代币名称')
    symbol = models.CharField(max_length=20, help_text='代币符号')
    decimals = models.IntegerField(help_text='小数位数')
    logo = models.URLField(max_length=500, blank=True, null=True, help_text='代币logo')
    is_active = models.BooleanField(default=True, help_text='是否激活')
    is_verified = models.BooleanField(default=False, help_text='是否已验证')
    is_visible = models.BooleanField(default=True, help_text='是否可见')
    is_recommended = models.BooleanField(default=False, help_text='是否推荐')
    created_at = models.DateTimeField(default=timezone.now, help_text='创建时间')
    updated_at = models.DateTimeField(auto_now=True, help_text='更新时间')
    
    class Meta:
        db_table = 'token'
        verbose_name = '代币'
        verbose_name_plural = '代币'
        unique_together = [['chain', 'address']]
    
    def __str__(self):
        return f"{self.name} ({self.symbol})"

class Transaction(models.Model):
    """交易记录模型"""
    TX_TYPE_CHOICES = [
        ('TRANSFER', '转账'),
        ('SWAP', '兑换'),
        ('APPROVE', '授权'),
        ('CONTRACT', '合约调用'),
    ]
    
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, help_text='关联钱包')
    tx_hash = models.CharField(max_length=100, unique=True, help_text='交易哈希')
    tx_type = models.CharField(max_length=20, choices=TX_TYPE_CHOICES, help_text='交易类型')
    from_address = models.CharField(max_length=100, help_text='发送地址')
    to_address = models.CharField(max_length=100, help_text='接收地址')
    amount = models.DecimalField(max_digits=65, decimal_places=0, help_text='交易金额(原始值)')
    token = models.ForeignKey(Token, null=True, on_delete=models.SET_NULL, help_text='代币')
    token_info = models.JSONField(null=True, blank=True, help_text='代币信息(SWAP等场景)')
    to_token_address = models.CharField(max_length=100, null=True, blank=True, help_text='目标代币地址(SWAP场景)')
    fee = models.DecimalField(max_digits=65, decimal_places=0, default=0, help_text='手续费(原始值)')
    status = models.BooleanField(default=True, help_text='交易状态')
    block_number = models.BigIntegerField(help_text='区块号')
    block_timestamp = models.DateTimeField(help_text='区块时间')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    
    class Meta:
        db_table = 'transaction'
        verbose_name = '交易记录'
        verbose_name_plural = '交易记录'
        ordering = ['-block_timestamp']
    
    def __str__(self):
        return f"{self.tx_hash} ({self.tx_type})"

class HiddenToken(models.Model):
    """隐藏的代币"""
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, help_text='关联钱包')
    token_address = models.CharField(max_length=100, help_text='代币地址')
    created_at = models.DateTimeField(auto_now_add=True, help_text='创建时间')
    
    class Meta:
        db_table = 'hidden_token'
        verbose_name = '隐藏代币'
        verbose_name_plural = '隐藏代币'
        unique_together = [['wallet', 'token_address']]
    
    def __str__(self):
        return f"{self.wallet.name} - {self.token_address}"

