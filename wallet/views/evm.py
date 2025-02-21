from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.parsers import JSONParser
from rest_framework import status
from django.utils import timezone
from decimal import Decimal, InvalidOperation as DecimalInvalidOperation
import logging
from functools import wraps
from typing import Union, Optional, Dict, List, Any, cast
from django.http import Http404
from asgiref.sync import sync_to_async
from django.core.cache import cache
from eth_account import Account
from base58 import b58encode
from django.core.exceptions import ObjectDoesNotExist

from ..models import Wallet, PaymentPassword, Token, Transaction
from ..serializers import WalletSerializer
from ..services.factory import ChainServiceFactory
from ..services.evm.utils import EVMUtils
from django.db.models.functions import Cast
from django.db.models import CharField
from django.db.models import Q
from django.db.models import F
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.functions import Greatest
from django.db.models.functions import Least
from django.db.models.functions import Now
from django.db.models.functions import Trunc
from django.db.models.functions import Extract
from django.db.models.functions import ExtractYear
from django.db.models.functions import ExtractMonth
from django.db.models.functions import ExtractDay
from django.db.models.functions import ExtractHour
from django.db.models.functions import ExtractMinute
from django.db.models.functions import ExtractSecond
from django.db.models.functions import ExtractWeek
from django.db.models.functions import ExtractQuarter
from ..services.evm.nft import EVMNFTService
from ..decorators import verify_payment_password

logger = logging.getLogger(__name__)

def async_to_sync_api(func):
    """异步转同步装饰器"""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        import asyncio
        return asyncio.run(func(*args, **kwargs))
    return wrapper

class EVMWalletViewSet(viewsets.ModelViewSet):
    """EVM钱包视图集"""
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    parser_classes = [JSONParser]
    queryset = Wallet.objects.filter(is_active=True)
    serializer_class = WalletSerializer

    async def get_wallet_async(self, wallet_id: Union[int, str], device_id: Optional[str] = None) -> Wallet:
        """获取钱包"""
        try:
            filters = {'id': int(wallet_id) if isinstance(wallet_id, str) else wallet_id, 'is_active': True}
            if device_id:
                filters['device_id'] = device_id
            
            wallet = await Wallet.objects.aget(**filters)
            if not wallet:
                raise Wallet.DoesNotExist()
            return wallet
        except Wallet.DoesNotExist:
            raise ValueError('钱包不存在')

    @action(detail=True, methods=['get'])
    @async_to_sync_api
    async def native_balance(self, request: Any, pk: Union[int, str]) -> Response:
        """获取原生代币余额"""
        try:
            device_id: Optional[str] = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取余额服务
            balance_service = ChainServiceFactory.get_balance_service(wallet.chain)
            balance = await balance_service.get_native_balance(wallet.address)
            
            return Response({
                'status': 'success',
                'message': '获取余额成功',
                'data': {
                    'balance': str(balance)
                }
            })
            
        except ValueError as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"获取原生代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f"获取原生代币余额失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    @async_to_sync_api
    async def token_balance(self, request: Any, pk: Union[int, str]) -> Response:
        """获取代币余额"""
        try:
            device_id: Optional[str] = request.query_params.get('device_id')
            token_address: Optional[str] = request.query_params.get('token_address')
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            if not token_address:
                return Response({
                    'status': 'error',
                    'message': '缺少token_address参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取余额服务
            balance_service = ChainServiceFactory.get_balance_service(wallet.chain)
            balance = await balance_service.get_token_balance(wallet.address, token_address) # type: ignore

            return Response({
                'status': 'success',
                'data': {
                    'balance': str(balance)
                }
            })

        except Exception as e:
            logger.error(f"获取代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    @async_to_sync_api
    async def tokens(self, request: Any, pk: Union[int, str]) -> Response:
        """获取所有代币余额"""
        try:
            device_id: Optional[str] = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取余额服务
            balance_service = ChainServiceFactory.get_balance_service(wallet.chain)
            tokens = await balance_service.get_all_token_balances(wallet.address)

            return Response({
                'status': 'success',
                'data': tokens
            })

        except Exception as e:
            logger.error(f"获取所有代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    @async_to_sync_api
    @verify_payment_password()
    async def transfer(self, request: Any, pk: Union[int, str]) -> Response:
        """转账接口(支持原生代币和 ERC20 代币)
        
        如果不传 token_address 参数,则转账原生代币
        如果传入 token_address 参数,则转账指定的 ERC20 代币
        """
        try:
            # 获取请求参数
            device_id: Optional[str] = request.data.get('device_id')
            to_address: Optional[str] = request.data.get('to_address')
            amount: Optional[str] = request.data.get('amount')
            payment_password: Optional[str] = request.data.get('payment_password')
            token_address: Optional[str] = request.data.get('token_address')  # 可选参数
            
            # 处理可选的gas参数
            try:
                gas_limit = int(request.data.get('gas_limit')) if request.data.get('gas_limit') and request.data.get('gas_limit').isdigit() else None
                gas_price = int(request.data.get('gas_price')) if request.data.get('gas_price') and request.data.get('gas_price').isdigit() else None
                max_priority_fee = int(request.data.get('max_priority_fee')) if request.data.get('max_priority_fee') and request.data.get('max_priority_fee').isdigit() else None
                max_fee = int(request.data.get('max_fee')) if request.data.get('max_fee') and request.data.get('max_fee').isdigit() else None
            except ValueError:
                return Response({
                    'status': 'error',
                    'message': 'gas参数必须为数字'
                }, status=status.HTTP_400_BAD_REQUEST)

            if not all([device_id, to_address, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 设置支付密码用于解密私钥
            wallet.payment_password = payment_password
            
            # 解密私钥
            try:
                private_key = wallet.decrypt_private_key()
                # 如果返回的是字节类型，则需要转换为十六进制格式
                if isinstance(private_key, bytes):
                    # 确保私钥是32字节长度
                    if len(private_key) != 32:
                        raise ValueError(f'无效的私钥长度: {len(private_key)}字节，期望长度: 32字节')
                    # 转换为十六进制格式，添加0x前缀
                    hex_str = private_key.hex()
                    private_key = '0x' + hex_str
                elif isinstance(private_key, str):
                    # 如果是字符串，确保是有效的十六进制格式
                    hex_str = private_key[2:] if private_key.startswith('0x') else private_key
                    # 移除所有非十六进制字符
                    hex_str = ''.join(c for c in hex_str if c in '0123456789abcdefABCDEF')
                    if len(hex_str) < 64:
                        hex_str = hex_str.zfill(64)
                    private_key = '0x' + hex_str.lower()
                
                # 验证私钥对应的地址是否匹配
                account = Account.from_key(private_key)
                derived_address = account.address
                if derived_address.lower() != wallet.address.lower():
                    raise ValueError(f'私钥地址不匹配: 期望 {wallet.address}, 实际 {derived_address}')
                    
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'解密私钥失败: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取转账服务
            transfer_service = ChainServiceFactory.get_transfer_service(wallet.chain)

            # 根据是否有 token_address 参数决定调用哪个转账方法
            if token_address:
                # ERC20 代币转账
                result = await transfer_service.transfer_token(
                    from_address=wallet.address,
                    to_address=to_address, # type: ignore
                    token_address=token_address,
                    amount=amount, # type: ignore
                    private_key=private_key,
                    gas_limit=gas_limit, # type: ignore
                    gas_price=gas_price, # type: ignore
                    max_priority_fee=max_priority_fee, # type: ignore
                    max_fee=max_fee # type: ignore
                )
            else:
                # 原生代币转账
                result = await transfer_service.transfer_native(
                    from_address=wallet.address,
                    to_address=to_address, # type: ignore
                    amount=amount, # type: ignore
                    private_key=private_key,
                    gas_limit=gas_limit,
                    gas_price=gas_price,
                    max_priority_fee=max_priority_fee,
                    max_fee=max_fee
                )
            
            if result.get('status') == 'error':
                return Response(result, status=400)
                
            return Response(result)
            
        except Exception as e:
            logger.error(f"转账失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f"转账失败: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    @async_to_sync_api
    async def estimate_fee(self, request, pk=None):
        """估算转账费用"""
        try:
            device_id = request.data.get('device_id')
            to_address = request.data.get('to_address')
            amount = request.data.get('amount')
            token_address = request.data.get('token_address')  # 可选参数

            if not all([device_id, to_address, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id) # type: ignore
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取转账服务
            transfer_service = ChainServiceFactory.get_transfer_service(wallet.chain)
            
            # 估算费用
            if token_address:
                result = await transfer_service.estimate_token_transfer_fee( # type: ignore
                    wallet.address,
                    to_address,
                    token_address,
                    amount
                )
            else:
                result = await transfer_service.estimate_native_transfer_fee( # type: ignore
                    wallet.address,
                    to_address,
                    amount
                )
                
            if result.get('status') == 'error': # type: ignore
                return Response(result, status=400)

            return Response({
                'status': 'success',
                'data': result
            })

        except Exception as e:
            logger.error(f"估算转账费用失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path=r'tokens/(?P<token_address>[^/.]+)/detail')
    @async_to_sync_api
    async def token_detail(self, request: Any, pk: Union[int, str], token_address: Optional[str] = None) -> Response:
        """获取代币详情"""
        try:
            device_id: Optional[str] = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id)
            logger.debug(f"请求获取代币详情，钱包地址: {wallet.address}, 代币地址: {token_address}")
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取代币信息服务
            token_info_service = ChainServiceFactory.get_token_info_service(wallet.chain)
            
            try:
                # 获取代币元数据
                token_data = await token_info_service.get_token_metadata(token_address) # type: ignore
                if not token_data:
                    logger.warning(f"从 Moralis 获取代币元数据失败，尝试从合约直接获取: {token_address}")
                    token_data = await token_info_service._get_token_info(token_address) # type: ignore
                
                if not token_data or not token_data.get('name'):
                    return Response({
                        'status': 'error',
                        'message': '获取代币信息失败，该合约可能不是标准的 ERC20 合约'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # 获取代币余额
                try:
                    balance_service = ChainServiceFactory.get_balance_service(wallet.chain)
                    balance_info = await balance_service.get_token_balance(wallet.address, token_address) # type: ignore
                    logger.info(f"获取到代币余额: {balance_info}")
                except Exception as balance_error:
                    logger.error(f"获取代币余额失败: {str(balance_error)}")
                    balance_info = {'balance': '0', 'balance_formatted': '0'}
                
                # 获取代币价格
                try:
                    price_data = await token_info_service.get_token_price(token_address) # type: ignore
                    logger.info(f"获取到代币价格: {price_data}")
                except Exception as price_error:
                    logger.error(f"获取代币价格失败: {str(price_error)}")
                    price_data = {'price_usd': '0', 'price_change_24h': '+0.00%'}
                
                # 计算价值
                try:
                    balance = Decimal(balance_info.get('balance_formatted', '0')) # type: ignore
                    price = Decimal(price_data.get('price_usd', '0'))
                    value = balance * price
                except (DecimalInvalidOperation, TypeError) as calc_error:
                    logger.error(f"计算代币价值失败: {str(calc_error)}")
                    balance = Decimal('0')
                    price = Decimal('0')
                    value = Decimal('0')
                
                return Response({
                    'status': 'success',
                    'message': '获取代币详情成功',
                    'data': {
                        **token_data,
                        'balance': balance_info.get('balance', '0'), # type: ignore
                        'balance_formatted': balance_info.get('balance_formatted', '0'), # type: ignore
                        'price_usd': str(price),
                        'value_usd': str(value),
                        'price_change_24h': price_data.get('price_change_24h', '+0.00%')
                    }
                })
                
            except Exception as token_error:
                logger.error(f"处理代币信息失败: {str(token_error)}")
                return Response({
                    'status': 'error',
                    'message': f'获取代币信息失败: {str(token_error)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(f"获取代币详情失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path=r'tokens/(?P<token_address>[^/.]+)/ohlcv')
    @async_to_sync_api
    async def token_ohlcv(self, request: Any, pk: Union[int, str], token_address: Optional[str] = None) -> Response:
        """获取代币价格走势图数据"""
        try:
            device_id: Optional[str] = request.query_params.get('device_id')
            timeframe: str = request.query_params.get('timeframe', '1h')
            currency: str = request.query_params.get('currency', 'usd')
            from_date: Optional[str] = request.query_params.get('from_date')
            to_date: Optional[str] = request.query_params.get('to_date')
            limit: int = int(request.query_params.get('limit', '24'))
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 验证时间周期参数
            valid_timeframes = ['1h', '1d', '1w', '1m']
            if timeframe not in valid_timeframes:
                return Response({
                    'status': 'error',
                    'message': f'无效的timeframe参数，有效值为: {", ".join(valid_timeframes)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取并验证钱包
            wallet = await self.get_wallet_async(pk, device_id)
            logger.debug(f"请求获取代币价格走势图，钱包地址: {wallet.address}, 代币地址: {token_address}")
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取代币信息服务
            token_info_service = ChainServiceFactory.get_token_info_service(wallet.chain)
            if not token_info_service:
                return Response({
                    'status': 'error',
                    'message': '代币信息服务不可用'
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # 获取价格走势数据
            ohlcv_data = await token_info_service.get_token_ohlcv(
                token_address, # type: ignore
                timeframe=timeframe,
                currency=currency,
                from_date=from_date,
                to_date=to_date,
                limit=limit
            )
            
            if not ohlcv_data:
                return Response({
                    'status': 'error',
                    'message': '获取价格走势数据失败'
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'status': 'success',
                'data': ohlcv_data
            })
            
        except Exception as e:
            logger.error(f"获取代币价格走势图数据失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取代币价格走势图数据失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='token-transfers')
    @async_to_sync_api
    async def token_transfers(self, request: Any, pk: Union[int, str]) -> Response:
        """获取代币转账记录"""
        try:
            device_id: Optional[str] = request.query_params.get('device_id')
            page: int = int(request.query_params.get('page', 1))
            page_size: int = int(request.query_params.get('page_size', 20))
            
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 定义同步函数来处理数据库操作
            @sync_to_async
            def get_transfers():
                # 移除 tx_type 过滤，显示所有类型的交易
                transfers_qs = Transaction.objects.filter(
                    wallet=wallet
                ).order_by('-block_timestamp', '-id')
                
                total_count = transfers_qs.count()
                
                # 分页
                start = (page - 1) * page_size
                end = start + page_size
                
                transfers = list(transfers_qs[start:end])
                
                # 格式化数据
                transfer_list = []
                for transfer in transfers:
                    transfer_data = {
                        'tx_hash': transfer.tx_hash,
                        'tx_type': transfer.tx_type,
                        'status': transfer.status,
                        'from_address': transfer.from_address,
                        'to_address': transfer.to_address,
                        'amount': str(transfer.amount),
                        'token_address': transfer.token.address if transfer.token else None,
                        'token_info': transfer.token_info,
                        'gas_price': str(transfer.gas_price),
                        'gas_used': str(transfer.gas_used),
                        'block_number': transfer.block_number,
                        'block_timestamp': transfer.block_timestamp.isoformat() if transfer.block_timestamp else None,
                        'explorer_url': EVMUtils.get_explorer_url(wallet.chain, transfer.tx_hash)
                    }
                    transfer_list.append(transfer_data)
                
                return total_count, transfer_list

            # 获取转账记录
            total_count, transfer_list = await get_transfers()

            return Response({
                'status': 'success',
                'data': {
                    'total': total_count,
                    'page': page,
                    'page_size': page_size,
                    'transfers': transfer_list
                }
            })
            
        except Exception as e:
            logger.error(f"获取代币转账记录失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取代币转账记录失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='swap/quote', url_name='swap-quote')
    @async_to_sync_api
    async def swap_quote(self, request: Any, pk: Union[int, str]) -> Response:
        """获取兑换报价"""
        try:
            # 验证参数
            device_id: Optional[str] = request.data.get('device_id')
            from_token: Optional[str] = request.data.get('from_token')
            to_token: Optional[str] = request.data.get('to_token')
            amount: Optional[str] = request.data.get('amount')
            slippage: float = float(request.data.get('slippage', 1.0))
            
            if not all([device_id, from_token, to_token, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)
            
            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=400)
            
            # 获取 Swap 服务
            swap_service = ChainServiceFactory.get_swap_service(wallet.chain)
            
            # 获取报价
            quote = await swap_service.get_quote(
                from_token=from_token, # type: ignore
                to_token=to_token, # type: ignore
                amount=amount, # type: ignore
                slippage=slippage
            ) # type: ignore
            
            if not quote:
                return Response({
                    'status': 'error',
                    'message': '获取报价失败'
                }, status=400)
            
            return Response(quote)
            
        except Exception as e:
            logger.error(f"获取兑换报价失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f"获取报价失败: {str(e)}"
            }, status=400)

    @action(detail=True, methods=['post'], url_path='swap/execute')
    @async_to_sync_api
    @verify_payment_password()
    async def swap_execute(self, request: Any, pk: Union[int, str]) -> Response:
        """执行代币兑换"""
        try:
            device_id: Optional[str] = request.data.get('device_id')
            from_token: Optional[str] = request.data.get('from_token')
            to_token: Optional[str] = request.data.get('to_token')
            amount: Optional[str] = request.data.get('amount')
            payment_password: Optional[str] = request.data.get('payment_password')
            slippage: float = float(request.data.get('slippage', 1.0))
            
            if not all([device_id, from_token, to_token, amount]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 设置支付密码用于解密私钥
            wallet.payment_password = payment_password
            
            # 解密私钥
            try:
                private_key = wallet.decrypt_private_key()
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'解密私钥失败: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取 Swap 服务
            swap_service = ChainServiceFactory.get_swap_service(wallet.chain)
            
            # 执行兑换
            result = await swap_service.execute_swap(
                from_token, # type: ignore
                to_token, # type: ignore
                amount, # type: ignore
                wallet.address, # type: ignore
                private_key,
                slippage # type: ignore
            )
            
            if result.get('status') == 'error':
                return Response(result, status=400)

            return Response(result)
            
        except Exception as e:
            logger.error(f"执行代币兑换失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='swap/tokens')
    @async_to_sync_api
    async def swap_tokens(self, request: Any, pk: Union[int, str]) -> Response:
        """获取支持的代币列表"""
        try:
            device_id: Optional[str] = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少device_id参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链类型'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取 Swap 服务
            swap_service = ChainServiceFactory.get_swap_service(wallet.chain)
            
            # 获取支持的代币列表
            tokens = await swap_service.get_supported_tokens()# type: ignore

            return Response({
                'status': 'success',
                'data': tokens
            })
            
        except Exception as e:
            logger.error(f"获取支持的代币列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get', 'post'], url_path='swap/allowance')
    @async_to_sync_api
    async def swap_allowance(self, request: Any, pk: Union[int, str]) -> Response:
        """获取代币授权额度"""
        try:
            # 根据请求方法获取参数
            if request.method == 'GET':
                device_id: Optional[str] = request.query_params.get('device_id')
                token_address: Optional[str] = request.query_params.get('token_address')
                spender: Optional[str] = request.query_params.get('spender')
            else:
                device_id = request.data.get('device_id')
                token_address = request.data.get('token_address')
                spender = request.data.get('spender')
            
            if not all([device_id, token_address, spender]):
                return Response({
                    'status': 'error',
                    'message': '缺少必要参数'
                }, status=400)
            
            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链'
                }, status=400)
            
            # 获取授权额度
            try:
                swap_service = ChainServiceFactory.get_swap_service(wallet.chain)
                allowance = await swap_service.get_token_allowance( # type: ignore
                    token_address, # type: ignore
                    wallet.address,
                    spender # type: ignore
                )
                
                return Response({
                    'status': 'success',
                    'message': '获取授权额度成功',
                    'data': {
                        'allowance': allowance
                    }
                })
                
            except Exception as e:
                logger.error(f"获取授权额度失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'获取授权额度失败: {str(e)}'
                }, status=400)
            
        except Exception as e:
            logger.error(f"获取授权额度失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=400)

    @action(detail=True, methods=['POST'], url_path='swap/approve')
    @async_to_sync_api
    @verify_payment_password()
    async def swap_approve(self, request: Any, pk: Union[int, str]) -> Response:
        """授权代币"""
        try:
            device_id: Optional[str] = request.data.get('device_id')
            token_address: Optional[str] = request.data.get('token_address')
            spender: Optional[str] = request.data.get('spender')
            amount: Optional[str] = request.data.get('amount')
            payment_password: Optional[str] = request.data.get('payment_password')
            
            if not all([device_id, token_address, spender, amount]):
                return Response({
                    'status': 'error',
                    'message': '参数不完整'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链'
                }, status=status.HTTP_400_BAD_REQUEST)
                
            # 设置支付密码用于解密私钥
            wallet.payment_password = payment_password
            
            # 解密私钥
            try:
                private_key = wallet.decrypt_private_key()
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f'解密私钥失败: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 构建授权交易
            swap_service = ChainServiceFactory.get_swap_service(wallet.chain)
            tx = await swap_service.build_approve_transaction(# type: ignore
                token_address,# type: ignore
                spender,# type: ignore
                amount,# type: ignore
                wallet.address
            ) 
            
            if tx.get('status') == 'error':
                return Response(tx, status=400)
            
            # 发送交易
            result = await swap_service._send_transaction(tx, private_key)# type: ignore
            
            if result.get('status') == 'error':
                return Response(result, status=400)
            
            return Response(result)
            
        except Exception as e:
            logger.error(f"授权失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'授权失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='tokens/manage')
    @async_to_sync_api
    async def manage_tokens(self, request: Any, pk: Union[int, str]) -> Response:
        """获取所有代币列表（包括隐藏的）"""
        try:
            # 获取请求参数
            device_id: Optional[str] = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
                
            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链'
                }, status=400)
            
            # 获取余额服务
            balance_service = ChainServiceFactory.get_balance_service(wallet.chain)
            
            # 获取所有代币余额，包括隐藏的
            balances = await balance_service.get_all_token_balances(wallet.address, include_hidden=True)# type: ignore
            
            return Response({
                'status': 'success',
                'data': balances['tokens']
            })
            
        except Exception as e:
            logger.error(f"获取代币管理列表失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取代币管理列表失败'
            }, status=500)

    @action(detail=True, methods=['post'], url_path='tokens/toggle-visibility')
    @async_to_sync_api
    async def toggle_token_visibility(self, request: Any, pk: Union[int, str]) -> Response:
        """切换代币的显示状态"""
        try:
            # 获取请求参数
            device_id: Optional[str] = request.query_params.get('device_id')
            if not device_id:
                return Response({
                    'status': 'error',
                    'message': '缺少设备ID'
                }, status=400)
                
            token_address: Optional[str] = request.data.get('token_address')
            if not token_address:
                return Response({
                    'status': 'error',
                    'message': '缺少代币地址'
                }, status=400)
                
            # 获取钱包
            wallet = await self.get_wallet_async(pk, device_id)
            
            # 验证是否是EVM链
            if wallet.chain not in EVMUtils.CHAIN_CONFIG:
                return Response({
                    'status': 'error',
                    'message': '不支持的链'
                }, status=400)
            
            # 查找并更新代币
            try:
                token, created = await sync_to_async(Token.objects.get_or_create)(
                    chain=wallet.chain,
                    address=token_address,
                    defaults={
                        'is_visible': True,  # 默认可见
                        'name': '',  # 这些字段可以稍后更新
                        'symbol': '',
                        'decimals': 18
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