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

from ...models import Wallet
from ...services.solana.swap import SolanaSwapService
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
    
    @action(detail=False, methods=['get'], url_path='quote')
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
            return Response({
                'status': 'success',
                'data': quote
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
            logger.error(f"获取兑换报价失败: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': str(e),
                    'code': 'QUOTE_FAILED'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'], url_path='execute')
    def execute(self, request, wallet_id=None):
        """
        执行兑换交易
        """
        device_id = request.data.get('device_id')
        quote_id = request.data.get('quote_id')
        from_token = request.data.get('from_token')
        to_token = request.data.get('to_token')
        amount = request.data.get('amount')
        payment_password = request.data.get('payment_password')
        slippage = request.data.get('slippage', '0.5')

        if not all([device_id, quote_id, from_token, to_token, amount, payment_password]):
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
                
            # 验证支付密码并获取私钥
            if not wallet.check_payment_password(payment_password):
                return Response(
                    {
                        'status': 'error',
                        'message': '支付密码错误',
                        'code': 'INVALID_PAYMENT_PASSWORD'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # 设置支付密码属性
                wallet.payment_password = payment_password
                private_key = wallet.decrypt_private_key()
            except Exception as e:
                logger.error(f"解密私钥失败: {str(e)}")
                return Response(
                    {
                        'status': 'error',
                        'message': f'解密私钥失败: {str(e)}',
                        'code': 'DECRYPT_FAILED'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 创建事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                swap_service = SolanaSwapService()
                # 同步调用异步方法
                result = loop.run_until_complete(
                    swap_service.execute_swap(
                        quote_id=quote_id,
                        from_token=from_token,
                        to_token=to_token,
                        amount=Decimal(amount),
                        from_address=wallet.address,
                        private_key=private_key,
                        slippage=float(slippage)
                    )
                )
                return Response({
                    'status': 'success',
                    'data': result
                })
            finally:
                loop.close()
                
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
            logger.error(f"执行兑换交易失败: {str(e)}")
            return Response(
                {
                    'status': 'error',
                    'message': str(e),
                    'code': 'SWAP_FAILED'
                },
                status=status.HTTP_400_BAD_REQUEST
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