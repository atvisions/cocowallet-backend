import aiohttp
import logging
import requests
import json
from typing import Dict, List
from decimal import Decimal
from django.utils import timezone
from . import BaseTokenService
from ..api_config import MoralisConfig
from ..models import Token
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TokenPriceService(BaseTokenService):
    """代币价格服务类，处理代币价格相关的功能"""

    @staticmethod
    async def update_token_prices(token_data: Dict) -> None:
        """更新代币价格信息"""
        # Moralis API 已经返回了完整的价格信息，不需要额外更新
        logger.info("代币价格已经包含在 Moralis API 响应中，无需更新")
        return

    @staticmethod
    async def _update_solana_token_prices(tokens: List[Dict]) -> None:
        """更新 Solana 代币价格"""
        try:
            # 收集需要查询价格的代币地址
            token_map = {}
            for token in tokens:
                if token.get('is_native'):
                    # 原生SOL代币使用特殊处理
                    token_map['SOL'] = token
                else:
                    mint = token.get('mint')
                    if mint:
                        token_map[mint] = token

            if not token_map:
                return

            # 使用Moralis API获取Solana代币价格
            base_url = MoralisConfig.SOLANA_URL
            
            # 逐个请求代币价格
            for token_address, token in token_map.items():
                try:
                    # 原生SOL代币使用特殊处理
                    if token_address == 'SOL':
                        price_url = MoralisConfig.SOLANA_TOKEN_PRICE_URL.format('So11111111111111111111111111111111111111112')
                    else:
                        price_url = MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(token_address)
                    
                    params = {
                        "network": "mainnet",
                        "address": token_address if token_address != 'SOL' else 'So11111111111111111111111111111111111111112'
                    }
                    
                    async with aiohttp.ClientSession() as session:
                        headers = {"X-API-Key": MoralisConfig.API_KEY}
                        
                        # 获取代币元数据
                        if not token.get('is_native'):
                            metadata_url = MoralisConfig.SOLANA_TOKEN_METADATA_URL
                            async with session.get(metadata_url, headers=headers, params=params) as metadata_response:
                                if metadata_response.status == 200:
                                    metadata = await metadata_response.json()
                                    if metadata:
                                        # 更新代币信息
                                        token['name'] = metadata.get('name', token.get('name', 'Unknown'))
                                        token['symbol'] = metadata.get('symbol', token.get('symbol', 'Unknown'))
                                        token['decimals'] = metadata.get('decimals', token.get('decimals', 9))
                                        token['logo'] = metadata.get('logo', token.get('logo', ''))
                            
                        # 获取代币价格
                        async with session.get(price_url, headers=headers) as price_response:
                            if price_response.status == 200:
                                price_data = await price_response.json()
                                if price_data:
                                    # 更新价格信息
                                    price_usd = price_data.get('usdPrice', 0)
                                    token['price_usd'] = f"{price_usd:.12f}".rstrip('0').rstrip('.')
                                    # 获取24小时涨跌幅，添加空值检查
                                    price_change = price_data.get('usdPrice24hrPercentChange')
                                    token['price_change_24h'] = f"{price_change:.12f}".rstrip('0').rstrip('.') if price_change is not None else '0'
                                    # 计算价值
                                    try:
                                        balance = Decimal(str(token.get('balance', 0)))
                                        price = Decimal(str(price_usd))
                                        value = balance * price
                                        token['value_usd'] = f"{value:.12f}".rstrip('0').rstrip('.')
                                    except Exception as e:
                                        logger.error(f"计算Solana代币价值时出错: {str(e)}")
                                        token['value_usd'] = '0'
                            else:
                                # 如果无法获取价格，设置默认值
                                token['price_usd'] = '0'
                                token['price_change_24h'] = '0'
                                token['value_usd'] = '0'
                                error_text = await price_response.text()
                                logger.warning(f"获取Solana代币 {token_address} 价格数据失败: {error_text}")
                except Exception as e:
                    logger.error(f"处理Solana代币 {token_address} 数据时出错: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"更新Solana代币价格时出错: {str(e)}")

    @staticmethod
    async def _update_evm_token_prices(chain: str, tokens: List[Dict]) -> None:
        """更新 EVM 链代币价格"""
        try:
            chain_id = TokenPriceService.CHAIN_MAPPING.get(chain, 'eth')
            token_addresses = []
            token_map = {}

            # 收集需要查询价格的代币地址
            for token in tokens:
                if token.get('is_native'):
                    # 添加原生代币的包装代币地址
                    if chain == 'ETH':
                        address = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
                    elif chain == 'BSC':
                        address = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
                    elif chain == 'POLYGON':
                        address = '0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0'
                    elif chain == 'BTC':
                        address = '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599'
                    else:
                        continue
                else:
                    address = token.get('contract')
                    if not address:
                        logger.warning(f"代币缺少合约地址: {token.get('symbol')}")
                        continue

                token_addresses.append(address)
                token_map[address.lower()] = token

            if not token_addresses:
                return

            # 使用新的Token Price API获取价格
            async with aiohttp.ClientSession() as session:
                headers = {"X-API-Key": MoralisConfig.API_KEY}
                
                for address in token_addresses:
                    try:
                        # 使用新的API端点格式
                        url = MoralisConfig.EVM_TOKEN_PRICE_URL.format(address)
                        params = {
                            "chain": chain_id,
                            "include": "percent_change"
                        }
                        
                        async with session.get(url, headers=headers, params=params) as response:
                            logger.info(f"代币 {address} 价格API响应状态: {response.status}")
                            if response.status == 200:
                                price_data = await response.json()
                                token = token_map.get(address.lower())
                                if token and price_data:
                                    # 更新价格信息
                                    price_usd = price_data.get('usdPrice', 0)
                                    token['price_usd'] = f"{price_usd:.12f}".rstrip('0').rstrip('.')
                                    price_change = price_data.get('24hPercentChange', 0)
                                    token['price_change_24h'] = f"{price_change:.12f}".rstrip('0').rstrip('.')
                                    # 计算价值
                                    try:
                                        balance = Decimal(str(token.get('balance', 0)))
                                        price = Decimal(str(price_usd))
                                        value = balance * price
                                        token['value_usd'] = f"{value:.12f}".rstrip('0').rstrip('.')
                                    except Exception as e:
                                        logger.error(f"计算代币价值时出错: {str(e)}")
                                        token['value_usd'] = '0'
                            else:
                                error_text = await response.text()
                                logger.error(f"获取代币 {address} 价格数据失败: {error_text}")
                    except Exception as e:
                        logger.error(f"处理代币 {address} 价格数据时出错: {str(e)}")
                        continue

        except Exception as e:
            logger.error(f"更新代币价格时出错: {str(e)}")

    @staticmethod
    def get_token_details(chain: str, address: str) -> Dict:
        """获取代币详细信息"""
        try:
            # 标准化地址
            normalized_address = address.lower() if chain != 'SOL' else address
            
            # 从数据库获取代币信息，包括缓存时间检查
            token = Token.objects.filter(
                chain=chain,
                address=normalized_address,
                updated_at__gte=timezone.now() - timedelta(minutes=5)  # 5分钟缓存
            ).first()
            
            # 如果有有效缓存，直接返回缓存数据
            if token and token.last_price and float(token.last_price) > 0:
                logger.info(f"使用缓存的代币详情数据: {token.symbol}")
                return {
                    'basic_info': {
                        'name': token.name,
                        'symbol': token.symbol,
                        'decimals': token.decimals,
                        'logo': token.logo,
                        'chain': chain,
                        'contract': normalized_address,
                        'description': token.description,
                        'created_at': token.created_at,
                        'possible_spam': token.possible_spam,
                    },
                    'market_data': {
                        'price_usd': token.last_price,
                        'price_change_24h': token.last_price_change,
                        'total_supply': token.total_supply,
                        'total_supply_formatted': token.total_supply_formatted,
                        'value_usd': token.last_value
                    },
                    'social_links': {
                        'website': token.website,
                        'twitter': token.twitter,
                        'telegram': token.telegram,
                        'discord': token.discord,
                        'github': token.github,
                        'medium': token.medium,
                        'reddit': token.reddit[0] if token.reddit else None
                    },
                    'technical_info': {
                        'standard': token.contract_type,
                        'verified': token.verified,
                        'security_score': token.security_score,
                        'is_native': token.is_native
                    }
                }

            # 如果没有缓存或缓存已过期，从API获取最新数据
            headers = {"X-API-Key": MoralisConfig.API_KEY}
            
            if chain in ['ETH', 'BNB', 'MATIC', 'AVAX']:
                # EVM链代币处理
                metadata_url = MoralisConfig.EVM_TOKEN_METADATA_URL
                params = {
                    "chain": TokenPriceService.CHAIN_MAPPING.get(chain, 'eth'),
                    "addresses": [normalized_address]
                }
                
                metadata_response = requests.get(metadata_url, headers=headers, params=params)
                if metadata_response.status_code != 200:
                    logger.warning(f"获取EVM代币元数据失败: {metadata_response.text}")
                    if token:
                        return TokenPriceService._get_cached_token_data(token)
                    raise ValueError(f"无法获取代币 {address} 的元数据信息")
                
                try:
                    metadata = metadata_response.json()
                    if not metadata or not isinstance(metadata, list) or len(metadata) == 0:
                        if token:
                            return TokenPriceService._get_cached_token_data(token)
                        raise ValueError(f"无法获取代币 {address} 的元数据信息")
                    metadata = metadata[0]
                except json.JSONDecodeError as e:
                    logger.error(f"解析代币元数据失败: {str(e)}")
                    if token:
                        return TokenPriceService._get_cached_token_data(token)
                    raise ValueError(f"解析代币 {address} 的元数据失败")
                
                # 获取价格信息
                price_url = MoralisConfig.EVM_TOKEN_PRICE_URL.format(normalized_address)
                params = {
                    "chain": TokenPriceService.CHAIN_MAPPING.get(chain, 'eth'),
                    "include": "percent_change"
                }
                price_response = requests.get(price_url, headers=headers, params=params)
                price_data = price_response.json() if price_response.status_code == 200 else {}
                
                token_data = {
                    'basic_info': {
                        'name': metadata.get('name'),
                        'symbol': metadata.get('symbol'),
                        'decimals': int(metadata.get('decimals', '18')),
                        'logo': metadata.get('logo') or metadata.get('thumbnail'),
                        'chain': chain,
                        'contract': normalized_address,
                        'description': metadata.get('description'),
                        'created_at': metadata.get('created_at'),
                        'possible_spam': metadata.get('possible_spam', False)
                    },
                    'market_data': {
                        'price_usd': str(price_data.get('usdPrice', '0')),
                        'price_change_24h': str(price_data.get('24hPercentChange', '0')),
                        'total_supply': metadata.get('total_supply'),
                        'total_supply_formatted': metadata.get('total_supply_formatted'),
                        'value_usd': '0'
                    },
                    'social_links': {
                        'website': metadata.get('links', {}).get('website'),
                        'twitter': metadata.get('links', {}).get('twitter'),
                        'telegram': metadata.get('links', {}).get('telegram'),
                        'discord': metadata.get('links', {}).get('discord'),
                        'github': metadata.get('links', {}).get('github'),
                        'medium': metadata.get('links', {}).get('medium'),
                        'reddit': metadata.get('links', {}).get('reddit')
                    },
                    'technical_info': {
                        'standard': 'ERC20',
                        'verified': metadata.get('verified_contract', False),
                        'security_score': metadata.get('security_score'),
                        'is_native': False
                    }
                }
                
                # 更新数据库缓存
                Token.objects.update_or_create(
                    chain=chain,
                    address=normalized_address,
                    defaults={
                        'name': token_data['basic_info']['name'],
                        'symbol': token_data['basic_info']['symbol'],
                        'decimals': token_data['basic_info']['decimals'],
                        'logo': token_data['basic_info']['logo'],
                        'description': token_data['basic_info']['description'],
                        'website': token_data['social_links']['website'],
                        'twitter': token_data['social_links']['twitter'],
                        'telegram': token_data['social_links']['telegram'],
                        'reddit': [token_data['social_links']['reddit']] if token_data['social_links']['reddit'] else [],
                        'discord': token_data['social_links']['discord'],
                        'github': token_data['social_links']['github'],
                        'medium': token_data['social_links']['medium'],
                        'total_supply': token_data['market_data']['total_supply'],
                        'total_supply_formatted': token_data['market_data']['total_supply_formatted'],
                        'last_price': token_data['market_data']['price_usd'],
                        'last_price_change': token_data['market_data']['price_change_24h'],
                        'security_score': token_data['technical_info']['security_score'],
                        'verified': token_data['technical_info']['verified'],
                        'created_at': token_data['basic_info']['created_at'],
                        'possible_spam': token_data['basic_info']['possible_spam'],
                        'updated_at': timezone.now()
                    }
                )
                
                return token_data
                
            elif chain == 'SOL':
                # Solana代币处理
                metadata_url = MoralisConfig.SOLANA_TOKEN_METADATA_URL.format(normalized_address)
                metadata_response = requests.get(metadata_url, headers=headers)
                
                if metadata_response.status_code != 200:
                    logger.warning(f"获取Solana代币元数据失败: {metadata_response.text}")
                    if token:
                        return TokenPriceService._get_cached_token_data(token)
                    raise ValueError(f"无法获取代币 {address} 的元数据信息")
                
                try:
                    metadata = metadata_response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"解析代币元数据失败: {str(e)}")
                    if token:
                        return TokenPriceService._get_cached_token_data(token)
                    raise ValueError(f"解析代币 {address} 的元数据失败")
                
                if not metadata:
                    if token:
                        return TokenPriceService._get_cached_token_data(token)
                    raise ValueError(f"无法获取代币 {address} 的元数据信息")
                
                # 获取价格信息
                price_url = MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(normalized_address)
                price_response = requests.get(price_url, headers=headers)
                price_data = price_response.json() if price_response.status_code == 200 else {}
                
                links = metadata.get('links', {})
                token_data = {
                    'basic_info': {
                        'name': metadata.get('name'),
                        'symbol': metadata.get('symbol'),
                        'decimals': int(metadata.get('decimals', '9')),
                        'logo': metadata.get('logo'),
                        'chain': chain,
                        'contract': normalized_address,
                        'description': metadata.get('description')
                    },
                    'market_data': {
                        'price_usd': str(price_data.get('usdPrice', '0')),
                        'price_change_24h': str(price_data.get('usdPrice24hrPercentChange', '0')),
                        'total_supply': metadata.get('totalSupply'),
                        'total_supply_formatted': metadata.get('totalSupplyFormatted'),
                        'value_usd': '0'
                    },
                    'social_links': {
                        'website': links.get('website'),
                        'twitter': links.get('twitter'),
                        'telegram': links.get('telegram'),
                        'discord': links.get('discord'),
                        'github': links.get('github'),
                        'medium': links.get('medium'),
                        'reddit': links.get('reddit')
                    },
                    'technical_info': {
                        'standard': metadata.get('standard', 'SPL'),
                        'verified': metadata.get('verified', False),
                        'is_native': normalized_address == 'So11111111111111111111111111111111111111112'
                    }
                }
                
                # 更新数据库缓存
                Token.objects.update_or_create(
                    chain=chain,
                    address=normalized_address,
                    defaults={
                        'name': token_data['basic_info']['name'],
                        'symbol': token_data['basic_info']['symbol'],
                        'decimals': token_data['basic_info']['decimals'],
                        'logo': token_data['basic_info']['logo'],
                        'description': token_data['basic_info']['description'],
                        'website': token_data['social_links']['website'],
                        'twitter': token_data['social_links']['twitter'],
                        'telegram': token_data['social_links']['telegram'],
                        'reddit': [token_data['social_links']['reddit']] if token_data['social_links']['reddit'] else [],
                        'discord': token_data['social_links']['discord'],
                        'github': token_data['social_links']['github'],
                        'medium': token_data['social_links']['medium'],
                        'total_supply': token_data['market_data']['total_supply'],
                        'total_supply_formatted': token_data['market_data']['total_supply_formatted'],
                        'last_price': token_data['market_data']['price_usd'],
                        'last_price_change': token_data['market_data']['price_change_24h'],
                        'contract_type': token_data['technical_info']['standard'],
                        'is_native': token_data['technical_info']['is_native'],
                        'updated_at': timezone.now()
                    }
                )
                
                return token_data
            
            raise ValueError(f"不支持的链类型: {chain}")
            
        except ValueError as e:
            logger.warning(str(e))
            raise
        except Exception as e:
            logger.error(f"获取代币详情时出错: {str(e)}")
            raise ValueError(f"获取代币详情失败: {str(e)}")

    @staticmethod
    def _get_cached_token_data(token: Token) -> Dict:
        """从Token模型获取缓存的代币数据"""
        return {
            'basic_info': {
                'name': token.name,
                'symbol': token.symbol,
                'decimals': token.decimals,
                'logo': token.logo,
                'chain': token.chain,
                'contract': token.address,
                'description': token.description,
                'created_at': token.created_at,
                'possible_spam': token.possible_spam,
            },
            'market_data': {
                'price_usd': token.last_price or '0',
                'price_change_24h': token.last_price_change or '0',
                'total_supply': token.total_supply,
                'total_supply_formatted': token.total_supply_formatted,
                'value_usd': token.last_value or '0'
            },
            'social_links': {
                'website': token.website,
                'twitter': token.twitter,
                'telegram': token.telegram,
                'discord': token.discord,
                'github': token.github,
                'medium': token.medium,
                'reddit': token.reddit[0] if token.reddit else None
            },
            'technical_info': {
                'standard': token.contract_type,
                'verified': token.verified,
                'security_score': token.security_score,
                'is_native': token.is_native
            }
        }

    @staticmethod
    async def get_token_price_history(chain: str, address: str, days: int = 7) -> List[Dict]:
        """获取代币价格历史数据"""
        try:
            if chain == 'SOL':
                # 处理Solana代币
                url = MoralisConfig.SOLANA_TOKEN_PRICE_HISTORY_URL.format(address)
                
                # 计算日期范围
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
                
                # 由于API限制每次最多返回100条数据，需要分批获取
                price_history = []
                current_start = start_date
                batch_days = 4  # 每4天96个小时的数据点
                
                while current_start < end_date:
                    current_end = min(current_start + timedelta(days=batch_days), end_date)
                    
                    params = {
                        "network": "mainnet",
                        "timeframe": "1h",  # 使用1小时为时间间隔
                        "currency": "usd",
                        "fromDate": current_start.strftime("%Y-%m-%d"),
                        "toDate": current_end.strftime("%Y-%m-%d"),
                        "limit": "96"  # 确保不超过100的限制
                    }
                    
                    logger.info(f"请求价格历史数据: URL={url}, Params={params}")
                    
                    async with aiohttp.ClientSession() as session:
                        headers = {"X-API-Key": MoralisConfig.API_KEY}
                        async with session.get(url, headers=headers, params=params) as response:
                            response_text = await response.text()
                            logger.info(f"价格历史数据API响应: {response_text}")
                            
                            if response.status == 200:
                                try:
                                    history_data = json.loads(response_text)
                                    if history_data:
                                        # 处理 OHLCV 数据格式
                                        result_data = history_data.get('result', [])
                                        for item in result_data:
                                            try:
                                                timestamp = item.get('timestamp')
                                                close_price = item.get('close', 0)  # 使用收盘价
                                                
                                                if timestamp and close_price is not None:
                                                    price_history.append({
                                                        'timestamp': timestamp,
                                                        'price_usd': f"{float(close_price):.12f}".rstrip('0').rstrip('.')
                                                    })
                                            except Exception as e:
                                                logger.error(f"处理 OHLCV 数据项时出错: {str(e)}, 数据: {item}")
                                                continue
                                except json.JSONDecodeError as e:
                                    logger.error(f"解析价格历史数据失败: {str(e)}")
                                except Exception as e:
                                    logger.error(f"处理价格历史数据时出错: {str(e)}")
                            else:
                                logger.error(f"获取代币价格历史数据失败: {response_text}")
                    
                    # 更新开始日期
                    current_start = current_end
                
                # 按时间戳排序
                price_history.sort(key=lambda x: x['timestamp'])
                return price_history
                
            else:
                # 处理EVM链代币
                chain_id = TokenPriceService.CHAIN_MAPPING.get(chain, 'eth')
                url = MoralisConfig.EVM_TOKEN_PRICE_HISTORY_URL.format(address)
                params = {
                    "chain": chain_id,
                    "days": str(days)
                }
                
                logger.info(f"请求价格历史数据: URL={url}, Params={params}")
                
                async with aiohttp.ClientSession() as session:
                    headers = {"X-API-Key": MoralisConfig.API_KEY}
                    async with session.get(url, headers=headers, params=params) as response:
                        response_text = await response.text()
                        logger.info(f"价格历史数据API响应: {response_text}")
                        
                        if response.status == 200:
                            try:
                                history_data = json.loads(response_text)
                                if history_data:
                                    price_history = []
                                    # 处理 EVM 链的价格历史数据
                                    if isinstance(history_data, list):
                                        data_list = history_data
                                    elif isinstance(history_data, dict):
                                        if 'prices' in history_data:
                                            data_list = history_data['prices']
                                        elif 'result' in history_data:
                                            data_list = history_data['result']
                                        else:
                                            data_list = [history_data]
                                    else:
                                        logger.error(f"无效的价格历史数据格式: {history_data}")
                                        return []

                                    for item in data_list:
                                        try:
                                            if isinstance(item, dict):
                                                timestamp = item.get('timestamp') or item.get('date')
                                                price = item.get('price') or item.get('value') or item.get('usdPrice', 0)
                                            else:
                                                timestamp, price = item if len(item) >= 2 else (None, 0)
                                            
                                            if timestamp and price is not None:
                                                price_history.append({
                                                    'timestamp': timestamp,
                                                    'price_usd': f"{float(price):.12f}".rstrip('0').rstrip('.')
                                                })
                                        except Exception as e:
                                            logger.error(f"处理价格历史数据项时出错: {str(e)}, 数据: {item}")
                                            continue

                                    return price_history
                            except json.JSONDecodeError as e:
                                logger.error(f"解析价格历史数据失败: {str(e)}")
                            except Exception as e:
                                logger.error(f"处理价格历史数据时出错: {str(e)}")
                        else:
                            logger.error(f"获取代币价格历史数据失败: {response_text}")
            
            return []
            
        except Exception as e:
            logger.error(f"获取代币价格历史数据时出错: {str(e)}")
            return []