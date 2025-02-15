from django.apps import AppConfig
import asyncio
import nest_asyncio


class WalletConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wallet"
    
    def ready(self):
        """在 Django 启动时初始化事件循环"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # 启用嵌套事件循环支持
        nest_asyncio.apply()
