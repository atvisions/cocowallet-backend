"""EVM 代币信息服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
import asyncio
from web3 import Web3
from asgiref.sync import sync_to_async
from django.utils import timezone
from datetime import datetime
from django.core.cache import cache
import json
import os

from ...models import Token
from ...api_config import RPCConfig, MoralisConfig
from .utils import EVMUtils

logger = logging.getLogger(__name__)

class EVMTokenInfoService:
    """EVM 代币信息服务实现类"""

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        
        # Alchemy API 配置
        self.api_url = RPCConfig.get_alchemy_url(chain)
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }
        self.timeout = aiohttp.ClientTimeout(total=30)

    def get_token_info(self, token_address: str) -> Dict:
        """获取代币信息"""
        return EVMUtils.run_in_event_loop(self._get_token_info(token_address))

    async def _get_token_info(self, token_address: str) -> Dict:
        """获取代币信息的异步实现"""
        try:
            # 验证地址
            if not EVMUtils.validate_address(token_address):
                raise ValueError(f"无效的代币地址: {token_address}")
                
            # 获取代币元数据
            metadata = await self.get_token_metadata(token_address)
            if metadata:
                return {
                    'address': token_address,
                    'name': metadata.get('name', ''),
                    'symbol': metadata.get('symbol', ''),
                    'decimals': int(metadata.get('decimals', 18)),
                    'total_supply': metadata.get('total_supply', '0'),
                    'total_supply_formatted': metadata.get('total_supply_formatted', '0'),
                    'logo': metadata.get('logo', ''),
                    'website': metadata.get('website', ''),
                    'description': metadata.get('description', ''),
                    'social_links': {
                        'twitter': metadata.get('twitter', ''),
                        'telegram': metadata.get('telegram', ''),
                        'discord': metadata.get('discord', ''),
                        'github': metadata.get('github', ''),
                        'medium': metadata.get('medium', '')
                    },
                    'verified': metadata.get('verified', False),
                    'price_usd': metadata.get('price_usd', '0'),
                    'price_change_24h': metadata.get('price_change_24h', '+0.00%')
                }
            
            # 如果元数据获取失败，尝试直接从合约获取基本信息
            try:
                contract = self.web3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=[{
                        "constant": True,
                        "inputs": [],
                        "name": "name",
                        "outputs": [{"name": "", "type": "string"}],
                        "type": "function"
                    }, {
                        "constant": True,
                        "inputs": [],
                        "name": "symbol",
                        "outputs": [{"name": "", "type": "string"}],
                        "type": "function"
                    }, {
                        "constant": True,
                        "inputs": [],
                        "name": "decimals",
                        "outputs": [{"name": "", "type": "uint8"}],
                        "type": "function"
                    }]
                )
                
                # 获取基本信息
                name = contract.functions.name().call()
                symbol = contract.functions.symbol().call()
                decimals = contract.functions.decimals().call()
                
                return {
                    'address': token_address,
                    'name': name,
                    'symbol': symbol,
                    'decimals': decimals,
                    'total_supply': '0',
                    'total_supply_formatted': '0',
                    'logo': '',
                    'website': '',
                    'description': '',
                    'social_links': {},
                    'verified': False,
                    'price_usd': '0',
                    'price_change_24h': '+0.00%'
                }
                
            except Exception as contract_error:
                logger.error(f"从合约获取代币信息失败: {str(contract_error)}")
                # 返回最基本的信息
                return {
                    'address': token_address,
                    'name': 'Unknown Token',
                    'symbol': '???',
                    'decimals': 18,
                    'total_supply': '0',
                    'total_supply_formatted': '0',
                    'logo': '',
                    'website': '',
                    'description': '',
                    'social_links': {},
                    'verified': False,
                    'price_usd': '0',
                    'price_change_24h': '+0.00%'
                }
            
        except Exception as e:
            logger.error(f"获取代币信息失败: {str(e)}")
            return {
                'address': token_address,
                'name': 'Unknown Token',
                'symbol': '???',
                'decimals': 18,
                'total_supply': '0',
                'total_supply_formatted': '0',
                'logo': '',
                'website': '',
                'description': '',
                'social_links': {},
                'verified': False,
                'price_usd': '0',
                'price_change_24h': '+0.00%'
            }

    async def get_token_metadata(self, token_address: str) -> Dict:
        """获取代币元数据"""
        try:
            # 获取 Moralis API 配置
            if not MoralisConfig.API_KEY:
                logger.error("未配置 MORALIS_API_KEY")
                return {}
            
            # 获取链 ID
            chain = MoralisConfig.get_chain_id(self.chain)
            
            # 构建 API URL
            url = MoralisConfig.EVM_TOKEN_METADATA_URL
            params = {
                'chain': chain,
                'addresses': [token_address]
            }
            
            logger.debug(f"请求 Moralis API - URL: {url}, 参数: {params}")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    url, 
                    headers=MoralisConfig.get_headers(), 
                    params=params
                ) as response:
                    response_text = await response.text()
                    logger.debug(f"Moralis API 响应: {response_text}")
                    
                    if response.status != 200:
                        logger.error(f"获取代币元数据失败: {response_text}")
                        return {}
                    
                    try:
                        results = json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.error(f"解析代币元数据失败: {response_text}")
                        return {}
                    
                    if not results or not isinstance(results, list) or len(results) == 0:
                        return {}
                    
                    result = results[0]  # 获取第一个结果
                    
                    # 获取代币价格
                    price_data = await self.get_token_price(token_address)
                    
                    # 构建完整的元数据
                    token_data = {
                        'name': result.get('name', ''),
                        'symbol': result.get('symbol', ''),
                        'decimals': int(result.get('decimals', 18)),
                        'logo': result.get('logo', ''),
                        'thumbnail': result.get('thumbnail', ''),
                        'type': 'token',
                        'contract_type': 'ERC20',
                        'description': result.get('description', ''),
                        'website': result.get('links', {}).get('website', ''),
                        'twitter': result.get('links', {}).get('twitter', ''),
                        'telegram': result.get('links', {}).get('telegram', ''),
                        'discord': result.get('links', {}).get('discord', ''),
                        'github': result.get('links', {}).get('github', ''),
                        'medium': result.get('links', {}).get('medium', ''),
                        'reddit': result.get('links', {}).get('reddit', ''),
                        'instagram': result.get('links', {}).get('instagram', ''),
                        'email': result.get('links', {}).get('email', ''),
                        'moralis': result.get('links', {}).get('moralis', ''),
                        'total_supply': result.get('total_supply', '0'),
                        'total_supply_formatted': result.get('total_supply_formatted', '0'),
                        'circulating_supply': result.get('circulating_supply', '0'),
                        'market_cap': result.get('market_cap', '0'),
                        'fully_diluted_valuation': result.get('fully_diluted_valuation', '0'),
                        'categories': result.get('categories', []),
                        'security_score': result.get('security_score', 0),
                        'verified': result.get('verified_contract', False),
                        'possible_spam': result.get('possible_spam', False),
                        'block_number': result.get('block_number', ''),
                        'validated': result.get('validated', 0),
                        'created_at': result.get('created_at', ''),
                        'price_usd': price_data.get('price_usd', '0'),
                        'price_change_24h': price_data.get('price_change_24h', '+0.00%')
                    }
                    
                    return token_data
            
        except Exception as e:
            logger.error(f"获取代币元数据失败: {str(e)}")
            return {}

    def validate_token_address(self, token_address: str) -> bool:
        """验证代币合约地址"""
        try:
            # 验证地址格式
            if not EVMUtils.validate_address(token_address):
                return False
                
            # 验证合约代码
            code = self.web3.eth.get_code(Web3.to_checksum_address(token_address))
            if code == b'' or code == '0x':
                return False
                
            # 验证是否实现了 ERC20 接口
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=[{
                    "constant": True,
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "type": "function"
                }]
            )
            
            try:
                contract.functions.decimals().call()
                return True
            except:
                return False
                
        except Exception as e:
            logger.error(f"验证代币地址失败: {str(e)}")
            return False

    async def _update_token_info(self, token_address: str, token_data: Dict) -> None:
        """更新代币信息"""
        try:
            token = await sync_to_async(Token.objects.filter(
                chain=self.chain,
                address=token_address
            ).first)()
            
            defaults = {
                'name': token_data.get('name', ''),
                'symbol': token_data.get('symbol', ''),
                'decimals': token_data.get('decimals', 18),
                'logo': token_data.get('logo', ''),
                'logo_hash': token_data.get('logo_hash', ''),
                'thumbnail': token_data.get('thumbnail', ''),
                'description': token_data.get('description', ''),
                'website': token_data.get('website', ''),
                'email': token_data.get('email', ''),
                'twitter': token_data.get('twitter', ''),
                'telegram': token_data.get('telegram', ''),
                'discord': token_data.get('discord', ''),
                'reddit': token_data.get('reddit', ''),
                'instagram': token_data.get('instagram', ''),
                'github': token_data.get('github', ''),
                'total_supply': token_data.get('total_supply', '0'),
                'total_supply_formatted': token_data.get('total_supply_formatted', '0'),
                'circulating_supply': token_data.get('circulating_supply', '0'),
                'market_cap': token_data.get('market_cap', '0'),
                'fully_diluted_valuation': token_data.get('fully_diluted_valuation', '0'),
                'categories': token_data.get('categories', []),
                'security_score': token_data.get('security_score', 0),
                'verified': token_data.get('verified', False),
                'possible_spam': token_data.get('possible_spam', False),
                'block_number': token_data.get('block_number', ''),
                'validated': token_data.get('validated', 0),
                'created_at': token_data.get('created_at', ''),
                'type': 'token',
                'contract_type': 'ERC20',
                'updated_at': timezone.now()
            }
            
            if token:
                # 更新现有记录
                for key, value in defaults.items():
                    if hasattr(token, key):
                        setattr(token, key, value)
                await sync_to_async(token.save)()
            else:
                # 创建新记录
                await sync_to_async(Token.objects.create)(
                    chain=self.chain,
                    address=token_address,
                    **defaults
                )
                
        except Exception as e:
            logger.error(f"更新代币信息失败: {str(e)}")

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
        try:
            # 获取当前价格
            current_price_data = await self.get_token_price(token_address)
            
            # 获取 Moralis API 配置
            if not MoralisConfig.API_KEY:
                logger.error("未配置 MORALIS_API_KEY")
                return {}
            
            # 获取链 ID
            chain = MoralisConfig.get_chain_id(self.chain)
            
            # 如果代币没有价格数据，说明可能没有流动性或未在交易所上市
            if current_price_data.get('price_usd', '0') == '0':
                logger.info(f"代币 {token_address} 在 {self.chain} 链上没有价格数据")
                return {
                    'timeframe': timeframe,
                    'currency': currency,
                    'data': [],
                    'price_usd': '0',
                    'price_change_24h': '+0.00%'
                }
            
            # 如果未提供时间范围，设置默认值
            if not from_date or not to_date:
                now = datetime.utcnow()
                if timeframe == '1h':
                    # 过去24小时
                    to_date = now.strftime("%Y-%m-%d")
                    from_date = (now - timezone.timedelta(days=1)).strftime("%Y-%m-%d")
                elif timeframe == '1d':
                    # 过去30天
                    to_date = now.strftime("%Y-%m-%d")
                    from_date = (now - timezone.timedelta(days=30)).strftime("%Y-%m-%d")
                elif timeframe == '1w':
                    # 过去90天
                    to_date = now.strftime("%Y-%m-%d")
                    from_date = (now - timezone.timedelta(days=90)).strftime("%Y-%m-%d")
                else:
                    # 默认过去30天
                    to_date = now.strftime("%Y-%m-%d")
                    from_date = (now - timezone.timedelta(days=30)).strftime("%Y-%m-%d")
            
            # 首先获取代币的交易对信息
            pairs_url = MoralisConfig.EVM_TOKEN_PAIRS_URL.format(token_address)
            pairs_params = {
                'chain': chain
            }
            
            logger.debug(f"请求 Moralis API 获取交易对 - URL: {pairs_url}, 参数: {pairs_params}")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    pairs_url, 
                    headers=MoralisConfig.get_headers(), 
                    params=pairs_params
                ) as response:
                    response_text = await response.text()
                    logger.debug(f"Moralis API 交易对响应: {response_text}")
                    
                    if response.status != 200:
                        logger.error(f"获取交易对信息失败: {response_text}")
                        return {}
                    
                    try:
                        pairs_result = json.loads(response_text)
                    except json.JSONDecodeError:
                        logger.error(f"解析交易对数据失败: {response_text}")
                        return {}
                    
                    # 检查返回的数据结构
                    if not pairs_result:
                        logger.error("没有找到交易对数据")
                        return {}
                        
                    # 获取 pairs 数组
                    pairs = pairs_result.get('pairs', [])
                    if not pairs:
                        logger.error("没有找到有效的交易对")
                        return {}
                    
                    # 使用第一个交易对的地址
                    pair_address = pairs[0].get('pair_address')
                    if not pair_address:
                        logger.error("交易对地址为空")
                        return {}
                    
                    # 构建 OHLCV API URL
                    url = MoralisConfig.EVM_TOKEN_PRICE_CHART_URL.format(pair_address)
                    params = {
                        'chain': chain,
                        'timeframe': timeframe,
                        'currency': currency,
                        'limit': limit,
                        'fromDate': from_date,
                        'toDate': to_date
                    }
                    
                    logger.debug(f"请求 Moralis API 获取价格数据 - URL: {url}, 参数: {params}")
                    
                    async with session.get(
                        url, 
                        headers=MoralisConfig.get_headers(), 
                        params=params
                    ) as response:
                        response_text = await response.text()
                        logger.debug(f"Moralis API OHLCV 响应: {response_text}")
                        
                        if response.status != 200:
                            logger.error(f"获取价格历史数据失败: {response_text}")
                            return {}
                        
                        try:
                            result = json.loads(response_text)
                        except json.JSONDecodeError:
                            logger.error(f"解析价格历史数据失败: {response_text}")
                            return {}
                        
                        if not result or not isinstance(result, dict) or 'result' not in result:
                            logger.error("返回数据格式不正确")
                            return {}
                        
                        # 获取结果数组
                        ohlcv_data = result.get('result', [])
                        if not isinstance(ohlcv_data, list):
                            logger.error("OHLCV 数据格式不正确")
                            return {}
                        
                        # 处理价格历史数据
                        data = []
                        for item in ohlcv_data:
                            try:
                                timestamp = int(datetime.strptime(
                                    item.get('timestamp', ''),
                                    "%Y-%m-%dT%H:%M:%S.%fZ"
                                ).timestamp())
                            except (ValueError, TypeError):
                                logger.error(f"解析时间戳失败: {item.get('timestamp', '')}")
                                continue
                            
                            try:
                                open_price = float(item.get('open', 0))
                                high_price = float(item.get('high', 0))
                                low_price = float(item.get('low', 0))
                                close_price = float(item.get('close', 0))
                                volume = float(item.get('volume', 0))
                                swaps = int(item.get('swaps', 0))
                            except (ValueError, TypeError):
                                logger.error(f"解析价格或交易量失败: {item}")
                                continue
                            
                            data.append({
                                'timestamp': timestamp,
                                'open': open_price,
                                'high': high_price,
                                'low': low_price,
                                'close': close_price,
                                'volume': volume,
                                'trades': swaps
                            })
                        
                        if not data:
                            logger.error("没有有效的价格历史数据")
                            return {}
                        
                        return {
                            'timeframe': timeframe,
                            'currency': currency,
                            'data': data,
                            'price_usd': current_price_data.get('price_usd', '0'),
                            'price_change_24h': current_price_data.get('price_change_24h', '+0.00%')
                        }
                    
        except Exception as e:
            logger.error(f"获取代币价格数据失败: {str(e)}")
            return {}

    async def get_token_price(self, token_address: str) -> Dict:
        """获取代币价格
        
        Args:
            token_address: 代币合约地址
            
        Returns:
            Dict: 价格信息，包含 price_usd 和 price_change_24h
        """
        try:
            # 检查缓存
            cache_key = f"token_price_{self.chain}_{token_address}"
            cached_price = cache.get(cache_key)
            if cached_price:
                return cached_price
            
            # 获取 Moralis API 配置
            if not MoralisConfig.API_KEY:
                logger.error("未配置 MORALIS_API_KEY")
                return {
                    'price_usd': '0',
                    'price_change_24h': '+0.00%'
                }
            
            # 获取链 ID
            chain = MoralisConfig.get_chain_id(self.chain)
            
            # 构建 API URL
            url = MoralisConfig.EVM_TOKEN_PRICE_URL.format(token_address)
            params = {
                'chain': chain,
                'include': 'percent_change'
            }
            
            logger.debug(f"请求 Moralis API - URL: {url}, 参数: {params}")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    url, 
                    headers=MoralisConfig.get_headers(), 
                    params=params
                ) as response:
                    response_text = await response.text()
                    logger.debug(f"Moralis API 响应: {response_text}")
                    
                    # 检查是否是已知的错误响应
                    if "No liquidity pools found" in response_text:
                        logger.info(f"代币 {token_address} 没有流动性池")
                        return {
                            'price_usd': '0',
                            'price_change_24h': '+0.00%'
                        }
                    
                    if response.status == 200:
                        try:
                            result = json.loads(response_text)
                        except json.JSONDecodeError:
                            logger.error(f"解析价格数据失败: {response_text}")
                            return {
                                'price_usd': '0',
                                'price_change_24h': '+0.00%'
                            }
                        
                        # 获取价格
                        try:
                            price = float(result.get('usdPrice', result.get('usdPriceFormatted', 0)))
                        except (TypeError, ValueError):
                            price = 0
                        
                        # 获取24小时价格变化
                        try:
                            price_change = float(result.get('24hrPercentChange', 0))
                        except (TypeError, ValueError):
                            price_change = 0
                        
                        # 格式化价格
                        if price < 0.000001:
                            formatted_price = '{:.12f}'.format(price)
                        elif price < 0.00001:
                            formatted_price = '{:.10f}'.format(price)
                        elif price < 0.0001:
                            formatted_price = '{:.8f}'.format(price)
                        elif price < 0.01:
                            formatted_price = '{:.6f}'.format(price)
                        else:
                            formatted_price = '{:.4f}'.format(price)
                        formatted_price = formatted_price.rstrip('0').rstrip('.')
                        
                        # 格式化价格变化
                        formatted_price_change = '{:+.2f}%'.format(price_change)
                        
                        price_data = {
                            'price_usd': formatted_price,
                            'price_change_24h': formatted_price_change
                        }
                        
                        # 缓存价格数据
                        if price_data['price_usd'] != '0':
                            cache.set(cache_key, price_data, timeout=300)  # 5分钟缓存
                            
                        return price_data
                    else:
                        logger.error(f"获取代币价格失败: {response_text}")
                        return {
                            'price_usd': '0',
                            'price_change_24h': '+0.00%'
                        }
                        
        except Exception as e:
            logger.error(f"获取代币价格失败: {str(e)}")
            return {
                'price_usd': '0',
                'price_change_24h': '+0.00%'
            } 