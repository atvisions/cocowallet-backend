from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from hdwallet import HDWallet
from hdwallet.utils import generate_mnemonic
from mnemonic import Mnemonic
import base64
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from io import BytesIO
from django.core.files.base import ContentFile
import re
import logging
import base58
from web3 import Web3
from solana.keypair import Keypair
from base58 import b58encode, b58decode
from eth_account import Account
from cryptography.fernet import Fernet
from wallet.models import Wallet, PaymentPassword, Chain
from wallet.serializers import WalletSerializer, WalletCreateSerializer, WalletSetupSerializer, ChainSelectionSerializer, VerifyMnemonicSerializer
from wallet.utils.validators import validate_device_id, validate_payment_password
from wallet.utils.encryption import encrypt_string, decrypt_string
from wallet.utils.exceptions import WalletError
from wallet.decorators import verify_payment_password
from wallet.services.factory import ChainServiceFactory
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os

# 启用 eth_account 的助记词功能
Account.enable_unaudited_hdwallet_features()

logger = logging.getLogger(__name__)

class WalletViewSet(viewsets.ModelViewSet):
    """钱包视图集"""
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    parser_classes = [JSONParser]
    queryset = Wallet.objects.filter(is_active=True)
    serializer_class = WalletSerializer

    def get_queryset(self):
        device_id = self.request.query_params.get('device_id') or self.request.data.get('device_id') # type: ignore
        if device_id:
            return self.queryset.filter(device_id=device_id)
        return self.queryset.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return WalletCreateSerializer
        elif self.action == 'set_password':
            return WalletSetupSerializer
        elif self.action == 'select_chain':
            return ChainSelectionSerializer
        return self.serializer_class

    def encrypt_data(self, data, key):
        """使用 Fernet 加密数据"""
        try:
            # 确保输入数据是字符串类型
            if not isinstance(data, str):
                data = str(data)
            
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
            # 输入验证
            if not encrypted_text:
                raise ValueError("加密文本不能为空")
            if not key:
                raise ValueError("密钥不能为空")
                
            logger.debug(f"开始解密数据，加密文本长度: {len(encrypted_text)}")
            
            # 使用 SHA256 生成固定长度的密钥
            key_bytes = hashlib.sha256(key.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            try:
                # Base64 解码
                encrypted_bytes = base64.b64decode(encrypted_text)
                
                # 解密数据
                decrypted = f.decrypt(encrypted_bytes)
                logger.debug(f"解密完成，解密后字节长度: {len(decrypted)}")
                
                # 返回原始字节数据
                return decrypted
                
            except base64.binascii.Error as e:
                logger.error(f"Base64 解码失败: {str(e)}")
                raise ValueError("无效的 Base64 编码")
            except Exception as e:
                logger.error(f"解密失败: {str(e)}")
                raise ValueError(f"解密失败: {str(e)}")
                
        except Exception as e:
            logger.error(f"解密数据失败: {str(e)}")
            raise ValueError(f"解密失败: {str(e)}")

    @action(detail=False, methods=['post'], url_path='verify_mnemonic')
    def verify_mnemonic(self, request):
        """验证助记词"""
        serializer = VerifyMnemonicSerializer(data=request.data)
        if not serializer.is_valid():
            logger.error(f"验证助记词参数错误: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        device_id = serializer.validated_data['device_id']
        chain = serializer.validated_data['chain']
        mnemonic = serializer.validated_data['mnemonic']
        payment_password = request.data.get('payment_password')
        
        if not payment_password:
            return Response({
                'status': 'error',
                'message': '请提供支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证支付密码
        try:
            payment_pwd = PaymentPassword.objects.get(device_id=device_id)
            if not payment_pwd.verify_password(payment_password):
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '请先设置支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证助记词
        try:
            if chain == 'SOL':
                # 使用助记词生成 Solana 钱包
                try:
                    # 使用助记词生成种子
                    seed = hashlib.pbkdf2_hmac(
                        'sha512',
                        mnemonic.encode('utf-8'),
                        'mnemonic'.encode('utf-8'),
                        2048
                    )
                    
                    # 使用种子的前32字节作为私钥
                    private_key_bytes = seed[:32]
                    
                    # 从私钥创建Solana密钥对
                    keypair = Keypair.from_seed(private_key_bytes)
                    address = str(keypair.public_key)
                    
                    # 加密私钥
                    key_bytes = hashlib.sha256(payment_password.encode()).digest()
                    f = Fernet(base64.urlsafe_b64encode(key_bytes))
                    encrypted = f.encrypt(private_key_bytes)
                    encrypted_private_key = base64.b64encode(encrypted).decode('utf-8')
                    
                    logger.debug(f"生成的私钥长度: {len(private_key_bytes)}")
                except Exception as e:
                    logger.error(f"生成 Solana 钱包失败: {str(e)}")
                    raise
            else:
                # 使用助记词生成 EVM 钱包
                try:
                    account = Account.from_mnemonic(mnemonic)
                    address = account.address
                    private_key_bytes = account.key
                    
                    # 加密私钥
                    key_bytes = hashlib.sha256(payment_password.encode()).digest()
                    f = Fernet(base64.urlsafe_b64encode(key_bytes))
                    encrypted = f.encrypt(private_key_bytes)
                    encrypted_private_key = base64.b64encode(encrypted).decode('utf-8')
                    
                    logger.debug(f"生成的 EVM 地址: {address}")
                except Exception as e:
                    logger.error(f"生成 EVM 钱包失败: {str(e)}")
                    raise
            
            # 检查是否已存在相同地址的钱包
            existing_wallet = Wallet.objects.filter(
                device_id=device_id,
                chain=chain,
                address=address
            ).first()
            
            if existing_wallet:
                if existing_wallet.is_active:
                    logger.warning(f"钱包已存在且处于激活状态: {address}")
                    return Response({
                        'status': 'error',
                        'message': '该钱包已存在且处于激活状态'
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    # 如果钱包存在但已被删除，重新激活它
                    logger.info(f"重新激活已存在的钱包: {address}")
                    existing_wallet.is_active = True
                    existing_wallet.encrypted_private_key = encrypted_private_key
                    existing_wallet.save()
                    return Response({
                        'status': 'success',
                        'message': '钱包已重新激活',
                        'wallet': WalletSerializer(existing_wallet).data
                    })
            
            # 生成随机头像
            try:
                from ..serializers import generate_avatar
                avatar_image = generate_avatar()
                avatar_io = BytesIO()
                avatar_image.save(avatar_io, format='PNG')
                avatar_content = avatar_io.getvalue()
                logger.debug(f"生成的头像大小: {len(avatar_content)} bytes")
            except Exception as e:
                logger.error(f"生成头像失败: {str(e)}")
                raise
            
            # 创建钱包
            try:
                wallet = Wallet.objects.create(
                    device_id=device_id,
                    name=f"{chain} Wallet 1",
                    chain=chain,
                    address=address,
                    encrypted_private_key=encrypted_private_key
                )
                logger.info(f"创建新钱包成功: {address}")
            except Exception as e:
                logger.error(f"创建钱包记录失败: {str(e)}")
                raise
            
            # 保存头像
            try:
                wallet.avatar.save(f'wallet_avatar_{wallet.pk}.png', ContentFile(avatar_content))
                logger.info(f"保存头像成功: {wallet.avatar.name}")
            except Exception as e:
                logger.error(f"保存头像失败: {str(e)}")
                raise
            
            return Response({
                'status': 'success',
                'message': '助记词验证成功',
                'wallet': WalletSerializer(wallet).data
            })
        except Exception as e:
            logger.error(f"助记词验证失败: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': f'助记词验证失败: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='set_password')
    def set_password(self, request):
        """设置支付密码"""
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        device_id = serializer.validated_data['device_id']
        payment_password = serializer.validated_data['payment_password']
        
        # 检查是否已存在支付密码
        if PaymentPassword.objects.filter(device_id=device_id).exists():
            return Response({
                'status': 'error',
                'message': '该设备已设置支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 创建支付密码
        PaymentPassword.objects.create(
            device_id=device_id,
            encrypted_password=self.encrypt_data(payment_password, device_id)
        )
        
        return Response({
            'status': 'success',
            'message': '支付密码设置成功'
        })

    @action(detail=False, methods=['get'], url_path='payment_password/status/(?P<device_id>[^/.]+)')
    def payment_password_status(self, request, device_id=None):
        """查询支付密码状态"""
        try:
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            payment_password = PaymentPassword.objects.filter(device_id=device_id).first()
            return Response({
                'status': 'success',
                'data': {
                    'has_payment_password': payment_password is not None,
                    'device_id': device_id
                }
            })
        except Exception as e:
            logger.error(f"查询支付密码状态失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'查询支付密码状态失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def verify_password(self, request):
        """验证支付密码"""
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        if not all([device_id, payment_password]):
            return Response({'error': '缺少必要参数'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            payment_password_obj = PaymentPassword.objects.get(device_id=device_id)
        except PaymentPassword.DoesNotExist:
            return Response({'error': '未设置支付密码'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证密码
        if not payment_password_obj.verify_password(payment_password):
            return Response({'error': '支付密码错误'}, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({'message': '支付密码验证成功'})

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """修改支付密码"""
        device_id = request.data.get('device_id')
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')
        
        if not all([device_id, old_password, new_password, confirm_password]):
            return Response({'error': '缺少必要参数'}, status=status.HTTP_400_BAD_REQUEST)
        
        if new_password != confirm_password:
            return Response({'error': '两次输入的新密码不一致'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            payment_password = PaymentPassword.objects.get(device_id=device_id)
        except PaymentPassword.DoesNotExist:
            return Response({'error': '未设置支付密码'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证旧密码
        if not payment_password.verify_password(old_password):
            return Response({'error': '旧密码错误'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 更新密码
        payment_password.set_password(new_password)
        payment_password.save()
        
        return Response({'message': '支付密码修改成功'})

    @action(detail=False, methods=['get'])
    def get_supported_chains(self, request):
        """获取支持的链列表"""
        try:
            supported_chains = {
                "ETH": {
                    "chain_id": "ETH",
                    "name": "Ethereum",
                    "symbol": "ETH",
                    "network": "Mainnet",
                    "status": "active",
                    "logo": "https://assets.coingecko.com/coins/images/279/large/ethereum.png"
                },
                "BASE": {
                    "chain_id": "BASE",
                    "name": "Base",
                    "symbol": "ETH",
                    "network": "Mainnet",
                    "status": "active",
                    "logo": "https://cdn.bitkeep.vip/operation/u_b_52a61660-82d7-11ee-beed-414173dd7838.png"
                },
                "SOL": {
                    "chain_id": "SOL",
                    "name": "Solana",
                    "symbol": "SOL",
                    "network": "Mainnet",
                    "status": "active",
                    "logo": "https://assets.coingecko.com/coins/images/4128/large/solana.png"
                }
            }
            
            return Response({
                'status': 'success',
                'message': '获取支持的链列表成功',
                'data': {
                    'supported_chains': supported_chains
                }
            })
            
        except Exception as e:
            logger.error(f"获取支持的链列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取支持的链列表失败: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['post'])
    def select_chain(self, request):
        """选择链"""
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        device_id = serializer.validated_data['device_id']
        chain = serializer.validated_data['chain']
        
        # 验证链是否支持
        supported_chains = {
            'ETH': {
                'name': 'Ethereum',
                'symbol': 'ETH',
                'network': 'Mainnet',
                'status': 'active'
            },
            'BSC': {
                'name': 'BNB Chain',
                'symbol': 'BNB',
                'network': 'Mainnet',
                'status': 'active'
            },
            'MATIC': {
                'name': 'Polygon',
                'symbol': 'MATIC',
                'network': 'Mainnet',
                'status': 'active'
            },
            'AVAX': {
                'name': 'Avalanche',
                'symbol': 'AVAX',
                'network': 'Mainnet',
                'status': 'active'
            },
            'BASE': {
                'name': 'Base',
                'symbol': 'ETH',
                'network': 'Mainnet',
                'status': 'active'
            },
            'ARBITRUM': {
                'name': 'Arbitrum',
                'symbol': 'ETH',
                'network': 'Mainnet',
                'status': 'active'
            },
            'OPTIMISM': {
                'name': 'Optimism',
                'symbol': 'ETH',
                'network': 'Mainnet',
                'status': 'active'
            },
            'SOL': {
                'name': 'Solana',
                'symbol': 'SOL',
                'network': 'Mainnet',
                'status': 'active'
            },
            'BTC': {
                'name': 'Bitcoin',
                'symbol': 'BTC',
                'network': 'Mainnet',
                'status': 'coming_soon'
            }
        }
        
        if chain not in supported_chains:
            return Response({
                'status': 'error',
                'message': '不支持的链类型'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if supported_chains[chain]['status'] == 'coming_soon':
            return Response({
                'status': 'error',
                'message': f"{supported_chains[chain]['name']} 即将支持"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 生成助记词
        mnemonic = Mnemonic("english").generate(strength=128)
        
        return Response({
            'status': 'success',
            'message': '链选择成功',
            'data': {
                'chain': chain,
                'chain_info': supported_chains[chain],
                'mnemonic': mnemonic
            }
        })

    def create(self, request, *args, **kwargs):
        """创建钱包"""
        serializer = WalletCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        device_id = serializer.validated_data['device_id']
        chain = serializer.validated_data['chain']
        payment_password = serializer.validated_data['payment_password']
        
        # 验证设备ID
        if not validate_device_id(device_id):
            return Response({
                'status': 'error',
                'message': '无效的设备ID'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 验证支付密码
        if not validate_payment_password(payment_password):
            return Response({
                'status': 'error',
                'message': '支付密码格式错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 生成助记词
            mnemonic = generate_mnemonic()
            
            # 创建HD钱包
            hd_wallet = HDWallet(symbol=chain)
            hd_wallet.from_mnemonic(mnemonic=mnemonic)
            
            # 获取第一个账户
            hd_wallet.from_path("m/44'/60'/0'/0/0")
            
            # 生成随机头像
            from ..serializers import generate_avatar
            avatar_image = generate_avatar()
            avatar_io = BytesIO()
            avatar_image.save(avatar_io, format='PNG')
            avatar_file = ContentFile(avatar_io.getvalue())
            
            # 创建钱包记录
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=f"Wallet {Wallet.objects.filter(device_id=device_id).count() + 1}",
                chain=chain,
                address=hd_wallet.address(),
                encrypted_private_key=encrypt_string(hd_wallet.private_key()),
                is_active=True,
                is_watch_only=False,
                is_imported=False
            )
            
            # 保存头像
            wallet.avatar.save(f'wallet_avatar_{wallet.pk}.png', avatar_file, save=True)
            
            # 创建支付密码
            PaymentPassword.objects.create(
                device_id=device_id,
                encrypted_password=encrypt_string(payment_password)
            )
            
            return Response({
                'status': 'success',
                'message': '钱包创建成功',
                'data': {
                    'wallet': WalletSerializer(wallet).data,
                    'mnemonic': mnemonic  # 返回助记词给用户
                }
            })
            
        except Exception as e:
            logger.error(f"创建钱包失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '创建钱包失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        try:
            PaymentPassword.objects.get(device_id=device_id, password=payment_password)
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        try:
            PaymentPassword.objects.get(device_id=device_id, password=payment_password)
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        instance.is_active = False
        instance.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def rename_wallet(self, request, pk=None):
        """重命名钱包"""
        try:
            wallet = Wallet.objects.get(pk=pk, is_active=True)
        except Wallet.DoesNotExist:
            return Response({
                'status': 'error',
                'message': f'找不到ID为{pk}的钱包'
            }, status=status.HTTP_404_NOT_FOUND)
            
        device_id = request.data.get('device_id')
        new_name = request.data.get('new_name')
        
        if not all([device_id, new_name]):
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 验证钱包所属权
        if wallet.device_id != device_id:
            return Response({
                'status': 'error',
                'message': '无权操作此钱包'
            }, status=status.HTTP_403_FORBIDDEN)
            
        # 更新钱包名称
        wallet.name = new_name
        wallet.save()
        
        return Response({
            'status': 'success',
            'message': '钱包重命名成功',
            'wallet': WalletSerializer(wallet).data
        })

    @action(detail=True, methods=['post'])
    def delete_wallet(self, request, pk=None):
        """删除钱包"""
        try:
            wallet = Wallet.objects.get(pk=pk, is_active=True)
        except Wallet.DoesNotExist:
            return Response({
                'status': 'error',
                'message': f'找不到ID为{pk}的钱包'
            }, status=status.HTTP_404_NOT_FOUND)
            
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        if not all([device_id, payment_password]):
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 验证支付密码
        try:
            payment_pwd = PaymentPassword.objects.get(device_id=device_id)
            if not payment_pwd.verify_password(payment_password):
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '设备未设置支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 验证钱包所属权
        if wallet.device_id != device_id:
            return Response({
                'status': 'error',
                'message': '无权操作此钱包'
            }, status=status.HTTP_403_FORBIDDEN)
            
        # 软删除钱包
        wallet.is_active = False
        wallet.save()
        
        return Response({
            'status': 'success',
            'message': '钱包删除成功'
        })

    @action(detail=False, methods=['post'])
    def import_private_key(self, request):
        """导入私钥"""
        try:
            device_id = request.data.get('device_id')
            private_key = request.data.get('private_key')
            chain = request.data.get('chain')
            payment_password = request.data.get('payment_password')
            name = request.data.get('name')
            
            if not all([device_id, private_key, chain, payment_password]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)
            
            # 验证支付密码
            try:
                payment_pwd = PaymentPassword.objects.get(device_id=device_id)
                if not payment_pwd.verify_password(payment_password):
                    return Response({
                        'status': 'error',
                        'message': '支付密码错误'
                    }, status=400)
            except PaymentPassword.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': '请先设置支付密码'
                }, status=400)
            
            # 根据链类型处理私钥
            if chain == 'SOL':
                try:
                    # 尝试解码 Base58
                    private_key_bytes = base58.b58decode(private_key)
                    
                    # 处理不同长度的私钥
                    if len(private_key_bytes) == 88:
                        # 88字节格式：提取前32字节作为私钥
                        private_key_bytes = private_key_bytes[:32]
                    elif len(private_key_bytes) == 64:
                        # 64字节格式：使用前32字节作为私钥
                        private_key_bytes = private_key_bytes[:32]
                    elif len(private_key_bytes) == 32:
                        # 32字节格式：直接使用
                        pass
                    else:
                        return Response({
                            'status': 'error',
                            'message': f'无效的 Solana 私钥长度: {len(private_key_bytes)}'
                        }, status=400)
                    
                    # 创建 Solana 钱包
                    keypair = Keypair.from_secret_key(private_key_bytes)
                    address = str(keypair.public_key)
                    
                    # 加密私钥
                    key_bytes = hashlib.sha256(payment_password.encode()).digest()
                    f = Fernet(base64.urlsafe_b64encode(key_bytes))
                    encrypted = f.encrypt(private_key_bytes)
                    encrypted_private_key = base64.b64encode(encrypted).decode('utf-8')
                    
                except Exception as e:
                    return Response({
                        'status': 'error',
                        'message': f'无效的 Solana 私钥格式: {str(e)}'
                    }, status=400)
            else:
                try:
                    # 移除可能的 0x 前缀
                    private_key_str = private_key[2:] if private_key.startswith('0x') else private_key
                    # 转换为字节
                    private_key_bytes = bytes.fromhex(private_key_str)
                    if len(private_key_bytes) != 32:
                        return Response({
                            'status': 'error',
                            'message': '无效的私钥长度'
                        }, status=400)
                    
                    # 创建 EVM 钱包
                    account = Account.from_key(private_key_bytes)
                    address = account.address
                    
                    # 加密私钥
                    key_bytes = hashlib.sha256(payment_password.encode()).digest()
                    f = Fernet(base64.urlsafe_b64encode(key_bytes))
                    encrypted = f.encrypt(private_key_bytes)
                    encrypted_private_key = base64.b64encode(encrypted).decode('utf-8')
                    
                except Exception as e:
                    return Response({
                        'status': 'error',
                        'message': f'无效的私钥格式: {str(e)}'
                    }, status=400)
            
            # 检查钱包是否已存在
            existing_wallet = Wallet.objects.filter(
                device_id=device_id,
                address=address
            ).first()
            
            if existing_wallet:
                if existing_wallet.is_active:
                    return Response({
                        'status': 'error',
                        'message': '钱包已存在且处于激活状态'
                    }, status=400)
                else:
                    # 如果钱包存在但已被删除，重新激活它
                    existing_wallet.is_active = True
                    existing_wallet.encrypted_private_key = encrypted_private_key
                    if name:
                        existing_wallet.name = name
                    existing_wallet.save()
                    return Response({
                        'status': 'success',
                        'message': '钱包已重新激活',
                        'data': {
                            'wallet_id': existing_wallet.id,
                            'address': address,
                            'chain': chain
                        }
                    })
            
            # 生成随机头像
            try:
                from ..serializers import generate_avatar
                avatar_image = generate_avatar()
                avatar_io = BytesIO()
                avatar_image.save(avatar_io, format='PNG')
                avatar_content = avatar_io.getvalue()
            except Exception as e:
                logger.error(f"生成头像失败: {str(e)}")
                raise
            
            # 如果未提供名称，生成默认名称
            if not name:
                existing_wallets_count = Wallet.objects.filter(
                    device_id=device_id,
                    chain=chain,
                    is_active=True
                ).count()
                name = f"{chain} Wallet {existing_wallets_count + 1}"
            
            # 创建钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=name,
                chain=chain,
                address=address,
                encrypted_private_key=encrypted_private_key,
                is_imported=True
            )
            
            # 保存头像
            wallet.avatar.save(f'wallet_avatar_{wallet.pk}.png', ContentFile(avatar_content), save=True)
            
            return Response({
                'status': 'success',
                'message': '导入钱包成功',
                'data': {
                    'wallet_id': wallet.id,
                    'address': address,
                    'chain': chain
                }
            })
            
        except Exception as e:
            logger.error(f"导入钱包失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'导入钱包失败: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['post'])
    def import_watch_only(self, request):
        """导入观察者钱包"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        address = request.data.get('address')
        name = request.data.get('name')
        
        if not all([device_id, chain, address]):
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # 验证地址格式
            if chain in ["ETH", "BASE", "BNB", "MATIC", "AVAX", "ARBITRUM", "OPTIMISM"]:
                from eth_utils import is_address
                if not is_address(address):
                    return Response({
                        'status': 'error',
                        'message': f'无效的{chain}地址'
                    }, status=status.HTTP_400_BAD_REQUEST)
                # 转换为校验和地址
                from web3 import Web3
                address = Web3.to_checksum_address(address)
                
            elif chain == "SOL":
                from solana.publickey import PublicKey
                try:
                    PublicKey(address)
                except:
                    return Response({
                        'status': 'error',
                        'message': '无效的Solana地址'
                    }, status=status.HTTP_400_BAD_REQUEST)
                    
            elif chain == "BTC":
                # TODO: 添加比特币地址验证
                return Response({
                    'status': 'error',
                    'message': 'BTC 导入功能即将支持'
                }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            # 检查钱包是否已存在（包括非活跃的）
            existing_wallet = Wallet.objects.filter(
                device_id=device_id,
                chain=chain,
                address=address
            ).first()
            
            if existing_wallet:
                if existing_wallet.is_active:
                    return Response({
                        'status': 'error',
                        'message': '该钱包已存在'
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    # 如果钱包存在但被软删除，重新激活它
                    existing_wallet.is_active = True
                    existing_wallet.is_watch_only = True
                    existing_wallet.is_imported = True
                    if name:  # 如果提供了新名称，更新名称
                        existing_wallet.name = name
                    existing_wallet.save()
                    return Response({
                        'status': 'success',
                        'message': '观察者钱包已重新激活',
                        'wallet': WalletSerializer(existing_wallet).data
                    })
                
            # 生成随机头像
            from ..serializers import generate_avatar
            avatar_image = generate_avatar()
            avatar_io = BytesIO()
            avatar_image.save(avatar_io, format='PNG')
            avatar_file = ContentFile(avatar_io.getvalue())
            
            # 如果未提供名称，生成默认名称
            if not name:
                existing_wallets_count = Wallet.objects.filter(
                    device_id=device_id,
                    chain=chain,
                    is_active=True
                ).count()
                name = f"Watch {chain} Wallet {existing_wallets_count + 1}"
            
            # 创建观察者钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=name,
                chain=chain,
                address=address,
                is_watch_only=True,
                is_imported=True
            )
            
            # 保存头像
            wallet.avatar.save(f'wallet_avatar_{wallet.pk}.png', avatar_file, save=True)
            
            return Response({
                'status': 'success',
                'message': '观察者钱包导入成功',
                'wallet': WalletSerializer(wallet).data
            })
            
        except Exception as e:
            logger.error(f"导入观察者钱包失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '导入观察者钱包失败，该钱包可能已存在'
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def show_private_key(self, request, pk=None):
        """显示私钥"""
        try:
            # 获取钱包
            wallet = self.get_object()
            
            # 获取设备ID和支付密码
            device_id = request.data.get('device_id')
            payment_password = request.data.get('payment_password')
            
            # 验证设备ID
            if not device_id or not wallet.check_device_id(device_id):
                return Response({
                    'status': 'error',
                    'message': '设备ID不匹配'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 验证支付密码
            if not payment_password:
                return Response({
                    'status': 'error',
                    'message': '请提供支付密码'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            payment_pwd = PaymentPassword.objects.filter(device_id=device_id).first()
            if not payment_pwd or not payment_pwd.verify_password(payment_password):
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 设置支付密码
            wallet.payment_password = payment_password
            
            # 解密私钥
            private_key = wallet.decrypt_private_key()
            
            # 根据链类型处理私钥
            if wallet.chain == 'SOL':
                # Solana 私钥处理
                if isinstance(private_key, bytes):
                    # 如果是 32 字节格式，需要转换为 88 字节格式
                    if len(private_key) == 32:
                        # 创建 Keypair 以获取完整的私钥
                        keypair = Keypair.from_secret_key(private_key)
                        private_key = keypair.secret_key
                    # 使用 Base58 编码
                    private_key = base58.b58encode(private_key).decode('ascii')
                elif isinstance(private_key, str):
                    # 如果已经是字符串，确保是 Base58 格式
                    try:
                        # 验证是否是有效的 Base58 格式
                        decoded = base58.b58decode(private_key)
                        if len(decoded) == 32:
                            # 如果是 32 字节的 Base58 编码，转换为 88 字节格式
                            keypair = Keypair.from_secret_key(decoded)
                            private_key = base58.b58encode(keypair.secret_key).decode('ascii')
                        elif len(decoded) == 88:
                            # 如果是 88 字节的 Base58 编码，直接使用
                            pass
                    except:
                        # 如果不是 Base58 格式，尝试其他格式
                        pass
            else:
                # EVM 链私钥处理
                if isinstance(private_key, bytes):
                    private_key = '0x' + private_key.hex()
                elif isinstance(private_key, str):
                    if not private_key.startswith('0x'):
                        private_key = '0x' + private_key
            
            return Response({
                'status': 'success',
                'message': '获取私钥成功',
                'data': {
                    'private_key': private_key,
                    'chain': wallet.chain,
                    'address': wallet.address
                }
            })
            
        except Exception as e:
            logger.error(f"显示私钥失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def list_all(self, request):
        """列出所有钱包，包括非活动的"""
        device_id = request.query_params.get('device_id')
        if not device_id:
            return Response({
                'status': 'error',
                'message': '缺少设备ID'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 获取所有钱包，包括非活动的
        wallets = Wallet.objects.filter(device_id=device_id)
        serializer = self.get_serializer(wallets, many=True)
        
        return Response({
            'status': 'success',
            'wallets': serializer.data
        })

    @action(detail=False, methods=['post'])
    def import_wallet(self, request):
        """导入钱包"""
        try:
            device_id = request.data.get('device_id')
            name = request.data.get('name')
            chain = request.data.get('chain')
            private_key = request.data.get('private_key')
            payment_password = request.data.get('payment_password')
            
            # 验证参数
            validate_device_id(device_id)
            validate_payment_password(payment_password)
            
            if not name:
                raise WalletError('钱包名称不能为空')
            
            if not chain or chain not in dict(Chain.CHOICES):
                raise WalletError('无效的区块链类型')
            
            if not private_key:
                raise WalletError('私钥不能为空')
            
            # 检查是否已存在相同设备ID的钱包
            if Wallet.objects.filter(device_id=device_id).exists():
                raise WalletError('该设备已创建过钱包')
            
            # 导入钱包
            with transaction.atomic():
                # 创建支付密码
                payment_password_obj = PaymentPassword.objects.create(
                    device_id=device_id,
                    encrypted_password=encrypt_string(payment_password)
                )
                
                # 获取地址
                service = ChainServiceFactory.get_service(chain, 'wallet')
                address = service.get_address_from_private_key(private_key)
                
                # 创建钱包
                wallet = Wallet.objects.create(
                    device_id=device_id,
                    name=name,
                    chain=chain,
                    address=address,
                    encrypted_private_key=encrypt_string(private_key)
                )
                
                # 返回结果
                serializer = self.get_serializer(wallet)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
                
        except WalletError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"导入钱包失败: {str(e)}")
            return Response({'error': '导入钱包失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def export_wallet(self, request, pk=None):
        """导出钱包"""
        try:
            wallet = self.get_object()
            payment_password = request.data.get('payment_password')
            
            # 验证支付密码
            if not wallet.check_payment_password(payment_password):
                raise WalletError('支付密码错误')
            
            # 解密私钥
            private_key = wallet.decrypt_private_key()
            
            return Response({
                'private_key': private_key
            })
            
        except WalletError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"导出钱包失败: {str(e)}")
            return Response({'error': '导出钱包失败'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)