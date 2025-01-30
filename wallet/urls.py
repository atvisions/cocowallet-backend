from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'wallets', views.WalletViewSet, basename='wallet')
router.register(r'mnemonic-backups', views.MnemonicBackupViewSet, basename='mnemonic-backup')

urlpatterns = [
    path('', include(router.urls)),
] 