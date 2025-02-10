import aiohttp
import asyncio
import logging
from decimal import Decimal
from typing import Dict, List
from django.utils import timezone
from asgiref.sync import sync_to_async

from ..base.balance import BaseBalanceService
from ...models import Token, Wallet
from ...api_config import MoralisConfig

logger = logging.getLogger(__name__)

class SolanaBalanceService(BaseBalanceService):
    """Solana 余额查询服务实现类"""

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
                
                # 获取代币账户地址
                token_account = await self._get_associated_token_address(address, token_address)
                logger.info(f"获取到代币账户地址: {token_account}")
                
                # 检查代币账户是否存在
                account_exists = await self._check_token_account_exists(token_account)
                logger.info(f"代币账户是否存在: {account_exists}")
                
                if not account_exists:
                    logger.warning(f"代币账户不存在: {token_account}")
                    # 尝试创建代币账户
                    try:
                        # 获取钱包
                        wallet = await Wallet.objects.aget(address=address, chain='SOL', is_active=True)
                        # 获取转账服务
                        transfer_service = await self._get_transfer_service()
                        if transfer_service:
                            # 创建代币账户
                            await transfer_service._create_token_account(wallet, token_address, wallet.decrypt_private_key())
                            logger.info("代币账户创建成功")
                            # 重新检查账户是否存在
                            account_exists = await self._check_token_account_exists(token_account)
                            if not account_exists:
                                logger.error("代币账户创建后仍不存在")
                                return Decimal('0')
                        else:
                            logger.error("无法获取转账服务")
                            return Decimal('0')
                    except Exception as e:
                        logger.error(f"创建代币账户失败: {str(e)}")
                        return Decimal('0')
                
                # 获取代币余额
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

    async def get_all_token_balances(self, address: str) -> List[Dict]:
        """获取所有代币余额"""
        result = []
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                # 1. 获取SOL原生代币余额和代币列表（并发请求）
                sol_balance_task = self.get_native_balance(address)
                tokens_task = self._fetch_with_retry(session, MoralisConfig.SOLANA_ACCOUNT_TOKENS_URL.format(address))
                
                # 同时获取关联账户的代币列表
                associated_tokens_task = self._fetch_with_retry(
                    session, 
                    MoralisConfig.SOLANA_ACCOUNT_TOKENS_URL.format(address),
                    params={'type': 'associated-token-account'}
                )
                
                sol_balance, tokens_data, associated_tokens_data = await asyncio.gather(
                    sol_balance_task, tokens_task, associated_tokens_task
                )
                logger.info(f"SOL余额: {sol_balance}")

                if not tokens_data:
                    tokens_data = []
                if not associated_tokens_data:
                    associated_tokens_data = []
                    
                # 合并主账户和关联账户的代币列表
                all_tokens = tokens_data + [
                    token for token in associated_tokens_data 
                    if token.get('mint') not in [t.get('mint') for t in tokens_data]
                ]
                    
                logger.info(f"获取到 {len(all_tokens)} 个SPL代币")

                # 2. 获取所有代币的价格（并发请求）
                price_tasks = []
                # SOL价格
                price_tasks.append((
                    'So11111111111111111111111111111111111111112',
                    self._fetch_with_retry(session, MoralisConfig.SOLANA_TOKEN_PRICE_URL.format('So11111111111111111111111111111111111111112'))
                ))
                
                # 其他代币价格
                token_addresses = [
                    token['mint'] for token in all_tokens 
                    if 'mint' in token and token['mint'] != 'So11111111111111111111111111111111111111112'
                ]
                for token_address in token_addresses:
                    price_tasks.append((
                        token_address,
                        self._fetch_with_retry(session, MoralisConfig.SOLANA_TOKEN_PRICE_URL.format(token_address))
                    ))

                # 等待所有价格请求完成
                price_results = await asyncio.gather(*(task[1] for task in price_tasks))
                price_map = {task[0]: price_result for task, price_result in zip(price_tasks, price_results)}

                # 3. 从数据库批量获取代币信息
                cached_tokens = await sync_to_async(list)(
                    Token.objects.filter(chain='SOL', address__in=token_addresses)
                    .values('address', 'name', 'symbol', 'decimals', 'logo')
                )
                token_info_map = {token['address']: token for token in cached_tokens}

                # 4. 处理SOL
                sol_price_data = price_map.get('So11111111111111111111111111111111111111112')
                if sol_price_data and isinstance(sol_price_data, dict):
                    sol_price = Decimal(str(sol_price_data.get('usdPrice', 0)))
                    price_change = Decimal(str(sol_price_data.get('usdPrice24hrPercentChange', 0)))
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

                # 5. 处理其他代币
                for token in all_tokens:
                    try:
                        mint = token.get('mint')
                        if not mint or mint == 'So11111111111111111111111111111111111111112':
                            continue

                        amount = Decimal(str(token.get('amount', '0')))
                        decimals = int(token.get('decimals', 0))
                        
                        # 获取代币信息
                        token_info = token_info_map.get(mint)
                        if not token_info:
                            token_info = {
                                'name': token.get('name', 'Unknown Token'),
                                'symbol': token.get('symbol', 'Unknown'),
                                'decimals': decimals,
                                'logo': token.get('logo', '')
                            }

                        # 获取价格
                        price_data = price_map.get(mint)
                        if isinstance(price_data, dict):
                            price = Decimal(str(price_data.get('usdPrice', 0)))
                            price_change = Decimal(str(price_data.get('usdPrice24hrPercentChange', 0)))
                            value = amount * price
                        else:
                            price = Decimal('0')
                            price_change = Decimal('0')
                            value = Decimal('0')

                        result.append({
                            'token_address': mint,
                            'symbol': token_info.get('symbol', 'Unknown'),
                            'name': token_info.get('name', 'Unknown Token'),
                            'balance': str(amount),
                            'decimals': decimals,
                            'logo': token_info.get('logo', ''),
                            'price_usd': str(price),
                            'price_change_24h': str(price_change),
                            'value_usd': str(value),
                            'is_native': False
                        })
                        logger.info(f"添加代币到列表: {mint}, 余额: {amount}, 价值: {value}")
                    except Exception as e:
                        logger.error(f"处理代币 {token.get('mint')} 时出错: {str(e)}")
                        continue

                # 按价值排序
                result.sort(key=lambda x: Decimal(x['value_usd']), reverse=True)
                
                # 计算总价值
                total_value = sum(Decimal(token['value_usd']) for token in result)
                
                final_result = {
                    'total_value_usd': str(total_value),
                    'tokens': result
                }
                
                logger.info(f"返回代币列表，总数: {len(result)}, 总价值: {total_value}")
                return final_result

            except Exception as e:
                logger.error(f"获取所有代币余额时出错: {str(e)}")
                return {'total_value_usd': '0', 'tokens': []}

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