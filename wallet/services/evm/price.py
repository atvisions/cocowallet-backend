"""EVM 价格服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
import asyncio
from web3 import Web3
from django.utils import timezone
from django.core.cache import cache

from ...models import Token
from ...api_config import RPCConfig, MoralisConfig
from .utils import EVMUtils

logger = logging.getLogger(__name__)

class EVMPriceService:
    """EVM 价格服务实现类"""

    PRICE_CACHE_TTL = 300  # 价格缓存5分钟

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        
        # Moralis API 配置
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def get_token_price(self, token_address: str) -> Optional[Dict]:
        """获取代币价格"""
        try:
            # 检查缓存
            cache_key = f"evm_token_price_{self.chain}_{token_address}"
            cached_price = cache.get(cache_key)
            if cached_price:
                return cached_price
                
            # 使用 Moralis API 获取价格
            url = MoralisConfig.EVM_TOKEN_PRICE_URL.format(token_address)
            params = {'chain': self.chain.lower()}
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取代币价格失败: {await response.text()}")
                    
                    result = await response.json()
                    if not result:
                        return None
                    
                    price_data = {
                        'address': token_address,
                        'price_usd': Decimal(str(result.get('usdPrice', 0))),
                        'price_change_24h': Decimal(str(result.get('24hrPercentChange', 0))),
                        'volume_24h': Decimal(str(result.get('24hrVolume', 0))),
                        'market_cap': Decimal(str(result.get('marketCap', 0)))
                    }
                    
                    # 缓存价格数据
                    cache.set(cache_key, price_data, self.PRICE_CACHE_TTL)
                    return price_data
            
        except Exception as e:
            logger.error(f"获取代币价格失败: {str(e)}")
            return None

    async def get_token_price_history(
        self,
        token_address: str,
        vs_currency: str = "usd",
        days: int = 7
    ) -> List[Dict]:
        """获取代币历史价格"""
        try:
            url = MoralisConfig.EVM_TOKEN_PRICE_HISTORY_URL.format(token_address) # type: ignore
            params = {
                'chain': self.chain.lower(),
                'vs_currency': vs_currency,
                'days': days
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取代币历史价格失败: {await response.text()}")
                    
                    result = await response.json()
                    if not result:
                        return []
                    
                    return [{
                        'timestamp': price['date'],
                        'price': str(price['price'])
                    } for price in result]
            
        except Exception as e:
            logger.error(f"获取代币历史价格失败: {str(e)}")
            return []

    async def get_multiple_token_prices(
        self,
        token_addresses: List[str],
        vs_currency: str = "usd"
    ) -> Dict[str, Dict]:
        """批量获取代币价格"""
        result = {}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 创建异步任务列表
                tasks = []
                for address in token_addresses:
                    cache_key = f"evm_token_price_{self.chain}_{address}"
                    cached_price = cache.get(cache_key)
                    if cached_price:
                        result[address] = cached_price
                    else:
                        tasks.append(self._get_single_token_price(session, address))
                
                if tasks:
                    # 并发执行所有任务
                    prices = await asyncio.gather(*tasks)
                    
                    # 处理结果
                    for price_data in prices:
                        if price_data and 'address' in price_data:
                            result[price_data['address']] = price_data
                            # 缓存价格数据
                            cache_key = f"evm_token_price_{self.chain}_{price_data['address']}"
                            cache.set(cache_key, price_data, self.PRICE_CACHE_TTL)
                
                return result
                
            except Exception as e:
                logger.error(f"批量获取代币价格失败: {str(e)}")
                return {addr: None for addr in token_addresses} # type: ignore

    async def _get_single_token_price(self, session: aiohttp.ClientSession, token_address: str) -> Optional[Dict]:
        """获取单个代币价格"""
        try:
            url = MoralisConfig.EVM_TOKEN_PRICE_URL.format(token_address)
            params = {'chain': self.chain.lower()}
            
            async with session.get(url, headers=self.headers, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    if result:
                        return {
                            'address': token_address,
                            'price_usd': Decimal(str(result.get('usdPrice', 0))),
                            'price_change_24h': Decimal(str(result.get('24hrPercentChange', 0))),
                            'volume_24h': Decimal(str(result.get('24hrVolume', 0))),
                            'market_cap': Decimal(str(result.get('marketCap', 0)))
                        }
                return None
                
        except Exception as e:
            logger.error(f"获取单个代币价格失败: {str(e)}")
            return None

    async def get_native_token_price(self) -> Optional[Dict]:
        """获取原生代币价格"""
        try:
            url = MoralisConfig.EVM_TOKEN_PRICE_BATCH_URL.format(self.chain.lower()) # type: ignore
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status != 200:
                        raise Exception(f"获取原生代币价格失败: {await response.text()}")
                    
                    result = await response.json()
                    if not result:
                        return None
                    
                    return {
                        'symbol': self.chain_config['symbol'],
                        'price_usd': Decimal(str(result.get('usdPrice', 0))),
                        'price_change_24h': Decimal(str(result.get('24hrPercentChange', 0))),
                        'volume_24h': Decimal(str(result.get('24hrVolume', 0))),
                        'market_cap': Decimal(str(result.get('marketCap', 0)))
                    }
            
        except Exception as e:
            logger.error(f"获取原生代币价格失败: {str(e)}")
            return None 