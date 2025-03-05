from typing import Dict, List, Optional, Tuple, Union
from decimal import Decimal
import logging
from django.core.cache import cache
from ..models import Token, TokenIndex
from ..services.evm_config import RPCConfig
from ..services.solana_config import MoralisConfig

logger = logging.getLogger(__name__)

class BaseTokenService:
    """代币服务基类，提供共用的功能和配置"""
    
    CHAIN_MAPPING = {
        'ETH': 'eth',
        'BSC': 'bsc',
        'POLYGON': 'polygon',
        'ARBITRUM': 'arbitrum',
        'OPTIMISM': 'optimism',
        'AVALANCHE': 'avalanche',
        'BASE': 'base'
    }

    NATIVE_TOKEN_MAPPING = {
        'eth': {'decimals': 18},
        'bsc': {'decimals': 18},
        'polygon': {'decimals': 18},
        'arbitrum': {'decimals': 18},
        'optimism': {'decimals': 18},
        'avalanche': {'decimals': 18},
        'base': {'decimals': 18}
    }

    @staticmethod
    def get_cache_key(prefix: str, *args) -> str:
        """生成缓存键"""
        return f'{prefix}_{"||".join(str(arg) for arg in args)}'

    @staticmethod
    def set_cache(key: str, data: any, timeout: Optional[int] = None) -> None: # type: ignore
        """设置缓存"""
        if timeout is None:
            cache_config = RPCConfig.get_cache_config()
            timeout = cache_config['TIMEOUT']
        cache.set(key, data, timeout)

    @staticmethod
    def get_cache(key: str) -> Optional[any]: # type: ignore
        """获取缓存"""
        return cache.get(key)

    @staticmethod
    def format_token_value(balance: Union[str, Decimal], decimals: int) -> Decimal:
        """格式化代币数值"""
        try:
            balance = Decimal(str(balance))
            return balance / Decimal(10 ** decimals)
        except Exception as e:
            logger.error(f"格式化代币数值出错: {str(e)}")
            return Decimal('0')