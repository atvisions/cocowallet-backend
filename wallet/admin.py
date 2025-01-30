from django.contrib import admin
from .models import Wallet, MnemonicBackup, PaymentPassword

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['name', 'chain', 'address', 'device_id', 'is_active', 'created_at']
    list_filter = ['chain', 'is_active']
    search_fields = ['name', 'address', 'device_id']
    ordering = ['-created_at']

@admin.register(MnemonicBackup)
class MnemonicBackupAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'created_at']
    search_fields = ['device_id']
    ordering = ['-created_at']

@admin.register(PaymentPassword)
class PaymentPasswordAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'created_at', 'updated_at']
    search_fields = ['device_id']
    ordering = ['-created_at']
