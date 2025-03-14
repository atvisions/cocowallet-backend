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
from solana.keypair import Keypair
from eth_account import Account

logger = logging.getLogger(__name__)

def decrypt_string(encrypted_text: str, key: str) -> str:
    """使用Fernet进行字符串解密"""
    try:
        # 使用key生成Fernet密钥
        key_bytes = hashlib.sha256(key.encode()).digest()
        f = Fernet(base64.urlsafe_b64encode(key_bytes))
        # 解密
        decrypted = f.decrypt(encrypted_text.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(f"解密字符串失败: {str(e)}")
        raise ValueError("解密失败")

def encrypt_string(text: str, key: str) -> str:
    """使用Fernet进行字符串加密"""
    try:
        # 使用key生成Fernet密钥
        key_bytes = hashlib.sha256(key.encode()).digest()
        f = Fernet(base64.urlsafe_b64encode(key_bytes))
        # 加密
        encrypted = f.encrypt(text.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"加密字符串失败: {str(e)}")
        raise ValueError("加密失败")

class Chain(models.TextChoices):
    """支持的链类型"""
    ETH = 'ETH', 'Ethereum'
    BSC = 'BNB', 'BNB Chain'
    MATIC = 'MATIC', 'Polygon'
    AVAX = 'AVAX', 'Avalanche'
    BASE = 'BASE', 'Base'
    ARBITRUM = 'ARBITRUM', 'Arbitrum'
    OPTIMISM = 'OPTIMISM', 'Optimism'
    SOL = 'SOL', 'Solana'
    BTC = 'BTC', 'Bitcoin'

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
    
    _payment_password = None  # 添加支付密码属性
    
    @property
    def payment_password(self):
        return self._payment_password
        
    @payment_password.setter
    def payment_password(self, value):
        self._payment_password = value

    def check_device(self, device_id: str) -> bool:
        """检查设备ID是否匹配
        
        Args:
            device_id: 设备ID
            
        Returns:
            bool: 是否匹配
        """
        return self.device_id == device_id
        
    def check_payment_password(self, payment_password: str) -> bool:
        """检查支付密码是否正确
        
        Args:
            payment_password: 支付密码
            
        Returns:
            bool: 是否正确
        """
        try:
            # 获取支付密码记录
            payment_pwd = PaymentPassword.objects.filter(device_id=self.device_id).first()
            if not payment_pwd:
                return False
            
            # 验证密码
            return payment_pwd.verify_password(payment_password)
        except Exception as e:
            logger.error(f"验证支付密码失败: {str(e)}")
            return False

    class Meta:
        verbose_name = '钱包'
        verbose_name_plural = '钱包'
        ordering = ['-created_at']
        unique_together = ['device_id', 'chain', 'address']

    def __str__(self):
        return f"{self.name} ({self.address})"

    def decrypt_private_key(self) -> str:
        """解密私钥"""
        if not self.encrypted_private_key:
            logger.error("钱包没有私钥")
            raise ValueError("钱包没有私钥")
        
        if self.is_watch_only:
            logger.error("观察者钱包没有私钥")
            raise ValueError("观察者钱包没有私钥")
            
        try:
            # 获取支付密码
            if not self.payment_password:
                raise ValueError("未提供支付密码")
            
            # 使用 Fernet 解密私钥
            from wallet.views.wallet import WalletViewSet
            wallet_viewset = WalletViewSet()
            decrypted = wallet_viewset.decrypt_data(self.encrypted_private_key, self.payment_password)
            
            # 确保解密后的数据是字符串类型
            if isinstance(decrypted, bytes):
                try:
                    decrypted = decrypted.decode('utf-8')
                except UnicodeDecodeError as e:
                    logger.error(f"UTF-8解码失败: {str(e)}")
                    raise ValueError("私钥解码失败")
            elif not isinstance(decrypted, str):
                logger.error(f"解密后的私钥类型无效: {type(decrypted)}")
                raise ValueError("私钥类型无效")
            
            # 根据链类型处理私钥格式
            if self.chain == 'SOL':
                try:
                    # 将Base58格式的数据解码回字节
                    decrypted_bytes = base58.b58decode(decrypted)
                    
                    # 如果是88字节的扩展格式，提取前64字节
                    if len(decrypted_bytes) == 88:
                        keypair_bytes = decrypted_bytes[:64]
                    # 如果已经是64字节的格式，直接使用
                    elif len(decrypted_bytes) == 64:
                        keypair_bytes = decrypted_bytes
                    # 如果是32字节的私钥，创建完整的密钥对
                    elif len(decrypted_bytes) == 32:
                        keypair = Keypair.from_seed(decrypted_bytes)
                        keypair_bytes = keypair.seed + bytes(keypair.public_key)
                    else:
                        raise ValueError(f"无效的私钥长度: {len(decrypted_bytes)}")
                    
                    # 验证生成的地址
                    keypair = Keypair.from_seed(keypair_bytes[:32])
                    generated_address = str(keypair.public_key)
                    logger.debug(f"生成的地址: {generated_address}")
                    
                    if generated_address != self.address:
                        raise ValueError(f"私钥不匹配: 期望={self.address}, 实际={generated_address}")
                    
                    # 返回64字节密钥对的Base58编码
                    return base58.b58encode(keypair_bytes).decode()
                    
                except Exception as e:
                    logger.error(f"验证SOL私钥失败: {str(e)}")
                    raise ValueError(f"SOL私钥验证失败: {str(e)}")
                    
            elif self.chain in ["ETH", "BASE", "BNB", "MATIC", "AVAX", "ARBITRUM", "OPTIMISM"]:
                try:
                    # 如果解密后的数据是字节类型
                    if isinstance(decrypted, bytes):
                        private_key_bytes = decrypted
                    # 如果是字符串类型，尝试转换为字节
                    elif isinstance(decrypted, str):
                        try:
                            # 如果是十六进制格式的字符串
                            if decrypted.startswith('0x'):
                                private_key_bytes = bytes.fromhex(decrypted[2:])
                            else:
                                private_key_bytes = bytes.fromhex(decrypted)
                        except ValueError:
                            # 如果不是十六进制格式，可能是字节字符串的字面值表示
                            private_key_bytes = eval(decrypted)
                    else:
                        raise ValueError(f"不支持的私钥格式: {type(decrypted)}")
                        
                    # 验证私钥长度
                    if len(private_key_bytes) != 32:
                        raise ValueError(f"无效的私钥长度: {len(private_key_bytes)}")
                        
                    # 验证私钥是否匹配地址
                    account = Account.from_key(private_key_bytes)
                    if account.address.lower() != self.address.lower():  # 使用小写比较
                        raise ValueError(f"私钥地址不匹配: 期望 {self.address}, 实际 {account.address}")
                    
                    # 返回十六进制格式的私钥
                    return '0x' + private_key_bytes.hex()
                    
                except Exception as e:
                    logger.error(f"验证EVM私钥失败: {str(e)}")
                    raise ValueError(f"EVM私钥验证失败: {str(e)}")
            else:
                raise ValueError(f"不支持的链类型: {self.chain}")
                
        except Exception as e:
            logger.error(f"解密私钥失败: {str(e)}")
            raise ValueError(f"解密私钥失败: {str(e)}")

    def _verify_address_match(self, generated_address: str) -> bool:
        """验证生成的地址是否与钱包地址匹配"""
        try:
            # 如果地址完全匹配
            if self.address == generated_address:
                return True
                
            # 如果是Solana钱包
            if self.chain == 'SOL':
                # 如果钱包地址是压缩公钥格式（以02或03开头的十六进制）
                if (self.address.startswith('02') or self.address.startswith('03')):
                    try:
                        # 从压缩公钥中提取实际的公钥数据（去掉前缀）
                        hex_str = self.address[2:]  # 移除02/03前缀
                        # 将十六进制转换为字节
                        hex_bytes = bytes.fromhex(hex_str)
                        # 转换为Base58格式
                        base58_address = base58.b58encode(hex_bytes).decode()
                        logger.debug(f"从压缩公钥转换后的Base58地址: {base58_address}")
                        return base58_address == generated_address
                    except Exception as e:
                        logger.error(f"压缩公钥转换失败: {str(e)}")
                        return False
                        
                # 如果钱包地址是Base58格式
                try:
                    wallet_bytes = base58.b58decode(self.address)
                    generated_bytes = base58.b58decode(generated_address)
                    return wallet_bytes == generated_bytes
                except Exception as e:
                    logger.error(f"Base58解码失败: {str(e)}")
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"地址验证失败: {str(e)}")
            return False

class Token(models.Model):
    """代币模型"""
    chain = models.CharField(max_length=10, verbose_name='链')
    address = models.CharField(max_length=255, verbose_name='合约地址')
    name = models.CharField(max_length=255, verbose_name='名称')
    symbol = models.CharField(max_length=50, verbose_name='符号')
    decimals = models.IntegerField(default=18, verbose_name='小数位数')
    logo = models.URLField(max_length=500, null=True, blank=True, verbose_name='Logo')
    logo_hash = models.CharField(max_length=255, null=True, blank=True, verbose_name='Logo哈希')
    thumbnail = models.URLField(max_length=500, null=True, blank=True, verbose_name='缩略图')
    type = models.CharField(max_length=20, default='token', verbose_name='类型')
    contract_type = models.CharField(max_length=20, default='ERC20', verbose_name='合约类型')
    description = models.TextField(null=True, blank=True, verbose_name='描述')
    website = models.URLField(max_length=500, null=True, blank=True, verbose_name='网站')
    email = models.EmailField(max_length=255, null=True, blank=True, verbose_name='邮箱')
    twitter = models.URLField(max_length=500, null=True, blank=True, verbose_name='Twitter')
    telegram = models.URLField(max_length=500, null=True, blank=True, verbose_name='Telegram')
    reddit = models.URLField(max_length=500, null=True, blank=True, verbose_name='Reddit')
    discord = models.URLField(max_length=500, null=True, blank=True, verbose_name='Discord')
    instagram = models.URLField(max_length=500, null=True, blank=True, verbose_name='Instagram')
    github = models.URLField(max_length=500, null=True, blank=True, verbose_name='GitHub')
    medium = models.URLField(max_length=500, null=True, blank=True, verbose_name='Medium')
    moralis = models.URLField(max_length=500, null=True, blank=True, verbose_name='Moralis')
    coingecko_id = models.CharField(max_length=100, null=True, blank=True, verbose_name='CoinGecko ID')
    total_supply = models.CharField(max_length=255, null=True, blank=True, verbose_name='总供应量')
    total_supply_formatted = models.CharField(max_length=255, null=True, blank=True, verbose_name='格式化总供应量')
    circulating_supply = models.CharField(max_length=255, null=True, blank=True, verbose_name='流通供应量')
    market_cap = models.CharField(max_length=255, null=True, blank=True, verbose_name='市值')
    fully_diluted_valuation = models.CharField(max_length=255, null=True, blank=True, verbose_name='完全稀释估值')
    categories = models.JSONField(default=list, null=True, blank=True, verbose_name='分类')
    security_score = models.IntegerField(null=True, blank=True, verbose_name='安全评分')
    verified = models.BooleanField(default=False, verbose_name='是否验证')
    possible_spam = models.BooleanField(default=False, verbose_name='是否可能是垃圾代币')
    block_number = models.CharField(max_length=255, null=True, blank=True, verbose_name='区块高度')
    validated = models.IntegerField(default=0, verbose_name='验证状态')
    created_at = models.DateTimeField(null=True, blank=True, verbose_name='创建时间')
    is_native = models.BooleanField(default=False, verbose_name='是否原生代币')
    is_visible = models.BooleanField(default=True, verbose_name='是否显示')
    is_recommended = models.BooleanField(default=False, verbose_name='是否推荐')
    
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
        ordering = ['-is_recommended', '-verified', '-created_at']

    def __str__(self):
        return f"{self.chain} - {self.symbol} ({self.address})"

class NFTCollection(models.Model):
    """NFT合集模型"""
    chain = models.CharField(max_length=20, verbose_name='区块链')
    contract_address = models.CharField(max_length=100, verbose_name='合约地址', null=True, blank=True)
    name = models.CharField(max_length=100, verbose_name='合集名称')
    symbol = models.CharField(max_length=100, verbose_name='合集符号')
    contract_type = models.CharField(max_length=20, default='ERC721', verbose_name='合约类型')
    description = models.TextField(verbose_name='描述', null=True, blank=True)
    logo = models.URLField(verbose_name='Logo URL', null=True, blank=True)
    banner = models.URLField(verbose_name='Banner URL', null=True, blank=True)
    is_verified = models.BooleanField(default=False, verbose_name='是否已验证')
    is_spam = models.BooleanField(default=False, verbose_name='是否垃圾合集')
    is_visible = models.BooleanField(default=True, verbose_name='是否显示')
    floor_price = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='地板价', default=Decimal('0'))
    floor_price_usd = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='地板价(USD)', default=Decimal('0'))
    floor_price_currency = models.CharField(max_length=10, default='eth', verbose_name='地板价币种')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = 'NFT合集'
        verbose_name_plural = 'NFT合集'
        ordering = ['-floor_price_usd', '-created_at']
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
    token_info = models.JSONField(null=True, blank=True, verbose_name='代币信息')
    gas_price = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Gas价格')
    gas_used = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Gas使用量')
    block_number = models.IntegerField(verbose_name='区块高度')
    block_timestamp = models.DateTimeField(verbose_name='区块时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '交易记录'
        verbose_name_plural = '交易记录'
        ordering = ['-block_timestamp']
        unique_together = ['chain', 'tx_hash', 'wallet']

    def __str__(self):
        return f"{self.tx_hash} ({self.tx_type})"

class MnemonicBackup(models.Model):
    """助记词备份模型"""
    device_id = models.CharField(max_length=100, verbose_name='设备ID')
    chain = models.CharField(max_length=20, verbose_name='区块链')
    encrypted_mnemonic = models.TextField(verbose_name='加密助记词')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    
    _payment_password = None
    
    @property
    def payment_password(self):
        return self._payment_password
        
    @payment_password.setter
    def payment_password(self, value):
        self._payment_password = value
    
    def decrypt_mnemonic(self) -> str:
        """解密助记词，根据不同链类型处理"""
        if not self.encrypted_mnemonic:
            logger.error("没有加密的助记词")
            raise ValueError("没有加密的助记词")
            
        try:
            # 获取支付密码
            if not self.payment_password:
                raise ValueError("未提供支付密码")
            
            # 使用 Fernet 解密助记词
            from wallet.views.wallet import WalletViewSet
            wallet_viewset = WalletViewSet()
            decrypted = wallet_viewset.decrypt_data(self.encrypted_mnemonic, self.payment_password)
            
            # 确保解密后的数据是字符串类型
            if isinstance(decrypted, bytes):
                try:
                    decrypted = decrypted.decode('utf-8')
                except UnicodeDecodeError as e:
                    logger.error(f"UTF-8解码失败: {str(e)}")
                    raise ValueError("助记词解码失败")
            elif not isinstance(decrypted, str):
                logger.error(f"解密后的助记词类型无效: {type(decrypted)}")
                raise ValueError("助记词类型无效")
            
            # 根据链类型处理助记词格式
            if self.chain == 'SOL':
                try:
                    # 对于 Solana，助记词应该是空格分隔的单词
                    words = decrypted.strip().split()
                    if len(words) not in [12, 24]:
                        raise ValueError(f"无效的助记词长度: {len(words)}个单词")
                    return ' '.join(words)
                except Exception as e:
                    logger.error(f"验证SOL助记词失败: {str(e)}")
                    raise ValueError(f"SOL助记词验证失败: {str(e)}")
            elif self.chain in ["ETH", "BASE", "BNB", "MATIC", "AVAX", "ARBITRUM", "OPTIMISM"]:
                try:
                    # 对于 EVM 链，助记词也是空格分隔的单词
                    words = decrypted.strip().split()
                    if len(words) not in [12, 15, 18, 21, 24]:
                        raise ValueError(f"无效的助记词长度: {len(words)}个单词")
                    return ' '.join(words)
                except Exception as e:
                    logger.error(f"验证EVM助记词失败: {str(e)}")
                    raise ValueError(f"EVM助记词验证失败: {str(e)}")
            else:
                raise ValueError(f"不支持的链类型: {self.chain}")
                
        except Exception as e:
            logger.error(f"解密助记词失败: {str(e)}")
            raise ValueError(f"解密助记词失败: {str(e)}")

    class Meta:
        verbose_name = '助记词备份'
        verbose_name_plural = '助记词备份'
        ordering = ['-created_at']
        unique_together = ['device_id', 'chain']

    def __str__(self):
        return f"Backup for device {self.device_id} on {self.chain}"

class PaymentPassword(models.Model):
    """支付密码模型"""
    device_id = models.CharField(max_length=100, unique=True, verbose_name='设备ID')
    encrypted_password = models.CharField(max_length=255, verbose_name='加密的支付密码')
    is_biometric_enabled = models.BooleanField(default=False, verbose_name='是否启用生物密码')
    biometric_verified_at = models.DateTimeField(null=True, blank=True, verbose_name='最后生物密码验证时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '支付密码'
        verbose_name_plural = '支付密码'

    def __str__(self):
        return f"Payment password for device {self.device_id}"

    @staticmethod
    async def verify_device_password(device_id: str, password: str) -> bool:
        """验证设备的支付密码
        
        Args:
            device_id: 设备ID
            password: 支付密码
            
        Returns:
            bool: 密码是否正确
        """
        try:
            from asgiref.sync import sync_to_async
            
            # 获取支付密码记录
            payment_pwd = await sync_to_async(PaymentPassword.objects.filter(
                device_id=device_id
            ).first)()
            
            if not payment_pwd:
                logger.error(f"找不到设备的支付密码记录: {device_id}")
                return False
                
            # 验证密码
            return payment_pwd.verify_password(password)
            
        except Exception as e:
            logger.error(f"验证支付密码失败: {str(e)}")
            return False

    def verify_password(self, password: str) -> bool:
        """验证支付密码"""
        try:
            # 解密存储的密码
            from wallet.views.wallet import WalletViewSet
            wallet_viewset = WalletViewSet()
            
            # 记录输入密码信息
            logger.debug(f"验证支付密码: device_id={self.device_id}, 输入密码类型={type(password)}")
            
            # 确保密码是字符串类型
            if not isinstance(password, str):
                logger.error(f"无效的密码类型: {type(password)}")
                return False
                
            try:
                # 解密存储的密码
                decrypted_password = wallet_viewset.decrypt_data(self.encrypted_password, self.device_id)
                logger.debug(f"解密后的密码类型: {type(decrypted_password)}")
                
                # 确保解密后的密码是字符串类型
                if isinstance(decrypted_password, bytes):
                    try:
                        decrypted_password = decrypted_password.decode('utf-8')
                    except UnicodeDecodeError as e:
                        logger.error(f"UTF-8解码失败: {str(e)}")
                        return False
                elif not isinstance(decrypted_password, str):
                    logger.error(f"解密后的密码类型无效: {type(decrypted_password)}")
                    return False
                    
                # 确保两个密码都是字符串类型并且去除可能的空白字符
                password = str(password).strip()
                decrypted_password = str(decrypted_password).strip()
                
                # 记录密码比较前的状态
                logger.debug(f"输入密码长度: {len(password)}, 解密密码长度: {len(decrypted_password)}")
                logger.debug(f"输入密码: {password}, 解密密码: {decrypted_password}")
                
                # 密码比较
                is_match = password == decrypted_password
                logger.debug(f"密码验证结果: {is_match}")
                
                return is_match
                
            except Exception as decrypt_error:
                logger.error(f"密码解密失败: {str(decrypt_error)}")
                return False
                
        except Exception as e:
            logger.error(f"验证支付密码失败: {str(e)}")
            return False

    def enable_biometric(self) -> bool:
        """启用生物密码
        
        Returns:
            bool: 是否成功启用
        """
        try:
            self.is_biometric_enabled = True
            self.save()
            return True
        except Exception as e:
            logger.error(f"启用生物密码失败: {str(e)}")
            return False

    def disable_biometric(self) -> bool:
        """禁用生物密码
        
        Returns:
            bool: 是否成功禁用
        """
        try:
            self.is_biometric_enabled = False
            self.biometric_verified_at = None
            self.save()
            return True
        except Exception as e:
            logger.error(f"禁用生物密码失败: {str(e)}")
            return False

    def update_biometric_verified_time(self) -> bool:
        """更新生物密码验证时间
        
        Returns:
            bool: 是否成功更新
        """
        try:
            from django.utils import timezone
            self.biometric_verified_at = timezone.now()
            self.save()
            return True
        except Exception as e:
            logger.error(f"更新生物密码验证时间失败: {str(e)}")
            return False

class TokenIndex(models.Model):
    """代币索引模型,只存储基本信息"""
    chain = models.CharField(max_length=10, verbose_name='链')
    address = models.CharField(max_length=255, verbose_name='合约地址')
    name = models.CharField(max_length=255, verbose_name='名称')
    symbol = models.CharField(max_length=50, verbose_name='符号')
    decimals = models.IntegerField(default=18, verbose_name='小数位数')
    is_native = models.BooleanField(default=False, verbose_name='是否原生代币')
    is_verified = models.BooleanField(default=False, verbose_name='是否已验证')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '代币索引'
        verbose_name_plural = '代币索引'
        unique_together = ('chain', 'address')
        indexes = [
            models.Index(fields=['chain', 'address']),
            models.Index(fields=['symbol']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.chain} - {self.symbol} ({self.address})"

class TokenIndexSource(models.Model):
    """代币数据源记录"""
    name = models.CharField(max_length=50, verbose_name='数据源名称')
    priority = models.IntegerField(verbose_name='优先级')
    last_sync = models.DateTimeField(auto_now=True, verbose_name='最后同步时间')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    
    class Meta:
        verbose_name = '代币数据源'
        verbose_name_plural = '代币数据源'
        ordering = ['priority']
        
    def __str__(self):
        return f"{self.name} (优先级: {self.priority})"

class TokenIndexMetrics(models.Model):
    """代币指标数据"""
    token = models.OneToOneField(TokenIndex, on_delete=models.CASCADE, related_name='metrics', verbose_name='代币')
    daily_volume = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='24h交易量(USD)')
    holder_count = models.IntegerField(default=0, verbose_name='持有人数')
    liquidity = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='流动性(USD)')
    market_cap = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='市值(USD)')
    price = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='价格(USD)')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '代币指标'
        verbose_name_plural = '代币指标'
        
    def __str__(self):
        return f"{self.token.symbol} 指标"

class TokenIndexGrade(models.Model):
    """代币等级评估"""
    GRADE_CHOICES = [
        ('A', 'A级 - 核心代币'),
        ('B', 'B级 - 常规代币'),
        ('C', 'C级 - 观察代币'),
    ]
    
    token = models.OneToOneField(TokenIndex, on_delete=models.CASCADE, related_name='grade', verbose_name='代币')
    grade = models.CharField(max_length=1, choices=GRADE_CHOICES, verbose_name='等级')
    score = models.IntegerField(default=0, verbose_name='综合评分')
    last_evaluated = models.DateTimeField(auto_now=True, verbose_name='最后评估时间')
    evaluation_reason = models.TextField(null=True, blank=True, verbose_name='评估原因')
    
    class Meta:
        verbose_name = '代币等级'
        verbose_name_plural = '代币等级'
        
    def __str__(self):
        return f"{self.token.symbol} ({self.grade}级)"

class TokenIndexReport(models.Model):
    """索引库状态报告"""
    total_tokens = models.IntegerField(verbose_name='代币总数')
    grade_a_count = models.IntegerField(verbose_name='A级代币数')
    grade_b_count = models.IntegerField(verbose_name='B级代币数')
    grade_c_count = models.IntegerField(verbose_name='C级代币数')
    new_tokens = models.IntegerField(verbose_name='新增代币数')
    removed_tokens = models.IntegerField(verbose_name='移除代币数')
    report_date = models.DateTimeField(auto_now_add=True, verbose_name='报告时间')
    details = models.JSONField(default=dict, verbose_name='详细信息')
    
    class Meta:
        verbose_name = '索引库报告'
        verbose_name_plural = '索引库报告'
        ordering = ['-report_date']
        
    def __str__(self):
        return f"代币索引报告 ({self.report_date.strftime('%Y-%m-%d %H:%M')})"