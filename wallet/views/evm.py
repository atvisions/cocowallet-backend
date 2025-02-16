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
from typing import Union, Optional, Dict, List
from django.http import Http404
from asgiref.sync import sync_to_async
from django.core.cache import cache
from eth_account import Account
from base58 import b58encode

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

logger = logging.getLogger(__name__)

def async_to_sync_api(func):
    """异步转同步装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        import asyncio
        return asyncio.run(func(*args, **kwargs))
    return wrapper

class EVMWalletViewSet(viewsets.ModelViewSet):
    """EVM钱包视图集"""
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    parser_classes = [JSONParser]

    async def get_wallet_async(self, wallet_id: int, device_id: str = None) -> Wallet:
        """获取钱包"""
        try:
            filters = {'id': wallet_id, 'is_active': True}
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
    async def native_balance(self, request, pk=None):
        """获取原生代币余额"""
        try:
            device_id = request.query_params.get('device_id')
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
            balance = await balance_service.get_native_balance(wallet.address)

            return Response({
                'status': 'success',
                'data': {
                    'balance': str(balance),
                    'symbol': EVMUtils.CHAIN_CONFIG[wallet.chain]['symbol']
                }
            })

        except Exception as e:
            logger.error(f"获取原生代币余额失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    @async_to_sync_api
    async def token_balance(self, request, pk=None):
        """获取代币余额"""
        try:
            device_id = request.query_params.get('device_id')
            token_address = request.query_params.get('token_address')
            
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
            balance = await balance_service.get_token_balance(wallet.address, token_address)

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
    async def tokens(self, request, pk=None):
        """获取所有代币余额"""
        try:
            device_id = request.query_params.get('device_id')
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
    async def transfer(self, request, pk=None):
        """转账接口(支持原生代币和 ERC20 代币)
        
        如果不传 token_address 参数,则转账原生代币
        如果传入 token_address 参数,则转账指定的 ERC20 代币
        """
        try:
            # 获取请求参数
            device_id = request.data.get('device_id')
            to_address = request.data.get('to_address')
            amount = request.data.get('amount')
            payment_password = request.data.get('payment_password')
            token_address = request.data.get('token_address')  # 可选参数
            
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

            if not all([device_id, to_address, amount, payment_password]):
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

            # 验证支付密码
            payment_pwd = await sync_to_async(PaymentPassword.objects.filter(
                device_id=device_id
            ).first)()
            
            if not payment_pwd or not payment_pwd.verify_password(payment_password):
                return Response({
                    'status': 'error',
                    'message': '支付密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取转账服务
            transfer_service = ChainServiceFactory.get_transfer_service(wallet.chain)
            
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

            # 根据是否有 token_address 参数决定调用哪个转账方法
            if token_address:
                # ERC20 代币转账
                result = await transfer_service.transfer_token(
                    from_address=wallet.address,
                    to_address=to_address,
                    token_address=token_address,
                    amount=amount,
                    private_key=private_key,
                    gas_limit=gas_limit,
                    gas_price=gas_price,
                    max_priority_fee=max_priority_fee,
                    max_fee=max_fee
                )
            else:
                # 原生代币转账
                result = await transfer_service.transfer(
                    from_address=wallet.address,
                    to_address=to_address,
                    amount=amount,
                    private_key=private_key,
                    gas_limit=gas_limit,
                    gas_price=gas_price,
                    max_priority_fee=max_priority_fee,
                    max_fee=max_fee
                )
            
            if result['status'] == 'error':
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
            wallet = await self.get_wallet_async(pk, device_id)
            
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
                result = await transfer_service.estimate_token_transfer_fee(
                    wallet.address,
                    to_address,
                    token_address,
                    amount
                )
            else:
                result = await transfer_service.estimate_native_transfer_fee(
                    wallet.address,
                    to_address,
                    amount
                )
                
            if result.get('status') == 'error':
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
            wallet = await self.get_wallet_async(pk, device_id)
            logger.debug(f"请求获取代币详情，钱包地址: {wallet.address}, 代币地址: {token_address}")
            
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
            
            # 获取代币元数据
            token_data = await token_info_service.get_token_metadata(token_address)
            if not token_data:
                return Response({
                    'status': 'error',
                    'message': '获取代币信息失败'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # 获取代币余额
            balance_service = ChainServiceFactory.get_balance_service(wallet.chain)
            balance = await balance_service.get_token_balance(wallet.address, token_address)
            
            # 格式化余额
            formatted_balance = str(balance)
            
            # 格式化价格
            price_usd = token_data.get('price_usd', '0')
            try:
                price = float(price_usd)
                if price < 0.000001:
                    formatted_price = '{:.12f}'.format(price)
                elif price < 0.00001:
                    formatted_price = '{:.10f}'.format(price)
                elif price < 0.0001:
                    formatted_price = '{:.8f}'.format(price)
                elif price < 0.01:
                    formatted_price = '{:.6f}'.format(price)
                else:
                    formatted_price = '{:.4f}'.format(price)
                formatted_price = formatted_price.rstrip('0').rstrip('.')
            except (ValueError, TypeError):
                formatted_price = '0'
            
            # 格式化价格变化
            price_change = token_data.get('price_change_24h', '0')
            try:
                change = float(price_change.rstrip('%'))  # 移除百分号
                formatted_price_change = '{:+.2f}%'.format(change)
            except (ValueError, TypeError):
                formatted_price_change = '+0.00%'
            
            # 计算价值
            try:
                # 使用 Decimal 进行精确计算
                balance_decimal = Decimal(str(balance))
                price_decimal = Decimal(str(price))
                value = balance_decimal * price_decimal
                
                # 根据价值大小格式化
                if value < 0.0001:
                    formatted_value = '{:.8f}'.format(float(value))
                elif value < 0.01:
                    formatted_value = '{:.6f}'.format(float(value))
                else:
                    formatted_value = '{:.4f}'.format(float(value))
                formatted_value = formatted_value.rstrip('0').rstrip('.')
            except (ValueError, TypeError, DecimalInvalidOperation):
                formatted_value = '0'
            
            # 获取代币可见性设置
            is_visible = True  # 默认可见
            token = await sync_to_async(Token.objects.filter(
                chain=wallet.chain,
                address=token_address
            ).first)()
            if token:
                is_visible = token.is_visible
            
            # 构建响应数据
            response_data = {
                'token_address': token_address,
                'name': token_data['name'],
                'symbol': token_data['symbol'],
                'decimals': token_data['decimals'],
                'logo': token_data['logo'],
                'thumbnail': token_data.get('thumbnail', ''),
                'type': token_data['type'],
                'contract_type': token_data['contract_type'],
                'description': token_data['description'],
                'website': token_data['website'],
                'twitter': token_data['twitter'],
                'telegram': token_data['telegram'],
                'discord': token_data['discord'],
                'github': token_data['github'],
                'medium': token_data['medium'],
                'reddit': token_data.get('reddit', ''),
                'instagram': token_data.get('instagram', ''),
                'email': token_data.get('email', ''),
                'moralis': token_data.get('moralis', ''),
                'total_supply': token_data['total_supply'],
                'total_supply_formatted': token_data['total_supply_formatted'],
                'circulating_supply': token_data.get('circulating_supply', '0'),
                'market_cap': token_data.get('market_cap', '0'),
                'fully_diluted_valuation': token_data.get('fully_diluted_valuation', '0'),
                'categories': token_data.get('categories', []),
                'security_score': token_data['security_score'],
                'verified': token_data['verified'],
                'possible_spam': token_data['possible_spam'],
                'block_number': token_data.get('block_number', ''),
                'validated': token_data.get('validated', 0),
                'created_at': token_data.get('created_at', ''),
                'is_native': False,
                'is_visible': is_visible,
                'balance': formatted_balance,
                'price_usd': formatted_price,
                'price_change_24h': formatted_price_change,
                'value_usd': formatted_value
            }

            return Response({
                'status': 'success',
                'data': response_data
            })
            
        except Exception as e:
            logger.error(f"获取代币详情失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'获取代币详情失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path=r'tokens/(?P<token_address>[^/.]+)/ohlcv')
    @async_to_sync_api
    async def token_ohlcv(self, request, pk=None, token_address=None):
        """获取代币价格走势图数据"""
        try:
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
                token_address,
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
    async def token_transfers(self, request, pk=None):
        """获取代币转账记录"""
        try:
            device_id = request.query_params.get('device_id')
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            
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
                transfers_qs = Transaction.objects.filter(
                    wallet=wallet,
                    tx_type='TRANSFER'
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