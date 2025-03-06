"""Solana 价格服务"""
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
import aiohttp
import asyncio
import json
from django.utils import timezone
import os
from datetime import datetime, timedelta

from ...models import Token
from ...services.solana_config import MoralisConfig

logger = logging.getLogger(__name__)

class SolanaPriceService:
    """Solana 价格服务实现类"""

    def __init__(self):
        self.headers = {
            "accept": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)
        self.coingecko_api_key = os.getenv('COINGECKO_API_KEY', '')
        self.jupiter_api_url = 'https://price.jup.ag/v4'
        self.coingecko_api_url = 'https://api.coingecko.com/api/v3'

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

    async def get_token_ohlcv(
        self,
        token_address: str,
        timeframe: str = '1h',
        limit: int = 24,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取代币K线数据"""
        try:
            logger.info(f"开始获取代币 {token_address} 的K线数据")
            logger.info(f"参数: timeframe={timeframe}, limit={limit}, from_date={from_date}, to_date={to_date}")
            
            # 验证时间周期
            valid_timeframes = {
                '1m': 1, '5m': 5, '15m': 15, '30m': 30,
                '1h': 60, '4h': 240, '1d': 1440, '1w': 10080
            }
            
            if timeframe not in valid_timeframes:
                logger.error(f'不支持的时间周期: {timeframe}')
                raise ValueError(f'不支持的时间周期: {timeframe}')

            # 计算时间范围
            now = datetime.now()
            if not to_date:
                to_date = now.strftime('%Y-%m-%d')
            
            if not from_date:
                # 根据时间周期和数量计算开始时间
                minutes = valid_timeframes[timeframe] * limit
                from_date = (now - timedelta(minutes=minutes)).strftime('%Y-%m-%d')
            
            logger.info(f"计算时间范围: from={from_date}, to={to_date}")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # 获取代币价格数据
                price_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/price"
                logger.info(f"获取代币价格: {price_url}")
                price_data = await self._fetch_with_retry(session, price_url)
                
                if not price_data:
                    logger.error("无法获取价格数据")
                    return []
                
                # 获取交易对信息
                pairs_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/pairs"
                logger.info(f"获取交易对信息: {pairs_url}")
                pairs_data = await self._fetch_with_retry(session, pairs_url)
                
                if not pairs_data:
                    logger.error("无法获取交易对信息")
                    return []
                
                # 处理交易对数据
                pairs_list = []
                if isinstance(pairs_data, dict):
                    pairs_list = pairs_data.get('pairs', [])
                elif isinstance(pairs_data, list):
                    pairs_list = pairs_data
                
                if not pairs_list:
                    logger.error("没有找到交易对数据")
                    return []
                
                # 获取流动性最大的交易对
                active_pairs = [p for p in pairs_list if not p.get('inactivePair', True)]
                if not active_pairs:
                    logger.error("没有找到活跃的交易对")
                    return []
                
                try:
                    pair = max(active_pairs, key=lambda x: float(x.get('liquidityUsd', 0)))
                    pair_address = pair.get('pairAddress')
                    if not pair_address:
                        logger.error("无法获取交易对地址")
                        return []
                except Exception as e:
                    logger.error(f"处理交易对数据时出错: {str(e)}")
                    return []
                
                # 获取 OHLCV 数据
                ohlcv_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/pairs/{pair_address}/ohlcv"
                params = {
                    'timeframe': timeframe,
                    'currency': 'usd',
                    'fromDate': from_date,
                    'toDate': to_date,
                    'limit': str(limit)
                }
                
                logger.info(f"获取K线数据: {ohlcv_url}, params={params}")
                ohlcv_data = await self._fetch_with_retry(session, ohlcv_url, params=params)
                
                if not ohlcv_data or not isinstance(ohlcv_data, dict):
                    logger.error(f"K线数据格式错误: {ohlcv_data}")
                    return []
                
                result = ohlcv_data.get('result', [])
                if not isinstance(result, list):
                    logger.error(f"K线数据结果格式错误: {result}")
                    return []
                
                # 转换数据格式
                formatted_data = []
                for item in result:
                    try:
                        timestamp = item.get('timestamp')
                        if not timestamp:
                            continue
                            
                        # 转换时间戳
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        ts = int(dt.timestamp() * 1000)
                        
                        # 处理价格数据
                        open_price = float(item.get('open', 0))
                        high_price = float(item.get('high', 0))
                        low_price = float(item.get('low', 0))
                        close_price = float(item.get('close', 0))
                        volume = float(item.get('volume', 0))
                        
                        # 验证数据有效性
                        if all(price == 0 for price in [open_price, high_price, low_price, close_price]):
                            logger.warning(f"跳过无效的价格数据: {item}")
                            continue
                            
                        formatted_data.append({
                            'timestamp': ts,
                            'open': str(open_price),
                            'high': str(high_price),
                            'low': str(low_price),
                            'close': str(close_price),
                            'volume': str(volume)
                        })
                    except Exception as e:
                        logger.error(f"处理K线数据项时出错: {str(e)}, 数据项: {item}")
                        continue
                
                if not formatted_data:
                    logger.error("没有有效的K线数据")
                    return []
                    
                logger.info(f"成功获取到 {len(formatted_data)} 条K线数据")
                return formatted_data
            
        except Exception as e:
            logger.error(f"获取代币K线数据失败: {str(e)}", exc_info=True)
            return []