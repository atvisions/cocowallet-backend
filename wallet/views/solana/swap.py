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

from ...models import Wallet
from ...services.solana.swap import SolanaSwapService

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
    
    @action(detail=True, methods=['get'])
    def quote(self, request, pk=None):
        """
        Get swap quote
        """
        device_id = request.query_params.get('device_id')
        from_token = request.query_params.get('from_token')
        to_token = request.query_params.get('to_token')
        amount = request.query_params.get('amount')
        slippage = request.query_params.get('slippage', '0.5')

        if not all([device_id, from_token, to_token, amount]):
            return Response(
                {'error': '缺少必要参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        wallet = get_object_or_404(Wallet, id=pk)
        if not self.check_wallet_access(wallet, device_id):
            return Response(
                {'error': '无权访问该钱包'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            swap_service = SolanaSwapService()
            quote = swap_service.get_swap_quote(
                wallet=wallet,
                from_token=from_token,
                to_token=to_token,
                amount=float(amount),
                slippage=float(slippage)
            )
            return Response(quote)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def execute(self, request, pk=None):
        """
        Execute swap
        """
        device_id = request.data.get('device_id')
        quote_id = request.data.get('quote_id')
        from_token = request.data.get('from_token')
        to_token = request.data.get('to_token')
        amount = request.data.get('amount')
        private_key = request.data.get('private_key')
        slippage = request.data.get('slippage', '0.5')

        if not all([device_id, quote_id, from_token, to_token, amount, private_key]):
            return Response(
                {'error': '缺少必要参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        wallet = get_object_or_404(Wallet, id=pk)
        if not self.check_wallet_access(wallet, device_id):
            return Response(
                {'error': '无权访问该钱包'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            swap_service = SolanaSwapService()
            result = swap_service.swap_execute(
                wallet=wallet,
                quote_id=quote_id,
                from_token=from_token,
                to_token=to_token,
                amount=float(amount),
                private_key=private_key,
                slippage=float(slippage)
            )
            return Response(result)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            ) 