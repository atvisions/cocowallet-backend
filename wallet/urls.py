from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views.wallet import WalletViewSet
from .views.mnemonic import MnemonicBackupViewSet
from .views.solana import SolanaWalletViewSet, SolanaSwapViewSet
from .views.nft import SolanaNFTViewSet, EVMNFTViewSet
from .views.evm import EVMWalletViewSet

# 创建路由器
router = DefaultRouter()
router.register(r'wallets', WalletViewSet, basename='wallet')
router.register(r'mnemonic-backups', MnemonicBackupViewSet, basename='mnemonic-backup')
router.register(r'solana/wallets', SolanaWalletViewSet, basename='solana-wallet')
router.register(r'solana/wallets/(?P<wallet_id>[^/.]+)/swap', SolanaSwapViewSet, basename='solana-swap')
router.register(r'solana/nfts', SolanaNFTViewSet, basename='solana-nft')
router.register(r'evm/wallets', EVMWalletViewSet, basename='evm-wallet')
router.register(r'evm/nfts', EVMNFTViewSet, basename='evm-nft')

# API 路由
urlpatterns = [
    path('', include(router.urls)),
]  
    