from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from decimal import Decimal

class BaseTokenInfoService(ABC):
    """代币信息服务的基础接口类"""
    
    @abstractmethod
    async def get_token_info(self, token_address: str) -> Dict:
        """获取代币基本信息（名称、符号、精度等）"""
        pass
    
    @abstractmethod
    async def get_token_metadata(self, token_address: str) -> Dict:
        """获取代币元数据（图标、描述、网站等）"""
        pass
    
    @abstractmethod
    async def validate_token_address(self, token_address: str) -> bool:
        """验证代币地址是否有效"""
        pass
    
    @abstractmethod
    async def get_token_supply(self, token_address: str) -> Dict:
        """获取代币供应量信息"""
        pass
    
    @abstractmethod
    async def get_token_ohlcv(
        self,
        token_address: str,
        timeframe: str = '1h',
        currency: str = 'usd',
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 24
    ) -> Dict:
        """获取代币价格走势图数据
        
        Args:
            token_address: 代币地址
            timeframe: 时间间隔，可选值：1h, 1d, 1w, 1m
            currency: 货币单位，默认usd
            from_date: 开始日期，格式：YYYY-MM-DD
            to_date: 结束日期，格式：YYYY-MM-DD
            limit: 返回数据条数，默认24条
        """
        pass 