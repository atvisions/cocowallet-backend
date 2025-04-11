from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
import logging
from asgiref.sync import async_to_sync, sync_to_async
from functools import wraps
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
import aiohttp
from typing import Optional
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from web3 import Web3
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.keypair import Keypair
from base58 import b58encode, b58decode
from eth_account import Account
from cryptography.fernet import Fernet
from wallet.models import Wallet, Token
from wallet.serializers import TokenSerializer
from wallet.utils.validators import validate_device_id, validate_payment_password
from wallet.utils.encryption import encrypt_string, decrypt_string
from wallet.utils.exceptions import WalletError
from wallet.decorators import verify_payment_password
from wallet.services.factory import ChainServiceFactory

logger = logging.getLogger(__name__)

def async_to_sync_api(func):
    """装饰器：将异步API转换为同步API"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return async_to_sync(func)(*args, **kwargs)
    return wrapper

class SolanaNFTViewSet(viewsets.ViewSet):
    """Solana NFT视图集"""
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [JSONParser]

    def transfer(self, request):
        """转移NFT"""
        try:
            # 验证设备ID
            device_id = request.data.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包ID
            wallet_id = request.data.get('wallet_id')
            if not wallet_id:
                return Response({
                    'status': 'error',
                    'message': '缺少wallet_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证NFT地址
            nft_address = request.data.get('nft_address')
            if not nft_address:
                return Response({
                    'status': 'error',
                    'message': '缺少nft_address参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证目标地址
            to_address = request.data.get('to_address')
            if not to_address:
                return Response({
                    'status': 'error',
                    'message': '缺少to_address参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证支付密码
            payment_password = request.data.get('payment_password')
            if not payment_password:
                return Response({
                    'status': 'error',
                    'message': '缺少payment_password参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            try:
                wallet = Wallet.objects.get(id=wallet_id, device_id=device_id)
            except Wallet.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': '钱包不存在'
                }, status=status.HTTP_404_NOT_FOUND)

            # 验证支付密码
            if not wallet.check_payment_password(payment_password):
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 解密私钥
            private_key = wallet.decrypt_private_key()

            # 调用链服务转移NFT
            service = ChainServiceFactory.get_service('SOL', 'nft')
            result = service.transfer_nft(
                private_key=private_key,
                nft_address=nft_address,
                to_address=to_address
            )

            return Response({
                'status': 'success',
                'message': 'NFT转移成功',
                'data': result
            })

        except Exception as e:
            logger.error(f"转移NFT失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'转移NFT失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def list(self, request):
        """获取NFT列表"""
        try:
            # 验证设备ID
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包ID
            wallet_id = request.query_params.get('wallet_id')
            if not wallet_id:
                return Response({
                    'status': 'error',
                    'message': '缺少wallet_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            try:
                wallet = Wallet.objects.get(id=wallet_id, device_id=device_id)
            except Wallet.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': '钱包不存在'
                }, status=status.HTTP_404_NOT_FOUND)

            # 调用链服务获取NFT列表
            service = ChainServiceFactory.get_service('SOL', 'nft')
            nfts = service.get_nfts(wallet.address)

            return Response({
                'status': 'success',
                'message': '获取NFT列表成功',
                'data': nfts
            })

        except Exception as e:
            logger.error(f"获取NFT列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取NFT列表失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class EVMNFTViewSet(viewsets.ViewSet):
    """EVM NFT视图集"""
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [JSONParser]

    def transfer(self, request):
        """转移NFT"""
        try:
            # 验证设备ID
            device_id = request.data.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包ID
            wallet_id = request.data.get('wallet_id')
            if not wallet_id:
                return Response({
                    'status': 'error',
                    'message': '缺少wallet_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证NFT地址
            nft_address = request.data.get('nft_address')
            if not nft_address:
                return Response({
                    'status': 'error',
                    'message': '缺少nft_address参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证目标地址
            to_address = request.data.get('to_address')
            if not to_address:
                return Response({
                    'status': 'error',
                    'message': '缺少to_address参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证支付密码
            payment_password = request.data.get('payment_password')
            if not payment_password:
                return Response({
                    'status': 'error',
                    'message': '缺少payment_password参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            try:
                wallet = Wallet.objects.get(id=wallet_id, device_id=device_id)
            except Wallet.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': '钱包不存在'
                }, status=status.HTTP_404_NOT_FOUND)

            # 验证支付密码
            if not wallet.check_payment_password(payment_password):
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 解密私钥
            private_key = wallet.decrypt_private_key()

            # 调用链服务转移NFT
            service = ChainServiceFactory.get_service(wallet.chain, 'nft')
            result = service.transfer_nft(
                private_key=private_key,
                nft_address=nft_address,
                to_address=to_address
            )

            return Response({
                'status': 'success',
                'message': 'NFT转移成功',
                'data': result
            })

        except Exception as e:
            logger.error(f"转移NFT失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'转移NFT失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def list(self, request):
        """获取NFT列表"""
        try:
            # 验证设备ID
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证钱包ID
            wallet_id = request.query_params.get('wallet_id')
            if not wallet_id:
                return Response({
                    'status': 'error',
                    'message': '缺少wallet_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            try:
                wallet = Wallet.objects.get(id=wallet_id, device_id=device_id)
            except Wallet.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': '钱包不存在'
                }, status=status.HTTP_404_NOT_FOUND)

            # 调用链服务获取NFT列表
            service = ChainServiceFactory.get_service(wallet.chain, 'nft')
            nfts = service.get_nfts(wallet.address)

            return Response({
                'status': 'success',
                'message': '获取NFT列表成功',
                'data': nfts
            })

        except Exception as e:
            logger.error(f"获取NFT列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取NFT列表失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)