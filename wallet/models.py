from django.db import models
from django.conf import settings
from decimal import Decimal
from cryptography.fernet import Fernet
import base64
import logging
import hashlib
import base58
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger(__name__)

def decrypt_string(encrypted_text: str, key: str) -> str:
    """简单的字符串解密函数"""
    try:
        key_hash = hashlib.sha256(key.encode()).digest()
        encrypted_bytes = base64.b64decode(encrypted_text)
        decrypted = bytes(a ^ b for a, b in zip(encrypted_bytes, key_hash * (len(encrypted_bytes) // len(key_hash) + 1)))
        return decrypted.decode()
    except Exception as e:
        logger.error(f"解密字符串失败: {str(e)}")
        raise ValueError("解密失败")

class TokenIndex(models.Model):
    """代币索引模型"""
    coin_id = models.CharField(verbose_name='代币ID', max_length=100, unique=True)
    name = models.CharField(verbose_name='名称', max_length=100)
    symbol = models.CharField(verbose_name='符号', max_length=20)
    rank = models.IntegerField(verbose_name='排名', default=0)
    is_new = models.BooleanField(verbose_name='是否新增', default=False)
    is_active = models.BooleanField(verbose_name='是否激活', default=True)
    type = models.CharField(verbose_name='类型', max_length=20, default='token')
    is_token_synced = models.BooleanField(verbose_name='代币已同步', default=False, help_text='代币详细信息是否已同步')
    updated_at = models.DateTimeField(verbose_name='更新时间', auto_now=True)
    
    class Meta:
        verbose_name = '代币索引'
        verbose_name_plural = '代币索引'
        ordering = ['rank']
        
    def __str__(self):
        return f"{self.name} ({self.symbol})"

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
        unique_together = ['device_id', 'chain', 'address']

    def __str__(self):
        return f"{self.name} ({self.address})"

    def decrypt_private_key(self) -> bytes:
        """解密私钥，返回字节格式"""
        if not self.encrypted_private_key:
            logger.error("钱包没有私钥")
            raise ValueError("钱包没有私钥")
        
        if self.is_watch_only:
            logger.error("观察者钱包没有私钥")
            raise ValueError("观察者钱包没有私钥")
            
        try:
            # 获取加密的私钥
            encrypted_bytes = self.encrypted_private_key
            logger.debug(f"加密私钥类型: {type(encrypted_bytes)}")
            logger.debug(f"加密私钥原始内容: {encrypted_bytes[:10]}...")  # 只显示前10个字符
            
            # 获取支付密码
            if not hasattr(self, 'payment_password'):
                raise ValueError("未提供支付密码")
            
            try:
                # 使用与支付密码相同的解密方式
                key_hash = hashlib.sha256(self.payment_password.encode()).digest()
                encrypted_data = base64.b64decode(encrypted_bytes)
                decrypted = bytes(a ^ b for a, b in zip(encrypted_data, key_hash * (len(encrypted_data) // len(key_hash) + 1)))
                logger.debug(f"解密后的数据长度: {len(decrypted)}")
                
                # 对于Solana钱包，验证解密后的私钥
                if self.chain == 'SOL':
                    try:
                        # 如果解密后的数据是64字节，取前32字节作为私钥
                        if len(decrypted) == 64:
                            logger.debug("检测到64字节数据，使用前32字节作为私钥")
                            private_key_bytes = decrypted[:32]
                            # 验证前32字节是否为有效私钥
                            try:
                                private_key_obj = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
                                public_key_bytes = private_key_obj.public_key().public_bytes(
                                    encoding=serialization.Encoding.Raw,
                                    format=serialization.PublicFormat.Raw
                                )
                                generated_address = base58.b58encode(public_key_bytes).decode()
                                
                                if generated_address == self.address:
                                    logger.info("找到匹配的私钥（使用前32字节）")
                                    return private_key_bytes
                                else:
                                    logger.debug("前32字节不匹配，尝试后32字节")
                                    # 尝试后32字节
                                    private_key_bytes = decrypted[32:]
                            except Exception as e:
                                logger.debug(f"使用前32字节失败: {str(e)}，尝试后32字节")
                                private_key_bytes = decrypted[32:]
                        else:
                            private_key_bytes = decrypted

                        # 使用私钥创建密钥对并验证
                        private_key_obj = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
                        public_key_bytes = private_key_obj.public_key().public_bytes(
                            encoding=serialization.Encoding.Raw,
                            format=serialization.PublicFormat.Raw
                        )
                        generated_address = base58.b58encode(public_key_bytes).decode()
                        
                        if generated_address == self.address:
                            logger.info("找到匹配的私钥")
                            return private_key_bytes
                        else:
                            logger.error(f"私钥不匹配: 期望={self.address}, 实际={generated_address}")
                            raise ValueError("私钥与钱包地址不匹配")
                            
                    except Exception as e:
                        logger.error(f"处理Solana私钥失败: {str(e)}")
                        raise ValueError(f"无效的Solana私钥格式: {str(e)}")
                
                return decrypted
                
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                raise ValueError(f"解密私钥失败: {str(e)}")
                
        except Exception as e:
            logger.error(f"解密私钥失败，详细错误: {str(e)}")
            logger.error(f"钱包ID: {self.id}, 地址: {self.address}")
            raise ValueError(f"解密私钥失败: {str(e)}")

class Token(models.Model):
    """代币模型"""
    chain = models.CharField(max_length=10, verbose_name='链')
    address = models.CharField(max_length=255, verbose_name='合约地址')
    name = models.CharField(max_length=255, verbose_name='名称')
    symbol = models.CharField(max_length=50, verbose_name='符号')
    decimals = models.IntegerField(default=18, verbose_name='小数位数')
    logo = models.URLField(max_length=500, null=True, blank=True, verbose_name='Logo')
    type = models.CharField(max_length=20, default='token', verbose_name='类型')
    contract_type = models.CharField(max_length=20, default='ERC20', verbose_name='合约类型')
    description = models.TextField(null=True, blank=True, verbose_name='描述')
    website = models.URLField(max_length=500, null=True, blank=True, verbose_name='网站')
    twitter = models.URLField(max_length=500, null=True, blank=True, verbose_name='Twitter')
    telegram = models.URLField(max_length=500, null=True, blank=True, verbose_name='Telegram')
    reddit = models.JSONField(default=list, null=True, blank=True, verbose_name='Reddit')
    discord = models.URLField(max_length=500, null=True, blank=True, verbose_name='Discord')
    github = models.URLField(max_length=500, null=True, blank=True, verbose_name='GitHub')
    medium = models.URLField(max_length=500, null=True, blank=True, verbose_name='Medium')
    total_supply = models.CharField(max_length=255, null=True, blank=True, verbose_name='总供应量')
    total_supply_formatted = models.CharField(max_length=255, null=True, blank=True, verbose_name='格式化总供应量')
    security_score = models.IntegerField(null=True, blank=True, verbose_name='安全评分')
    verified = models.BooleanField(default=False, verbose_name='是否验证')
    created_at = models.DateTimeField(null=True, blank=True, verbose_name='创建时间')
    possible_spam = models.BooleanField(default=False, verbose_name='是否可能是垃圾代币')
    is_native = models.BooleanField(default=False, verbose_name='是否原生代币')
    is_visible = models.BooleanField(default=True, verbose_name='是否显示')
    
    # 缓存字段
    last_balance = models.CharField(max_length=255, null=True, blank=True, verbose_name='最后余额')
    last_price = models.CharField(max_length=255, null=True, blank=True, verbose_name='最后价格')
    last_price_change = models.CharField(max_length=255, null=True, blank=True, verbose_name='最后24h价格变化')
    last_value = models.CharField(max_length=255, null=True, blank=True, verbose_name='最后价值')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '代币'
        verbose_name_plural = '代币'
        unique_together = ('chain', 'address')
        indexes = [
            models.Index(fields=['chain', 'address']),
        ]

    def __str__(self):
        return f"{self.chain} - {self.symbol} ({self.address})"

class NFTCollection(models.Model):
    """NFT合集模型"""
    chain = models.CharField(max_length=20, verbose_name='区块链')
    contract_address = models.CharField(max_length=100, verbose_name='合约地址', null=True, blank=True)
    name = models.CharField(max_length=100, verbose_name='合集名称')
    symbol = models.CharField(max_length=20, verbose_name='合集符号')
    description = models.TextField(verbose_name='描述', null=True, blank=True)
    logo = models.URLField(verbose_name='Logo URL', null=True, blank=True)
    banner = models.URLField(verbose_name='Banner URL', null=True, blank=True)
    website = models.URLField(verbose_name='官网', null=True, blank=True)
    discord = models.URLField(verbose_name='Discord', null=True, blank=True)
    twitter = models.URLField(verbose_name='Twitter', null=True, blank=True)
    is_verified = models.BooleanField(default=False, verbose_name='是否已验证')
    is_recommended = models.BooleanField(default=False, verbose_name='是否推荐')
    floor_price = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='地板价', default=Decimal('0'))
    volume_24h = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='24h交易量', default=Decimal('0'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = 'NFT合集'
        verbose_name_plural = 'NFT合集'
        ordering = ['-is_recommended', '-floor_price']
        unique_together = ['chain', 'contract_address']

    def __str__(self):
        return f"{self.name} ({self.chain})"

class Transaction(models.Model):
    """交易记录模型"""
    TYPE_CHOICES = [
        ('TRANSFER', '转账'),
        ('APPROVE', '授权'),
        ('SWAP', '兑换'),
        ('MINT', '铸造'),
        ('BURN', '销毁'),
        ('OTHER', '其他'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', '待处理'),
        ('SUCCESS', '成功'),
        ('FAILED', '失败'),
    ]
    
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, verbose_name='钱包')
    chain = models.CharField(max_length=20, verbose_name='区块链')
    tx_hash = models.CharField(max_length=100, verbose_name='交易哈希')
    tx_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='交易类型')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name='状态')
    from_address = models.CharField(max_length=100, verbose_name='发送地址')
    to_address = models.CharField(max_length=100, verbose_name='接收地址')
    amount = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='数量')
    token = models.ForeignKey(Token, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='代币')
    nft_collection = models.ForeignKey(NFTCollection, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='NFT合集')
    nft_token_id = models.CharField(max_length=100, null=True, blank=True, verbose_name='NFT Token ID')
    gas_price = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Gas价格')
    gas_used = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Gas使用量')
    block_number = models.IntegerField(verbose_name='区块高度')
    block_timestamp = models.DateTimeField(verbose_name='区块时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '交易记录'
        verbose_name_plural = '交易记录'
        ordering = ['-block_timestamp']
        unique_together = ['chain', 'tx_hash']

    def __str__(self):
        return f"{self.tx_hash} ({self.tx_type})"

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

    def verify_password(self, password: str) -> bool:
        """验证支付密码"""
        try:
            # 解密存储的密码
            decrypted_password = decrypt_string(self.encrypted_password, self.device_id)
            # 比较密码
            return password == decrypted_password
        except Exception as e:
            logger.error(f"验证支付密码失败: {str(e)}")
            return False
