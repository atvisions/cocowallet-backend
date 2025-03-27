"""
Solana swap related views
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.parsers import JSONParser
import logging
import asyncio
from decimal import Decimal
import decimal
import json
from django.utils import timezone

from ...models import Wallet, Token, Transaction
from ...services.solana.swap import SolanaSwapService, SwapError
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

logger = logging.getLogger(__name__)

class SolanaSwapViewSet(viewsets.ViewSet):
    """
    Solana swap related endpoints
    """
    permission_classes = [AllowAny]
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    parser_classes = [JSONParser]
    
    def check_wallet_access(self, wallet: Wallet, device_id: str) -> bool:
        """检查设备是否有权限访问钱包"""
        return wallet.device_id == device_id

    @action(detail=False, methods=['get'], url_path='tokens')
    def tokens(self, request, wallet_id=None):
        """
        获取支持的交换代币列表
        """
        device_id = request.query_params.get('device_id')
        if not device_id:
            return Response(
                {
                    'status': 'error',
                    'message': '缺少设备ID参数',
                    'code': 'MISSING_DEVICE_ID'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            wallet = get_object_or_404(Wallet, id=wallet_id)
            if not self.check_wallet_access(wallet, device_id):
                return Response(
                    {
                        'status': 'error',
                        'message': '无权访问该钱包',
                        'code': 'WALLET_ACCESS_DENIED'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            swap_service = SolanaSwapService()
            tokens = swap_service.get_tokens()
            
            return Response({
                'status': 'success',
                'data': {
                    'tokens': tokens
                }
            })
        except Wallet.DoesNotExist:
            return Response(
                {
                    'status': 'error',
                    'message': '钱包不存在',
                    'code': 'WALLET_NOT_FOUND'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"获取交换代币列表失败: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': f'获取交换代币列表失败: {str(e)}',
                    'code': 'GET_TOKENS_FAILED'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'], url_path='quote', url_name='quote')
    def quote(self, request, wallet_id=None):
        """
        获取兑换报价
        """
        device_id = request.query_params.get('device_id')
        from_token = request.query_params.get('from_token')
        to_token = request.query_params.get('to_token')
        amount = request.query_params.get('amount')
        slippage = request.query_params.get('slippage', '0.5')

        if not all([device_id, from_token, to_token, amount]):
            return Response(
                {
                    'status': 'error',
                    'message': '缺少必要参数',
                    'code': 'MISSING_PARAMS'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            wallet = get_object_or_404(Wallet, id=wallet_id)
            if not self.check_wallet_access(wallet, device_id):
                return Response(
                    {
                        'status': 'error',
                        'message': '无权访问该钱包',
                        'code': 'WALLET_ACCESS_DENIED'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            swap_service = SolanaSwapService()
            quote = swap_service.get_quote(
                wallet_id=wallet_id,
                device_id=device_id,
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                slippage=slippage
            )
            return Response(quote)
        except Exception as e:
            logger.error(f"获取兑换报价失败: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': str(e),
                    'code': 'QUOTE_FAILED'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def execute(self, request, wallet_id=None):
        """执行代币兑换"""
        try:
            # 获取请求参数
            device_id = request.data.get('device_id')
            quote_id = request.data.get('quote_id')
            from_token = request.data.get('from_token')
            to_token = request.data.get('to_token')
            amount = request.data.get('amount')
            payment_password = request.data.get('payment_password')
            slippage = request.data.get('slippage')
            
            # 验证必要参数
            if not all([device_id, quote_id, from_token, to_token, amount, payment_password]):
                return Response(
                    {
                        'status': 'error',
                        'message': '缺少必要参数',
                        'code': 'MISSING_PARAMS'
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 验证 quote_id 格式
            try:
                quote_data = json.loads(quote_id)
                logger.debug(f"解析的报价数据: {quote_data}")
            except json.JSONDecodeError as e:
                return Response(
                    {
                        'status': 'error',
                        'message': '无效的报价数据格式',
                        'code': 'INVALID_QUOTE_FORMAT'
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 验证钱包访问权限
            wallet = get_object_or_404(Wallet, id=wallet_id)
            if not self.check_wallet_access(wallet, device_id):
                return Response(
                    {
                        'status': 'error',
                        'message': '无权访问该钱包',
                        'code': 'WALLET_ACCESS_DENIED'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # 验证支付密码
            if not wallet.check_payment_password(payment_password):
                return Response(
                    {
                        'status': 'error',
                        'message': '支付密码错误',
                        'code': 'INVALID_PAYMENT_PASSWORD'
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 设置支付密码并获取私钥
            wallet.payment_password = payment_password
            try:
                private_key = wallet.decrypt_private_key()
                if not private_key:
                    raise ValueError("获取私钥失败")
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response(
                    {
                        'status': 'error',
                        'message': f'获取私钥失败: {str(e)}',
                        'code': 'GET_PRIVATE_KEY_FAILED'
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 转换数值类型并处理精度
            try:
                # 获取代币精度
                from_token_decimals = 5  # Bonk 代币精度为 5
                if from_token == 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v':
                    from_token_decimals = 6  # USDC 代币精度为 6
                elif from_token == 'So11111111111111111111111111111111111111112':
                    from_token_decimals = 9  # SOL 代币精度为 9
                
                # 转换金额为 Decimal
                amount_decimal = Decimal(amount) / Decimal(10 ** from_token_decimals)
                
                # 转换滑点
                if slippage:
                    slippage = Decimal(slippage)
                else:
                    slippage = Decimal('0.5')
                    
                # 确保金额不超过代币精度
                max_decimals = Decimal('10') ** (-from_token_decimals)
                if amount_decimal % max_decimals != 0:
                    return Response(
                        {
                            'status': 'error',
                            'message': f'金额精度超过代币精度 ({from_token_decimals})',
                            'code': 'INVALID_AMOUNT_PRECISION'
                        }, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
            except (TypeError, ValueError, decimal.InvalidOperation) as e:
                return Response(
                    {
                        'status': 'error',
                        'message': f'金额或滑点格式错误: {str(e)}',
                        'code': 'INVALID_NUMBER_FORMAT'
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 在保存交易记录前添加日志和检查
            logger.info(f"原始金额: {amount}, 类型: {type(amount)}")

            # 如果金额太大，可以尝试转换
            if isinstance(amount, str) and len(amount) > 15:
                try:
                    # 尝试将金额转换为合理范围
                    decimals = 9  # 根据代币类型调整
                    amount_decimal = Decimal(amount) / Decimal(10 ** decimals)
                    logger.info(f"转换后的金额: {amount_decimal}")
                    amount = amount_decimal
                except Exception as e:
                    logger.error(f"转换金额失败: {str(e)}")
            
            # 获取代币的小数位数
            token = Token.objects.filter(chain='SOL', address=from_token).first()
            decimals = token.decimals if token else 9  # 默认使用 9 位小数（SOL）

            # 转换金额
            try:
                amount_decimal = Decimal(amount) / Decimal(10 ** decimals)
                logger.info(f"转换后的金额: {amount_decimal}")
                
                # 保存交易记录
                transaction = Transaction(
                    wallet=wallet,
                    chain='SOL',
                    tx_hash=quote_id,
                    tx_type='SWAP',
                    status='PENDING',
                    from_address=wallet.address,
                    to_address=wallet.address,
                    amount=amount_decimal,  # 使用转换后的金额
                    to_token_address=to_token,
                    gas_price=Decimal('0.000005'),
                    gas_used=Decimal('1'),
                    block_number=0,
                    block_timestamp=timezone.now()
                )
                transaction.save()
                
            except Exception as e:
                logger.error(f"保存交易记录失败: {str(e)}")
                logger.error(f"错误类型: {type(e).__name__}")
            
            # 执行兑换
            swap_service = SolanaSwapService()
            
            # 异步执行兑换
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    swap_service.execute_swap(
                        quote_id=quote_id,
                        from_token=from_token,
                        to_token=to_token,
                        amount=int(amount_decimal),  # 转换为整数
                        from_address=wallet.address,
                        private_key=private_key,
                        slippage=slippage
                    )
                )
                
                return Response({
                    'status': 'success',
                    'data': result
                })
            except SwapError as e:
                logger.error(f"执行兑换失败: {str(e)}")
                return Response(
                    {
                        'status': 'error',
                        'message': str(e),
                        'code': 'SWAP_FAILED'
                    }, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            except Exception as e:
                logger.error(f"执行兑换时发生未知错误: {str(e)}")
                return Response(
                    {
                        'status': 'error',
                        'message': f'执行兑换失败: {str(e)}',
                        'code': 'UNKNOWN_ERROR'
                    }, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"执行兑换视图错误: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': f'执行兑换失败: {str(e)}',
                    'code': 'VIEW_ERROR'
                }, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='prices')
    def prices(self, request, wallet_id=None):
        """
        获取代币价格信息
        """
        device_id = request.query_params.get('device_id')
        token_addresses = request.query_params.get('token_addresses')

        if not device_id:
            return Response(
                {
                    'status': 'error',
                    'message': '缺少设备ID参数',
                    'code': 'MISSING_DEVICE_ID'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not token_addresses:
            return Response(
                {
                    'status': 'error',
                    'message': '缺少代币地址参数',
                    'code': 'MISSING_TOKEN_ADDRESSES'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            wallet = get_object_or_404(Wallet, id=wallet_id)
            if not self.check_wallet_access(wallet, device_id):
                return Response(
                    {
                        'status': 'error',
                        'message': '无权访问该钱包',
                        'code': 'WALLET_ACCESS_DENIED'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            # 将token_addresses字符串转换为列表
            token_list = token_addresses.split(',')

            swap_service = SolanaSwapService()
            prices = swap_service.get_token_prices(token_list)
            
            return Response({
                'status': 'success',
                'data': {
                    'prices': prices
                }
            })
        except Wallet.DoesNotExist:
            return Response(
                {
                    'status': 'error',
                    'message': '钱包不存在',
                    'code': 'WALLET_NOT_FOUND'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"获取代币价格失败: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': str(e),
                    'code': 'GET_PRICES_FAILED'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='status/(?P<signature>[^/.]+)')
    def status(self, request, wallet_id=None, signature=None):
        """
        查询交易状态
        
        Args:
            signature: 交易签名
        """
        device_id = request.query_params.get('device_id')
        if not device_id:
            return Response(
                {
                    'status': 'error',
                    'message': '缺少设备ID参数',
                    'code': 'MISSING_DEVICE_ID'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            wallet = get_object_or_404(Wallet, id=wallet_id)
            if not self.check_wallet_access(wallet, device_id):
                return Response(
                    {
                        'status': 'error',
                        'message': '无权访问该钱包',
                        'code': 'WALLET_ACCESS_DENIED'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            swap_service = SolanaSwapService()
            result = swap_service.get_transaction_status_sync(signature)
            return Response({
                'status': 'success',
                'data': result
            })

        except Wallet.DoesNotExist:
            return Response(
                {
                    'status': 'error',
                    'message': '钱包不存在',
                    'code': 'WALLET_NOT_FOUND'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"查询交易状态失败: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': str(e),
                    'code': 'GET_STATUS_FAILED'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'], url_path='estimate_fees')
    def estimate_fees(self, request, wallet_id=None):
        """
        估算交易费用
        """
        device_id = request.query_params.get('device_id')
        from_token = request.query_params.get('from_token')
        to_token = request.query_params.get('to_token')
        amount = request.query_params.get('amount')

        if not all([device_id, from_token, to_token, amount]):
            return Response(
                {
                    'status': 'error',
                    'message': '缺少必要参数',
                    'code': 'MISSING_PARAMS'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            wallet = get_object_or_404(Wallet, id=wallet_id)
            if not self.check_wallet_access(wallet, device_id):
                return Response(
                    {
                        'status': 'error',
                        'message': '无权访问该钱包',
                        'code': 'WALLET_ACCESS_DENIED'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            swap_service = SolanaSwapService()
            fees = swap_service.estimate_fees(
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                wallet_address=wallet.address
            )
            
            return Response({
                'status': 'success',
                'data': fees
            })

        except Wallet.DoesNotExist:
            return Response(
                {
                    'status': 'error',
                    'message': '钱包不存在',
                    'code': 'WALLET_NOT_FOUND'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"估算交易费用失败: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': str(e),
                    'code': 'ESTIMATE_FEES_FAILED'
                },
                status=status.HTTP_400_BAD_REQUEST
            )