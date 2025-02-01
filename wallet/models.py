from django.db import models
from django.conf import settings
from decimal import Decimal

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

class Token(models.Model):
    """代币模型"""
    chain = models.CharField(max_length=10, verbose_name='链')
    name = models.CharField(max_length=100, verbose_name='名称')
    symbol = models.CharField(max_length=20, verbose_name='符号')
    address = models.CharField(max_length=100, verbose_name='合约地址')
    decimals = models.IntegerField(default=18, verbose_name='小数位数')
    logo = models.URLField(max_length=500, null=True, blank=True, verbose_name='Logo URL')
    
    # 基本信息
    coin_id = models.CharField(max_length=100, verbose_name='币种ID')
    rank = models.IntegerField(null=True, blank=True, verbose_name='排名')
    is_new = models.BooleanField(default=False, verbose_name='是否新币')
    is_active = models.BooleanField(default=True, verbose_name='是否活跃')
    type = models.CharField(max_length=20, default='token', verbose_name='类型')
    contract_type = models.CharField(max_length=20, null=True, blank=True, verbose_name='合约类型')
    
    # 扩展信息
    description = models.TextField(null=True, blank=True, verbose_name='描述')
    tags = models.JSONField(default=list, blank=True, verbose_name='标签')
    team = models.JSONField(default=list, blank=True, verbose_name='团队')
    open_source = models.BooleanField(default=True, verbose_name='是否开源')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='项目开始时间')
    development_status = models.CharField(max_length=50, null=True, blank=True, verbose_name='开发状态')
    hardware_wallet = models.BooleanField(default=False, verbose_name='是否支持硬件钱包')
    proof_type = models.CharField(max_length=50, null=True, blank=True, verbose_name='共识机制')
    org_structure = models.CharField(max_length=50, null=True, blank=True, verbose_name='组织结构')
    hash_algorithm = models.CharField(max_length=50, null=True, blank=True, verbose_name='哈希算法')
    
    # 链接
    website = models.URLField(max_length=500, null=True, blank=True, verbose_name='官网')
    explorer = models.JSONField(default=list, blank=True, verbose_name='区块浏览器')
    reddit = models.JSONField(default=list, blank=True, verbose_name='Reddit链接')
    source_code = models.JSONField(default=list, blank=True, verbose_name='源代码')
    technical_doc = models.URLField(max_length=500, null=True, blank=True, verbose_name='技术文档')
    twitter = models.URLField(max_length=500, null=True, blank=True, verbose_name='Twitter')
    telegram = models.URLField(max_length=500, null=True, blank=True, verbose_name='Telegram')
    
    # 扩展链接数据
    links_extended = models.JSONField(default=list, blank=True, verbose_name='扩展链接')
    
    # 白皮书
    whitepaper_link = models.URLField(max_length=500, null=True, blank=True, verbose_name='白皮书链接')
    whitepaper_thumbnail = models.URLField(max_length=500, null=True, blank=True, verbose_name='白皮书缩略图')
    
    # 时间信息
    first_data_at = models.DateTimeField(null=True, blank=True, verbose_name='首次数据时间')
    last_data_at = models.DateTimeField(null=True, blank=True, verbose_name='最后数据时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '代币'
        verbose_name_plural = '代币'
        unique_together = ('coin_id', 'chain', 'address')

    def __str__(self):
        return f"{self.name} ({self.symbol}) on {self.chain}"

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
