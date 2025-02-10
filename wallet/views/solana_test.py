from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from decimal import Decimal
from django.conf import settings

from ..services.factory import ChainServiceFactory
from ..services.base.base_service import BaseService
from ..models import Token, Wallet

class SolanaServiceTestView(APIView):
    """Solana 服务测试接口"""

    async def get(self, request):
        """测试 Solana 服务的健康状态和基本功能"""
        try:
            # 获取所有服务实例
            balance_service = ChainServiceFactory.get_balance_service('SOL')
            transfer_service = ChainServiceFactory.get_transfer_service('SOL')
            price_service = ChainServiceFactory.get_price_service('SOL')
            history_service = ChainServiceFactory.get_history_service('SOL')
            token_info_service = ChainServiceFactory.get_token_info_service('SOL')

            # 检查所有服务的健康状态
            health_checks = {
                'balance_service': await balance_service.check_health() if balance_service else {'status': 'error', 'message': 'Service not available'},
                'transfer_service': await transfer_service.check_health() if transfer_service else {'status': 'error', 'message': 'Service not available'},
                'price_service': await price_service.check_health() if price_service else {'status': 'error', 'message': 'Service not available'},
                'history_service': await history_service.check_health() if history_service else {'status': 'error', 'message': 'Service not available'},
                'token_info_service': await token_info_service.check_health() if token_info_service else {'status': 'error', 'message': 'Service not available'},
            }

            return Response({
                'status': 'success',
                'message': '服务健康检查完成',
                'data': health_checks
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'服务健康检查失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    async def post(self, request):
        """测试特定的 Solana 服务功能"""
        try:
            action = request.data.get('action')
            if not action:
                return Response({
                    'status': 'error',
                    'message': '缺少 action 参数'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 获取请求参数
            address = request.data.get('address')
            token_address = request.data.get('token_address')

            # 根据不同的操作执行相应的测试
            if action == 'get_native_balance':
                if not address:
                    return Response({
                        'status': 'error',
                        'message': '缺少地址参数'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                balance_service = ChainServiceFactory.get_balance_service('SOL')
                if not balance_service:
                    return Response({
                        'status': 'error',
                        'message': '余额服务不可用'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                balance = await balance_service.get_native_balance(address)
                return Response({
                    'status': 'success',
                    'data': {
                        'balance': str(balance),
                        'symbol': 'SOL'
                    }
                })

            elif action == 'get_token_balance':
                if not address or not token_address:
                    return Response({
                        'status': 'error',
                        'message': '缺少必要参数'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                balance_service = ChainServiceFactory.get_balance_service('SOL')
                if not balance_service:
                    return Response({
                        'status': 'error',
                        'message': '余额服务不可用'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                balance = await balance_service.get_token_balance(address, token_address)
                return Response({
                    'status': 'success',
                    'data': {
                        'balance': str(balance),
                        'token_address': token_address
                    }
                })

            elif action == 'transfer_native':
                # 验证必要参数
                from_address = request.data.get('from_address')
                to_address = request.data.get('to_address')
                amount = request.data.get('amount')
                private_key = request.data.get('private_key')

                if not all([from_address, to_address, amount, private_key]):
                    return Response({
                        'status': 'error',
                        'message': '缺少必要参数'
                    }, status=status.HTTP_400_BAD_REQUEST)

                try:
                    amount = Decimal(amount)
                except:
                    return Response({
                        'status': 'error',
                        'message': '金额格式错误'
                    }, status=status.HTTP_400_BAD_REQUEST)

                transfer_service = ChainServiceFactory.get_transfer_service('SOL')
                if not transfer_service:
                    return Response({
                        'status': 'error',
                        'message': '转账服务不可用'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                result = await transfer_service.transfer_native(
                    from_address=from_address,
                    to_address=to_address,
                    amount=amount,
                    private_key=private_key
                )

                return Response({
                    'status': 'success',
                    'data': result
                })

            elif action == 'transfer_token':
                # 验证必要参数
                from_address = request.data.get('from_address')
                to_address = request.data.get('to_address')
                token_address = request.data.get('token_address')
                amount = request.data.get('amount')
                private_key = request.data.get('private_key')

                if not all([from_address, to_address, token_address, amount, private_key]):
                    return Response({
                        'status': 'error',
                        'message': '缺少必要参数'
                    }, status=status.HTTP_400_BAD_REQUEST)

                try:
                    amount = Decimal(amount)
                except:
                    return Response({
                        'status': 'error',
                        'message': '金额格式错误'
                    }, status=status.HTTP_400_BAD_REQUEST)

                transfer_service = ChainServiceFactory.get_transfer_service('SOL')
                if not transfer_service:
                    return Response({
                        'status': 'error',
                        'message': '转账服务不可用'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                result = await transfer_service.transfer_token(
                    from_address=from_address,
                    to_address=to_address,
                    token_address=token_address,
                    amount=amount,
                    private_key=private_key
                )

                return Response({
                    'status': 'success',
                    'data': result
                })

            elif action == 'get_token_info':
                if not token_address:
                    return Response({
                        'status': 'error',
                        'message': '缺少代币地址参数'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                token_info_service = ChainServiceFactory.get_token_info_service('SOL')
                if not token_info_service:
                    return Response({
                        'status': 'error',
                        'message': '代币信息服务不可用'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                token_info = await token_info_service.get_token_info(token_address)
                return Response({
                    'status': 'success',
                    'data': token_info
                })

            elif action == 'get_token_price':
                if not token_address:
                    return Response({
                        'status': 'error',
                        'message': '缺少代币地址参数'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                price_service = ChainServiceFactory.get_price_service('SOL')
                if not price_service:
                    return Response({
                        'status': 'error',
                        'message': '价格服务不可用'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                price = await price_service.get_token_price(token_address)
                return Response({
                    'status': 'success',
                    'data': {
                        'price': str(price),
                        'currency': 'USD'
                    }
                })

            elif action == 'get_transaction_history':
                if not address:
                    return Response({
                        'status': 'error',
                        'message': '缺少地址参数'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                history_service = ChainServiceFactory.get_history_service('SOL')
                if not history_service:
                    return Response({
                        'status': 'error',
                        'message': '交易历史服务不可用'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                transactions = await history_service.get_native_transactions(
                    address,
                    limit=request.data.get('limit', 10),
                    offset=request.data.get('offset', 0)
                )
                return Response({
                    'status': 'success',
                    'data': transactions
                })

            else:
                return Response({
                    'status': 'error',
                    'message': f'不支持的操作: {action}'
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'操作执行失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 