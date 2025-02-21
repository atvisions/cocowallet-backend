from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
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

from ..models import Wallet, PaymentPassword
from ..serializers import (
    WalletSerializer, 
    WalletCreateSerializer,
    WalletSetupSerializer,
    ChainSelectionSerializer # type: ignore
)
from ..decorators import verify_payment_password

logger = logging.getLogger(__name__)

class WalletViewSet(viewsets.ModelViewSet):
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
            logger.debug(f"开始加密数据，输入数据类型: {type(data)}")
            
            # 确保输入数据是字符串类型
            if not isinstance(data, str):
                data = str(data)
            
            # 确保密钥是字符串类型
            if not isinstance(key, str):
                key = str(key)
            
            logger.debug(f"处理后的数据长度: {len(data)}, 密钥长度: {len(key)}")
            
            # 使用 SHA256 生成固定长度的密钥
            key_bytes = hashlib.sha256(key.encode()).digest()
            f = Fernet(base64.urlsafe_b64encode(key_bytes))
            
            # 加密数据
            encrypted = f.encrypt(data.encode())
            result = base64.b64encode(encrypted).decode('utf-8')
            
            logger.debug(f"加密完成，结果长度: {len(result)}")
            return result
                
        except Exception as e:
            logger.error(f"加密数据失败: {str(e)}, 数据类型: {type(data)}")
            raise ValueError(f"加密失败: {str(e)}")

    def decrypt_data(self, encrypted_text, key):
        """使用 Fernet 解密数据"""
        try:
            logger.debug(f"开始解密数据，加密文本长度: {len(encrypted_text)}")
            
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
                result = decrypted.decode('utf-8')
                
                logger.debug(f"解密完成，结果长度: {len(result)}")
                return result
                
            except Exception as e:
                logger.error(f"解密失败: {str(e)}")
                raise ValueError(f"解密失败: {str(e)}")
                
        except Exception as e:
            logger.error(f"解密数据失败: {str(e)}")
            raise ValueError(f"解密失败: {str(e)}")

    @action(detail=False, methods=['post'])
    def set_password(self, request):
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

    @action(detail=False, methods=['post'])
    def select_chain(self, request):
        """选择链
        
        支持的链:
        1. ETH (Ethereum) - 以太坊主网
        2. BSC (BNB Chain) - 币安智能链
        3. MATIC (Polygon) - Polygon主网
        4. AVAX (Avalanche) - Avalanche C-Chain
        5. BASE (Base) - Base主网
        6. ARBITRUM (Arbitrum) - Arbitrum One
        7. OPTIMISM (Optimism) - Optimism主网
        8. SOL (Solana) - Solana主网
        9. BTC (Bitcoin) - 比特币主网 (即将支持)
        """
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
        mnemonic = generate_mnemonic(language="english", strength=128)
        
        return Response({
            'status': 'success',
            'message': '链选择成功',
            'data': {
                'chain': chain,
                'chain_info': supported_chains[chain],
                'mnemonic': mnemonic
            }
        })

    @action(detail=False, methods=['post'])
    def generate_mnemonic(self, request):
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        if not device_id or not payment_password:
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 验证支付密码
        try:
            PaymentPassword.objects.get(device_id=device_id, password=payment_password)
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 生成助记词
        mnemonic = generate_mnemonic(language="english", strength=128)
        encrypted_mnemonic = self.encrypt_data(mnemonic, payment_password)
        
        return Response({
            'status': 'success',
            'mnemonic': mnemonic,
            'encrypted_mnemonic': encrypted_mnemonic
        })

    @action(detail=False, methods=['post'])
    def verify_mnemonic(self, request):
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        mnemonic = request.data.get('mnemonic')
        
        if not all([device_id, chain, mnemonic]):
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证助记词格式
        if not Mnemonic("english").check(mnemonic):
            return Response({
                'status': 'error',
                'message': '助记词格式错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 获取或创建支付密码
            payment_pwd, created = PaymentPassword.objects.get_or_create(
                device_id=device_id,
                defaults={'encrypted_password': self.encrypt_data('123456', device_id)}
            )
            
            # 创建 HD 钱包
            hdwallet = HDWallet()
            hdwallet.from_mnemonic(mnemonic)
            
            # 根据不同链设置路径和获取地址
            if chain in ["ETH", "BSC", "MATIC", "AVAX", "BASE", "ARBITRUM", "OPTIMISM"]:
                # 使用 BIP44 路径生成 EVM 链钱包
                hdwallet.from_path("m/44'/60'/0'/0/0")
                private_key = hdwallet.private_key()
                # 确保私钥是32字节
                private_key_bytes = bytes.fromhex(private_key)
                if len(private_key_bytes) != 32:
                    logger.error(f"生成的私钥长度不正确: {len(private_key_bytes)}字节")
                    raise ValueError(f"生成的私钥长度不正确: {len(private_key_bytes)}字节")
                # 使用 web3.eth.account 来生成地址
                account = Account.from_key(private_key_bytes)
                address = account.address
                # 存储十六进制格式的私钥
                private_key_to_store = '0x' + private_key_bytes.hex()
            elif chain == "SOL":
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
                
                # 创建88字节格式的私钥（32字节私钥 + 32字节公钥 + 24字节额外数据）
                public_key_bytes = bytes(keypair.public_key)
                extra_bytes = bytes([0] * 24)  # 24字节的额外数据
                extended_key = private_key_bytes + public_key_bytes + extra_bytes
                
                # 将完整的88字节数据转换为Base58格式存储
                private_key_to_store = b58encode(extended_key).decode()
            else:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 检查是否已存在相同地址的钱包
            existing_wallet = Wallet.objects.filter(
                device_id=device_id,
                chain=chain,
                address=address
            ).first()
            
            if existing_wallet:
                if existing_wallet.is_active:
                    return Response({
                        'status': 'error',
                        'message': '该钱包已存在且处于激活状态'
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    # 如果钱包存在但已被删除，重新激活它
                    existing_wallet.is_active = True
                    decrypted_password = self.decrypt_data(payment_pwd.encrypted_password, device_id)
                    # 确保 decrypted_password 是字符串类型
                    if isinstance(decrypted_password, bytes):
                        decrypted_password = decrypted_password.decode('utf-8')
                    existing_wallet.encrypted_private_key = self.encrypt_data(private_key_to_store, decrypted_password)
                    existing_wallet.save()
                    return Response({
                        'status': 'success',
                        'wallet': WalletSerializer(existing_wallet).data
                    })
            
            # 生成随机头像
            from ..serializers import generate_avatar
            avatar_image = generate_avatar()
            avatar_io = BytesIO()
            avatar_image.save(avatar_io, format='PNG')
            avatar_file = ContentFile(avatar_io.getvalue())
            
            # 使用支付密码加密私钥
            decrypted_password = self.decrypt_data(payment_pwd.encrypted_password, device_id)
            # 确保 decrypted_password 是字符串类型
            if isinstance(decrypted_password, bytes):
                decrypted_password = decrypted_password.decode('utf-8')
            
            # 创建钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=f"{chain} Wallet 1",
                chain=chain,
                address=address,
                encrypted_private_key=self.encrypt_data(private_key_to_store, decrypted_password)
            )
            
            # 保存头像
            wallet.avatar.save(f'wallet_avatar_{wallet.pk}.png', avatar_file, save=True)
            
            return Response({
                'status': 'success',
                'wallet': WalletSerializer(wallet).data
            })
            
        except Exception as e:
            logger.error(f"创建钱包失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'创建钱包失败: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        device_id = serializer.validated_data['device_id']
        payment_password = serializer.validated_data['payment_password']
        
        try:
            PaymentPassword.objects.get(device_id=device_id, password=payment_password)
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

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

    @action(detail=False, methods=['post'], url_path='verify_password')
    def verify_password(self, request):
        """验证支付密码"""
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        if not device_id or not payment_password:
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 获取支付密码记录
            payment_pwd = PaymentPassword.objects.filter(device_id=device_id).first()
            if not payment_pwd:
                return Response({
                    'status': 'error',
                    'message': '设备未设置支付密码'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 验证密码
            if payment_pwd.verify_password(payment_password):
                return Response({
                    'status': 'success',
                    'message': '支付密码验证成功'
                })
            else:
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'验证支付密码失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'payment_password/status/(?P<device_id>[^/.]+)')  # 修改URL路径格式
    def payment_password_status(self, request, device_id=None):  # 添加device_id参数
        """查询支付密码状态"""
        try:
            if not device_id:  # 使用URL路径中的device_id
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
    def verify_old_password(self, request):
        """验证旧密码"""
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        if not device_id or not payment_password:
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 获取支付密码记录
            payment_pwd = PaymentPassword.objects.filter(device_id=device_id).first()
            if not payment_pwd:
                return Response({
                    'status': 'error',
                    'message': '设备未设置支付密码'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 验证密码
            is_valid = payment_pwd.verify_password(payment_password)
            
            return Response({
                'status': 'success',
                'data': {
                    'is_valid': is_valid
                }
            })
            
        except Exception as e:
            logger.error(f"验证旧密码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'验证旧密码失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """修改支付密码"""
        device_id = request.data.get('device_id')
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')
        
        if not all([device_id, old_password, new_password, confirm_password]):
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if new_password != confirm_password:
            return Response({
                'status': 'error',
                'message': '新密码和确认密码不一致'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        if not re.match(r'^\d{6}$', new_password):
            return Response({
                'status': 'error',
                'message': '新密码必须是6位数字'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # 验证旧密码
            payment_password = PaymentPassword.objects.get(device_id=device_id)
            if not payment_password.verify_password(old_password):
                logger.error(f"旧密码验证失败，设备ID: {device_id}")
                return Response({
                    'status': 'error',
                    'message': '旧密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 更新密码
            payment_password.encrypted_password = self.encrypt_data(new_password, device_id)
            payment_password.save()
            
            # 重新加密所有钱包的私钥
            wallets = Wallet.objects.filter(device_id=device_id, is_active=True)
            for wallet in wallets:
                try:
                    # 使用旧密码解密私钥
                    decrypted_key = self.decrypt_data(wallet.encrypted_private_key, old_password)
                    # 使用新密码加密私钥
                    wallet.encrypted_private_key = self.encrypt_data(decrypted_key, new_password)
                    wallet.save()
                except Exception as e:
                    logger.error(f"重新加密钱包私钥失败: {str(e)}")
            
            return Response({
                'status': 'success',
                'message': '支付密码修改成功'
            })
            
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '设备未设置支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"修改密码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'修改密码失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        """通过私钥导入钱包"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        private_key = request.data.get('private_key')
        name = request.data.get('name')
        payment_password = request.data.get('payment_password')
        
        if not all([device_id, chain, private_key, payment_password]):
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 获取支付密码
        payment_pwd = PaymentPassword.objects.filter(device_id=device_id).first()
        if not payment_pwd:
            return Response({
                'status': 'error',
                'message': '未设置支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 验证密码
        if not payment_pwd.verify_password(payment_password):
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # 根据不同链处理私钥
            if chain in ["ETH", "BASE", "BNB", "MATIC", "AVAX", "ARBITRUM", "OPTIMISM"]:
                # 所有 EVM 兼容链使用相同的私钥处理逻辑
                # 移除0x前缀（如果有）
                private_key_str = private_key[2:] if private_key.startswith('0x') else private_key
                # 移除所有非十六进制字符
                private_key_str = ''.join(c for c in private_key_str if c in '0123456789abcdefABCDEF')
                # 确保私钥长度为64个字符（32字节）
                if len(private_key_str) < 64:
                    private_key_str = private_key_str.zfill(64)
                elif len(private_key_str) > 64:
                    raise ValueError('私钥长度超过64个字符')
                
                # 验证私钥是否有效
                try:
                    account = Account.from_key('0x' + private_key_str)
                    address = account.address
                except Exception as e:
                    raise ValueError(f'无效的私钥: {str(e)}')
                
                # 转换为字节类型存储
                private_key_to_store = bytes.fromhex(private_key_str)
                
            elif chain == "SOL":
                try:
                    # 尝试解码 Base58 格式的私钥
                    private_key_bytes = b58decode(private_key)
                    
                    # 如果是88字节的扩展格式，提取前64字节
                    if len(private_key_bytes) == 88:
                        keypair_bytes = private_key_bytes[:64]
                    # 如果已经是64字节的格式，直接使用
                    elif len(private_key_bytes) == 64:
                        keypair_bytes = private_key_bytes
                    # 如果是32字节的私钥，创建完整的密钥对
                    elif len(private_key_bytes) == 32:
                        keypair = Keypair.from_seed(private_key_bytes)
                        keypair_bytes = keypair.seed + bytes(keypair.public_key)
                    else:
                        raise ValueError(f"无效的私钥长度: {len(private_key_bytes)}")
                    
                    # 验证生成的地址
                    keypair = Keypair.from_seed(keypair_bytes[:32])
                    address = str(keypair.public_key)
                    logger.debug(f"生成的地址: {address}")
                    
                    # 创建88字节格式的私钥（32字节私钥 + 32字节公钥 + 24字节额外数据）
                    public_key_bytes = bytes(keypair.public_key)
                    extra_bytes = bytes([0] * 24)  # 24字节的额外数据
                    private_key_to_store = keypair_bytes[:32] + public_key_bytes + extra_bytes
                    
                    # 将完整的88字节数据转换为Base58格式存储
                    private_key_to_store = b58encode(private_key_to_store).decode()
                    
                except Exception as e:
                    logger.error(f"处理Solana私钥失败: {str(e)}")
                    raise ValueError(f"无效的Solana私钥: {str(e)}")
            elif chain == "BTC":
                # TODO: 添加比特币私钥导入支持
                return Response({
                    'status': 'error',
                    'message': 'BTC 导入功能即将支持'
                }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            # 检查钱包是否已存在
            existing_wallet = Wallet.objects.filter(
                device_id=device_id,
                chain=chain,
                address=address
            ).first()
            
            if existing_wallet:
                if existing_wallet.is_active:
                    return Response({
                        'status': 'error',
                        'message': '该钱包已存在且处于激活状态'
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    # 如果钱包存在但已被删除，重新激活它
                    existing_wallet.is_active = True
                    decrypted_password = self.decrypt_data(payment_pwd.encrypted_password, device_id)
                    existing_wallet.encrypted_private_key = self.encrypt_data(private_key_to_store, decrypted_password)
                    existing_wallet.save()
                    return Response({
                        'status': 'success',
                        'message': '钱包已重新激活',
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
                existing_wallets = Wallet.objects.filter(
                    device_id=device_id,
                    chain=chain,
                    is_active=True
                ).count()
                name = f"Imported {chain} Wallet {existing_wallets + 1}"
            
            # 创建钱包
            decrypted_password = self.decrypt_data(payment_pwd.encrypted_password, device_id)
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=name,
                chain=chain,
                address=address,
                encrypted_private_key=self.encrypt_data(str(private_key_to_store), decrypted_password),
                is_imported=True
            )
            
            # 保存头像
            wallet.avatar.save(f'wallet_avatar_{wallet.pk}.png', avatar_file, save=True)
            
            return Response({
                'status': 'success',
                'message': '钱包导入成功',
                'wallet': WalletSerializer(wallet).data
            })
            
        except Exception as e:
            logger.error(f"导入私钥失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'导入私钥失败: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)

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
        """显示钱包私钥"""
        try:
            # 获取钱包
            wallet = self.get_object()
            
            # 验证设备ID
            device_id = request.data.get('device_id')
            if not device_id or device_id != wallet.device_id:
                return Response({
                    'status': 'error',
                    'message': '设备ID不匹配'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 验证支付密码
            payment_password = request.data.get('payment_password')
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
            
            # 设置支付密码用于解密
            wallet.payment_password = payment_password
            
            # 解密私钥
            private_key = wallet.decrypt_private_key()
            
            # 如果返回的是字节类型，则需要转换
            if isinstance(private_key, bytes):
                if wallet.chain == 'SOL':
                    # Solana 使用 Base58 格式
                    private_key = base58.b58encode(private_key).decode('ascii')
                else:
                    # 其他链使用十六进制格式
                    private_key = private_key.hex()
            
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

    @action(detail=False, methods=['get'])
    def get_supported_chains(self, request):
        """获取支持的链列表
        
        Returns:
            {
                'status': 'success',
                'message': '获取支持的链列表成功',
                'data': {
                    'supported_chains': {
                        'ETH': {
                            'chain_id': 'ETH',  # 前端选择链时应该使用的标识符
                            'name': 'Ethereum',
                            'symbol': 'ETH',
                            'network': 'Mainnet',
                            'status': 'active',
                            'logo': 'https://assets.coingecko.com/coins/images/279/large/ethereum.png'
                        },
                        ...
                    }
                }
            }
        """
        try:
            supported_chains = {
                'ETH': {
                    'chain_id': 'ETH',  # 添加 chain_id 字段
                    'name': 'Ethereum',
                    'symbol': 'ETH',
                    'network': 'Mainnet',
                    'status': 'active',
                    'logo': 'https://assets.coingecko.com/coins/images/279/large/ethereum.png'
                },
                'BSC': {
                    'chain_id': 'BSC',
                    'name': 'BNB Chain',
                    'symbol': 'BNB',
                    'network': 'Mainnet',
                    'status': 'active',
                    'logo': 'https://assets.coingecko.com/coins/images/825/large/bnb-icon2_2x.png'
                },
                'MATIC': {
                    'chain_id': 'MATIC',
                    'name': 'Polygon',
                    'symbol': 'MATIC',
                    'network': 'Mainnet',
                    'status': 'active',
                    'logo': 'https://assets.coingecko.com/coins/images/4713/large/matic-token-icon.png'
                },
                'AVAX': {
                    'chain_id': 'AVAX',
                    'name': 'Avalanche',
                    'symbol': 'AVAX',
                    'network': 'Mainnet',
                    'status': 'active',
                    'logo': 'https://assets.coingecko.com/coins/images/12559/large/Avalanche_Circle_RedWhite_Trans.png'
                },
                'BASE': {
                    'chain_id': 'BASE',
                    'name': 'Base',
                    'symbol': 'ETH',
                    'network': 'Mainnet',
                    'status': 'active',
                    'logo': 'https://cdn.bitkeep.vip/operation/u_b_52a61660-82d7-11ee-beed-414173dd7838.png'
                },
                'ARBITRUM': {
                    'chain_id': 'ARBITRUM',
                    'name': 'Arbitrum',
                    'symbol': 'ETH',
                    'network': 'Mainnet',
                    'status': 'active'
                },
                'OPTIMISM': {
                    'chain_id': 'OPTIMISM',
                    'name': 'Optimism',
                    'symbol': 'ETH',
                    'network': 'Mainnet',
                    'status': 'active'
                },
                'SOL': {
                    'chain_id': 'SOL',
                    'name': 'Solana',
                    'symbol': 'SOL',
                    'network': 'Mainnet',
                    'status': 'active'
                },
                'BTC': {
                    'chain_id': 'BTC',
                    'name': 'Bitcoin',
                    'symbol': 'BTC',
                    'network': 'Mainnet',
                    'status': 'coming_soon',
                    'logo': 'https://assets.coingecko.com/coins/images/1/large/bitcoin.png'
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
                'message': '获取支持的链列表失败',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)