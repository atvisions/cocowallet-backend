from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views.wallet import WalletViewSet
from .views.mnemonic import MnemonicBackupViewSet
from .views.solana import SolanaWalletViewSet, SolanaSwapViewSet
from .views.solana.history import SolanaHistoryViewSet
from .views.nft import SolanaNFTViewSet, EVMNFTViewSet
from .views.evm import EVMWalletViewSet
from .views.referral import ReferralViewSet
from .views.tasks import TaskViewSet, ShareTaskTokenViewSet

# 创建路由器
router = DefaultRouter()
router.register(r'wallets', WalletViewSet, basename='wallet')
router.register(r'mnemonic-backups', MnemonicBackupViewSet, basename='mnemonic-backup')
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'tasks/share-tasks', ShareTaskTokenViewSet, basename='share-task')
router.register(r'solana/wallets', SolanaWalletViewSet, basename='solana-wallet')
router.register(r'solana/wallets/(?P<wallet_id>[^/.]+)/token-transfers', SolanaHistoryViewSet, basename='solana-history')
router.register(r'solana/wallets/(?P<wallet_id>\d+)/swap', SolanaSwapViewSet, basename='solana-swap')

router.register(r'solana/nfts', SolanaNFTViewSet, basename='solana-nft')
router.register(r'evm/wallets', EVMWalletViewSet, basename='evm-wallet')
router.register(r'evm/nfts', EVMNFTViewSet, basename='evm-nft')
router.register(r'referrals', ReferralViewSet, basename='referral')

# API 路由
urlpatterns = [
    path('', include(router.urls)),
]