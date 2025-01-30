from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.request import Request
from django.conf import settings
from .models import Wallet, MnemonicBackup, PaymentPassword
from .serializers import (
    WalletSerializer,
    WalletCreateSerializer,
    WalletUpdateSerializer,
    WalletImportSerializer,
    MnemonicBackupSerializer,
    PaymentPasswordSerializer,
    WalletSetupSerializer,
    generate_avatar
)
from mnemonic import Mnemonic
from hdwallet import HDWallet
from hdwallet.utils import generate_entropy
import base64
import os
import hashlib
from io import BytesIO
from django.core.files.base import ContentFile
import json
import re
import base58
import nacl.signing
from .services import TokenService, NFTService
import asyncio
from asgiref.sync import sync_to_async
import logging

logger = logging.getLogger(__name__)

def encrypt_string(text, key):
    """简单的字符串加密函数"""
    key_hash = hashlib.sha256(key.encode()).digest()
    text_bytes = text.encode()
    encrypted = bytes(a ^ b for a, b in zip(text_bytes, key_hash * (len(text_bytes) // len(key_hash) + 1)))
    return base64.b64encode(encrypted).decode()

def decrypt_string(encrypted_text, key):
    """简单的字符串解密函数"""
    key_hash = hashlib.sha256(key.encode()).digest()
    encrypted_bytes = base64.b64decode(encrypted_text.encode())
    decrypted = bytes(a ^ b for a, b in zip(encrypted_bytes, key_hash * (len(encrypted_bytes) // len(key_hash) + 1)))
    return decrypted.decode()

class WalletViewSet(viewsets.ModelViewSet):
    """钱包视图集"""
    serializer_class = WalletSerializer
    queryset = Wallet.objects.all()

    def get_queryset(self):
        request: Request = self.request
        # 从 query_params 或 data 中获取 device_id
        device_id = request.query_params.get('device_id') or request.data.get('device_id')
        if not device_id:
            return Wallet.objects.none()
        # 如果是删除操作，不过滤 is_active 状态
        if self.action == 'destroy':
            return Wallet.objects.filter(device_id=device_id)
        return Wallet.objects.filter(device_id=device_id, is_active=True)

    def list(self, request, *args, **kwargs):
        device_id = request.query_params.get('device_id')
        if not device_id:
            return Response({'error': '请提供device_id参数'}, status=status.HTTP_400_BAD_REQUEST)
        
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'wallets': serializer.data,
            'total': len(serializer.data)
        })

    def get_serializer_class(self):
        if self.action == 'create':
            return WalletCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return WalletUpdateSerializer
        elif self.action == 'import_wallet':
            return WalletImportSerializer
        elif self.action == 'setup':
            return WalletSetupSerializer
        return self.serializer_class

    @action(detail=False, methods=['post'])
    def set_password(self, request):
        """设置支付密码"""
        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')
        payment_password_confirm = request.data.get('payment_password_confirm')

        if not device_id:
            return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
        if not payment_password:
            return Response({'error': '请输入支付密码'}, status=status.HTTP_400_BAD_REQUEST)
        if not payment_password_confirm:
            return Response({'error': '请输入确认密码'}, status=status.HTTP_400_BAD_REQUEST)
        if payment_password != payment_password_confirm:
            return Response({'error': '两次输入的密码不一致'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^\d{6}$', payment_password):
            return Response({'error': '支付密码必须是6位数字'}, status=status.HTTP_400_BAD_REQUEST)

        if PaymentPassword.objects.filter(device_id=device_id).exists():
            return Response({'error': '已设置过支付密码'}, status=status.HTTP_400_BAD_REQUEST)

        # 加密并保存支付密码
        encrypted_password = encrypt_string(payment_password, device_id)
        PaymentPassword.objects.create(
            device_id=device_id,
            encrypted_password=encrypted_password
        )
        return Response({'message': '支付密码设置成功'}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """修改支付密码"""
        device_id = request.data.get('device_id')
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')
        new_password_confirm = request.data.get('new_password_confirm')

        if not device_id:
            return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
        if not old_password:
            return Response({'error': '请输入原支付密码'}, status=status.HTTP_400_BAD_REQUEST)
        if not new_password:
            return Response({'error': '请输入新支付密码'}, status=status.HTTP_400_BAD_REQUEST)
        if not new_password_confirm:
            return Response({'error': '请输入确认密码'}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != new_password_confirm:
            return Response({'error': '两次输入的新密码不一致'}, status=status.HTTP_400_BAD_REQUEST)
        if not re.match(r'^\d{6}$', new_password):
            return Response({'error': '支付密码必须是6位数字'}, status=status.HTTP_400_BAD_REQUEST)
        if old_password == new_password:
            return Response({'error': '新密码不能与原密码相同'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 获取并验证原密码
            payment_password = PaymentPassword.objects.get(device_id=device_id)
            decrypted_old_password = decrypt_string(payment_password.encrypted_password, device_id)
            
            if old_password != decrypted_old_password:
                return Response({'error': '原密码错误'}, status=status.HTTP_400_BAD_REQUEST)

            # 获取助记词备份
            mnemonic_backup = MnemonicBackup.objects.filter(device_id=device_id).first()
            if mnemonic_backup:
                # 使用旧密码解密助记词
                decrypted_mnemonic = decrypt_string(mnemonic_backup.encrypted_mnemonic, decrypted_old_password)
                # 使用新密码重新加密助记词
                mnemonic_backup.encrypted_mnemonic = encrypt_string(decrypted_mnemonic, new_password)
                mnemonic_backup.save()

            # 获取所有钱包
            wallets = Wallet.objects.filter(device_id=device_id)
            for wallet in wallets:
                # 使用旧密码解密私钥
                decrypted_private_key = decrypt_string(wallet.encrypted_private_key, decrypted_old_password)
                # 使用新密码重新加密私钥
                wallet.encrypted_private_key = encrypt_string(decrypted_private_key, new_password)
                wallet.save()

            # 更新支付密码
            payment_password.encrypted_password = encrypt_string(new_password, device_id)
            payment_password.save()

            return Response({'message': '支付密码修改成功'}, status=status.HTTP_200_OK)

        except PaymentPassword.DoesNotExist:
            return Response({'error': '未设置支付密码'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': '密码修改失败'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def select_chain(self, request):
        """选择区块链"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')

        if not device_id:
            return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
        if not chain:
            return Response({'error': '请选择区块链'}, status=status.HTTP_400_BAD_REQUEST)
        if not PaymentPassword.objects.filter(device_id=device_id).exists():
            return Response({'error': '请先设置支付密码'}, status=status.HTTP_400_BAD_REQUEST)

        # 生成助记词
        mnemo = Mnemonic("english")
        mnemonic_str = mnemo.generate(strength=256)
        
        # 临时保存助记词
        request.session[f'temp_mnemonic_{device_id}_{chain}'] = mnemonic_str
        
        return Response({
            'message': '链选择成功',
            'chain': chain,
            'mnemonic': mnemonic_str.split()
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def verify_mnemonic(self, request):
        """验证助记词并创建钱包"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        mnemonic_words = request.data.get('mnemonic_words', [])

        if not device_id or not chain:
            return Response({'error': '请提供device_id和chain'}, status=status.HTTP_400_BAD_REQUEST)
        if not mnemonic_words:
            return Response({'error': '请输入助记词'}, status=status.HTTP_400_BAD_REQUEST)

        # 获取之前生成的助记词
        original_mnemonic = request.session.get(f'temp_mnemonic_{device_id}_{chain}')
        if not original_mnemonic:
            return Response({'error': '助记词已过期，请重新开始'}, status=status.HTTP_400_BAD_REQUEST)

        # 验证助记词
        if ' '.join(mnemonic_words) != original_mnemonic:
            return Response({'error': '助记词验证失败'}, status=status.HTTP_400_BAD_REQUEST)

        # 获取支付密码
        payment_password_obj = PaymentPassword.objects.get(device_id=device_id)
        payment_password = decrypt_string(payment_password_obj.encrypted_password, device_id)

        # 创建HD钱包
        hdwallet = HDWallet()
        hdwallet.from_mnemonic(original_mnemonic)
        
        # 根据不同链生成地址
        chain_config = settings.SUPPORTED_CHAINS[chain]
        hdwallet.from_path(chain_config['path'])
        
        if chain == 'BTC':
            address = hdwallet.p2pkh_address()
        elif chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
            address = hdwallet.public_key()  # 获取公钥
            # 使用 keccak256 哈希和取后20字节生成以太坊地址
            keccak = hashlib.sha3_256()
            keccak.update(bytes.fromhex(address))
            address = '0x' + keccak.hexdigest()[-40:]
        elif chain == 'SOL':
            # Solana地址生成逻辑
            public_key = hdwallet.public_key()
            address = base58.b58encode(bytes.fromhex(public_key)).decode()

        # 加密私钥
        encrypted_private_key = encrypt_string(hdwallet.private_key(), payment_password)

        # 生成随机头像
        avatar = generate_avatar()
        img_io = BytesIO()
        avatar.save(img_io, format='PNG', quality=100)
        img_content = ContentFile(img_io.getvalue())

        # 保存钱包
        wallet = Wallet.objects.create(
            device_id=device_id,
            name=f"My {chain} Wallet",
            chain=chain,
            address=address,
            encrypted_private_key=encrypted_private_key
        )

        # 保存头像
        wallet.avatar.save(f"wallet_avatar_{device_id}_{chain}.png", img_content, save=True)

        # 保存加密的助记词
        if not MnemonicBackup.objects.filter(device_id=device_id).exists():
            MnemonicBackup.objects.create(
                device_id=device_id,
                encrypted_mnemonic=encrypt_string(original_mnemonic, payment_password)
            )

        # 清除临时助记词
        del request.session[f'temp_mnemonic_{device_id}_{chain}']

        return Response({
            'message': '钱包创建成功',
            'wallet': WalletSerializer(wallet).data
        }, status=status.HTTP_201_CREATED)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # 检查设备是否已创建过相同链的钱包
        device_id = serializer.validated_data['device_id']
        chain = serializer.validated_data['chain']
        if Wallet.objects.filter(device_id=device_id, chain=chain).exists():
            return Response({'error': f'此设备已创建过 {chain} 钱包'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 生成或使用提供的助记词
        mnemonic_str = serializer.validated_data.get('mnemonic')
        if not mnemonic_str:
            mnemo = Mnemonic("english")
            mnemonic_str = mnemo.generate(strength=256)

        # 创建HD钱包
        hdwallet = HDWallet()
        hdwallet.from_mnemonic(mnemonic_str)
        
        # 根据不同链生成地址
        chain_config = settings.SUPPORTED_CHAINS[chain]
        hdwallet.from_path(chain_config['path'])
        
        if chain == 'BTC':
            address = hdwallet.p2pkh_address()
        elif chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
            address = hdwallet.public_key()  # 获取公钥
            # 使用 keccak256 哈希和取后20字节生成以太坊地址
            keccak = hashlib.sha3_256()
            keccak.update(bytes.fromhex(address))
            address = '0x' + keccak.hexdigest()[-40:]
        elif chain == 'SOL':
            # Solana地址生成逻辑
            public_key = hdwallet.public_key()
            address = base58.b58encode(bytes.fromhex(public_key)).decode()
        
        # 加密私钥
        encrypted_private_key = encrypt_string(hdwallet.private_key(), serializer.validated_data['password'])
        
        # 生成随机头像
        avatar = generate_avatar()
        img_io = BytesIO()
        avatar.save(img_io, format='PNG', quality=100)
        img_content = ContentFile(img_io.getvalue())
        
        # 保存钱包
        wallet = Wallet.objects.create(
            device_id=device_id,
            name=serializer.validated_data['name'],
            chain=chain,
            address=address,
            encrypted_private_key=encrypted_private_key
        )
        
        # 保存头像
        wallet.avatar.save(f"wallet_avatar_{device_id}_{chain}.png", img_content, save=True)
        
        # 检查是否已有助记词备份
        if not MnemonicBackup.objects.filter(device_id=device_id).exists():
            # 保存加密的助记词
            MnemonicBackup.objects.create(
                device_id=device_id,
                encrypted_mnemonic=encrypt_string(mnemonic_str, serializer.validated_data['password'])
            )
        
        return Response({
            'wallet': WalletSerializer(wallet).data,
            'mnemonic': mnemonic_str if not MnemonicBackup.objects.filter(device_id=device_id).exists() else None
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def import_wallet(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # 检查设备是否已创建过相同链的钱包
        device_id = serializer.validated_data['device_id']
        chain = serializer.validated_data['chain']
        if Wallet.objects.filter(device_id=device_id, chain=chain).exists():
            return Response({'error': f'此设备已创建过 {chain} 钱包'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证助记词
        try:
            mnemo = Mnemonic("english")
            if not mnemo.check(serializer.validated_data['mnemonic']):
                return Response({'error': '无效的助记词'}, status=status.HTTP_400_BAD_REQUEST)
        except:
            return Response({'error': '无效的助记词'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 创建HD钱包
        hdwallet = HDWallet()
        hdwallet.from_mnemonic(serializer.validated_data['mnemonic'])
        
        # 根据不同链生成地址
        chain_config = settings.SUPPORTED_CHAINS[chain]
        hdwallet.from_path(chain_config['path'])
        
        if chain == 'BTC':
            address = hdwallet.p2pkh_address()
        elif chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
            address = hdwallet.public_key()  # 获取公钥
            # 使用 keccak256 哈希和取后20字节生成以太坊地址
            keccak = hashlib.sha3_256()
            keccak.update(bytes.fromhex(address))
            address = '0x' + keccak.hexdigest()[-40:]
        elif chain == 'SOL':
            # Solana地址生成逻辑
            public_key = hdwallet.public_key()
            address = base58.b58encode(bytes.fromhex(public_key)).decode()
        
        # 加密私钥
        encrypted_private_key = encrypt_string(hdwallet.private_key(), serializer.validated_data['password'])
        
        # 生成随机头像
        avatar = generate_avatar()
        img_io = BytesIO()
        avatar.save(img_io, format='PNG', quality=100)
        img_content = ContentFile(img_io.getvalue())
        
        # 保存钱包
        wallet = Wallet.objects.create(
            device_id=device_id,
            name=serializer.validated_data['name'],
            chain=chain,
            address=address,
            encrypted_private_key=encrypted_private_key
        )
        
        # 保存头像
        wallet.avatar.save(f"wallet_avatar_{device_id}_{chain}.png", img_content, save=True)
        
        return Response(WalletSerializer(wallet).data)

    def destroy(self, request, *args, **kwargs):
        """删除钱包（软删除）"""
        try:
            wallet = self.get_object()
        except:
            return Response({'error': '钱包不存在'}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.data.get('device_id')
        payment_password = request.data.get('payment_password')

        # 验证设备ID
        if not device_id:
            return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
        if device_id != wallet.device_id:
            return Response({'error': '无权操作此钱包'}, status=status.HTTP_403_FORBIDDEN)

        # 验证支付密码
        try:
            payment_password_obj = PaymentPassword.objects.get(device_id=device_id)
            decrypted_password = decrypt_string(payment_password_obj.encrypted_password, device_id)
            if not payment_password:
                return Response({'error': '请提供支付密码'}, status=status.HTTP_400_BAD_REQUEST)
            if payment_password != decrypted_password:
                return Response({'error': '支付密码错误'}, status=status.HTTP_400_BAD_REQUEST)
        except PaymentPassword.DoesNotExist:
            return Response({'error': '未设置支付密码'}, status=status.HTTP_400_BAD_REQUEST)

        # 执行软删除
        wallet.is_active = False
        wallet.save()
        
        return Response({
            'message': '钱包删除成功'
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def import_by_mnemonic(self, request):
        """通过助记词导入钱包"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        mnemonic = request.data.get('mnemonic')
        payment_password = request.data.get('payment_password')  # 仅在未设置支付密码时需要

        if not device_id or not chain or not mnemonic:
            return Response({'error': '请提供所有必要参数'}, status=status.HTTP_400_BAD_REQUEST)

        # 检查是否已设置支付密码
        try:
            payment_password_obj = PaymentPassword.objects.get(device_id=device_id)
            # 如果已设置支付密码，使用已有的密码
            payment_password = decrypt_string(payment_password_obj.encrypted_password, device_id)
        except PaymentPassword.DoesNotExist:
            # 如果未设置支付密码，验证新密码
            if not payment_password:
                return Response({'error': '请提供支付密码'}, status=status.HTTP_400_BAD_REQUEST)
            if not re.match(r'^\d{6}$', payment_password):
                return Response({'error': '支付密码必须是6位数字'}, status=status.HTTP_400_BAD_REQUEST)
            # 保存新的支付密码
            payment_password_obj = PaymentPassword.objects.create(
                device_id=device_id,
                encrypted_password=encrypt_string(payment_password, device_id)
            )

        # 验证助记词
        try:
            mnemo = Mnemonic("english")
            if not mnemo.check(' '.join(mnemonic) if isinstance(mnemonic, list) else mnemonic):
                return Response({'error': '无效的助记词'}, status=status.HTTP_400_BAD_REQUEST)
            mnemonic_str = ' '.join(mnemonic) if isinstance(mnemonic, list) else mnemonic
        except:
            return Response({'error': '无效的助记词'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 创建HD钱包
            hdwallet = HDWallet()
            hdwallet.from_mnemonic(mnemonic_str)
            
            # 根据不同链生成地址
            chain_config = settings.SUPPORTED_CHAINS[chain]
            hdwallet.from_path(chain_config['path'])
            
            if chain == 'BTC':
                address = hdwallet.p2pkh_address()
            elif chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
                address = hdwallet.public_key()
                keccak = hashlib.sha3_256()
                keccak.update(bytes.fromhex(address))
                address = '0x' + keccak.hexdigest()[-40:]
            elif chain == 'SOL':
                public_key = hdwallet.public_key()
                address = base58.b58encode(bytes.fromhex(public_key)).decode()

            # 加密私钥
            encrypted_private_key = encrypt_string(hdwallet.private_key(), payment_password)

            # 生成随机头像
            avatar = generate_avatar()
            img_io = BytesIO()
            avatar.save(img_io, format='PNG', quality=100)
            img_content = ContentFile(img_io.getvalue())

            # 获取同链钱包数量，用于生成名称
            same_chain_count = Wallet.objects.filter(device_id=device_id, chain=chain, is_active=True).count()
            wallet_name = f"Imported {chain} Wallet" if same_chain_count == 0 else f"Imported {chain} Wallet {same_chain_count + 1}"

            # 保存钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=wallet_name,
                chain=chain,
                address=address,
                encrypted_private_key=encrypted_private_key,
                is_imported=True
            )

            # 保存头像
            wallet.avatar.save(f"wallet_avatar_{device_id}_{chain}_{same_chain_count + 1}.png", img_content, save=True)

            # 保存加密的助记词（如果还没有备份）
            if not MnemonicBackup.objects.filter(device_id=device_id).exists():
                MnemonicBackup.objects.create(
                    device_id=device_id,
                    encrypted_mnemonic=encrypt_string(mnemonic_str, payment_password)
                )

            return Response({
                'message': '钱包导入成功',
                'wallet': WalletSerializer(wallet).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': '钱包导入失败'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def import_by_private_key(self, request):
        """通过私钥导入钱包"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        private_key = request.data.get('private_key')
        payment_password = request.data.get('payment_password')  # 仅在未设置支付密码时需要

        if not device_id or not chain or not private_key:
            return Response({'error': '请提供所有必要参数'}, status=status.HTTP_400_BAD_REQUEST)

        # 检查是否已设置支付密码
        try:
            payment_password_obj = PaymentPassword.objects.get(device_id=device_id)
            # 如果已设置支付密码，使用已有的密码
            payment_password = decrypt_string(payment_password_obj.encrypted_password, device_id)
        except PaymentPassword.DoesNotExist:
            # 如果未设置支付密码，验证新密码
            if not payment_password:
                return Response({'error': '请提供支付密码'}, status=status.HTTP_400_BAD_REQUEST)
            if not re.match(r'^\d{6}$', payment_password):
                return Response({'error': '支付密码必须是6位数字'}, status=status.HTTP_400_BAD_REQUEST)
            # 保存新的支付密码
            payment_password_obj = PaymentPassword.objects.create(
                device_id=device_id,
                encrypted_password=encrypt_string(payment_password, device_id)
            )

        try:
            # 验证私钥格式并生成地址
            if chain == 'SOL':
                # 清理私钥格式
                private_key = private_key.strip()
                
                try:
                    # 尝试 base58 解码
                    decoded_bytes = base58.b58decode(private_key)
                    
                    # 如果是完整的 keypair（64字节）
                    if len(decoded_bytes) == 64:
                        # 前32字节是私钥
                        private_key_bytes = decoded_bytes[:32]
                        # 后32字节是公钥
                        public_key_bytes = decoded_bytes[32:]
                        # 验证公钥
                        address = base58.b58encode(public_key_bytes).decode()
                    # 如果是纯私钥（32字节）
                    elif len(decoded_bytes) == 32:
                        private_key_bytes = decoded_bytes
                        # 使用 ed25519 生成公钥
                        from cryptography.hazmat.primitives import serialization
                        from cryptography.hazmat.primitives.asymmetric import ed25519
                        private_key_obj = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
                        public_key_bytes = private_key_obj.public_key().public_bytes(
                            encoding=serialization.Encoding.Raw,
                            format=serialization.PublicFormat.Raw
                        )
                        address = base58.b58encode(public_key_bytes).decode()
                    else:
                        raise ValueError("Invalid private key length")
                        
                    # 保存私钥
                    private_key = base58.b58encode(private_key_bytes).decode()

                except Exception as e:
                    return Response({
                        'error': '无效的Solana私钥格式',
                        'detail': str(e)
                    }, status=status.HTTP_400_BAD_REQUEST)

            elif chain == 'BTC':
                # 比特币私钥导入逻辑
                try:
                    from bitcoinlib.keys import Key
                    from bitcoinlib.encoding import to_hexstring

                    # 处理私钥格式
                    if private_key.startswith('0x'):
                        private_key = private_key[2:]
                    
                    # 支持 WIF 格式和十六进制格式
                    try:
                        # 尝试 WIF 格式
                        key = Key(private_key)
                    except:
                        try:
                            # 尝试十六进制格式
                            if not re.match(r'^[0-9a-fA-F]{64}$', private_key):
                                raise ValueError("Invalid private key format")
                            key = Key(private_key, compressed=True)
                        except Exception as e:
                            return Response({
                                'error': '无效的比特币私钥格式',
                                'detail': str(e)
                            }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # 获取地址和私钥
                    address = key.address()
                    private_key = to_hexstring(key.private_byte)  # 统一使用十六进制格式存储
                    
                except Exception as e:
                    return Response({
                        'error': '无效的比特币私钥格式',
                        'detail': str(e)
                    }, status=status.HTTP_400_BAD_REQUEST)

            elif chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
                # 以太坊系列私钥导入逻辑
                try:
                    from eth_account import Account
                    from eth_utils import to_checksum_address
                    
                    # 处理私钥格式
                    if private_key.startswith('0x'):
                        private_key = private_key[2:]
                    if not re.match(r'^[0-9a-fA-F]{64}$', private_key):
                        return Response({'error': '无效的私钥格式'}, status=status.HTTP_400_BAD_REQUEST)
                    
                    # 使用 eth_account 处理私钥
                    account = Account.from_key('0x' + private_key)
                    address = to_checksum_address(account.address)
                    
                except Exception as e:
                    return Response({
                        'error': '无效的私钥格式',
                        'detail': str(e)
                    }, status=status.HTTP_400_BAD_REQUEST)

            # 加密私钥
            encrypted_private_key = encrypt_string(private_key, payment_password)

            # 生成随机头像
            avatar = generate_avatar()
            img_io = BytesIO()
            avatar.save(img_io, format='PNG', quality=100)
            img_content = ContentFile(img_io.getvalue())

            # 获取同链钱包数量，用于生成名称
            same_chain_count = Wallet.objects.filter(device_id=device_id, chain=chain, is_active=True).count()
            wallet_name = f"Imported {chain} Wallet" if same_chain_count == 0 else f"Imported {chain} Wallet {same_chain_count + 1}"

            # 保存钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=wallet_name,
                chain=chain,
                address=address,
                encrypted_private_key=encrypted_private_key,
                is_imported=True
            )

            # 保存头像
            wallet.avatar.save(f"wallet_avatar_{device_id}_{chain}_{same_chain_count + 1}.png", img_content, save=True)

            return Response({
                'message': '钱包导入成功',
                'wallet': WalletSerializer(wallet).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                'error': '钱包导入失败',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def import_by_keystore(self, request):
        """通过keystore导入钱包"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        keystore = request.data.get('keystore')
        keystore_password = request.data.get('keystore_password')
        payment_password = request.data.get('payment_password')  # 仅在未设置支付密码时需要

        if not all([device_id, chain, keystore, keystore_password]):
            return Response({'error': '请提供所有必要参数'}, status=status.HTTP_400_BAD_REQUEST)

        # 检查是否已设置支付密码
        try:
            payment_password_obj = PaymentPassword.objects.get(device_id=device_id)
            # 如果已设置支付密码，使用已有的密码
            payment_password = decrypt_string(payment_password_obj.encrypted_password, device_id)
        except PaymentPassword.DoesNotExist:
            # 如果未设置支付密码，验证新密码
            if not payment_password:
                return Response({'error': '请提供支付密码'}, status=status.HTTP_400_BAD_REQUEST)
            if not re.match(r'^\d{6}$', payment_password):
                return Response({'error': '支付密码必须是6位数字'}, status=status.HTTP_400_BAD_REQUEST)
            # 保存新的支付密码
            payment_password_obj = PaymentPassword.objects.create(
                device_id=device_id,
                encrypted_password=encrypt_string(payment_password, device_id)
            )

        try:
            # 解密keystore
            if chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
                from eth_account import Account
                import json
                
                # 验证keystore格式
                try:
                    keystore_json = json.loads(keystore)
                except:
                    return Response({'error': '无效的keystore格式'}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    private_key = Account.decrypt(keystore_json, keystore_password)
                    address = Account.from_key(private_key).address
                except ValueError:
                    return Response({'error': 'keystore密码错误'}, status=status.HTTP_400_BAD_REQUEST)
                
                # 加密私钥
                encrypted_private_key = encrypt_string(private_key.hex(), payment_password)
            else:
                return Response({'error': '暂不支持该链的keystore导入'}, status=status.HTTP_400_BAD_REQUEST)

            # 生成随机头像
            avatar = generate_avatar()
            img_io = BytesIO()
            avatar.save(img_io, format='PNG', quality=100)
            img_content = ContentFile(img_io.getvalue())

            # 获取同链钱包数量，用于生成名称
            same_chain_count = Wallet.objects.filter(device_id=device_id, chain=chain, is_active=True).count()
            wallet_name = f"Imported {chain} Wallet" if same_chain_count == 0 else f"Imported {chain} Wallet {same_chain_count + 1}"

            # 保存钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=wallet_name,
                chain=chain,
                address=address,
                encrypted_private_key=encrypted_private_key,
                is_imported=True
            )

            # 保存头像
            wallet.avatar.save(f"wallet_avatar_{device_id}_{chain}_{same_chain_count + 1}.png", img_content, save=True)

            return Response({
                'message': '钱包导入成功',
                'wallet': WalletSerializer(wallet).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': '钱包导入失败'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def import_watch_only(self, request):
        """导入观察者钱包（只有地址）"""
        device_id = request.data.get('device_id')
        chain = request.data.get('chain')
        address = request.data.get('address')

        if not device_id or not chain or not address:
            return Response({'error': '请提供所有必要参数'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 验证地址格式
            if chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
                from eth_utils import is_address, to_checksum_address
                if not is_address(address):
                    return Response({'error': '无效的地址格式'}, status=status.HTTP_400_BAD_REQUEST)
                address = to_checksum_address(address)
            elif chain == 'BTC':
                # 验证比特币地址
                pass
            elif chain == 'SOL':
                # 验证Solana地址
                pass

            # 生成随机头像
            avatar = generate_avatar()
            img_io = BytesIO()
            avatar.save(img_io, format='PNG', quality=100)
            img_content = ContentFile(img_io.getvalue())

            # 获取同链钱包数量，用于生成名称
            same_chain_count = Wallet.objects.filter(device_id=device_id, chain=chain, is_active=True).count()
            wallet_name = f"Watch {chain} Wallet" if same_chain_count == 0 else f"Watch {chain} Wallet {same_chain_count + 1}"

            # 保存钱包
            wallet = Wallet.objects.create(
                device_id=device_id,
                name=wallet_name,
                chain=chain,
                address=address,
                is_watch_only=True,
                is_imported=True
            )

            # 保存头像
            wallet.avatar.save(f"wallet_avatar_{device_id}_{chain}_{same_chain_count + 1}.png", img_content, save=True)

            return Response({
                'message': '观察者钱包导入成功',
                'wallet': WalletSerializer(wallet).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': '钱包导入失败'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='rename')
    def rename(self, request, pk=None):
        """重命名钱包"""
        try:
            wallet = self.get_object()
        except:
            return Response({'error': '钱包不存在'}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.data.get('device_id')
        if not device_id:
            return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
        if device_id != wallet.device_id:
            return Response({'error': '无权操作此钱包'}, status=status.HTTP_403_FORBIDDEN)

        new_name = request.data.get('name')
        if not new_name:
            return Response({'error': '请提供新的钱包名称'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_name) > 100:
            return Response({'error': '钱包名称不能超过100个字符'}, status=status.HTTP_400_BAD_REQUEST)
            
        wallet.name = new_name
        wallet.save()
        
        return Response({
            'message': '钱包重命名成功',
            'wallet': WalletSerializer(wallet).data
        })

    @action(detail=True, methods=['get'])
    def tokens(self, request, pk=None):
        """获取钱包代币列表和总价值"""
        try:
            wallet = self.get_object()
        except:
            return Response({'error': '钱包不存在'}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.query_params.get('device_id')
        if not device_id:
            return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
        if device_id != wallet.device_id:
            return Response({'error': '无权访问此钱包'}, status=status.HTTP_403_FORBIDDEN)

        try:
            # 使用同步方式调用异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(TokenService().get_wallet_tokens(wallet))
            loop.close()
            return Response(result)
        except Exception as e:
            print(f"Error in tokens view: {str(e)}")  # 添加错误日志
            return Response({
                'error': '获取代币列表失败',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def value(self, request, pk=None):
        """获取钱包总价值"""
        try:
            wallet = self.get_object()
        except:
            return Response({'error': '钱包不存在'}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.query_params.get('device_id')
        if not device_id:
            return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
        if device_id != wallet.device_id:
            return Response({'error': '无权访问此钱包'}, status=status.HTTP_403_FORBIDDEN)

        try:
            # 使用同步方式调用异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            total_value = loop.run_until_complete(TokenService().get_wallet_value(wallet))
            loop.close()
            return Response({
                'total_value_usd': TokenService._format_value(str(total_value))
            })
        except Exception as e:
            return Response({
                'error': '获取钱包价值失败',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def nfts(self, request, pk=None):
        """获取钱包的 NFT 列表"""
        try:
            wallet = self.get_object()
            
            # 使用同步方式调用异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(NFTService.get_wallet_nfts(wallet))
            loop.close()
            
            return Response(result)
        except Exception as e:
            logger.error(f"Error in nfts view: {str(e)}")
            return Response(
                {'error': f'获取 NFT 列表失败: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'], url_path='nft-collections')
    def nft_collections(self, request, pk=None):
        """获取钱包的 NFT 合集列表"""
        try:
            wallet = self.get_object()
            
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
            if device_id != wallet.device_id:
                return Response({'error': '无权访问此钱包'}, status=status.HTTP_403_FORBIDDEN)
            
            # 使用同步方式调用异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(NFTService.get_wallet_nft_summary(wallet))
            loop.close()
            
            return Response(result)
        except Exception as e:
            logger.error(f"Error in nft_collections view: {str(e)}")
            return Response(
                {'error': f'获取 NFT 合集列表失败: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'], url_path='nft-collections/(?P<collection_id>[^/.]+)/nfts')
    def collection_nfts(self, request, pk=None, collection_id=None):
        """获取 NFT 合集内的 NFT 列表"""
        try:
            wallet = self.get_object()
            
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
            if device_id != wallet.device_id:
                return Response({'error': '无权访问此钱包'}, status=status.HTTP_403_FORBIDDEN)
            
            if not collection_id:
                return Response(
                    {'error': '请提供合集 ID'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 使用同步方式调用异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            nfts = loop.run_until_complete(NFTService.get_collection_nfts(wallet, collection_id))
            loop.close()
            
            return Response({
                'nfts': nfts,
                'total_count': len(nfts)
            })
        except Exception as e:
            logger.error(f"Error in collection_nfts view: {str(e)}")
            return Response(
                {'error': f'获取合集 NFT 列表失败: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'], url_path='nft-collections/(?P<collection_id>[^/.]+)/nfts/(?P<mint>[^/.]+)')
    def nft_detail(self, request, pk=None, collection_id=None, mint=None):
        """获取 NFT 详情"""
        try:
            wallet = self.get_object()
            
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({'error': '请提供device_id'}, status=status.HTTP_400_BAD_REQUEST)
            if device_id != wallet.device_id:
                return Response({'error': '无权访问此钱包'}, status=status.HTTP_403_FORBIDDEN)
            
            if not collection_id:
                return Response(
                    {'error': '请提供合集 ID'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not mint:
                return Response(
                    {'error': '请提供 NFT ID'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 使用同步方式调用异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            nft_detail = loop.run_until_complete(NFTService.get_nft_detail(wallet, collection_id, mint))
            loop.close()
            
            if not nft_detail:
                return Response(
                    {'error': 'NFT 不存在'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            return Response(nft_detail)
        except Exception as e:
            logger.error(f"Error in nft_detail view: {str(e)}")
            return Response(
                {'error': f'获取 NFT 详情失败: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

class MnemonicBackupViewSet(viewsets.ModelViewSet):
    """助记词备份视图集"""
    serializer_class = MnemonicBackupSerializer
    queryset = MnemonicBackup.objects.all()

    def get_queryset(self):
        request: Request = self.request
        device_id = request.query_params.get('device_id')
        if device_id:
            return MnemonicBackup.objects.filter(device_id=device_id)
        return MnemonicBackup.objects.none()
