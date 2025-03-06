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
from decimal import Decimal
from typing import Optional
from django.db.models import QuerySet
from django.utils import timezone
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
import asyncio
from django.core.cache import cache
import os
import json
import decimal

from ...models import Wallet, Token, Transaction, PaymentPassword
from ...serializers import WalletSerializer
from ...services.factory import ChainServiceFactory
from ...services.solana_config import RPCConfig, MoralisConfig, HeliusConfig
from ...decorators import verify_payment_password

# Helius API 配置
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY', '')
HELIUS_URL = f'https://rpc.helius.xyz/?api-key={HELIUS_API_KEY}'  # 更新为正确的端点

logger = logging.getLogger(__name__)

def async_to_sync_api(func):
    """装饰器：将异步API转换为同步API"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        return async_to_sync(func)(*args, **kwargs)
    return wrapper

class SolanaWalletViewSet(viewsets.ModelViewSet):
    """Solana钱包视图集"""
    serializer_class = WalletSerializer
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    parser_classes = [JSONParser]

    def get_queryset(self) -> QuerySet[Wallet]:
        """获取查询集"""
        # 从请求参数中获取device_id
        device_id = self.request.GET.get('device_id')
        logger.debug(f"查询参数 device_id: {device_id}")
        
        # 基础查询集
        queryset = Wallet.objects.all()
        
        # 如果是详情请求，不应用device_id过滤
        if self.action in ['retrieve', 'tokens', 'native_balance', 'token_balance']:
            return queryset
        
        # 列表请求时应用device_id过滤
        if device_id:
            queryset = queryset.filter(device_id=device_id)
            logger.debug(f"查询到的钱包数量: {queryset.count()}")
            return queryset
        return Wallet.objects.none()

    async def get_wallet_async(self, wallet_id: int, device_id: Optional[str] = None) -> Wallet:
        """异步获取钱包对象"""
        try:
            # 使用sync_to_async包装数据库查询
            get_wallet = sync_to_async(Wallet.objects.filter(id=wallet_id).first)
            wallet = await get_wallet()
            
            if not wallet:
                logger.error(f"找不到钱包，ID: {wallet_id}")
                raise ObjectDoesNotExist(f"找不到ID为{wallet_id}的钱包")
            
            # 验证device_id
            if device_id and wallet.device_id != device_id:
                logger.error(f"设备ID不匹配，钱包device_id: {wallet.device_id}, 请求device_id: {device_id}")
                raise ObjectDoesNotExist("无权访问该钱包")
                
            logger.debug(f"成功获取钱包: {wallet.address}")
            return wallet
            
        except Exception as e:
            logger.error(f"获取钱包时出错: {str(e)}")
            raise

    @action(detail=True, methods=['get'])
    @async_to_sync_api
    async def tokens(self, request, pk=None):
        """获取SOL钱包的所有代币余额"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(int(pk), device_id)
            logger.debug(f"请求获取代币余额，钱包地址: {wallet.address}, device_id: {device_id}")
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取SOL余额服务
            balance_service = ChainServiceFactory.get_balance_service('SOL')
            if not balance_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL余额服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 获取所有代币余额
            logger.debug(f"开始获取代币余额，钱包地址: {wallet.address}")
            result = await balance_service.get_all_token_balances(wallet.address, include_hidden=False)
            
            # 返回结果
            return Response({
                'status': 'success',
                'data': result
            })
            
        except ObjectDoesNotExist as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            logger.error(f"获取代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取代币余额失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    @async_to_sync_api
    async def native_balance(self, request, pk=None):
        """获取SOL原生代币余额"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取SOL余额服务
            balance_service = ChainServiceFactory.get_balance_service('SOL')
            if not balance_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL余额服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 获取原生SOL余额
            balance = await balance_service.get_native_balance(wallet.address)
            
            return Response({
                'status': 'success',
                'data': {
                    'balance': str(balance),
                    'symbol': 'SOL',
                    'is_native': True
                }
            })
            
        except ObjectDoesNotExist as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"获取SOL原生代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取余额失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    @async_to_sync_api
    async def token_balance(self, request, pk=None):
        """获取指定SOL代币余额"""
        try:
            device_id = request.query_params.get('device_id')
            token_address = request.query_params.get('token_address')
            
            if not device_id or not token_address:
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取SOL余额服务
            balance_service = ChainServiceFactory.get_balance_service('SOL')
            if not balance_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL余额服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 获取指定代币余额
            balance = await balance_service.get_token_balance(wallet.address, token_address)
            
            # 获取代币信息服务
            token_info_service = ChainServiceFactory.get_token_info_service('SOL')
            token_info = await token_info_service.get_token_info(token_address) if token_info_service else {}
            
            return Response({
                'status': 'success',
                'data': {
                    'token_address': token_address,
                    'balance': str(balance),
                    'symbol': token_info.get('symbol', 'Unknown'),
                    'name': token_info.get('name', 'Unknown Token'),
                    'decimals': token_info.get('decimals', 0),
                    'logo': token_info.get('logo', ''),
                    'is_native': False
                }
            })
            
        except ObjectDoesNotExist as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"获取代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取余额失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='tokens/(?P<symbol>[^/.]+)/(?P<token_address>[^/.]+)/detail')
    @async_to_sync_api
    async def token_detail(self, request, pk=None, symbol=None, token_address=None):
        """获取指定代币的详细信息"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(int(pk), device_id)
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取代币信息服务
            token_info_service = ChainServiceFactory.get_token_info_service('SOL')
            if not token_info_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL代币信息服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 获取代币详细信息
            token_info = await token_info_service.get_token_info(token_address)
            
            # 获取代币余额
            balance_service = ChainServiceFactory.get_balance_service('SOL')
            balance = await balance_service.get_token_balance(wallet.address, token_address) if balance_service else Decimal('0')
            
            # 获取代币价格服务
            price_service = ChainServiceFactory.get_price_service('SOL')
            if price_service:
                price_info = await price_service.get_token_price(token_address)
            else:
                price_info = {}
            
            # 组装返回数据
            response_data = {
                'token_address': token_address,
                'symbol': token_info.get('symbol', symbol),
                'name': token_info.get('name', 'Unknown Token'),
                'decimals': token_info.get('decimals', 0),
                'logo': token_info.get('logo', ''),
                'balance': str(balance),
                'price': token_info.get('price', '0'),
                'price_change_24h': token_info.get('price_change_24h', '0'),
                'price_change_7d': token_info.get('price_change_7d', '0'),
                'price_change_30d': token_info.get('price_change_30d', '0'),
                'market_cap': token_info.get('market_cap', '0'),
                'market_cap_rank': token_info.get('market_cap_rank', 0),
                'volume_24h': token_info.get('volume_24h', '0'),
                'volume_change_24h': token_info.get('volume_change_24h', '0'),
                'total_supply': token_info.get('total_supply', '0'),
                'max_supply': token_info.get('max_supply', '0'),
                'circulating_supply': token_info.get('circulating_supply', '0'),
                'ath': token_info.get('ath', '0'),
                'ath_date': token_info.get('ath_date', ''),
                'atl': token_info.get('atl', '0'),
                'atl_date': token_info.get('atl_date', ''),
                'is_native': symbol == 'SOL' and token_address == 'SOL',
                'contract_address': token_info.get('contract_address', token_address),
                'website': token_info.get('website', ''),
                'twitter': token_info.get('twitter', ''),
                'telegram': token_info.get('telegram', ''),
                'discord': token_info.get('discord', ''),
                'description': token_info.get('description', ''),
                'updated_at': str(timezone.now())
            }
            
            # 计算代币余额的美元价值
            try:
                price = Decimal(response_data['price'])
                balance_value = balance * price
                response_data['balance_value'] = str(balance_value)
            except (ValueError, TypeError, decimal.InvalidOperation):
                response_data['balance_value'] = '0'
            
            return Response({
                'status': 'success',
                'data': response_data
            })
            
        except ObjectDoesNotExist as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"获取代币详情失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取代币详情失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='tokens/(?P<token_address>[^/.]+)/ohlcv')
    @async_to_sync_api
    async def token_ohlcv(self, request, pk=None, token_address=None):
        """获取代币的K线数据"""
        try:
            device_id = request.query_params.get('device_id')
            timeframe = request.query_params.get('timeframe', '1h')  # 默认1小时
            limit = int(request.query_params.get('limit', '24'))     # 默认24条数据
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(int(pk), device_id)
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取价格服务
            price_service = ChainServiceFactory.get_price_service('SOL')
            if not price_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL价格服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 获取K线数据
            ohlcv_data = await price_service.get_token_ohlcv(
                token_address=token_address,
                timeframe=timeframe,
                limit=limit
            )
            
            if not ohlcv_data:
                return Response({
                    'status': 'error',
                    'message': '无法获取K线数据'
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'status': 'success',
                'data': {
                    'token_address': token_address,
                    'timeframe': timeframe,
                    'ohlcv': ohlcv_data
                }
            })
            
        except ObjectDoesNotExist as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"获取代币K线数据失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取K线数据失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 