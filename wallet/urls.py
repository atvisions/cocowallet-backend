from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views.wallet import WalletViewSet
from .views.mnemonic import MnemonicBackupViewSet
from .views.solana import SolanaWalletViewSet

# 创建路由器
router = DefaultRouter()
router.register(r'wallets', WalletViewSet, basename='wallet')
router.register(r'mnemonic-backups', MnemonicBackupViewSet, basename='mnemonic-backup')
router.register(r'solana/wallets', SolanaWalletViewSet, basename='solana-wallet')

# API 路由
urlpatterns = [
    path('', include(router.urls)),
] 