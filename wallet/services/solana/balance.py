import aiohttp
import asyncio
import logging
from decimal import Decimal
from typing import Dict, List, Optional
from django.utils import timezone
from datetime import timedelta
from asgiref.sync import sync_to_async
from django.core.cache import cache
import time
import json

from ...models import Token, Wallet
from ...api_config import MoralisConfig, RPCConfig

logger = logging.getLogger(__name__)

class SolanaBalanceService:
    """Solana 余额查询服务实现类"""

    PRICE_CACHE_TTL = 300  # 价格缓存5分钟
    TOKEN_CACHE_TTL = 86400  # 代币元数据缓存24小时

    def __init__(self):
        self.headers = {
            "accept": "application/json",
            "X-API-Key": MoralisConfig.API_KEY
        }
        self.timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)

    def get_health_check_url(self) -> str:
        """获取健康检查URL"""
        return f"{MoralisConfig.SOLANA_URL}/ping"

    async def _get_transfer_service(self):
        """获取转账服务（延迟导入避免循环依赖）"""
        from ..factory import ChainServiceFactory
        return ChainServiceFactory.get_transfer_service('SOL')

    async def get_native_balance(self, address: str) -> Decimal:
        """获取 SOL 原生代币余额"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                url = MoralisConfig.SOLANA_ACCOUNT_BALANCE_URL.format(address)
                sol_data = await self._fetch_with_retry(session, url)
                
                if sol_data and 'lamports' in sol_data:
                    # 将lamports转换为SOL (1 SOL = 10^9 lamports)
                    lamports = Decimal(str(sol_data['lamports']))
                    sol_balance = lamports / Decimal('1000000000')
                    logger.info(f"获取到的SOL余额: {sol_balance} SOL (lamports: {lamports})")
                    return sol_balance
                return Decimal('0')
            except Exception as e:
                logger.error(f"获取SOL余额时出错: {str(e)}")
                return Decimal('0')

    async def get_token_balance(self, address: str, token_address: str) -> Decimal:
        """获取指定代币余额"""
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                logger.info(f"开始获取代币余额 - 钱包地址: {address}, 代币地址: {token_address}")
                
                # 直接获取代币余额，不检查关联账户
                url = MoralisConfig.SOLANA_ACCOUNT_TOKENS_URL.format(address)
                logger.info(f"请求代币余额 URL: {url}")
                tokens_data = await self._fetch_with_retry(session, url)
                logger.info(f"获取到的代币数据: {tokens_data}")
                
                if not tokens_data:
                    logger.warning("未获取到代币数据")
                    return Decimal('0')
                
                for token in tokens_data:
                    if token.get('mint') == token_address:
                        amount = Decimal(token.get('amount', '0'))
                        decimals = int(token.get('decimals', 0))
                        balance = amount / Decimal(str(10 ** decimals))
                        logger.info(f"找到代币余额 - 原始数量: {amount}, 精度: {decimals}, 最终余额: {balance}")
                        return balance
                
                logger.warning(f"在返回数据中未找到代币 {token_address}")
                return Decimal('0')
            except Exception as e:
                logger.error(f"获取代币余额时出错: {str(e)}")
                return Decimal('0')

    async def _get_associated_token_address(self, wallet_address: str, token_address: str) -> str:
        """获取关联代币账户地址"""
        try:
            url = f"{MoralisConfig.SOLANA_URL}/account/{wallet_address}/tokens/{token_address}/associated"
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                response = await self._fetch_with_retry(session, url)
                if response and 'associatedTokenAddress' in response:
                    return response['associatedTokenAddress']
                return ''
        except Exception as e:
            logger.error(f"获取关联代币账户地址失败: {str(e)}")
            return ''

    async def _check_token_account_exists(self, account_address: str) -> bool:
        """检查代币账户是否存在"""
        if not account_address:
            return False
        
        try:
            url = f"{MoralisConfig.SOLANA_URL}/account/{account_address}"
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                response = await self._fetch_with_retry(session, url)
                return bool(response and response.get('lamports', 0) > 0)
        except Exception as e:
            logger.error(f"检查代币账户是否存在时出错: {str(e)}")
            return False

    async def _get_cached_price(self, token_address: str) -> Dict:
        """获取缓存的价格数据"""
        cache_key = f"solana_token_price_{token_address}"
        price_data = cache.get(cache_key)
        if price_data:
            return price_data
        return None # type: ignore

    async def _cache_price(self, token_address: str, price_data: Dict):
        """缓存价格数据"""
        cache_key = f"solana_token_price_{token_address}"
        cache.set(cache_key, price_data, self.PRICE_CACHE_TTL)

    async def _get_or_create_token_metadata(self, token_address: str, token_data: Dict) -> Token:
        """获取或创建代币元数据"""
        try:
            # 先从数据库获取
            token = await sync_to_async(Token.objects.filter(
                chain='SOL',
                address=token_address
            ).first)()
            
            if token:
                # 检查是否需要更新缓存的价格数据
                if token.last_price and token.updated_at > timezone.now() - timedelta(seconds=self.PRICE_CACHE_TTL):
                    return token
                    
            if not token:
                # 创建新的代币记录
                token = await sync_to_async(Token.objects.create)(
                    chain='SOL',
                    address=token_address,
                    name=token_data.get('name', 'Unknown Token'),
                    symbol=token_data.get('symbol', 'Unknown'),
                    decimals=token_data.get('decimals', 0),
                    logo=token_data.get('logo', ''),
                    type='token',
                    contract_type='SPL',
                    is_visible=True
                )
                logger.info(f"创建新代币记录: {token_address}")
                
            return token
            
        except Exception as e:
            logger.error(f"获取或创建代币元数据失败: {str(e)}")
            return None # type: ignore

    async def _update_token_price(self, token: Token, price_data: Dict):
        """更新代币价格信息"""
        try:
            if not price_data:
                return
                
            token.last_price = str(price_data.get('usdPrice', '0'))
            token.last_price_change = str(price_data.get('usdPrice24hrPercentChange', '0'))
            token.updated_at = timezone.now()
            await sync_to_async(token.save)()
            
        except Exception as e:
            logger.error(f"更新代币价格失败: {str(e)}")

    async def get_all_token_balances(self, address: str, include_hidden: bool = False) -> Dict:
        """获取所有代币余额
        
        Args:
            address: 钱包地址
            include_hidden: 是否包含隐藏的代币，默认为 False
            
        Returns:
            Dict: 代币余额信息
        """
        try:
            tokens = []
            total_value = 0
            
            # 获取原生代币余额
            native_balance = await self.get_native_balance(address)
            logger.info(f"原生代币余额: {native_balance}")
            
            if native_balance > 0:  # 只有当余额大于0时才添加
                # 使用 Wrapped SOL 的合约地址
                wsol_address = "So11111111111111111111111111111111111111112"
                
                # 获取 SOL 价格数据
                price_data = await self._get_cached_price(wsol_address)
                if not price_data:
                    # 如果缓存中没有，则直接获取价格
                    async with aiohttp.ClientSession(timeout=self.timeout) as session:
                        price_data = await self._fetch_with_retry(
                            session, 
                            MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(wsol_address)
                        )
                        if price_data:
                            await self._cache_price(wsol_address, price_data)
                
                # 获取价格和价格变化
                price_usd = price_data.get('usdPrice', '0') if price_data else '0'
                price_change_24h = f"{price_data.get('usdPrice24hrPercentChange', 0):+.2f}%" if price_data else '+0.00%'
                
                # 计算价值
                value = float(native_balance) * float(price_usd)
                total_value += value
                
                native_token = {
                    'chain': 'SOL',
                    'address': wsol_address,  # 使用 Wrapped SOL 地址
                    'name': 'Solana',
                    'symbol': 'SOL',
                    'decimals': 9,
                    'logo': 'https://assets.coingecko.com/coins/images/4128/large/solana.png',
                    'balance': str(native_balance),
                    'balance_formatted': str(native_balance),
                    'price_usd': str(price_usd),
                    'value_usd': str(value),
                    'price_change_24h': price_change_24h,
                    'is_native': True,
                    'is_visible': True
                }
                tokens.append(native_token)
            
            # 获取 SPL 代币余额
            url = f"{MoralisConfig.SOLANA_ACCOUNT_TOKENS_URL.format(address)}"
            logger.info(f"获取 SPL 代币余额 URL: {url}")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"获取代币列表失败: 状态码 {response.status}, 错误信息: {error_text}")
                        return {
                            'total_value_usd': str(total_value),
                            'tokens': tokens
                        }
                    
                    token_balances = await response.json()
                    logger.info(f"获取到 {len(token_balances)} 个 SPL 代币")
                    
                    # 获取所有代币的显示状态
                    token_addresses = [token['mint'] for token in token_balances]
                    db_tokens = await sync_to_async(list)(Token.objects.filter(
                        chain='SOL',
                        address__in=token_addresses
                    ).values('address', 'is_visible'))
                    
                    # 创建地址到显示状态的映射
                    visibility_map = {t['address']: t['is_visible'] for t in db_tokens}
                    logger.info(f"数据库中找到 {len(db_tokens)} 个代币记录")
                    
                    # 处理 SPL 代币
                    for token_data in token_balances:
                        try:
                            token_address = token_data['mint']
                            logger.info(f"处理代币 {token_address}")
                            
                            # 如果代币被隐藏且不包含隐藏代币，则跳过
                            if not include_hidden and not visibility_map.get(token_address, True):
                                logger.info(f"跳过隐藏代币 {token_address}")
                                continue
                                
                            decimals = int(token_data.get('decimals', 9))
                            
                            # 跳过 decimals 为 0 的代币（可能是 NFT）
                            if decimals == 0:
                                logger.info(f"跳过 NFT 代币 {token_address} (decimals=0)")
                                continue
                                
                            # 计算余额
                            try:
                                # 使用原始余额数据
                                raw_balance = token_data.get('amount', '0')
                                if isinstance(raw_balance, str) and '.' in raw_balance:
                                    # 如果原始余额包含小数点，直接使用
                                    balance_formatted = raw_balance
                                    balance = raw_balance
                                else:
                                    # 否则进行精度转换
                                    balance = str(raw_balance)
                                    balance_formatted = str(float(raw_balance) / (10 ** decimals))
                                
                                logger.info(f"代币 {token_address} 余额: {balance_formatted} (原始: {balance})")
                                
                                # 如果格式化后的余额为0，跳过
                                if float(balance_formatted) <= 0:
                                    logger.info(f"跳过零余额代币 {token_address}")
                                    continue
                                    
                            except (ValueError, TypeError) as e:
                                logger.warning(f"无法解析代币余额: {token_data}, 错误: {str(e)}")
                                continue
                            
                            # 获取代币价格
                            price_data = await self._get_cached_price(token_address)
                            if not price_data:
                                # 如果缓存中没有，则获取代币价格
                                price_response = await self._fetch_with_retry(
                                    session, 
                                    MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(token_address)
                                )
                                if price_response:
                                    price_data = price_response
                                    await self._cache_price(token_address, price_response)
                            
                            # 获取价格和价格变化
                            price = float(price_data.get('usdPrice', '0') if price_data else '0')
                            price_change = price_data.get('usdPrice24hrPercentChange', 0) if price_data else 0
                            logger.info(f"代币 {token_address} 价格: ${price}, 24h变化: {price_change}%")
                            
                            # 计算价值
                            value = float(balance_formatted) * price
                            total_value += value
                            
                            token_info = {
                                'chain': 'SOL',
                                'address': token_address,
                                'name': token_data.get('name', ''),
                                'symbol': token_data.get('symbol', ''),
                                'decimals': decimals,
                                'logo': token_data.get('logo', ''),
                                'balance': balance,
                                'balance_formatted': balance_formatted,
                                'price_usd': str(price),
                                'value_usd': str(value),
                                'price_change_24h': f"{price_change:+.2f}%" if price_change else '+0.00%',
                                'is_native': False,
                                'is_visible': visibility_map.get(token_address, True)
                            }
                            
                            tokens.append(token_info)
                            logger.info(f"成功添加代币 {token_address}")
                            
                        except Exception as e:
                            logger.error(f"处理代币数据失败: {str(e)}, 数据: {token_data}")
                            continue
                    
                    # 按价值排序
                    tokens.sort(key=lambda x: float(x['value_usd']), reverse=True)
                    logger.info(f"最终返回 {len(tokens)} 个代币")
                    
                    return {
                        'total_value_usd': str(total_value),
                        'tokens': tokens
                    }
                    
        except Exception as e:
            logger.error(f"获取代币列表失败: {str(e)}")
            return {
                'total_value_usd': '0',
                'tokens': []
            }

    async def _async_update_tokens(self, new_tokens: List[Dict], price_update_needed: List[str]):
        """异步更新代币信息和价格"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # 1. 创建新代币
                for token_data in new_tokens:
                    try:
                        await sync_to_async(Token.objects.create)(
                            chain='SOL',
                            address=token_data['address'],
                            name=token_data['name'],
                            symbol=token_data['symbol'],
                            decimals=token_data['decimals'],
                            logo=token_data['logo'],
                            type='token',
                            contract_type='SPL',
                            is_visible=True
                        )
                        logger.info(f"创建新代币记录: {token_data['address']}")
                    except Exception as e:
                        logger.error(f"创建代币记录失败: {str(e)}")

                # 2. 更新价格
                price_tasks = []
                for token_address in price_update_needed:
                    price_tasks.append((
                        token_address,
                        self._fetch_with_retry(session, MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(token_address))
                    ))

                if price_tasks:
                    price_results = await asyncio.gather(*(task[1] for task in price_tasks))
                    for token_address, price_data in zip([task[0] for task in price_tasks], price_results):
                        if price_data:
                            try:
                                token = await sync_to_async(Token.objects.get)(chain='SOL', address=token_address)
                                await self._update_token_price(token, price_data)
                                await self._cache_price(token_address, price_data)
                            except Exception as e:
                                logger.error(f"更新代币价格失败: {str(e)}")

        except Exception as e:
            logger.error(f"异步更新代币信息失败: {str(e)}")

    async def _fetch_with_retry(self, session, url, method="get", **kwargs):
        """带重试的HTTP请求函数"""
        kwargs['headers'] = self.headers
        # 添加 network 参数
        if 'params' not in kwargs:
            kwargs['params'] = {}
        kwargs['params']['network'] = 'mainnet'
        
        logger.debug(f"开始请求: {url}")
        logger.debug(f"请求头: {self.headers}")
        logger.debug(f"请求参数: {kwargs['params']}")
        
        for attempt in range(3):
            try:
                async with getattr(session, method)(url, **kwargs) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"请求成功: {url}, 响应: {data}")
                        return data
                    elif response.status == 429:  # Rate limit
                        retry_after = int(response.headers.get('Retry-After', 2))
                        logger.warning(f"请求频率限制: {url}, 等待 {retry_after} 秒后重试")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"请求失败: {url}, 状态码: {response.status}")
                        try:
                            error_content = await response.text()
                            logger.error(f"错误响应内容: {error_content}")
                        except:
                            pass
                        return None
            except Exception as e:
                if attempt < 2:
                    wait_time = 2 * (attempt + 1)
                    logger.warning(f"请求出错: {url}, 错误: {str(e)}, {wait_time} 秒后重试")
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"请求最终失败: {url}, 错误: {str(e)}")
                return None
        return None