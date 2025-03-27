import aiohttp
import asyncio
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
from django.utils import timezone
from asgiref.sync import sync_to_async
from moralis import evm_api, sol_api
import json
from django.conf import settings

from ...models import Token, Wallet, Transaction
from ...services.solana_config import MoralisConfig, RPCConfig, HeliusConfig
from datetime import timedelta, datetime
import async_timeout

logger = logging.getLogger(__name__)

class SolanaTokenInfoService:
    """Solana 代币信息服务"""
    
    def __init__(self):
        self.headers = {
            "accept": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)
        self.max_retries = 3

    async def get_token_metadata(self, address: str) -> Optional[Dict]:
        """获取代币元数据"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # 获取代币元数据
                url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{address}/metadata"
                logger.debug(f"请求Moralis API获取代币元数据: {url}")
                
                metadata_response = await self._fetch_with_retry(session, url)
                if not metadata_response:
                    logger.error(f"无法获取代币元数据: {address}")
                    return None

                logger.info(f"Moralis API返回的原始数据: {json.dumps(metadata_response, indent=2)}")
                
                # 从 links 中提取社交媒体链接
                links = metadata_response.get('links', {})
                
                # 处理和转换数据
                processed_data = {
                    'name': metadata_response.get('name', ''),
                    'symbol': metadata_response.get('symbol', ''),
                    'decimals': int(metadata_response.get('decimals', 0)),
                    'logo': metadata_response.get('logo', ''),
                    'description': metadata_response.get('description', ''),
                    'website': links.get('website', ''),
                    'twitter': links.get('twitter', ''),
                    'telegram': links.get('telegram', ''),
                    'discord': links.get('discord', ''),
                    'github': links.get('github', ''),
                    'medium': links.get('medium', ''),
                    'total_supply': metadata_response.get('totalSupply', ''),
                    'total_supply_formatted': metadata_response.get('totalSupplyFormatted', ''),
                    'is_native': address == 'So11111111111111111111111111111111111111112',
                    'verified': bool(metadata_response.get('metaplex', {}).get('primarySaleHappened', False)),
                    'contract_type': metadata_response.get('standard', 'SPL'),
                    'metaplex_data': metadata_response.get('metaplex', {})
                }

                # 获取价格数据
                price_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{address}/price"
                price_response = await self._fetch_with_retry(session, price_url)
                
                if price_response:
                    try:
                        price = float(price_response.get('usdPrice', 0))
                        price_change = float(price_response.get('24hrPercentChange', 0))
                        
                        processed_data.update({
                            'price_usd': str(price),
                            'price_change_24h': f"{price_change:+.2f}%",
                            'volume_24h': str(price_response.get('volume24h', 0))
                        })
                    except (ValueError, TypeError) as e:
                        logger.error(f"处理价格数据失败: {str(e)}")

                logger.info(f"处理后的数据: {json.dumps(processed_data, indent=2)}")
                return processed_data

        except Exception as e:
            logger.error(f"获取代币元数据失败: {str(e)}")
            logger.exception(e)
            return None

    async def _fetch_with_retry(self, session, url, method="get", **kwargs):
        """带重试的HTTP请求函数"""
        kwargs['headers'] = self.headers
        if 'params' not in kwargs:
            kwargs['params'] = {}
        kwargs['params']['network'] = 'mainnet'
        
        logger.info(f"发起请求: {url}")
        
        for attempt in range(self.max_retries):
            try:
                async with getattr(session, method)(url, **kwargs) as response:
                    response_text = await response.text()
                    logger.info(f"响应状态码: {response.status}")
                    
                    if response.status == 200:
                        try:
                            data = json.loads(response_text)
                            return data
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON解析错误: {str(e)}")
                            return None
                    elif response.status == 429:  # Rate limit
                        retry_after = int(response.headers.get('Retry-After', 2))
                        logger.warning(f"请求频率限制，等待 {retry_after} 秒后重试")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"请求失败: {url}, 状态码: {response.status}")
                        return None
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    logger.warning(f"请求出错: {str(e)}, {wait_time} 秒后重试")
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"请求最终失败: {str(e)}")
                return None
        return None

    async def get_token_info(self, token_address: str) -> Dict:
        """获取代币基本信息"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 添加详细日志
                logger.info(f"开始获取代币信息: {token_address}")
                
                # 获取代币元数据
                url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/metadata"
                logger.info(f"请求Moralis元数据URL: {url}")
                logger.info(f"请求头: {self.headers}")
                
                # 添加重试机制和错误处理
                retry_count = 0
                max_retries = 3
                
                while retry_count < max_retries:
                    try:
                        metadata_response = await self._fetch_with_retry(session, url)
                        logger.info(f"Moralis元数据响应 (尝试 {retry_count + 1}): {metadata_response}")
                        
                        if metadata_response:
                            break
                        
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(1)  # 等待1秒后重试
                    except Exception as e:
                        logger.error(f"获取元数据失败 (尝试 {retry_count + 1}): {str(e)}")
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(1)
                        else:
                            raise
                
                # 获取代币价格
                price_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/price"
                logger.info(f"请求Moralis价格URL: {price_url}")
                
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        price_response = await self._fetch_with_retry(session, price_url)
                        logger.info(f"Moralis价格响应 (尝试 {retry_count + 1}): {price_response}")
                        
                        if price_response:
                            break
                        
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"获取价格失败 (尝试 {retry_count + 1}): {str(e)}")
                        retry_count += 1
                        if retry_count < max_retries:
                            await asyncio.sleep(1)
                        else:
                            raise

                # 检查响应
                if not metadata_response:
                    logger.error(f"无法获取代币元数据: {token_address}")
                    return {}

                # 处理元数据响应
                links = metadata_response.get('links', {})
                token_data = {
                    'name': metadata_response.get('name', 'Unknown Token'),
                    'symbol': metadata_response.get('symbol', 'Unknown'),
                    'decimals': int(metadata_response.get('decimals', 0)),
                    'logo': metadata_response.get('logo', ''),
                    'description': metadata_response.get('description') or '',
                    'website': links.get('website', ''),
                    'twitter': links.get('twitter', ''),
                    'telegram': links.get('telegram', ''),
                    'discord': links.get('discord', ''),
                    'github': links.get('github', ''),
                    'medium': links.get('medium', ''),
                    'total_supply': metadata_response.get('totalSupply', '0'),
                    'total_supply_formatted': metadata_response.get('totalSupplyFormatted', '0'),
                    'is_native': token_address == 'So11111111111111111111111111111111111111112',
                    'verified': bool(metadata_response.get('metaplex', {}).get('primarySaleHappened', False)),
                    'contract_type': metadata_response.get('standard', 'SPL'),
                    'from_cache': False
                }

                # 处理价格数据
                if price_response:
                    try:
                        price = float(price_response.get('usdPrice', 0))
                        price_change_24h = float(price_response.get('usdPrice24hrPercentChange', 0))
                        
                        token_data.update({
                            'price': price,
                            'price_change_24h': price_change_24h,
                            'market_cap': price * float(token_data['total_supply_formatted']),
                            'volume_24h': float(price_response.get('volume24h', 0))
                        })
                    except Exception as e:
                        logger.error(f"处理价格数据失败: {str(e)}")

                logger.info(f"最终的代币数据: {token_data}")
                return token_data

            except Exception as e:
                logger.error(f"获取代币信息时出错: {str(e)}")
                return {}

    async def get_token_supply(self, token_address: str) -> Dict:
        """获取代币供应量信息"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0",
                    "id": "my-id",
                    "method": HeliusConfig.GET_TOKEN_METADATA, # type: ignore
                    "params": {
                        "id": token_address
                    }
                }
                
                async with session.post(HeliusConfig.get_rpc_url(), json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        if 'result' in result:
                            helius_data = result['result']
                            content = helius_data.get('content', {})
                            metadata = content.get('metadata', {})
                            
                            decimals = metadata.get('decimals', 0)
                            total_supply = Decimal(metadata.get('supply', '0'))
                            
                            # 转换为实际数量
                            total_supply = total_supply / Decimal(str(10 ** decimals))
                            
                            return {
                                'total_supply': str(total_supply),
                                'circulating_supply': str(total_supply),  # Helius API 目前不提供流通量信息
                                'holder_count': 0,  # Helius API 目前不提供持有人数量信息
                                'decimals': decimals
                            }
                    
                    return {}
                    
        except Exception as e:
            logger.error(f"获取代币供应量信息失败: {str(e)}")
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

    async def _update_token_info(self, token_address: str, token_data: Dict) -> None:
        """更新数据库中的代币信息"""
        try:
            token_obj = await sync_to_async(Token.objects.filter(
                chain='SOL',
                address=token_address
            ).first)()
            
            if token_obj:
                # 更新数据库中的代币信息
                token_obj.name = token_data['name']
                token_obj.symbol = token_data['symbol']
                token_obj.decimals = token_data['decimals']
                token_obj.logo = token_data['logo']
                token_obj.price = float(token_data['price'])
                token_obj.price_change_24h = float(token_data['price_change_24h'])
                token_obj.price_change_7d = float(token_data['price_change_7d'])
                token_obj.price_change_30d = float(token_data['price_change_30d'])
                token_obj.market_cap = float(token_data['market_cap'])
                token_obj.market_cap_rank = token_data['market_cap_rank']
                token_obj.volume_24h = float(token_data['volume_24h'])
                token_obj.volume_change_24h = float(token_data['volume_change_24h'])
                token_obj.circulating_supply = token_data['circulating_supply']
                token_obj.max_supply = token_data['max_supply']
                token_obj.ath = float(token_data['ath'])
                token_obj.ath_date = token_data['ath_date']
                token_obj.atl = float(token_data['atl'])
                token_obj.atl_date = token_data['atl_date']
                token_obj.website = token_data.get('website', '')
                token_obj.twitter = token_data.get('twitter', '')
                token_obj.telegram = token_data.get('telegram', '')
                token_obj.discord = token_data.get('discord', '')
                token_obj.save()
        except Exception as e:
            logger.error(f"更新代币信息时出错: {str(e)}")

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
                        raise ValueError("Unsupported timeframe")
                        
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
                    logger.error(f"交易对数据格式错误，期望是列表或包含pairs字段的字典，实际是: {type(pairs_data)}")
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