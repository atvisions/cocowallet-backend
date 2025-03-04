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

from ..models import Wallet, Token, Transaction, PaymentPassword
from ..serializers import WalletSerializer
from ..services.factory import ChainServiceFactory
from ..api_config import RPCConfig, MoralisConfig, HeliusConfig
from ..decorators import verify_payment_password

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
            wallet = await self.get_wallet_async(int(pk), device_id) # type: ignore
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
            result = await balance_service.get_all_token_balances(wallet.address, include_hidden=False) # type: ignore
            
            # 返回结果
            return Response({
                'status': 'success',
                'data': result
            })
            
        except WalletNotFoundError: # type: ignore
            return Response({
                'status': 'error',
                'message': '钱包不存在'
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
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            
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
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            
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
            balance = await balance_service.get_token_balance(wallet.address, token_address) # type: ignore
            
            # 获取代币信息服务
            token_info_service = ChainServiceFactory.get_token_info_service('SOL')
            token_info = await token_info_service.get_token_info(token_address) if token_info_service else {} # type: ignore
            
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
            logger.error(f"获取SOL代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取代币余额失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='tokens/toggle-visibility')
    @async_to_sync_api
    async def toggle_token_visibility(self, request, pk=None):
        """切换代币的显示状态"""
        try:
            # 获取请求参数
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
                
            token_address = request.data.get('token_address')
            if not token_address:
                return Response({
                    'status': 'error',
                    'message': '缺少代币地址'
                }, status=400)
                
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=400)
            
            # 查找并更新代币
            try:
                token, created = await sync_to_async(Token.objects.get_or_create)(
                    chain='SOL',
                    address=token_address,
                    defaults={
                        'is_visible': True,  # 默认可见
                        'name': '',  # 这些字段可以稍后更新
                        'symbol': '',
                        'decimals': 9
                    }
                )
                token.is_visible = not token.is_visible
                await sync_to_async(token.save)()
                
                return Response({
                    'status': 'success',
                    'message': '更新成功',
                    'data': {
                        'token_address': token.address,
                        'is_visible': token.is_visible
                    }
                })
            except Exception as e:
                logger.error(f"更新代币显示状态失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': '更新代币显示状态失败'
                }, status=500)
                
        except Exception as e:
            logger.error(f"切换代币显示状态失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '切换代币显示状态失败'
            }, status=500)

    @action(detail=True, methods=['get'], url_path=r'tokens/SOL/(?P<token_address>[^/.]+)/detail')
    @async_to_sync_api
    async def token_detail(self, request, pk=None, token_address=None):
        """获取代币详情"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            logger.debug(f"请求获取代币详情，钱包地址: {wallet.address}, 代币地址: {token_address}")
            
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
            
            try:
                # 获取代币元数据
                token_data = await token_info_service.get_token_metadata(token_address) # type: ignore
                if not token_data:
                    logger.warning(f"从 Moralis 获取代币元数据失败，尝试从合约直接获取: {token_address}")
                    token_data = await token_info_service.get_token_info(token_address) # type: ignore
                
                if not token_data or not token_data.get('name'):
                    return Response({
                        'status': 'error',
                        'message': '获取代币信息失败，该代币可能不存在'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 获取代币余额
                try:
                    balance_service = ChainServiceFactory.get_balance_service('SOL')
                    if not balance_service:
                        raise ValueError('SOL余额服务不可用')
                        
                    balance_info = await balance_service.get_token_balance(wallet.address, token_address) # type: ignore
                    logger.info(f"获取到代币余额: {balance_info}")
                    
                    # 确保余额数据格式正确
                    if isinstance(balance_info, (int, float, str, Decimal)):
                        balance = str(balance_info)
                        balance_formatted = str(balance_info)
                    elif isinstance(balance_info, dict):
                        balance = str(balance_info.get('balance', '0'))
                        balance_formatted = str(balance_info.get('balance_formatted', '0'))
                    else:
                        balance = '0'
                        balance_formatted = '0'
                        
                except Exception as balance_error:
                    logger.error(f"获取代币余额失败: {str(balance_error)}")
                    balance = '0'
                    balance_formatted = '0'
                
                # 计算价值
                try:
                    balance_decimal = Decimal(balance_formatted)
                    price_decimal = Decimal(token_data.get('price_usd', '0'))
                    value = balance_decimal * price_decimal
                    value_str = str(value)
                except Exception as calc_error:
                    logger.error(f"计算代币价值失败: {str(calc_error)}")
                    value_str = '0'
                
                return Response({
                    'status': 'success',
                    'message': '获取代币详情成功',
                    'data': {
                        **token_data,
                        'balance': balance,
                        'balance_formatted': balance_formatted,
                        'value_usd': value_str
                    }
                })
                
            except Exception as token_error:
                logger.error(f"处理代币信息失败: {str(token_error)}")
                return Response({
                    'status': 'error',
                    'message': f'获取代币信息失败: {str(token_error)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
        except ObjectDoesNotExist as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"获取代币详情失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path=r'tokens/(?P<token_address>[^/.]+)/ohlcv')
    @async_to_sync_api
    async def token_ohlcv(self, request, pk=None, token_address=None):
        """获取代币价格走势图数据"""
        try:
            logger.debug(f"收到 OHLCV 请求: pk={pk}, token_address={token_address}, params={request.query_params}")
            logger.debug(f"请求路径: {request.path}")
            logger.debug(f"请求方法: {request.method}")
            logger.debug(f"请求头: {request.headers}")
            logger.debug(f"请求URL: {request.build_absolute_uri()}")
            logger.debug(f"请求解析的参数: {request.resolver_match.kwargs if request.resolver_match else None}")
            device_id = request.query_params.get('device_id')
            timeframe = request.query_params.get('timeframe', '1h')
            currency = request.query_params.get('currency', 'usd')
            from_date = request.query_params.get('from_date')
            to_date = request.query_params.get('to_date')
            limit = int(request.query_params.get('limit', '24'))
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not pk or not token_address:
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(int(pk), device_id)
            logger.debug(f"请求获取代币价格走势图，钱包地址: {wallet.address}, 代币地址: {token_address}")
            
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
            
            # 获取价格走势图数据
            try:
                ohlcv_data = await token_info_service.get_token_ohlcv( # type: ignore
                    token_address,
                    timeframe=timeframe,
                    currency=currency,
                    from_date=from_date,
                    to_date=to_date,
                    limit=limit
                )
                logger.debug(f"获取到的OHLCV数据: {ohlcv_data}")
                
                if not ohlcv_data or not ohlcv_data.get('data'):
                    logger.error("OHLCV数据为空")
                    return Response({
                        'status': 'error',
                        'message': '无法获取价格走势图数据'
                    }, status=status.HTTP_404_NOT_FOUND)
                
                return Response({
                    'status': 'success',
                    'data': ohlcv_data
                })
                
            except Exception as e:
                logger.error(f"获取OHLCV数据时出错: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': '无法获取价格走势图数据'
                }, status=status.HTTP_404_NOT_FOUND)
            
        except ObjectDoesNotExist as e:
            logger.error(f"找不到钱包或代币: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"获取代币价格走势图失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取价格走势图失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    @async_to_sync_api
    @verify_payment_password()
    async def transfer(self, request, pk=None):
        """转账接口"""
        try:
            device_id = request.data.get('device_id')
            to_address = request.data.get('to_address')
            amount = request.data.get('amount')
            token_address = request.data.get('token_address')
            payment_password = request.data.get('payment_password')
            token_info = request.data.get('token_info')  # 从请求中获取代币信息
            
            if not all([device_id, to_address, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(int(pk), device_id)
            logger.debug(f"请求转账，钱包地址: {wallet.address}, 接收地址: {to_address}, 金额: {amount}")
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 设置支付密码用于解密私钥
            wallet.payment_password = payment_password
            
            try:
                # 获取私钥
                private_key = wallet.decrypt_private_key()
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'解密私钥失败: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取转账服务
            transfer_service = ChainServiceFactory.get_transfer_service('SOL')
            if not transfer_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL转账服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 执行转账
            try:
                async with transfer_service:  # 使用异步上下文管理器
                    if token_address:
                        # SPL代币转账
                        result = await transfer_service.transfer_token(
                            from_address=wallet.address,
                            to_address=to_address,
                            token_address=token_address,
                            amount=Decimal(amount),
                            private_key=private_key
                        )
                    else:
                        # SOL原生代币转账
                        result = await transfer_service.transfer_native(
                            from_address=wallet.address,
                            to_address=to_address,
                            amount=Decimal(amount),
                            private_key=private_key
                        )
                
                if result.get('success'):
                    # 创建交易记录
                    tx_data = {
                        'wallet': wallet,
                        'chain': 'SOL',
                        'tx_hash': result['transaction_hash'],
                        'tx_type': 'TRANSFER',
                        'status': 'SUCCESS',
                        'from_address': wallet.address,
                        'to_address': to_address,
                        'amount': Decimal(amount),
                        'gas_price': Decimal(result.get('fee', '0')),
                        'gas_used': Decimal('1'),
                        'block_number': result.get('block_slot', 0),
                        'block_timestamp': timezone.now()
                    }

                    # 如果是代币转账,添加代币信息
                    if token_address:
                        try:
                            token = await Token.objects.aget(chain='SOL', address=token_address)
                            tx_data['token'] = token
                        except Token.DoesNotExist:
                            # 如果代币不存在,只保存代币地址
                            tx_data['token_address'] = token_address
                        
                        if token_info:
                            tx_data['token_info'] = token_info

                    # 创建交易记录
                    await Transaction.objects.acreate(**tx_data)
                    
                    return Response({
                        'status': 'success',
                        'data': {
                            'transaction_hash': result.get('transaction_hash'),
                            'block_hash': result.get('block_hash'),
                            'fee': result.get('fee')
                        }
                    })
                else:
                    return Response({
                        'status': 'error',
                        'message': result.get('error') or '转账失败'
                    }, status=status.HTTP_400_BAD_REQUEST)
                    
            except Exception as e:
                logger.error(f"执行转账时出错: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'转账失败: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except ObjectDoesNotExist as e:
            logger.error(f"找不到钱包: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"转账失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'转账失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    @async_to_sync_api
    async def estimate_fee(self, request, pk=None):
        """估算转账费用"""
        try:
            device_id = request.data.get('device_id')
            to_address = request.data.get('to_address')
            amount = request.data.get('amount')
            token_address = request.data.get('token_address')
            
            if not all([device_id, to_address, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(int(pk), device_id) # type: ignore
            logger.debug(f"请求估算转账费用，钱包地址: {wallet.address}, 接收地址: {to_address}, 金额: {amount}")
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取转账服务
            transfer_service = ChainServiceFactory.get_transfer_service('SOL')
            if not transfer_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL转账服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 估算费用
            try:
                if token_address:
                    # SPL代币转账费用
                    fee = await transfer_service.estimate_token_transfer_fee( # type: ignore
                        from_address=wallet.address,
                        to_address=to_address,
                        token_address=token_address,
                        amount=amount
                    )
                else:
                    # SOL原生代币转账费用
                    fee = await transfer_service.estimate_native_transfer_fee( # type: ignore
                        from_address=wallet.address,
                        to_address=to_address,
                        amount=amount
                    )
                
                return Response({
                    'status': 'success',
                    'data': {
                        'fee': str(fee)
                    }
                })
                
            except Exception as e:
                logger.error(f"估算转账费用时出错: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'估算费用失败: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except ObjectDoesNotExist as e:
            logger.error(f"找不到钱包: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"估算费用失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'估算费用失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='swap/quote')
    @async_to_sync_api
    async def get_swap_quote(self, request, pk=None):
        """获取代币兑换报价"""
        try:
            device_id = request.query_params.get('device_id')
            from_token = request.query_params.get('from_token')
            to_token = request.query_params.get('to_token')
            amount = request.query_params.get('amount')
            slippage = request.query_params.get('slippage')
            
            if not all([device_id, from_token, to_token, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取 Swap 服务
            swap_service = ChainServiceFactory.get_swap_service('SOL') # type: ignore
            if not swap_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL Swap服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 获取兑换报价
            quote = await swap_service.get_swap_quote( # type: ignore
                from_token=from_token,
                to_token=to_token,
                amount=Decimal(str(amount)),
                slippage=Decimal(str(slippage)) if slippage else None
            )
            
            return Response({
                'status': 'success',
                'data': quote
            })
            
        except ObjectDoesNotExist as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"获取兑换报价失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取兑换报价失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'], url_path='swap/execute')
    @async_to_sync_api
    @verify_payment_password()
    async def swap_execute(self, request, pk=None):
        """执行代币兑换"""
        try:
            device_id = request.data.get('device_id')
            quote_id = request.data.get('quote_id')
            from_token = request.data.get('from_token')
            to_token = request.data.get('to_token')
            amount = request.data.get('amount')
            payment_password = request.data.get('payment_password')
            slippage = request.data.get('slippage')
            
            if not all([device_id, quote_id, from_token, to_token, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持SOL链钱包'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 设置支付密码
            wallet.payment_password = payment_password
            
            # 获取私钥
            try:
                private_key = wallet.decrypt_private_key()
            except Exception as e:
                return Response({
                    'status': 'error',
                    'message': f'解密私钥失败: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取 Swap 服务
            swap_service = ChainServiceFactory.get_swap_service('SOL') # type: ignore
            if not swap_service:
                return Response({
                    'status': 'error',
                    'message': 'SOL Swap服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 执行兑换
            result = await swap_service.execute_swap( # type: ignore
                quote_id=quote_id, # type: ignore
                from_token=from_token,
                to_token=to_token,
                amount=Decimal(str(amount)),
                from_address=wallet.address,
                private_key=private_key,
                slippage=Decimal(str(slippage)) if slippage else None
            )
            
            # 创建交易记录
            # 获取交易详情
            client = AsyncClient(RPCConfig.SOLANA_MAINNET_RPC_URL)
            try:
                tx_info = await client.get_transaction(
                    result['tx_hash'],
                    commitment=Commitment("confirmed")
                )
                if tx_info and 'result' in tx_info:
                    tx_result = tx_info['result']
                    block_number = tx_result.get('slot', 0)
                    gas_fee = tx_result.get('meta', {}).get('fee', 0)
                    gas_price = Decimal(str(gas_fee / 1e9))  # 转换为 SOL
                else:
                    block_number = 0
                    gas_price = Decimal('0')
            except Exception as e:
                logger.error(f"获取交易详情失败: {str(e)}")
                block_number = 0
                gas_price = Decimal('0')
            finally:
                await client.close()

            # 获取代币信息
            try:
                token = await sync_to_async(Token.objects.get)(chain='SOL', address=from_token)
            except Token.DoesNotExist:
                token = None
                logger.warning(f"找不到代币信息: {from_token}")

            # 创建交易记录
            await sync_to_async(Transaction.objects.create)(
                wallet=wallet,
                chain='SOL',
                tx_hash=result['tx_hash'],
                tx_type='SWAP',
                status='SUCCESS',
                from_address=wallet.address,
                to_address='Jupiter',  # 使用固定值，因为是通过Jupiter DEX进行的交易
                amount=Decimal(str(result['amount_in'])),
                gas_price=gas_price,
                gas_used=Decimal('1'),
                block_number=block_number,
                block_timestamp=timezone.now(),
                token=token,
                token_info={  # 添加代币信息
                    'address': from_token,
                    'name': 'Solana',
                    'symbol': 'SOL',
                    'decimals': 9,
                    'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
                } if from_token == 'So11111111111111111111111111111111111111112' else None
            )
            
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
            logger.error(f"执行兑换失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'执行兑换失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='token-transfers')
    @async_to_sync_api
    async def token_transfers(self, request, pk=None):
        """获取代币转账记录"""
        try:
            # 获取请求参数
            device_id = request.query_params.get('device_id')
            page = int(request.query_params.get('page', '1'))
            page_size = int(request.query_params.get('page_size', '20'))
            token_address = request.query_params.get('token_address')
            tx_type = request.query_params.get('tx_type')
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 计算分页
            start = (page - 1) * page_size
            end = start + page_size
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(int(pk), device_id) # type: ignore
            logger.debug(f"请求获取转账记录，钱包地址: {wallet.address}")
            
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '不支持的链'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 构建查询条件
            from django.db.models import Q
            
            base_query = Q(chain='SOL', status='SUCCESS')
            wallet_query = Q(wallet=wallet) | Q(to_address=wallet.address)  # 包含作为发送方和接收方的交易
            
            query = base_query & wallet_query
            
            if token_address:
                query &= Q(token__address=token_address)
            if tx_type:
                query &= Q(tx_type=tx_type)
            
            # 获取总记录数
            total_count = await Transaction.objects.filter(query).acount() # type: ignore
            
            # 获取交易记录
            transactions = []
            async for tx in Transaction.objects.filter(query).order_by('-block_timestamp')[start:end].select_related('token', 'nft_collection'): # type: ignore
                # 判断交易方向
                is_received = tx.to_address == wallet.address
                
                # 基础交易数据
                tx_data = {
                    'tx_hash': tx.tx_hash,
                    'tx_type': tx.tx_type,
                    'status': tx.status,
                    'from_address': tx.from_address,
                    'to_address': tx.to_address,
                    'amount': tx.amount,
                    'direction': 'RECEIVED' if is_received else 'SENT',
                    'gas_price': tx.gas_price,
                    'gas_used': tx.gas_used,
                    'gas_fee': str(tx.gas_price * tx.gas_used) if tx.gas_price and tx.gas_used else '0',
                    'block_number': tx.block_number,
                    'block_timestamp': tx.block_timestamp,
                    'created_at': tx.created_at,
                }

                # 添加代币信息
                if tx.tx_type == 'TRANSFER':
                    if tx.token:
                        tx_data['token'] = {
                            'address': tx.token.address,
                            'name': tx.token.name,
                            'symbol': tx.token.symbol,
                            'decimals': tx.token.decimals,
                            'logo': tx.token.logo if tx.token.logo else f'https://d23exngyjlavgo.cloudfront.net/solana_{tx.token.address}'
                        }
                    elif tx.token_info:  # 使用 token_info 字段
                        tx_data['token'] = tx.token_info
                    else:  # 默认SOL代币信息
                        tx_data['token'] = {
                            'address': 'So11111111111111111111111111111111111111112',
                            'name': 'Solana',
                            'symbol': 'SOL',
                            'decimals': 9,
                            'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
                        }
                elif tx.tx_type == 'SWAP':
                    # 添加源代币信息
                    if tx.token:
                        tx_data['from_token'] = {
                            'address': tx.token.address,
                            'name': tx.token.name,
                            'symbol': tx.token.symbol,
                            'decimals': tx.token.decimals,
                            'logo': tx.token.logo if tx.token.logo else f'https://d23exngyjlavgo.cloudfront.net/solana_{tx.token.address}'
                        }
                    elif tx.token_info:  # 使用 token_info 字段
                        tx_data['from_token'] = tx.token_info
                    
                    # 添加目标代币信息（从 token_info 中获取）
                    if hasattr(tx, 'token_info') and tx.token_info and 'to_token' in tx.token_info:
                        tx_data['to_token'] = tx.token_info['to_token']
                    else:
                        # 默认 SOL 代币信息
                        tx_data['to_token'] = {
                            'address': 'So11111111111111111111111111111111111111112',
                            'name': 'Solana',
                            'symbol': 'SOL',
                            'decimals': 9,
                            'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
                        }
                elif tx.tx_type == 'NFT_TRANSFER' and tx.nft_collection:
                    tx_data['nft'] = {
                        'token_id': tx.nft_token_id,
                        'collection_name': tx.nft_collection.name,
                        'collection_symbol': tx.nft_collection.symbol,
                        'logo': tx.nft_collection.logo,
                        'is_verified': tx.nft_collection.is_verified
                    }

                transactions.append(tx_data)
            
            return Response({
                'status': 'success',
                'data': {
                    'total': total_count,
                    'page': page,
                    'page_size': page_size,
                    'transactions': transactions
                }
            })
            
        except Exception as e:
            logger.error(f"获取转账记录失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取转账记录失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='recommended-tokens')
    @async_to_sync_api
    async def recommended_tokens(self, request):
        """获取推荐代币列表"""
        try:
            # 从请求参数获取链类型
            chain = request.query_params.get('chain', 'SOL')
            
            # 验证链类型
            if chain not in ['SOL', 'ETH', 'BASE']:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 从数据库获取推荐代币
            recommended_tokens = await sync_to_async(list)(Token.objects.filter(
                chain=chain,
                is_recommended=True,
                is_visible=True
            ).order_by('-created_at'))

            # 转换为列表
            tokens = []
            for token in recommended_tokens:
                # 格式化价格
                price_usd = token.last_price or '0'
                try:
                    price = float(price_usd)
                    if price < 0.00001:
                        formatted_price = '{:.8f}'.format(price)
                    elif price < 0.01:
                        formatted_price = '{:.6f}'.format(price)
                    else:
                        formatted_price = '{:.4f}'.format(price)
                    formatted_price = formatted_price.rstrip('0').rstrip('.')
                except (ValueError, TypeError):
                    formatted_price = '0'

                # 格式化价格变化
                price_change = token.last_price_change or '0'
                try:
                    change = float(price_change)
                    formatted_change = '{:+.2f}%'.format(change)
                except (ValueError, TypeError):
                    formatted_change = '+0.00%'

                tokens.append({
                    'token_address': token.address,
                    'symbol': token.symbol,
                    'name': token.name,
                    'decimals': token.decimals,
                    'logo': token.logo,
                    'price_usd': formatted_price,
                    'price_change_24h': formatted_change,
                    'is_native': token.is_native,
                    'verified': token.verified,
                    'description': token.description,
                    'website': token.website,
                    'twitter': token.twitter,
                    'telegram': token.telegram,
                    'discord': token.discord
                })

            return Response({
                'status': 'success',
                'data': tokens
            })

        except Exception as e:
            logger.error(f"获取推荐代币失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取推荐代币失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='tokens/manage')
    @async_to_sync_api
    async def manage_tokens(self, request, pk=None):
        """获取代币管理列表（包括隐藏的代币）"""
        try:
            device_id = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=400)
                
            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            
            # 验证是否是 Solana 链
            if wallet.chain != 'SOL':
                return Response({
                    'status': 'error',
                    'message': '该接口仅支持 Solana 链钱包'
                }, status=400)
            
            # 获取余额服务
            balance_service = ChainServiceFactory.get_balance_service(wallet.chain)
            
            # 获取所有代币余额，包括隐藏的
            balances = await balance_service.get_all_token_balances(wallet.address, include_hidden=True) # type: ignore
            
            return Response({
                'status': 'success',
                'message': '获取成功',
                'data': balances
            })
            
        except Exception as e:
            logger.error(f"获取代币管理列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取代币管理列表失败'
            }, status=500)

    @action(detail=True, methods=['get'], url_path='transaction-status')
    @async_to_sync_api
    async def transaction_status(self, request, pk=None):
        """获取交易状态"""
        try:
            device_id = request.query_params.get('device_id')
            tx_hash = request.query_params.get('tx_hash')
            
            if not device_id or not tx_hash:
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)
                
            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            if not wallet:
                return Response({
                    'status': 'error',
                    'message': '钱包不存在'
                }, status=404)
                
            # 获取交易服务
            chain_service = ChainServiceFactory.get_service(wallet.chain, 'transfer')
            
            # 获取交易状态
            tx_status = await chain_service.get_transaction_status(tx_hash)
            
            return Response({
                'status': 'success',
                'data': tx_status
            })
            
        except Exception as e:
            logger.error(f"获取交易状态失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=400)

   