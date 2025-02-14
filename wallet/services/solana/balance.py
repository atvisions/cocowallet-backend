import aiohttp
import asyncio
import logging
from decimal import Decimal
from typing import Dict, List
from django.utils import timezone
from asgiref.sync import sync_to_async
from django.core.cache import cache
from datetime import timedelta
import time

from ..base.balance import BaseBalanceService
from ...models import Token, Wallet
from ...api_config import MoralisConfig

logger = logging.getLogger(__name__)

class SolanaBalanceService(BaseBalanceService):
    """Solana 余额查询服务实现类"""

    PRICE_CACHE_TTL = 300  # 价格缓存5分钟
    TOKEN_CACHE_TTL = 86400  # 代币元数据缓存24小时

    def __init__(self):
        super().__init__()
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

    async def get_all_token_balances(self, address: str) -> List[Dict]:
        """获取所有代币余额"""
        result = []
        start_time = time.time()
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 1. 先获取本地缓存的代币列表
                cached_tokens = await sync_to_async(list)(
                    Token.objects.filter(chain='SOL', is_visible=True)
                    .values('address', 'name', 'symbol', 'decimals', 'logo', 'last_price', 'last_price_change', 'updated_at')
                )
                token_info_map = {token['address']: token for token in cached_tokens}
                logger.info(f"从数据库获取代币信息耗时: {time.time() - start_time:.2f}秒")

                # 2. 并发获取SOL余额和代币列表
                sol_balance_task = self.get_native_balance(address)
                tokens_task = self._fetch_with_retry(session, MoralisConfig.SOLANA_ACCOUNT_TOKENS_URL.format(address))
                
                sol_balance, tokens_data = await asyncio.gather(sol_balance_task, tokens_task)
                logger.info(f"获取基础数据耗时: {time.time() - start_time:.2f}秒")
                
                if not tokens_data:
                    tokens_data = []
                logger.info(f"获取到 {len(tokens_data)} 个SPL代币")

                # 3. 处理SOL代币
                sol_price_data = await self._get_cached_price('So11111111111111111111111111111111111111112')
                if sol_price_data:
                    sol_price = Decimal(str(sol_price_data.get('usdPrice', 0)))
                    price_change = Decimal(str(sol_price_data.get('usdPrice24hrPercentChange', 0)))
                else:
                    # 如果缓存中没有，则获取SOL价格
                    sol_price_response = await self._fetch_with_retry(
                        session, 
                        MoralisConfig.SOLANA_TOKEN_PRICE_URL.format('So11111111111111111111111111111111111111112')
                    )
                    if sol_price_response:
                        sol_price = Decimal(str(sol_price_response.get('usdPrice', 0)))
                        price_change = Decimal(str(sol_price_response.get('usdPrice24hrPercentChange', 0)))
                        await self._cache_price('So11111111111111111111111111111111111111112', sol_price_response)
                    else:
                        sol_price = Decimal('0')
                        price_change = Decimal('0')
                
                sol_value = sol_balance * sol_price
                result.append({
                    'token_address': 'So11111111111111111111111111111111111111112',
                    'symbol': 'SOL',
                    'name': 'Solana',
                    'balance': str(sol_balance),
                    'decimals': 9,
                    'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png',
                    'price_usd': str(sol_price),
                    'price_change_24h': str(price_change),
                    'value_usd': str(sol_value),
                    'is_native': True
                })

                # 4. 处理其他代币
                new_tokens = []  # 需要创建的新代币
                price_update_needed = []  # 需要更新价格的代币
                processed_tokens = set()  # 用于跟踪已处理的代币
                
                # 4.1 首先处理API返回的代币
                for token_data in tokens_data:
                    try:
                        mint = token_data.get('mint')
                        if not mint or mint == 'So11111111111111111111111111111111111111112':
                            continue

                        processed_tokens.add(mint)
                        amount = Decimal(str(token_data.get('amount', '0')))
                        decimals = int(token_data.get('decimals', 0))
                        
                        # 检查本地数据库中是否存在
                        token_info = token_info_map.get(mint)
                        if not token_info:
                            # 如果不存在，添加到待创建列表
                            new_tokens.append({
                                'address': mint,
                                'name': token_data.get('name', 'Unknown Token'),
                                'symbol': token_data.get('symbol', 'Unknown'),
                                'decimals': decimals,
                                'logo': token_data.get('logo', ''),
                                'data': token_data
                            })
                            continue
                            
                        # 检查价格是否需要更新
                        if not token_info.get('last_price') or \
                           not token_info.get('updated_at') or \
                           token_info['updated_at'] < timezone.now() - timedelta(seconds=self.PRICE_CACHE_TTL):
                            price_update_needed.append(mint)
                            
                        # 使用本地缓存的价格数据
                        price = Decimal(token_info.get('last_price', '0'))
                        price_change = Decimal(token_info.get('last_price_change', '0'))
                        value = amount * price

                        result.append({
                            'token_address': mint,
                            'symbol': token_info['symbol'],
                            'name': token_info['name'],
                            'balance': str(amount),
                            'decimals': decimals,
                            'logo': token_info['logo'],
                            'price_usd': str(price),
                            'price_change_24h': str(price_change),
                            'value_usd': str(value),
                            'is_native': False
                        })
                        logger.info(f"添加代币到列表: {mint}, 余额: {amount}, 价值: {value}")
                    except Exception as e:
                        logger.error(f"处理代币 {token_data.get('mint')} 时出错: {str(e)}")
                        continue

                # 4.2 处理数据库中的代币（可能API没有返回但用户之前有余额）
                tokens_data_map = {token.get('mint'): token for token in tokens_data if token.get('mint')}
                db_tokens_to_check = [
                    token_info for token_info in cached_tokens 
                    if token_info['address'] not in processed_tokens 
                    and token_info['address'] != 'So11111111111111111111111111111111111111112'
                ]
                
                if db_tokens_to_check:
                    # 批量获取所有代币余额
                    tokens_response = await self._fetch_with_retry(session, MoralisConfig.SOLANA_ACCOUNT_TOKENS_URL.format(address))
                    if tokens_response:
                        tokens_data_map.update({
                            token.get('mint'): token 
                            for token in tokens_response 
                            if token.get('mint')
                        })
                    
                    for token_info in db_tokens_to_check:
                        mint = token_info['address']
                        try:
                            token_data = tokens_data_map.get(mint)
                            if token_data and Decimal(token_data.get('amount', '0')) > 0:
                                amount = Decimal(token_data.get('amount', '0'))
                                decimals = int(token_data.get('decimals', 0))
                                balance = amount / Decimal(str(10 ** decimals))
                                
                                if balance > 0:
                                    # 检查价格是否需要更新
                                    if not token_info.get('last_price') or \
                                       not token_info.get('updated_at') or \
                                       token_info['updated_at'] < timezone.now() - timedelta(seconds=self.PRICE_CACHE_TTL):
                                        price_update_needed.append(mint)
                                        
                                    price = Decimal(token_info.get('last_price', '0'))
                                    price_change = Decimal(token_info.get('last_price_change', '0'))
                                    value = balance * price

                                    result.append({
                                        'token_address': mint,
                                        'symbol': token_info['symbol'],
                                        'name': token_info['name'],
                                        'balance': str(balance),
                                        'decimals': token_info['decimals'],
                                        'logo': token_info['logo'],
                                        'price_usd': str(price),
                                        'price_change_24h': str(price_change),
                                        'value_usd': str(value),
                                        'is_native': False
                                    })
                                    logger.info(f"从数据库添加代币到列表: {mint}, 余额: {balance}, 价值: {value}")
                        except Exception as e:
                            logger.error(f"处理数据库代币 {mint} 时出错: {str(e)}")
                            continue

                # 5. 异步处理新代币和价格更新
                if new_tokens or price_update_needed:
                    asyncio.create_task(self._async_update_tokens(new_tokens, price_update_needed))

                # 按价值排序
                result.sort(key=lambda x: Decimal(x['value_usd']), reverse=True)
                
                # 计算总价值
                total_value = sum(Decimal(token['value_usd']) for token in result)
                
                final_result = {
                    'total_value_usd': str(total_value),
                    'tokens': result
                }
                
                logger.info(f"返回代币列表，总数: {len(result)}, 总价值: {total_value}")
                logger.info(f"总耗时: {time.time() - start_time:.2f}秒")
                return final_result # type: ignore

            except Exception as e:
                logger.error(f"获取所有代币余额时出错: {str(e)}")
                return {'total_value_usd': '0', 'tokens': []} # type: ignore

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