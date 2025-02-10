from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from decimal import Decimal

class BasePriceService(ABC):
    """价格服务的基础接口类"""
    
    @abstractmethod
    async def get_token_price(self, token_address: str, vs_currency: str = "usd") -> Decimal:
        """获取代币价格"""
        pass
    
    @abstractmethod
    async def get_token_price_history(
        self,
        token_address: str,
        vs_currency: str = "usd",
        days: int = 7
    ) -> List[Dict]:
        """获取代币历史价格"""
        pass
    
    @abstractmethod
    async def get_multiple_token_prices(
        self,
        token_addresses: List[str],
        vs_currency: str = "usd"
    ) -> Dict[str, Decimal]:
        """批量获取代币价格"""
        pass 