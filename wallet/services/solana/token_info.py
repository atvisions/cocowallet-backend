import aiohttp
import asyncio
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
from django.utils import timezone
from asgiref.sync import sync_to_async
from moralis import evm_api, sol_api
import json

from ..base.token_info import BaseTokenInfoService
from ...models import Token, Wallet, Transaction
from ...api_config import MoralisConfig, APIConfig
from datetime import timedelta, datetime
import async_timeout

logger = logging.getLogger(__name__)

class SolanaTokenInfoService(BaseTokenInfoService):
    """Solana 代币信息服务实现类"""

    def __init__(self):
        self.headers = {
            "accept": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)
        self.max_retries = 3

    async def get_token_info(self, token_address: str) -> Dict:
        """获取代币基本信息"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 从 API 获取最新数据
                url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/metadata"
                response = await self._fetch_with_retry(session, url)
                
                if response:
                    # 从 links 中提取社交媒体链接
                    links = response.get('links', {})
                    
                    token_data = {
                        'name': response.get('name', 'Unknown Token'),
                        'symbol': response.get('symbol', 'Unknown'),
                        'decimals': int(response.get('decimals', 0)),
                        'logo': response.get('logo', ''),
                        'description': response.get('description') or '',
                        'website': links.get('website', ''),
                        'twitter': links.get('twitter', ''),
                        'telegram': links.get('telegram', ''),
                        'discord': links.get('discord', ''),
                        'github': links.get('github', ''),
                        'medium': links.get('medium', ''),
                        'total_supply': response.get('totalSupply', '0'),
                        'total_supply_formatted': response.get('totalSupplyFormatted', '0'),
                        'is_native': token_address == 'So11111111111111111111111111111111111111112',
                        'verified': bool(response.get('metaplex', {}).get('primarySaleHappened', False)),
                        'contract_type': response.get('standard', 'SPL'),
                        'from_cache': False
                    }

                    # 更新数据库
                    await sync_to_async(Token.objects.update_or_create)(
                        chain='SOL',
                        address=token_address,
                        defaults={
                            'name': token_data['name'],
                            'symbol': token_data['symbol'],
                            'decimals': token_data['decimals'],
                            'logo': token_data['logo'],
                            'type': 'token',
                            'contract_type': token_data['contract_type'],
                            'description': token_data['description'],
                            'website': token_data['website'],
                            'twitter': token_data['twitter'],
                            'telegram': token_data['telegram'],
                            'discord': token_data['discord'],
                            'github': token_data['github'],
                            'medium': token_data['medium'],
                            'total_supply': token_data['total_supply'],
                            'total_supply_formatted': token_data['total_supply_formatted'],
                            'verified': token_data['verified'],
                            'is_native': token_data['is_native'],
                            'updated_at': timezone.now()
                        }
                    )
                    return token_data

                return {}

            except Exception as e:
                logger.error(f"获取代币信息时出错: {str(e)}")
                return {}

    async def get_token_metadata(self, token_address: str) -> Dict:
        """获取代币元数据"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 从 Moralis API 获取最新数据
                url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/metadata"
                metadata = await self._fetch_with_retry(session, url)
                logger.debug(f"Moralis API 返回的元数据: {metadata}")
                
                if metadata:
                    # 获取价格信息
                    price_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/price"
                    price_data = await self._fetch_with_retry(session, price_url)
                    logger.debug(f"从API获取的价格数据: {price_data}")
                    
                    price_usd = '0'
                    price_change = '0'
                    if price_data and isinstance(price_data, dict):
                        try:
                            usd_price = price_data.get('usdPrice')
                            price_change_24h = price_data.get('usdPrice24hrPercentChange')
                            
                            logger.debug(f"原始价格数据 - usdPrice: {usd_price}, price_change_24h: {price_change_24h}")
                            
                            if usd_price is not None:
                                price_usd = str(usd_price)
                            if price_change_24h is not None:
                                price_change = str(price_change_24h)
                            
                            logger.debug(f"处理后的价格数据 - price_usd: {price_usd}, price_change: {price_change}")
                        except Exception as e:
                            logger.error(f"处理价格数据时出错: {str(e)}")
                    else:
                        logger.warning(f"无法获取价格数据或数据格式不正确: {price_data}")
                    
                    # 从 links 中提取社交媒体链接
                    links = metadata.get('links', {})
                    
                    token_data = {
                        'name': metadata.get('name', 'Unknown Token'),
                        'symbol': metadata.get('symbol', 'Unknown'),
                        'decimals': int(metadata.get('decimals', 0)),
                        'logo': metadata.get('logo', ''),
                        'description': metadata.get('description') or '',
                        'website': links.get('website', ''),
                        'twitter': links.get('twitter', ''),
                        'telegram': links.get('telegram', ''),
                        'discord': links.get('discord', ''),
                        'github': links.get('github', ''),
                        'medium': links.get('medium', ''),
                        'coingecko_id': '',  # Moralis API 不返回此字段
                        'total_supply': metadata.get('totalSupply', '0'),
                        'total_supply_formatted': metadata.get('totalSupplyFormatted', '0'),
                        'security_score': 0,  # Moralis API 不返回此字段
                        'verified': bool(metadata.get('metaplex', {}).get('primarySaleHappened', False)),
                        'possible_spam': False,  # Moralis API 不返回此字段
                        'is_native': token_address == 'So11111111111111111111111111111111111111112',
                        'price_usd': price_usd,
                        'price_change_24h': price_change,
                        'from_cache': False
                    }

                    # 更新数据库
                    await sync_to_async(Token.objects.update_or_create)(
                        chain='SOL',
                        address=token_address,
                        defaults={
                            'name': token_data['name'],
                            'symbol': token_data['symbol'],
                            'decimals': token_data['decimals'],
                            'logo': token_data['logo'],
                            'type': 'token',
                            'contract_type': metadata.get('standard', 'SPL'),
                            'description': token_data['description'],
                            'website': token_data['website'],
                            'twitter': token_data['twitter'],
                            'telegram': token_data['telegram'],
                            'discord': token_data['discord'],
                            'github': token_data['github'],
                            'medium': token_data['medium'],
                            'coingecko_id': token_data['coingecko_id'],
                            'total_supply': token_data['total_supply'],
                            'total_supply_formatted': token_data['total_supply_formatted'],
                            'security_score': token_data['security_score'],
                            'verified': token_data['verified'],
                            'possible_spam': token_data['possible_spam'],
                            'is_native': token_data['is_native'],
                            'last_price': price_usd,
                            'last_price_change': price_change,
                            'updated_at': timezone.now()
                        }
                    )

                    return token_data

                return {}

            except Exception as e:
                logger.error(f"获取代币元数据时出错: {str(e)}")
                return {}

    async def validate_token_address(self, token_address: str) -> bool:
        """验证代币地址是否有效"""
        try:
            # 检查地址格式
            if not isinstance(token_address, str) or len(token_address) != 44:
                return False

            # 检查是否能获取到代币信息
            token_info = await self.get_token_info(token_address)
            return bool(token_info.get('name') and token_info.get('symbol'))

        except Exception as e:
            logger.error(f"验证代币地址时出错: {str(e)}")
            return False

    async def get_token_supply(self, token_address: str) -> Dict:
        """获取代币供应量信息"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/supply"
                response = await self._fetch_with_retry(session, url)
                
                if response:
                    decimals = response.get('decimals', 0)
                    total_supply = Decimal(response.get('total_supply', '0'))
                    circulating_supply = Decimal(response.get('circulating_supply', '0'))
                    
                    # 转换为实际数量
                    total_supply = total_supply / Decimal(str(10 ** decimals))
                    circulating_supply = circulating_supply / Decimal(str(10 ** decimals))

                    return {
                        'total_supply': str(total_supply),
                        'circulating_supply': str(circulating_supply),
                        'holder_count': response.get('holder_count', 0),
                        'decimals': decimals
                    }

                return {}

            except Exception as e:
                logger.error(f"获取代币供应量信息时出错: {str(e)}")
                return {}

    async def _update_token_info(self, token_address: str, token_data: Dict) -> None:
        """更新数据库中的代币信息"""
        try:
            await sync_to_async(Token.objects.update_or_create)(
                chain='SOL',
                address=token_address,
                defaults={
                    'name': token_data['name'],
                    'symbol': token_data['symbol'],
                    'decimals': token_data['decimals'],
                    'logo': token_data['logo'],
                    'is_native': token_data['is_native'],
                    'updated_at': timezone.now()
                }
            )
        except Exception as e:
            logger.error(f"更新代币信息时出错: {str(e)}")

    async def _fetch_with_retry(self, session: aiohttp.ClientSession, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> Any:
        """带重试的 HTTP 请求
        
        Args:
            session: aiohttp session
            url: 请求地址
            params: 请求参数
            headers: 请求头
        """
        default_headers = {
            'Accept': 'application/json',
            'X-API-Key': MoralisConfig.API_KEY
        }
        
        if headers:
            default_headers.update(headers)
            
        logger.debug(f"发起请求: {url}")
        logger.debug(f"请求参数: {params}")
        logger.debug(f"请求头: {default_headers}")
        
        for i in range(self.max_retries):
            try:
                async with session.get(url, params=params, headers=default_headers) as response:
                    logger.debug(f"响应状态码: {response.status}")
                    response_text = await response.text()
                    logger.debug(f"响应内容: {response_text}")
                    
                    if response.status == 200:
                        return json.loads(response_text)
                    else:
                        logger.error(f"请求失败: {response.status} - {response_text}")
                        
            except Exception as e:
                logger.error(f"请求异常: {str(e)}")
                if i == self.max_retries - 1:
                    raise
                await asyncio.sleep(1)
        return None

    async def get_token_ohlcv(
        self,
        token_address: str,
        timeframe: str = '1h',
        currency: str = 'usd',
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 24
    ) -> Dict:
        """获取代币价格走势图数据"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                logger.debug(f"开始获取代币 {token_address} 的 OHLCV 数据")
                logger.debug(f"参数: timeframe={timeframe}, currency={currency}, limit={limit}, from_date={from_date}, to_date={to_date}")
                
                # 构建查询参数
                params = {
                    'timeframe': timeframe,
                    'currency': currency,
                    'limit': limit,
                    'network': 'mainnet'
                }
                
                # 如果没有指定日期范围，设置默认范围
                now = datetime.now()
                if timeframe == '1h':
                    from_date = (now - timedelta(days=1)).strftime('%Y-%m-%d')
                elif timeframe == '1d':
                    from_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')
                elif timeframe == '1w':
                    from_date = (now - timedelta(days=180)).strftime('%Y-%m-%d')
                else:  # 1m
                    from_date = (now - timedelta(days=365)).strftime('%Y-%m-%d')
                to_date = now.strftime('%Y-%m-%d')
                
                # 如果指定了日期范围，则使用指定的日期
                if from_date:
                    try:
                        datetime.strptime(from_date, '%Y-%m-%d')
                    except Exception as e:
                        logger.error(f"转换开始日期时出错: {str(e)}")
                        
                if to_date:
                    try:
                        datetime.strptime(to_date, '%Y-%m-%d')
                    except Exception as e:
                        logger.error(f"转换结束日期时出错: {str(e)}")
                
                params['fromDate'] = from_date
                params['toDate'] = to_date
                
                logger.debug(f"查询参数: {params}")
                
                # 获取代币的交易对地址
                pairs_url = MoralisConfig.SOLANA_TOKEN_PAIRS_URL.format(token_address)
                logger.debug(f"请求交易对数据: {pairs_url}")
                pairs_data = await self._fetch_with_retry(session, pairs_url)
                logger.debug(f"获取到的交易对数据: {pairs_data}")
                
                if not pairs_data:
                    logger.error(f"获取交易对数据失败")
                    return {}
                
                # 处理交易对数据
                pairs_list = []
                if isinstance(pairs_data, dict):
                    # 如果是字典格式，尝试从 pairs 字段获取列表
                    pairs_list = pairs_data.get('pairs', [])
                    if not isinstance(pairs_list, list):
                        logger.error(f"交易对数据中的 pairs 字段不是列表: {type(pairs_list)}")
                        return {}
                elif isinstance(pairs_data, list):
                    # 如果直接是列表格式
                    pairs_list = pairs_data
                else:
                    logger.error(f"交易对数据格式错误: {type(pairs_data)}")
                    return {}
                
                # 过滤出活跃的交易对
                active_pairs = [p for p in pairs_list if not p.get('inactivePair', True)]
                
                if len(active_pairs) == 0:
                    logger.warning(f"未找到代币 {token_address} 的活跃交易对")
                    return {}
                
                # 获取流动性最大的交易对
                try:
                    pair = max(active_pairs, key=lambda x: float(x.get('liquidityUsd', 0)))
                    logger.debug(f"选择的交易对: {pair}")
                    pair_address = pair.get('pairAddress')
                    logger.debug(f"交易对地址: {pair_address}")
                except Exception as e:
                    logger.error(f"处理交易对数据时出错: {str(e)}")
                    return {}
                
                if not pair_address:
                    logger.warning(f"未找到代币 {token_address} 的有效交易对")
                    return {}
                
                # 获取OHLCV数据
                url = MoralisConfig.SOLANA_TOKEN_PAIRS_OHLCV_URL.format(pair_address)
                logger.debug(f"请求OHLCV数据: {url}, 参数: {params}")
                ohlcv_data = await self._fetch_with_retry(session, url, params=params)
                logger.debug(f"获取到的OHLCV数据: {ohlcv_data}")
                
                if not ohlcv_data:
                    logger.error(f"获取OHLCV数据失败")
                    return {}
                    
                if not isinstance(ohlcv_data, dict):
                    logger.error(f"OHLCV数据格式错误，期望是字典，实际是: {type(ohlcv_data)}")
                    return {}
                
                # 处理数据
                result = []
                ohlcv_list = ohlcv_data.get('result', [])
                if not isinstance(ohlcv_list, list):
                    logger.error(f"OHLCV数据中的 result 字段不是列表: {type(ohlcv_list)}")
                    return {}
                
                for item in ohlcv_list:
                    try:
                        # 检查必要字段是否存在
                        required_fields = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                        if not all(field in item for field in required_fields):
                            logger.warning(f"OHLCV数据项缺少必要字段: {item}")
                            continue
                            
                        # 转换数据类型
                        timestamp_str = item.get('timestamp', '')
                        try:
                            # 将ISO 8601时间字符串转换为datetime对象
                            dt = datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%fZ')
                            # 转换为Unix时间戳(毫秒)
                            timestamp = int(dt.timestamp() * 1000)
                        except Exception as e:
                            logger.error(f"转换时间戳出错: {str(e)}, 时间字符串: {timestamp_str}")
                            continue
                            
                        open_price = float(item.get('open', 0))
                        high_price = float(item.get('high', 0))
                        low_price = float(item.get('low', 0))
                        close_price = float(item.get('close', 0))
                        volume = float(item.get('volume', 0))
                        trades = int(item.get('trades', 0))
                        
                        # 验证数据有效性
                        if timestamp == 0 or all(price == 0 for price in [open_price, high_price, low_price, close_price]):
                            logger.warning(f"跳过无效的OHLCV数据项: {item}")
                            continue
                            
                        result.append({
                            'timestamp': timestamp,
                            'open': open_price,
                            'high': high_price,
                            'low': low_price,
                            'close': close_price,
                            'volume': volume,
                            'trades': trades
                        })
                    except (TypeError, ValueError) as e:
                        logger.error(f"处理OHLCV数据项时出错: {str(e)}, 数据项: {item}")
                        continue
                
                if not result:
                    logger.error("处理后的OHLCV数据为空")
                    return {}
                
                logger.debug(f"处理后的OHLCV数据: {result}")
                
                return {
                    'pair_address': pair_address,
                    'timeframe': timeframe,
                    'currency': currency,
                    'data': result
                }
                
            except Exception as e:
                logger.error(f"获取代币OHLCV数据时出错: {str(e)}")
                return {} 