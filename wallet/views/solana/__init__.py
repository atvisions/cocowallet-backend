"""
Solana related views
"""
from .tokens import SolanaWalletViewSet
from .swap import SolanaSwapViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import viewsets
from ...models import Token

__all__ = ['SolanaWalletViewSet', 'SolanaSwapViewSet']