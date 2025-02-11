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

from ..models import Wallet, PaymentPassword
from ..serializers import (
    WalletSerializer, 
    WalletCreateSerializer,
    WalletSetupSerializer,
    ChainSelectionSerializer # type: ignore
)

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
        """使用简单的异或加密方法，支持字符串和二进制数据"""
        try:
            logger.debug(f"加密数据类型: {type(data)}")
            logger.debug(f"加密数据长度: {len(data) if hasattr(data, '__len__') else 'unknown'}")
            key_hash = hashlib.sha256(key.encode()).digest()
            # 如果输入是字符串，转换为字节
            if isinstance(data, str):
                logger.debug("数据类型为字符串，转换为字节")
                data_bytes = data.encode()
            elif isinstance(data, bytes):
                logger.debug("数据类型为字节，直接使用")
                data_bytes = data
            else:
                logger.error(f"不支持的数据类型: {type(data)}")
                raise ValueError(f"不支持的数据类型: {type(data)}")
            encrypted = bytes(a ^ b for a, b in zip(data_bytes, key_hash * (len(data_bytes) // len(key_hash) + 1)))
            result = base64.b64encode(encrypted).decode()
            logger.debug(f"加密结果长度: {len(result)}")
            return result
        except Exception as e:
            logger.error(f"加密数据失败: {str(e)}, 数据类型: {type(data)}")
            raise ValueError("加密失败")

    def decrypt_data(self, encrypted_text, key):
        """使用简单的异或解密方法，返回字节类型"""
        try:
            key_hash = hashlib.sha256(key.encode()).digest()
            encrypted_bytes = base64.b64decode(encrypted_text)
            decrypted = bytes(a ^ b for a, b in zip(encrypted_bytes, key_hash * (len(encrypted_bytes) // len(key_hash) + 1)))
            return decrypted
        except Exception as e:
            logger.error(f"解密数据失败: {str(e)}")
            raise ValueError("解密失败")

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
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        device_id = serializer.validated_data['device_id']
        chain = serializer.validated_data['chain']
        
        # 生成助记词
        mnemonic = generate_mnemonic(language="english", strength=128)
        
        return Response({
            'status': 'success',
            'message': '链选择成功',
            'data': {
                'chain': chain,
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
            if chain == "ETH" or chain == "BASE":
                hdwallet.from_path("m/44'/60'/0'/0/0")
                address = hdwallet.public_key()
                private_key = hdwallet.private_key()
            elif chain == "SOL":
                from solana.keypair import Keypair
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.asymmetric import ed25519
                from base58 import b58encode
                
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
                private_key = b58encode(extended_key).decode()
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
                    existing_wallet.encrypted_private_key = self.encrypt_data(private_key, decrypted_password)
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
            decrypted_password = self.decrypt_data(payment_pwd.encrypted_password, device_id).decode()
            
            # 只使用32字节的私钥部分
            private_key_bytes = seed[:32]
            # 创建完整的Solana密钥对
            keypair = Keypair.from_seed(private_key_bytes)
            # 创建88字节格式的私钥（32字节私钥 + 32字节公钥 + 24字节额外数据）
            public_key_bytes = bytes(keypair.public_key)
            extra_bytes = bytes([0] * 24)  # 24字节的额外数据
            extended_key = private_key_bytes + public_key_bytes + extra_bytes
            # 将完整的88字节数据转换为Base58格式
            encrypted_private_key = self.encrypt_data(base58.b58encode(extended_key).decode(), decrypted_password)
            
            # 创建钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=f"SOL Wallet 1",  # 使用固定名称
                chain=chain,
                address=address,
                encrypted_private_key=encrypted_private_key
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

    @action(detail=False, methods=['post'])
    def verify_password(self, request):
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        
        if not device_id or not payment_password:
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            PaymentPassword.objects.get(device_id=device_id, password=payment_password)
            return Response({
                'status': 'success',
                'message': '支付密码验证成功'
            })
        except PaymentPassword.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '支付密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)

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
        payment_pwd = request.data.get('payment_password')
        
        if not all([device_id, chain, private_key, payment_pwd]):
            return Response({
                'status': 'error',
                'message': '缺少必要参数'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # 获取支付密码
        payment_password = PaymentPassword.objects.filter(device_id=device_id).first()
        if not payment_password:
            return Response({
                'status': 'error',
                'message': '未设置支付密码'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # 根据不同链处理私钥
            if chain == "ETH" or chain == "BASE":
                from eth_account import Account
                account = Account.from_key(private_key)
                address = account.address
                private_key_to_store = private_key
            elif chain == "SOL":
                from solana.keypair import Keypair
                from base58 import b58decode, b58encode
                try:
                    # 尝试Base58解码
                    private_key_bytes = b58decode(private_key)
                    # 如果是64字节的完整密钥对，直接使用
                    if len(private_key_bytes) == 64:
                        logger.debug("检测到64字节的完整密钥对，直接使用")
                        private_key_to_store = private_key  # 保持原始格式
                    elif len(private_key_bytes) == 32:
                        # 如果是32字节的私钥，创建完整的密钥对
                        logger.debug("检测到32字节的私钥，创建完整密钥对")
                        keypair = Keypair.from_seed(private_key_bytes)
                        private_key_to_store = b58encode(keypair.seed + bytes(keypair.public_key)).decode()
                    else:
                        raise ValueError("私钥长度错误")
                    logger.debug(f"存储的私钥格式: {private_key_to_store}")
                except Exception as e:
                    logger.error(f"Base58解码失败: {str(e)}")
                    # 如果不是Base58格式，尝试十六进制格式
                    try:
                        private_key_bytes = bytes.fromhex(private_key)
                        if len(private_key_bytes) == 64:
                            logger.debug("检测到64字节的十六进制密钥对，转换为Base58格式")
                            private_key_to_store = b58encode(private_key_bytes).decode()
                        elif len(private_key_bytes) == 32:
                            logger.debug("检测到32字节的十六进制私钥，创建完整密钥对")
                            keypair = Keypair.from_seed(private_key_bytes)
                            private_key_to_store = b58encode(keypair.seed + bytes(keypair.public_key)).decode()
                        else:
                            raise ValueError("私钥长度错误")
                        logger.debug(f"存储的私钥格式: {private_key_to_store}")
                    except Exception as e:
                        logger.error(f"十六进制解码失败: {str(e)}")
                        raise ValueError("无效的私钥格式")
                
                # 验证地址
                try:
                    keypair = Keypair.from_secret_key(b58decode(private_key_to_store))
                    address = str(keypair.public_key)
                    logger.debug(f"生成的地址: {address}")
                except Exception as e:
                    logger.error(f"验证密钥对失败: {str(e)}")
                    raise ValueError("无效的密钥对格式")
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
                    decrypted_password = self.decrypt_data(payment_password.encrypted_password, device_id)
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
            decrypted_password = self.decrypt_data(payment_password.encrypted_password, device_id)
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=name,
                chain=chain,
                address=address,
                encrypted_private_key=self.encrypt_data(private_key_to_store, decrypted_password),
                is_imported=True
            )
            
            # 保存头像
            wallet.avatar.save(f'wallet_avatar_{wallet.id}.png', avatar_file, save=True) # type: ignore
            
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
            if chain == "ETH" or chain == "BASE":
                from eth_utils import is_address
                if not is_address(address):
                    return Response({
                        'status': 'error',
                        'message': '无效的以太坊地址'
                    }, status=status.HTTP_400_BAD_REQUEST)
            elif chain == "SOL":
                from solana.publickey import PublicKey
                try:
                    PublicKey(address)
                except:
                    return Response({
                        'status': 'error',
                        'message': '无效的Solana地址'
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            # 检查钱包是否已存在
            if Wallet.objects.filter(device_id=device_id, chain=chain, address=address, is_active=True).exists():
                return Response({
                    'status': 'error',
                    'message': '该钱包已存在'
                }, status=status.HTTP_400_BAD_REQUEST)
                
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
                name = f"Watch {chain} Wallet {existing_wallets + 1}"
            
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
            wallet.avatar.save(f'wallet_avatar_{wallet.id}.png', avatar_file, save=True) # type: ignore
            
            return Response({
                'status': 'success',
                'message': '观察者钱包导入成功',
                'wallet': WalletSerializer(wallet).data
            })
            
        except Exception as e:
            logger.error(f"导入观察者钱包失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'导入观察者钱包失败: {str(e)}'
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