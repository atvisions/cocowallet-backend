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
    """Decrypt string using Fernet"""
    try:
        # Generate Fernet key using the provided key
        key_bytes = hashlib.sha256(key.encode()).digest()
        f = Fernet(base64.urlsafe_b64encode(key_bytes))
        # Decrypt
        decrypted = f.decrypt(encrypted_text.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Failed to decrypt string: {str(e)}")
        raise ValueError("Decryption failed")

def encrypt_string(text: str, key: str) -> str:
    """Encrypt string using Fernet"""
    try:
        # Generate Fernet key using the provided key
        key_bytes = hashlib.sha256(key.encode()).digest()
        f = Fernet(base64.urlsafe_b64encode(key_bytes))
        # Encrypt
        encrypted = f.encrypt(text.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Failed to encrypt string: {str(e)}")
        raise ValueError("Encryption failed")

class Chain(models.TextChoices):
    """Supported chain types"""
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
    """Wallet model"""
    CHAIN_CHOICES = [(key, value['name']) for key, value in settings.SUPPORTED_CHAINS.items()]
    
    device_id = models.CharField(max_length=100, verbose_name='Device ID')
    name = models.CharField(max_length=100, verbose_name='Wallet Name')
    chain = models.CharField(max_length=20, verbose_name='Blockchain')
    address = models.CharField(max_length=100, verbose_name='Address')
    encrypted_private_key = models.TextField(verbose_name='Encrypted Private Key', null=True, blank=True)
    avatar = models.ImageField(upload_to='wallet_avatars/', verbose_name='Avatar', null=True, blank=True)
    is_active = models.BooleanField(default=True, verbose_name='Is Active')
    is_watch_only = models.BooleanField(default=False, verbose_name='Is Watch-Only Wallet')
    is_imported = models.BooleanField(default=False, verbose_name='Is Imported Wallet')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')
    
    _payment_password = None  # Add payment password attribute
    
    @property
    def payment_password(self):
        return self._payment_password
        
    @payment_password.setter
    def payment_password(self, value):
        self._payment_password = value

    def check_device(self, device_id: str) -> bool:
        """Check if device ID matches
        
        Args:
            device_id: Device ID
            
        Returns:
            bool: Whether it matches
        """
        return self.device_id == device_id
        
    def check_payment_password(self, payment_password: str) -> bool:
        """Check if payment password is correct
        
        Args:
            payment_password: Payment password
            
        Returns:
            bool: Whether it is correct
        """
        try:
            # Get payment password record
            payment_pwd = PaymentPassword.objects.filter(device_id=self.device_id).first()
            if not payment_pwd:
                return False
            
            # Verify password
            return payment_pwd.verify_password(payment_password)
        except Exception as e:
            logger.error(f"Failed to verify payment password: {str(e)}")
            return False

    class Meta:
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'
        ordering = ['-created_at']
        unique_together = ['device_id', 'chain', 'address']

    def __str__(self):
        return f"{self.name} ({self.address})"

    def decrypt_private_key(self) -> str:
        """Decrypt private key"""
        if not self.encrypted_private_key:
            logger.error("Wallet does not have a private key")
            raise ValueError("Wallet does not have a private key")
        
        if self.is_watch_only:
            logger.error("Watch-Only wallet does not have a private key")
            raise ValueError("Watch-Only wallet does not have a private key")
            
        try:
            # Get payment password
            if not self.payment_password:
                raise ValueError("Payment password not provided")
            
            # Use Fernet to decrypt private key
            from wallet.views.wallet import WalletViewSet
            wallet_viewset = WalletViewSet()
            decrypted = wallet_viewset.decrypt_data(self.encrypted_private_key, self.payment_password)
            
            # Ensure decrypted data is string type
            if isinstance(decrypted, bytes):
                try:
                    decrypted = decrypted.decode('utf-8')
                except UnicodeDecodeError as e:
                    logger.error(f"UTF-8 decoding failed: {str(e)}")
                    raise ValueError("Private key decoding failed")
            elif not isinstance(decrypted, str):
                logger.error(f"Invalid decrypted private key type: {type(decrypted)}")
                raise ValueError("Invalid private key type")
            
            # Process private key based on chain type
            if self.chain == 'SOL':
                try:
                    # Decode Base58 format data back to bytes
                    decrypted_bytes = base58.b58decode(decrypted)
                    
                    # If it's an 88-byte extended format, extract the first 64 bytes
                    if len(decrypted_bytes) == 88:
                        keypair_bytes = decrypted_bytes[:64]
                    # If it's already in 64-byte format, use directly
                    elif len(decrypted_bytes) == 64:
                        keypair_bytes = decrypted_bytes
                    # If it's a 32-byte private key, create a complete key pair
                    elif len(decrypted_bytes) == 32:
                        keypair = Keypair.from_seed(decrypted_bytes)
                        keypair_bytes = keypair.seed + bytes(keypair.public_key)
                    else:
                        raise ValueError(f"Invalid private key length: {len(decrypted_bytes)}")
                    
                    # Verify generated address
                    keypair = Keypair.from_seed(keypair_bytes[:32])
                    generated_address = str(keypair.public_key)
                    logger.debug(f"Generated address: {generated_address}")
                    
                    if generated_address != self.address:
                        raise ValueError(f"Private key does not match: Expected={self.address}, Actual={generated_address}")
                    
                    # Return Base58 encoded 64-byte key pair
                    return base58.b58encode(keypair_bytes).decode()
                    
                except Exception as e:
                    logger.error(f"Failed to verify SOL private key: {str(e)}")
                    raise ValueError(f"Failed to verify SOL private key: {str(e)}")
                    
            elif self.chain in ["ETH", "BASE", "BNB", "MATIC", "AVAX", "ARBITRUM", "OPTIMISM"]:
                try:
                    # If decrypted data is byte type
                    if isinstance(decrypted, bytes):
                        private_key_bytes = decrypted
                    # If it's string type, try to convert to bytes
                    elif isinstance(decrypted, str):
                        try:
                            # If it's hexadecimal format string
                            if decrypted.startswith('0x'):
                                private_key_bytes = bytes.fromhex(decrypted[2:])
                            else:
                                private_key_bytes = bytes.fromhex(decrypted)
                        except ValueError:
                            # If it's not hexadecimal format, it might be a literal value representation of byte string
                            private_key_bytes = eval(decrypted)
                    else:
                        raise ValueError(f"Unsupported private key format: {type(decrypted)}")
                        
                    # Verify private key length
                    if len(private_key_bytes) != 32:
                        raise ValueError(f"Invalid private key length: {len(private_key_bytes)}")
                        
                    # Verify private key matches address
                    account = Account.from_key(private_key_bytes)
                    if account.address.lower() != self.address.lower():  # Use lowercase comparison
                        raise ValueError(f"Private key address does not match: Expected {self.address}, Actual {account.address}")
                    
                    # Return hexadecimal format private key
                    return '0x' + private_key_bytes.hex()
                    
                except Exception as e:
                    logger.error(f"Failed to verify EVM private key: {str(e)}")
                    raise ValueError(f"Failed to verify EVM private key: {str(e)}")
            else:
                raise ValueError(f"Unsupported chain type: {self.chain}")
                
        except Exception as e:
            logger.error(f"Failed to decrypt private key: {str(e)}")
            raise ValueError(f"Failed to decrypt private key: {str(e)}")

    def _verify_address_match(self, generated_address: str) -> bool:
        """Verify if generated address matches wallet address"""
        try:
            # If address is completely matched
            if self.address == generated_address:
                return True
                
            # If it's a Solana wallet
            if self.chain == 'SOL':
                # If wallet address is compressed public key format (hexadecimal starting with 02 or 03)
                if (self.address.startswith('02') or self.address.startswith('03')):
                    try:
                        # Extract actual public key data from compressed public key (remove prefix)
                        hex_str = self.address[2:]  # Remove 02/03 prefix
                        # Convert hexadecimal to bytes
                        hex_bytes = bytes.fromhex(hex_str)
                        # Convert to Base58 format
                        base58_address = base58.b58encode(hex_bytes).decode()
                        logger.debug(f"Base58 address from compressed public key: {base58_address}")
                        return base58_address == generated_address
                    except Exception as e:
                        logger.error(f"Failed to convert compressed public key: {str(e)}")
                        return False
                        
                # If wallet address is Base58 format
                try:
                    wallet_bytes = base58.b58decode(self.address)
                    generated_bytes = base58.b58decode(generated_address)
                    return wallet_bytes == generated_bytes
                except Exception as e:
                    logger.error(f"Failed to decode Base58: {str(e)}")
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"Address verification failed: {str(e)}")
            return False

class Token(models.Model):
    """Token model"""
    chain = models.CharField(max_length=10, verbose_name='Chain')
    address = models.CharField(max_length=255, verbose_name='Contract Address')
    name = models.CharField(max_length=255, verbose_name='Name')
    symbol = models.CharField(max_length=50, verbose_name='Symbol')
    decimals = models.IntegerField(default=18, verbose_name='Decimal Places')
    logo = models.URLField(max_length=500, null=True, blank=True, verbose_name='Logo')
    logo_hash = models.CharField(max_length=255, null=True, blank=True, verbose_name='Logo Hash')
    thumbnail = models.URLField(max_length=500, null=True, blank=True, verbose_name='Thumbnail')
    type = models.CharField(max_length=20, default='token', verbose_name='Type')
    contract_type = models.CharField(max_length=20, default='ERC20', verbose_name='Contract Type')
    description = models.TextField(null=True, blank=True, verbose_name='Description')
    website = models.URLField(max_length=500, null=True, blank=True, verbose_name='Website')
    email = models.EmailField(max_length=255, null=True, blank=True, verbose_name='Email')
    twitter = models.URLField(max_length=500, null=True, blank=True, verbose_name='Twitter')
    telegram = models.URLField(max_length=500, null=True, blank=True, verbose_name='Telegram')
    reddit = models.URLField(max_length=500, null=True, blank=True, verbose_name='Reddit')
    discord = models.URLField(max_length=500, null=True, blank=True, verbose_name='Discord')
    instagram = models.URLField(max_length=500, null=True, blank=True, verbose_name='Instagram')
    github = models.URLField(max_length=500, null=True, blank=True, verbose_name='GitHub')
    medium = models.URLField(max_length=500, null=True, blank=True, verbose_name='Medium')
    moralis = models.URLField(max_length=500, null=True, blank=True, verbose_name='Moralis')
    coingecko_id = models.CharField(max_length=100, null=True, blank=True, verbose_name='CoinGecko ID')
    total_supply = models.CharField(max_length=255, null=True, blank=True, verbose_name='Total Supply')
    total_supply_formatted = models.CharField(max_length=255, null=True, blank=True, verbose_name='Formatted Total Supply')
    circulating_supply = models.CharField(max_length=255, null=True, blank=True, verbose_name='Circulating Supply')
    market_cap = models.CharField(max_length=255, null=True, blank=True, verbose_name='Market Cap')
    fully_diluted_valuation = models.CharField(max_length=255, null=True, blank=True, verbose_name='Fully Diluted Valuation')
    categories = models.JSONField(default=list, null=True, blank=True, verbose_name='Categories')
    security_score = models.IntegerField(null=True, blank=True, verbose_name='Security Score')
    verified = models.BooleanField(default=False, verbose_name='Is Verified')
    possible_spam = models.BooleanField(default=False, verbose_name='Is Possible Spam')
    block_number = models.CharField(max_length=255, null=True, blank=True, verbose_name='Block Height')
    validated = models.IntegerField(default=0, verbose_name='Validation Status')
    created_at = models.DateTimeField(null=True, blank=True, verbose_name='Created Time')
    is_native = models.BooleanField(default=False, verbose_name='Is Native Token')
    is_visible = models.BooleanField(default=True, verbose_name='Is Visible')
    is_recommended = models.BooleanField(default=False, verbose_name='Is Recommended')
    
    # Cache fields
    last_balance = models.CharField(max_length=255, null=True, blank=True, verbose_name='Last Balance')
    last_price = models.CharField(max_length=255, null=True, blank=True, verbose_name='Last Price')
    last_price_change = models.CharField(max_length=255, null=True, blank=True, verbose_name='Last 24h Price Change')
    last_value = models.CharField(max_length=255, null=True, blank=True, verbose_name='Last Value')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    # Add category field
    category = models.ForeignKey(
        'TokenCategory', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='tokens',
        verbose_name='Token Category'
    )

    class Meta:
        verbose_name = 'Token'
        verbose_name_plural = 'Tokens'
        unique_together = ('chain', 'address')
        indexes = [
            models.Index(fields=['chain', 'address']),
        ]
        ordering = ['-is_recommended', '-verified', '-created_at']

    def __str__(self):
        return f"{self.chain} - {self.symbol} ({self.address})"

class NFTCollection(models.Model):
    """NFT Collection model"""
    chain = models.CharField(max_length=20, verbose_name='Blockchain')
    contract_address = models.CharField(max_length=100, verbose_name='Contract Address', null=True, blank=True)
    name = models.CharField(max_length=100, verbose_name='Collection Name')
    symbol = models.CharField(max_length=100, verbose_name='Collection Symbol')
    contract_type = models.CharField(max_length=20, default='ERC721', verbose_name='Contract Type')
    description = models.TextField(verbose_name='Description', null=True, blank=True)
    logo = models.URLField(verbose_name='Logo URL', null=True, blank=True)
    banner = models.URLField(verbose_name='Banner URL', null=True, blank=True)
    is_verified = models.BooleanField(default=False, verbose_name='Is Verified')
    is_spam = models.BooleanField(default=False, verbose_name='Is Spam')
    is_visible = models.BooleanField(default=True, verbose_name='Is Visible')
    floor_price = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Floor Price', default=Decimal('0'))
    floor_price_usd = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Floor Price (USD)', default=Decimal('0'))
    floor_price_currency = models.CharField(max_length=10, default='eth', verbose_name='Floor Price Currency')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    class Meta:
        verbose_name = 'NFT Collection'
        verbose_name_plural = 'NFT Collections'
        ordering = ['-floor_price_usd', '-created_at']
        unique_together = ['chain', 'contract_address']

    def __str__(self):
        return f"{self.name} ({self.chain})"

class Transaction(models.Model):
    """Transaction record model"""
    TYPE_CHOICES = [
        ('TRANSFER', 'Transfer'),
        ('APPROVE', 'Approve'),
        ('SWAP', 'Swap'),
        ('MINT', 'Mint'),
        ('BURN', 'Burn'),
        ('OTHER', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]
    
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, verbose_name='Wallet')
    chain = models.CharField(max_length=20, verbose_name='Blockchain')
    tx_hash = models.CharField(max_length=100, verbose_name='Transaction Hash')
    tx_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='Transaction Type')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name='Status')
    from_address = models.CharField(max_length=100, verbose_name='From Address')
    to_address = models.CharField(max_length=100, verbose_name='To Address')
    amount = models.CharField(max_length=64, default='0')
    token = models.ForeignKey(Token, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='Token')
    nft_collection = models.ForeignKey(NFTCollection, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='NFT Collection')
    nft_token_id = models.CharField(max_length=100, null=True, blank=True, verbose_name='NFT Token ID')
    token_info = models.JSONField(null=True, blank=True, verbose_name='Token Info')
    gas_price = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Gas Price')
    gas_used = models.DecimalField(max_digits=30, decimal_places=18, verbose_name='Gas Used')
    block_number = models.IntegerField(verbose_name='Block Height')
    block_timestamp = models.DateTimeField(verbose_name='Block Time')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    to_token_address = models.CharField(max_length=255, null=True, blank=True, help_text="Target Token Address (for Swap transaction)")

    class Meta:
        verbose_name = 'Transaction Record'
        verbose_name_plural = 'Transaction Records'
        ordering = ['-block_timestamp']
        unique_together = ['chain', 'tx_hash', 'wallet']

    def __str__(self):
        return f"{self.tx_hash} ({self.tx_type})"

class MnemonicBackup(models.Model):
    """Mnemonic backup model"""
    device_id = models.CharField(max_length=100, verbose_name='Device ID')
    chain = models.CharField(max_length=20, verbose_name='Blockchain')
    encrypted_mnemonic = models.TextField(verbose_name='Encrypted Mnemonic')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    
    _payment_password = None
    
    @property
    def payment_password(self):
        return self._payment_password
        
    @payment_password.setter
    def payment_password(self, value):
        self._payment_password = value
    
    def decrypt_mnemonic(self) -> str:
        """Decrypt mnemonic, process based on different chain type"""
        if not self.encrypted_mnemonic:
            logger.error("No encrypted mnemonic")
            raise ValueError("No encrypted mnemonic")
            
        try:
            # Get payment password
            if not self.payment_password:
                raise ValueError("Payment password not provided")
            
            # Use Fernet to decrypt mnemonic
            from wallet.views.wallet import WalletViewSet
            wallet_viewset = WalletViewSet()
            decrypted = wallet_viewset.decrypt_data(self.encrypted_mnemonic, self.payment_password)
            
            # Ensure decrypted data is string type
            if isinstance(decrypted, bytes):
                try:
                    decrypted = decrypted.decode('utf-8')
                except UnicodeDecodeError as e:
                    logger.error(f"UTF-8 decoding failed: {str(e)}")
                    raise ValueError("Mnemonic decoding failed")
            elif not isinstance(decrypted, str):
                logger.error(f"Invalid decrypted mnemonic type: {type(decrypted)}")
                raise ValueError("Invalid mnemonic type")
            
            # Process mnemonic based on chain type
            if self.chain == 'SOL':
                try:
                    # For Solana, mnemonic should be space-separated words
                    words = decrypted.strip().split()
                    if len(words) not in [12, 24]:
                        raise ValueError(f"Invalid mnemonic length: {len(words)} words")
                    return ' '.join(words)
                except Exception as e:
                    logger.error(f"Failed to verify SOL mnemonic: {str(e)}")
                    raise ValueError(f"Failed to verify SOL mnemonic: {str(e)}")
            elif self.chain in ["ETH", "BASE", "BNB", "MATIC", "AVAX", "ARBITRUM", "OPTIMISM"]:
                try:
                    # For EVM chains, mnemonic is also space-separated words
                    words = decrypted.strip().split()
                    if len(words) not in [12, 15, 18, 21, 24]:
                        raise ValueError(f"Invalid mnemonic length: {len(words)} words")
                    return ' '.join(words)
                except Exception as e:
                    logger.error(f"Failed to verify EVM mnemonic: {str(e)}")
                    raise ValueError(f"Failed to verify EVM mnemonic: {str(e)}")
            else:
                raise ValueError(f"Unsupported chain type: {self.chain}")
                
        except Exception as e:
            logger.error(f"Failed to decrypt mnemonic: {str(e)}")
            raise ValueError(f"Failed to decrypt mnemonic: {str(e)}")

    class Meta:
        verbose_name = 'Mnemonic Backup'
        verbose_name_plural = 'Mnemonic Backups'
        ordering = ['-created_at']
        unique_together = ['device_id', 'chain']

    def __str__(self):
        return f"Backup for device {self.device_id} on {self.chain}"

class PaymentPassword(models.Model):
    """Payment password model"""
    device_id = models.CharField(max_length=100, unique=True, verbose_name='Device ID')
    encrypted_password = models.CharField(max_length=255, verbose_name='Encrypted Payment Password')
    is_biometric_enabled = models.BooleanField(default=False, verbose_name='Is Biometric Enabled')
    biometric_verified_at = models.DateTimeField(null=True, blank=True, verbose_name='Last Biometric Password Verification Time')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    class Meta:
        verbose_name = 'Payment Password'
        verbose_name_plural = 'Payment Passwords'

    def __str__(self):
        return f"Payment password for device {self.device_id}"

    @staticmethod
    async def verify_device_password(device_id: str, password: str) -> bool:
        """Verify device payment password
        
        Args:
            device_id: Device ID
            password: Payment password
            
        Returns:
            bool: Whether password is correct
        """
        try:
            from asgiref.sync import sync_to_async
            
            # Get payment password record
            payment_pwd = await sync_to_async(PaymentPassword.objects.filter(
                device_id=device_id
            ).first)()
            
            if not payment_pwd:
                logger.error(f"Failed to find payment password record for device: {device_id}")
                return False
                
            # Verify password
            return payment_pwd.verify_password(password)
            
        except Exception as e:
            logger.error(f"Failed to verify payment password: {str(e)}")
            return False

    def verify_password(self, password: str) -> bool:
        """Verify payment password"""
        try:
            # Decrypt stored password
            from wallet.views.wallet import WalletViewSet
            wallet_viewset = WalletViewSet()
            
            # Record input password information
            logger.debug(f"Verifying payment password: device_id={self.device_id}, input password type={type(password)}")
            
            # Ensure password is string type
            if not isinstance(password, str):
                logger.error(f"Invalid password type: {type(password)}")
                return False
                
            try:
                # Decrypt stored password
                decrypted_password = wallet_viewset.decrypt_data(self.encrypted_password, self.device_id)
                logger.debug(f"Decrypted password type: {type(decrypted_password)}")
                
                # Ensure decrypted password is string type
                if isinstance(decrypted_password, bytes):
                    try:
                        decrypted_password = decrypted_password.decode('utf-8')
                    except UnicodeDecodeError as e:
                        logger.error(f"UTF-8 decoding failed: {str(e)}")
                        return False
                elif not isinstance(decrypted_password, str):
                    logger.error(f"Invalid decrypted password type: {type(decrypted_password)}")
                    return False
                    
                # Ensure both passwords are string types and remove possible whitespace characters
                password = str(password).strip()
                decrypted_password = str(decrypted_password).strip()
                
                # Record password comparison state before
                logger.debug(f"Input password length: {len(password)}, decrypted password length: {len(decrypted_password)}")
                logger.debug(f"Input password: {password}, decrypted password: {decrypted_password}")
                
                # Password comparison
                is_match = password == decrypted_password
                logger.debug(f"Password verification result: {is_match}")
                
                return is_match
                
            except Exception as decrypt_error:
                logger.error(f"Failed to decrypt password: {str(decrypt_error)}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to verify payment password: {str(e)}")
            return False

    def enable_biometric(self) -> bool:
        """Enable biometric password
        
        Returns:
            bool: Whether successful enable
        """
        try:
            self.is_biometric_enabled = True
            self.save()
            return True
        except Exception as e:
            logger.error(f"Failed to enable biometric password: {str(e)}")
            return False

    def disable_biometric(self) -> bool:
        """Disable biometric password
        
        Returns:
            bool: Whether successful disable
        """
        try:
            self.is_biometric_enabled = False
            self.biometric_verified_at = None
            self.save()
            return True
        except Exception as e:
            logger.error(f"Failed to disable biometric password: {str(e)}")
            return False

    def update_biometric_verified_time(self) -> bool:
        """Update biometric password verification time
        
        Returns:
            bool: Whether successful update
        """
        try:
            from django.utils import timezone
            self.biometric_verified_at = timezone.now()
            self.save()
            return True
        except Exception as e:
            logger.error(f"Failed to update biometric password verification time: {str(e)}")
            return False

class TokenIndex(models.Model):
    """Token index model, only store basic information"""
    chain = models.CharField(max_length=10, verbose_name='Chain')
    address = models.CharField(max_length=255, verbose_name='Contract Address')
    name = models.CharField(max_length=255, verbose_name='Name')
    symbol = models.CharField(max_length=50, verbose_name='Symbol')
    decimals = models.IntegerField(default=18, verbose_name='Decimal Places')
    is_native = models.BooleanField(default=False, verbose_name='Is Native Token')
    is_verified = models.BooleanField(default=False, verbose_name='Is Verified')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    class Meta:
        verbose_name = 'Token Index'
        verbose_name_plural = 'Token Indexes'
        unique_together = ('chain', 'address')
        indexes = [
            models.Index(fields=['chain', 'address']),
            models.Index(fields=['symbol']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.chain} - {self.symbol} ({self.address})"

class TokenIndexSource(models.Model):
    """Token data source record"""
    name = models.CharField(max_length=50, verbose_name='Data Source Name')
    priority = models.IntegerField(verbose_name='Priority')
    last_sync = models.DateTimeField(auto_now=True, verbose_name='Last Sync Time')
    is_active = models.BooleanField(default=True, verbose_name='Is Active')
    
    class Meta:
        verbose_name = 'Token Data Source'
        verbose_name_plural = 'Token Data Sources'
        ordering = ['priority']
        
    def __str__(self):
        return f"{self.name} (Priority: {self.priority})"

class TokenIndexMetrics(models.Model):
    """Token index metrics data"""
    token = models.OneToOneField(TokenIndex, on_delete=models.CASCADE, related_name='metrics', verbose_name='Token')
    daily_volume = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='24h Transaction Volume (USD)')
    holder_count = models.IntegerField(default=0, verbose_name='Holder Count')
    liquidity = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='Liquidity (USD)')
    market_cap = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='Market Cap (USD)')
    price = models.DecimalField(max_digits=30, decimal_places=18, default=Decimal('0'), verbose_name='Price (USD)')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')
    
    class Meta:
        verbose_name = 'Token Metrics'
        verbose_name_plural = 'Token Metrics'
        
    def __str__(self):
        return f"{self.token.symbol} Metrics"

class TokenIndexGrade(models.Model):
    """Token grade evaluation"""
    GRADE_CHOICES = [
        ('A', 'A Grade - Core Token'),
        ('B', 'B Grade - Regular Token'),
        ('C', 'C Grade - Observation Token'),
    ]
    
    token = models.OneToOneField(TokenIndex, on_delete=models.CASCADE, related_name='grade', verbose_name='Token')
    grade = models.CharField(max_length=1, choices=GRADE_CHOICES, verbose_name='Grade')
    score = models.IntegerField(default=0, verbose_name='Overall Score')
    last_evaluated = models.DateTimeField(auto_now=True, verbose_name='Last Evaluation Time')
    evaluation_reason = models.TextField(null=True, blank=True, verbose_name='Evaluation Reason')
    
    class Meta:
        verbose_name = 'Token Grade'
        verbose_name_plural = 'Token Grades'
        
    def __str__(self):
        return f"{self.token.symbol} ({self.grade} Grade)"

class TokenIndexReport(models.Model):
    """Index library status report"""
    total_tokens = models.IntegerField(verbose_name='Total Tokens')
    grade_a_count = models.IntegerField(verbose_name='A Grade Tokens')
    grade_b_count = models.IntegerField(verbose_name='B Grade Tokens')
    grade_c_count = models.IntegerField(verbose_name='C Grade Tokens')
    new_tokens = models.IntegerField(verbose_name='New Tokens')
    removed_tokens = models.IntegerField(verbose_name='Removed Tokens')
    report_date = models.DateTimeField(auto_now_add=True, verbose_name='Report Time')
    details = models.JSONField(default=dict, verbose_name='Details')
    
    class Meta:
        verbose_name = 'Index Library Report'
        verbose_name_plural = 'Index Library Reports'
        ordering = ['-report_date']
        
    def __str__(self):
        return f"Token Index Report ({self.report_date.strftime('%Y-%m-%d %H:%M')})"

class TokenCategory(models.Model):
    """Token category model"""
    name = models.CharField(max_length=50, verbose_name='Category Name')
    code = models.CharField(max_length=20, unique=True, verbose_name='Category Code')
    description = models.TextField(blank=True, null=True, verbose_name='Category Description')
    icon = models.CharField(max_length=255, blank=True, null=True, verbose_name='Category Icon')
    priority = models.IntegerField(default=0, verbose_name='Display Priority')
    is_active = models.BooleanField(default=True, verbose_name='Is Active')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    class Meta:
        verbose_name = 'Token Category'
        verbose_name_plural = 'Token Categories'
        ordering = ['priority', 'name']

    def __str__(self):
        return self.name

class ReferralRelationship(models.Model):
    """Recommendation relationship model"""
    referrer_device_id = models.CharField(max_length=100, verbose_name='Referrer Device ID')
    referred_device_id = models.CharField(max_length=100, verbose_name='Referred Device ID')
    download_completed = models.BooleanField(default=True, verbose_name='Is Download Completed')
    wallet_created = models.BooleanField(default=False, verbose_name='Is Wallet Created/Imported')
    download_points_awarded = models.BooleanField(default=False, verbose_name='Is Download Points Awarded')
    wallet_points_awarded = models.BooleanField(default=False, verbose_name='Is Wallet Points Awarded')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    class Meta:
        verbose_name = 'Recommendation Relationship'
        verbose_name_plural = 'Recommendation Relationships'
        unique_together = ['referrer_device_id', 'referred_device_id']
        indexes = [
            models.Index(fields=['referrer_device_id']),
            models.Index(fields=['referred_device_id']),
        ]

    def __str__(self):
        return f"{self.referrer_device_id} -> {self.referred_device_id}"

class UserPoints(models.Model):
    """User points model"""
    device_id = models.CharField(max_length=100, unique=True, verbose_name='Device ID')
    total_points = models.IntegerField(default=0, verbose_name='Total Points')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    class Meta:
        verbose_name = 'User Points'
        verbose_name_plural = 'User Points'
        indexes = [
            models.Index(fields=['device_id']),
        ]

    def __str__(self):
        return f"{self.device_id}: {self.total_points} points"

    @classmethod
    def get_or_create_user_points(cls, device_id):
        """Get or create user points record"""
        user_points, created = cls.objects.get_or_create(
            device_id=device_id,
            defaults={'total_points': 0}
        )
        return user_points

    def add_points(self, points, action_type, description=None, related_device_id=None):
        """Add points and record history"""
        self.total_points += points
        self.save()
        
        # Create points history record
        PointsHistory.objects.create(
            device_id=self.device_id,
            points=points,
            action_type=action_type,
            description=description,
            related_device_id=related_device_id
        )
        
        return self.total_points

class PointsHistory(models.Model):
    """Points history model"""
    ACTION_TYPES = [
        ('DOWNLOAD_REFERRAL', 'Download Recommendation'),
        ('WALLET_REFERRAL', 'Wallet Creation Recommendation'),
        ('POINTS_USED', 'Points Used'),
        ('ADMIN_ADJUSTMENT', 'Admin Adjustment'),
        ('OTHER', 'Other'),
    ]
    
    device_id = models.CharField(max_length=100, verbose_name='Device ID')
    points = models.IntegerField(verbose_name='Points Change')
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES, verbose_name='Action Type')
    description = models.TextField(null=True, blank=True, verbose_name='Description')
    related_device_id = models.CharField(max_length=100, null=True, blank=True, verbose_name='Related Device ID')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')

    class Meta:
        verbose_name = 'Points History'
        verbose_name_plural = 'Points History'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['device_id']),
            models.Index(fields=['action_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        action = dict(self.ACTION_TYPES).get(self.action_type, self.action_type)
        return f"{self.device_id}: {self.points} points ({action})"

class ReferralLink(models.Model):
    """Recommendation link model"""
    device_id = models.CharField(max_length=100, verbose_name='Device ID')
    code = models.CharField(max_length=20, unique=True, verbose_name='Recommendation Code')
    is_active = models.BooleanField(default=True, verbose_name='Is Active')
    clicks = models.IntegerField(default=0, verbose_name='Click Count')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Time')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated Time')

    class Meta:
        verbose_name = 'Recommendation Link'
        verbose_name_plural = 'Recommendation Links'
        indexes = [
            models.Index(fields=['device_id']),
            models.Index(fields=['code']),
        ]

    def __str__(self):
        return f"{self.device_id}: {self.code}"

    @classmethod
    def generate_code(cls, length=8):
        """Generate unique recommendation code"""
        import random
        import string
        
        while True:
            # Generate random string
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
            
            # Check if it already exists
            if not cls.objects.filter(code=code).exists():
                return code

    @classmethod
    def get_or_create_link(cls, device_id):
        """Get or create recommendation link"""
        referral_link = cls.objects.filter(device_id=device_id, is_active=True).first()
        
        if not referral_link:
            code = cls.generate_code()
            referral_link = cls.objects.create(
                device_id=device_id,
                code=code,
                is_active=True
            )
            
        return referral_link

    def increment_clicks(self):
        """Increment click count"""
        self.clicks += 1
        self.save()
        return self.clicks

    def record_download(self, device_id):
        """Record download and increment click count"""
        from .models import ReferralRelationship, UserPoints
        
        # Increment click count
        self.increment_clicks()
        
        # Prevent self-referral
        if self.device_id == device_id:
            return False
        
        # Create or update referral relationship
        relationship, created = ReferralRelationship.objects.get_or_create(
            referrer_device_id=self.device_id,
            referred_device_id=device_id,
            defaults={
                'download_completed': True,
                'wallet_created': False,
                'download_points_awarded': False,
                'wallet_points_awarded': False
            }
        )
        
        # If new relationship, award download points
        if created or not relationship.download_points_awarded:
            # Get or create referrer's points record
            user_points = UserPoints.get_or_create_user_points(self.device_id)
            
            # Add points (5 points)
            user_points.add_points(
                points=5,
                action_type='DOWNLOAD_REFERRAL',
                description=f'User {device_id} downloaded the app through your referral',
                related_device_id=device_id
            )
            
            # Mark download points as awarded
            relationship.download_points_awarded = True
            relationship.save()
        
        return True

