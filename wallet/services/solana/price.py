import aiohttp
import asyncio
import logging
from decimal import Decimal
from typing import Dict, List, Optional
from django.utils import timezone
from asgiref.sync import sync_to_async

from ..base.price import BasePriceService
from ...models import Token
from ...api_config import MoralisConfig

logger = logging.getLogger(__name__)

class SolanaPriceService(BasePriceService):
    """Solana 价格服务实现类"""

    def __init__(self):
        self.headers = {
            "accept": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)

    async def get_token_price(self, token_address: str) -> Optional[Dict]:
        """获取代币价格"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                price_url = MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(token_address)
                price_data = await self._fetch_with_retry(session, price_url)
                
                if price_data and 'usdPrice' in price_data:
                    return {
                        'address': token_address,
                        'price': Decimal(str(price_data['usdPrice']))
                    }
                return None
            except Exception as e:
                logger.error(f"获取代币价格时出错: {str(e)}")
                return None

    async def get_token_price_history(
        self,
        token_address: str,
        vs_currency: str = "usd",
        days: int = 7
    ) -> List[Dict]:
        """获取代币历史价格"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 首先尝试获取交易对价格
                url = MoralisConfig.SOLANA_TOKEN_PAIRS_PRICE_URL.format(token_address)
                pairs_data = await self._fetch_with_retry(session, url)
                
                if pairs_data:
                    # 如果能获取到交易对价格，说明可以获取 OHLCV 数据
                    now = timezone.now()
                    to_date = now.strftime('%Y-%m-%d')
                    from_date = (now - timezone.timedelta(days=1)).strftime('%Y-%m-%d')
                    
                    ohlcv_url = MoralisConfig.SOLANA_TOKEN_PAIRS_OHLCV_URL.format(token_address)
                    params = {
                        'timeframe': '1h',
                        'currency': vs_currency,
                        'fromDate': from_date,
                        'toDate': to_date,
                        'limit': '24'
                    }
                    
                    async with session.get(ohlcv_url, headers=self.headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data and isinstance(data, dict) and 'result' in data:
                                ohlcv_data = data['result']
                                if len(ohlcv_data) > 0:
                                    # 取第一个和最后一个数据点计算24小时变化
                                    first_data = ohlcv_data[0]
                                    last_data = ohlcv_data[-1]
                                    return [
                                        {
                                            'timestamp': int(first_data['timestamp'].timestamp() * 1000),
                                            'price': str(first_data['close'])
                                        },
                                        {
                                            'timestamp': int(last_data['timestamp'].timestamp() * 1000),
                                            'price': str(last_data['close'])
                                        }
                                    ]
                
                # 如果无法获取 OHLCV 数据，回退到使用当前价格
                current_price = await self.get_token_price(token_address)
                if current_price:
                    now = int(timezone.now().timestamp() * 1000)
                    yesterday = now - (24 * 60 * 60 * 1000)  # 24小时前
                    return [
                        {
                            'timestamp': yesterday,
                            'price': str(current_price['price'])
                        },
                        {
                            'timestamp': now,
                            'price': str(current_price['price'])
                        }
                    ]
                
                return []
            except Exception as e:
                logger.error(f"获取代币历史价格时出错: {str(e)}")
                return []

    async def get_token_prices(self, token_addresses: List[str]) -> Dict[str, Dict]:
        """批量获取代币价格"""
        result = {}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = []
            for address in token_addresses:
                price_url = MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(address)
                tasks.append(self._get_single_token_price(session, price_url))
            
            prices = await asyncio.gather(*tasks)
            
            for token_address, price in zip(token_addresses, prices):
                result[token_address] = price

            return result

    async def _get_single_token_price(self, session, price_url: str) -> Dict:
        """获取单个代币价格"""
        try:
            price_data = await self._fetch_with_retry(session, price_url)
            
            if price_data and 'usdPrice' in price_data:
                return {
                    'address': price_url.split('/')[-1],
                    'price': Decimal(str(price_data['usdPrice']))
                }
        except Exception as e:
            logger.error(f"获取单个代币价格时出错: {str(e)}")
        return {'address': price_url.split('/')[-1], 'price': Decimal('0')}

    async def _fetch_with_retry(self, session, url, method="get", **kwargs):
        """带重试的HTTP请求函数"""
        kwargs['headers'] = self.headers
        for attempt in range(3):
            try:
                async with getattr(session, method)(url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:  # Rate limit
                        retry_after = int(response.headers.get('Retry-After', 2))
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"请求失败: {url}, 状态码: {response.status}")
                        if response.status != 404:  # 对于非404错误，记录响应内容
                            try:
                                error_content = await response.text()
                                logger.error(f"错误响应内容: {error_content}")
                            except:
                                pass
                        return None
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                logger.error(f"请求失败: {url}, 错误: {str(e)}")
                return None
        return None

    async def get_multiple_token_prices(
        self,
        token_addresses: List[str],
        vs_currency: str = "usd"
    ) -> Dict[str, Decimal]:
        """批量获取代币价格"""
        result = {}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 创建异步任务列表
                tasks = [
                    self._get_single_token_price(session, token_address)
                    for token_address in token_addresses
                ]
                
                # 并发执行所有任务
                prices = await asyncio.gather(*tasks)
                
                # 组装结果
                for token_address, price in zip(token_addresses, prices):
                    result[token_address] = price.get('price', Decimal('0')) if price else Decimal('0')

                return result
            except Exception as e:
                logger.error(f"批量获取代币价格时出错: {str(e)}")
                return {addr: Decimal('0') for addr in token_addresses} 