import aiohttp
import logging
from typing import Dict, List, Optional
from decimal import Decimal
from moralis import evm_api, sol_api
from . import BaseTokenService
from ..models import Wallet, Token, Transaction
from ..api_config import MoralisConfig, APIConfig, Chain
from ..constants import SOLANA_TOKEN_LIST
import json
from asgiref.sync import sync_to_async
from django.utils import timezone
from datetime import timedelta
import asyncio
import async_timeout
from django.db.models import Q

logger = logging.getLogger(__name__)

class TokenBalanceService(BaseTokenService):
    """代币余额服务类，处理代币余额相关的功能"""

    # 链到 Moralis 链 ID 的映射
    CHAIN_MAPPING = APIConfig.CHAIN_TO_MORALIS

    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # 秒

    @staticmethod
    async def fetch_with_retry(session, url, method="get", **kwargs):
        """带重试的HTTP请求函数"""
        for attempt in range(TokenBalanceService.MAX_RETRIES):
            try:
                async with getattr(session, method)(url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:  # Rate limit
                        retry_after = int(response.headers.get('Retry-After', TokenBalanceService.RETRY_DELAY))
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"请求失败: {url}, 状态码: {response.status}")
                        return None
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt < TokenBalanceService.MAX_RETRIES - 1:
                    await asyncio.sleep(TokenBalanceService.RETRY_DELAY * (attempt + 1))
                    continue
                logger.error(f"请求失败: {url}, 错误: {str(e)}")
                return None
        return None

    @staticmethod
    async def get_token_balances(wallet: Wallet) -> Dict:
        """获取钱包的代币余额"""
        logger.info(f"开始获取钱包 {wallet.address} 在 {wallet.chain} 链上的代币余额")
        
        try:
            # 从数据库一次性获取所需的最小字段集
            cached_tokens = await sync_to_async(list)(Token.objects.filter(
                chain=wallet.chain,
                updated_at__gte=timezone.now() - timedelta(minutes=5)
            ).only(
                'address', 'name', 'symbol', 'decimals', 'logo', 'is_native',
                'last_balance', 'last_price', 'last_price_change', 'last_value',
                'updated_at'
            ).values())

            logger.info(f"从数据库获取到 {len(cached_tokens)} 个缓存代币信息")

            # 创建缓存映射以提高查找效率
            cached_token_map = {token['address']: token for token in cached_tokens}

            # 强制从API获取新数据
            logger.info("从API获取最新数据")
            if wallet.chain == 'SOL':
                tokens = await TokenBalanceService._get_solana_balances(wallet, force_update=True)
            elif wallet.chain == 'BTC':
                tokens = await TokenBalanceService._get_btc_balances(wallet.address)
            else:
                tokens = await TokenBalanceService._get_evm_balances(wallet, force_update=True)

            # 计算总余额并排序
            total_usd_value = sum(float(token.get('value_usd', '0') or '0') for token in tokens)
            tokens.sort(key=lambda x: float(x.get('value_usd', '0') or '0'), reverse=True)

            logger.info(f"钱包总余额: ${total_usd_value}")
            logger.info(f"返回代币列表，总数: {len(tokens)}")

            return {
                'total_usd_value': str(total_usd_value),
                'tokens': tokens
            }
        except Exception as e:
            logger.error(f"获取代币余额时发生错误: {str(e)}，错误类型: {type(e).__name__}")
            return {
                'total_usd_value': '0',
                'tokens': []
            }

    @staticmethod
    async def get_wallet_tokens(wallet: Wallet) -> Dict:
        """获取钱包的代币列表"""
        return await TokenBalanceService.get_token_balances(wallet)

    @staticmethod
    async def _get_solana_balances(wallet: Wallet, force_update: bool = False) -> List[Dict]:
        """获取 Solana 代币余额"""
        try:
            token_list = []
            headers = {
                "accept": "application/json",
                "X-API-Key": MoralisConfig.API_KEY
            }
            
            # 设置更宽松的超时控制
            timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_connect=5, sock_read=10)
            
            # 预先从数据库批量获取所有SOL代币信息
            cached_tokens = await sync_to_async(list)(
                Token.objects.filter(chain='SOL')
                .values('address', 'name', 'symbol', 'decimals', 'logo', 'is_native', 
                       'last_balance', 'last_price', 'last_price_change', 'last_value', 'updated_at')
            )
            cached_token_map = {token['address']: token for token in cached_tokens}
            
            # 批量数据库更新列表
            db_updates = []
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 获取SOL余额
                try:
                    sol_balance_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{wallet.address}/balance"
                    sol_data = await TokenBalanceService.fetch_with_retry(session, sol_balance_url, headers=headers)
                    
                    if sol_data and 'solana' in sol_data:
                        sol_balance = str(float(sol_data['solana']) / 1e9)
                        # 检查缓存中的SOL数据是否需要更新
                        sol_cached = cached_token_map.get('So11111111111111111111111111111111111111112', {})
                        need_update = force_update or not sol_cached or (
                            sol_cached and (
                                sol_cached.get('last_balance') != sol_balance or
                                not sol_cached.get('last_price') or
                                float(sol_cached.get('last_price', '0')) <= 0 or
                                not sol_cached.get('last_price_change')
                            )
                        )
                        
                        if need_update:
                            # 获取SOL价格
                            sol_price_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/So11111111111111111111111111111111111111112/price"
                            price_data = await TokenBalanceService.fetch_with_retry(session, sol_price_url, headers=headers)
                            
                            if price_data:
                                price_usd = str(price_data.get('usdPrice', 0))
                                price_change = str(price_data.get('usdPrice24hrPercentChange', 0))
                                value_usd = str(float(sol_balance) * float(price_usd))
                        else:
                            # 使用缓存数据
                            price_usd = sol_cached.get('last_price', '0')
                            price_change = sol_cached.get('last_price_change', '0')
                            value_usd = str(float(sol_balance) * float(price_usd))
                        
                        token_list.append({
                            'symbol': 'SOL',
                            'name': 'Solana',
                            'balance': sol_balance,
                            'decimals': 9,
                            'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png',
                            'chain': 'SOL',
                            'contract': 'So11111111111111111111111111111111111111112',
                            'is_native': True,
                            'price_usd': price_usd,
                            'price_change_24h': price_change,
                            'value_usd': value_usd
                        })
                        
                        if need_update:
                            # 更新SOL代币缓存
                            db_updates.append({
                                'chain': 'SOL',
                                'address': 'So11111111111111111111111111111111111111112',
                                'defaults': {
                                    'name': 'Solana',
                                    'symbol': 'SOL',
                                    'decimals': 9,
                                    'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png',
                                    'is_native': True,
                                    'last_balance': sol_balance,
                                    'last_price': price_usd,
                                    'last_price_change': price_change,
                                    'last_value': value_usd,
                                    'updated_at': timezone.now()
                                }
                            })
                except Exception as e:
                    logger.error(f"获取SOL余额时出错: {str(e)}")

                # 获取代币列表
                try:
                    # 使用多个不同的API端点获取代币列表
                    tokens_data = []
                    
                    # 1. 使用 /portfolio 端点获取完整的代币列表
                    portfolio_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{wallet.address}/portfolio"
                    portfolio_result = await TokenBalanceService.fetch_with_retry(session, portfolio_url, headers=headers)
                    if portfolio_result and isinstance(portfolio_result.get('tokens'), list):
                        tokens_data.extend(portfolio_result['tokens'])
                    
                    # 2. 使用 /spl 端点补充数据
                    spl_tokens_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{wallet.address}/spl"
                    spl_tokens_result = await TokenBalanceService.fetch_with_retry(session, spl_tokens_url, headers=headers) or []
                    if isinstance(spl_tokens_result, list):
                        for spl_token in spl_tokens_result:
                            # 检查是否已存在
                            mint = spl_token.get('mint')
                            if mint and not any(t.get('mint') == mint for t in tokens_data):
                                tokens_data.append(spl_token)
                    
                    # 合并所有代币数据，使用字典去重
                    all_tokens = {}
                    for token in tokens_data:
                        # 尝试获取代币地址
                        mint = (token.get('mint') or 
                               token.get('token_address') or 
                               token.get('address') or 
                               token.get('contract'))
                        
                        if not mint or mint == 'So11111111111111111111111111111111111111112':  # 跳过SOL代币
                            continue
                            
                        # 如果已存在，合并数据
                        if mint in all_tokens:
                            existing_token = all_tokens[mint]
                            # 使用非空值更新现有数据
                            for key, value in token.items():
                                if value is not None and value != '':
                                    existing_token[key] = value
                        else:
                            all_tokens[mint] = token
                    
                    if all_tokens:
                        # 使用信号量限制并发请求
                        semaphore = asyncio.Semaphore(5)  # 增加并发数到5
                        
                        async def process_token(token):
                            try:
                                mint = (token.get('mint') or 
                                      token.get('token_address') or 
                                      token.get('address') or 
                                      token.get('contract'))
                                if not mint:
                                    return
                                
                                # 获取代币精度
                                decimals = (token.get('decimals') or 
                                          token.get('decimal') or 
                                          token.get('token_decimals', 0))
                                try:
                                    decimals = int(decimals)
                                except (TypeError, ValueError):
                                    decimals = 0
                                
                                if decimals == 0:  # 跳过NFT
                                    return
                                
                                # 获取代币余额
                                balance = (token.get('amount') or 
                                         token.get('balance') or 
                                         token.get('token_amount') or 
                                         token.get('quantity', '0'))
                                try:
                                    if float(balance) == 0:
                                        return
                                except (TypeError, ValueError):
                                    return
                                
                                # 检查缓存中的代币数据是否需要更新
                                token_cached = cached_token_map.get(mint, {})
                                need_update = force_update or not token_cached or (
                                    token_cached and (
                                        token_cached.get('last_balance') != balance or
                                        not token_cached.get('last_price') or
                                        float(token_cached.get('last_price', '0')) <= 0 or
                                        not token_cached.get('last_price_change')
                                    )
                                )
                                
                                if need_update:
                                    async with semaphore:
                                        # 获取代币价格
                                        price_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{mint}/price"
                                        price_data = await TokenBalanceService.fetch_with_retry(session, price_url, headers=headers)
                                        
                                        if price_data:
                                            price_usd = str(price_data.get('usdPrice', 0))
                                            price_change = str(price_data.get('usdPrice24hrPercentChange', 0))
                                            value_usd = str(float(balance) * float(price_usd))
                                            
                                            # 获取代币元数据
                                            metadata_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{mint}/metadata"
                                            metadata = await TokenBalanceService.fetch_with_retry(session, metadata_url, headers=headers)
                                            
                                            if metadata:
                                                token_data = {
                                                    'symbol': metadata.get('symbol', token.get('symbol', 'Unknown')),
                                                    'name': metadata.get('name', token.get('name', 'Unknown Token')),
                                                    'balance': balance,
                                                    'decimals': metadata.get('decimals', decimals),
                                                    'logo': metadata.get('logo', token.get('logo')),
                                                    'chain': 'SOL',
                                                    'contract': mint,
                                                    'is_native': False,
                                                    'price_usd': price_usd,
                                                    'price_change_24h': price_change,
                                                    'value_usd': value_usd
                                                }
                                                
                                                token_list.append(token_data)
                                                
                                                # 添加到数据库更新列表
                                                db_updates.append({
                                                    'chain': 'SOL',
                                                    'address': mint,
                                                    'defaults': {
                                                        'name': token_data['name'],
                                                        'symbol': token_data['symbol'],
                                                        'decimals': token_data['decimals'],
                                                        'logo': token_data['logo'],
                                                        'type': 'token',
                                                        'contract_type': 'SPL',
                                                        'last_balance': token_data['balance'],
                                                        'last_price': token_data['price_usd'],
                                                        'last_price_change': token_data['price_change_24h'],
                                                        'last_value': token_data['value_usd'],
                                                        'updated_at': timezone.now()
                                                    }
                                                })
                                else:
                                    # 使用缓存数据
                                    token_data = {
                                        'symbol': token_cached.get('symbol', token.get('symbol', 'Unknown')),
                                        'name': token_cached.get('name', token.get('name', 'Unknown Token')),
                                        'balance': balance,
                                        'decimals': token_cached.get('decimals', decimals),
                                        'logo': token_cached.get('logo', token.get('logo')),
                                        'chain': 'SOL',
                                        'contract': mint,
                                        'is_native': False,
                                        'price_usd': token_cached.get('last_price', '0'),
                                        'price_change_24h': token_cached.get('last_price_change', '0'),
                                        'value_usd': str(float(balance) * float(token_cached.get('last_price', '0')))
                                    }
                                    token_list.append(token_data)
                                    
                            except Exception as e:
                                logger.error(f"处理代币 {token.get('mint')} 时出错: {str(e)}")
                        
                        # 并行处理所有代币
                        await asyncio.gather(*[process_token(token) for token in all_tokens.values()], return_exceptions=True)
                except Exception as e:
                    logger.error(f"获取代币列表时出错: {str(e)}")

                # 批量更新数据库
                if db_updates:
                    async def update_db():
                        try:
                            async with async_timeout.timeout(20):  # 增加数据库操作超时时间
                                for update in db_updates:
                                    try:
                                        await sync_to_async(Token.objects.update_or_create)(
                                            chain=update['chain'],
                                            address=update['address'],
                                            defaults=update['defaults']
                                        )
                                    except Exception as e:
                                        logger.error(f"更新数据库失败: {str(e)}")
                        except asyncio.TimeoutError:
                            logger.error("数据库更新超时")
                    
                    # 在后台更新数据库
                    asyncio.create_task(update_db())

            # 按价值排序代币列表
            token_list.sort(key=lambda x: float(x.get('value_usd', '0') or '0'), reverse=True)
            logger.info(f"返回代币列表，总数: {len(token_list)}")
            return token_list
        
        except Exception as e:
            logger.error(f"获取Solana代币余额时发生错误: {str(e)}，错误类型: {type(e).__name__}")
            return []

    @staticmethod
    async def _get_btc_balances(address: str) -> List[Dict]:
        """获取比特币余额"""
        # TODO: 实现比特币余额获取逻辑
        return []

    @staticmethod
    async def _get_evm_balances(wallet: Wallet, force_update: bool = False) -> List[Dict]:
        """获取 EVM 链代币余额"""
        try:
            chain = TokenBalanceService.CHAIN_MAPPING.get(Chain(wallet.chain))
            if not chain:
                logger.error(f"不支持的链类型: {wallet.chain}")
                return []

            token_list = []
            logger.info(f"开始获取 {wallet.chain} 链上地址 {wallet.address} 的代币余额")
            
            async with aiohttp.ClientSession() as session:
                try:
                    # 1. 获取原生代币余额
                    native_url = MoralisConfig.EVM_WALLET_NATIVE_BALANCE_URL.format(wallet.address)
                    headers = {
                        "accept": "application/json",
                        "X-API-Key": MoralisConfig.API_KEY
                    }
                    params = {"chain": chain}
                    
                    logger.info(f"请求原生代币余额: URL={native_url}, Params={params}")
                    
                    async with session.get(native_url, headers=headers, params=params) as native_response:
                        if native_response.status == 200:
                            native_data = await native_response.json()
                            if native_data and 'balance' in native_data:
                                balance = int(native_data['balance']) / 1e18  # Convert wei to ETH
                                
                                # 获取原生代币价格
                                native_token_data = {
                                    'symbol': wallet.chain,  # ETH, BNB 等
                                    'name': f"{wallet.chain} Token",
                                    'balance': str(balance),
                                    'decimals': 18,
                                    'logo': f"https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/{wallet.chain.lower()}/info/logo.png",
                                    'chain': wallet.chain,
                                    'contract': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',  # WETH合约地址
                                    'is_native': True,
                                    'price_usd': '0',
                                    'price_change_24h': '0',
                                    'value_usd': '0'
                                }
                                
                                # 获取原生代币价格和价格变化
                                native_price_url = MoralisConfig.EVM_TOKEN_PRICE_URL.format('0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2')  # WETH合约地址
                                native_price_params = {
                                    "chain": chain,
                                    "include": "percent_change"
                                }
                                async with session.get(native_price_url, headers=headers, params=native_price_params) as price_response:
                                    price_text = await price_response.text()
                                    logger.info(f"原生代币价格响应: {price_text}")
                                    
                                    if price_response.status == 200:
                                        try:
                                            price_data = json.loads(price_text)
                                            if price_data:
                                                price_usd = price_data.get('usdPrice', 0)
                                                native_token_data['price_usd'] = str(price_usd)
                                                price_change = price_data.get('24hrPercentChange', 0)
                                                native_token_data['price_change_24h'] = str(price_change)
                                                value_usd = float(balance) * float(price_usd)
                                                native_token_data['value_usd'] = str(value_usd)
                                                
                                                # 保存原生代币信息到数据库
                                                await sync_to_async(Token.objects.update_or_create)(
                                                    chain=wallet.chain,
                                                    address='0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',  # WETH合约地址
                                                    defaults={
                                                        'name': native_token_data['name'],
                                                        'symbol': native_token_data['symbol'],
                                                        'decimals': native_token_data['decimals'],
                                                        'logo': native_token_data['logo'],
                                                        'type': 'token',
                                                        'contract_type': 'NATIVE',
                                                        'is_native': True,
                                                        'last_balance': native_token_data['balance'],
                                                        'last_price': native_token_data['price_usd'],
                                                        'last_price_change': native_token_data['price_change_24h'],
                                                        'last_value': native_token_data['value_usd'],
                                                        'updated_at': timezone.now()
                                                    }
                                                )
                                        except json.JSONDecodeError as e:
                                            logger.error(f"解析原生代币价格数据失败: {str(e)}")
                                
                                # 确保原生代币被添加到列表中，即使价格获取失败
                                token_list.append(native_token_data)
                                logger.info(f"添加原生代币: {native_token_data['symbol']}, 余额: {native_token_data['balance']}, 价格: {native_token_data['price_usd']}")

                    # 2. 获取代币列表和余额
                    url = MoralisConfig.EVM_WALLET_TOKENS_URL.format(wallet.address)
                    params = {
                        "chain": chain,
                        "include": "all"
                    }
                    
                    logger.info(f"请求代币列表: URL={url}, Params={params}")
                    
                    async with session.get(url, headers=headers, params=params) as response:
                        logger.info(f"Moralis API响应状态码: {response.status}")
                        response_text = await response.text()
                        logger.info(f"Moralis API响应内容: {response_text}")
                        
                        if response.status == 200:
                            try:
                                response_data = json.loads(response_text)
                                tokens = response_data.get('result', [])
                                logger.info(f"成功获取代币数据: {tokens}")
                                logger.info(f"代币列表长度: {len(tokens)}")

                                for token in tokens:
                                    try:
                                        # 处理原生代币
                                        if token.get('native_token', False):
                                            # 如果已经添加过原生代币，跳过
                                            if any(t.get('is_native', False) for t in token_list):
                                                logger.info(f"跳过重复的原生代币: {token.get('symbol')}")
                                                continue
                                                
                                            native_token_data = {
                                                'symbol': token.get('symbol', wallet.chain),
                                                'name': token.get('name', f"{wallet.chain} Token"),
                                                'balance': token.get('balance_formatted', '0'),
                                                'decimals': token.get('decimals', 18),
                                                'logo': token.get('logo') or f"https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/{wallet.chain.lower()}/info/logo.png",
                                                'chain': wallet.chain,
                                                'contract': 'native',
                                                'is_native': True,
                                                'price_usd': str(token.get('usd_price', '0')),
                                                'price_change_24h': str(token.get('usd_price_24hr_percent_change', '0')),
                                                'value_usd': str(token.get('usd_value', '0'))
                                            }
                                            
                                            # 保存原生代币信息到数据库
                                            await sync_to_async(Token.objects.update_or_create)(
                                                chain=wallet.chain,
                                                address='native',
                                                defaults={
                                                    'name': native_token_data['name'],
                                                    'symbol': native_token_data['symbol'],
                                                    'decimals': native_token_data['decimals'],
                                                    'logo': native_token_data['logo'],
                                                    'type': 'token',
                                                    'contract_type': 'NATIVE',
                                                    'is_native': True,
                                                    'last_balance': native_token_data['balance'],
                                                    'last_price': native_token_data['price_usd'],
                                                    'last_price_change': native_token_data['price_change_24h'],
                                                    'last_value': native_token_data['value_usd'],
                                                    'updated_at': timezone.now()
                                                }
                                            )
                                            token_list.append(native_token_data)
                                            logger.info(f"添加原生代币: {native_token_data['symbol']}, 余额: {native_token_data['balance']}, 价格: {native_token_data['price_usd']}")
                                            continue

                                        # 跳过可能的垃圾代币和原生代币的包装代币
                                        if (token.get('possible_spam', False) or 
                                            token.get('token_address', '').lower() in [
                                                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',  # ETH
                                                '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c',  # WBNB
                                                '0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270',  # WMATIC
                                                '0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7'   # WAVAX
                                            ]):
                                            logger.info(f"跳过代币: {token.get('symbol')} ({token.get('token_address')})")
                                            continue

                                        token_address = token.get('token_address', '').lower()
                                        
                                        # 构建代币数据
                                        token_data = {
                                            'symbol': token.get('symbol', ''),
                                            'name': token.get('name', ''),
                                            'balance': token.get('balance_formatted', '0'),
                                            'decimals': token.get('decimals', 18),
                                            'logo': token.get('logo', ''),
                                            'price_usd': str(token.get('usd_price', '0')),
                                            'price_change_24h': str(token.get('usd_price_24hr_percent_change', '0')),
                                            'value_usd': str(token.get('usd_value', '0')),
                                            'chain': wallet.chain,
                                            'contract': token.get('token_address', ''),
                                            'is_native': token.get('native_token', False)
                                        }

                                        # 获取代币价格和价格变化
                                        price_url = MoralisConfig.EVM_TOKEN_PRICE_URL.format(token_address)
                                        price_params = {
                                            "chain": chain,
                                            "include": "percent_change"
                                        }
                                        async with session.get(price_url, headers=headers, params=price_params) as price_response:
                                            price_text = await price_response.text()
                                            logger.info(f"代币 {token_address} 价格响应: {price_text}")
                                            
                                            if price_response.status == 200:
                                                try:
                                                    price_data = json.loads(price_text)
                                                    if price_data:
                                                        price_usd = price_data.get('usdPrice', 0)
                                                        token_data['price_usd'] = str(price_usd)
                                                        price_change = price_data.get('24hrPercentChange', 0)
                                                        token_data['price_change_24h'] = str(price_change)
                                                        
                                                        try:
                                                            balance = Decimal(str(token_data['balance']))
                                                            value = balance * Decimal(str(price_usd))
                                                            token_data['value_usd'] = str(value)
                                                        except Exception as e:
                                                            logger.error(f"计算代币价值时出错: {str(e)}")
                                                            token_data['value_usd'] = '0'
                                                except json.JSONDecodeError as e:
                                                    logger.error(f"解析代币价格数据失败: {str(e)}")
                                            else:
                                                logger.warning(f"获取代币 {token_address} 价格失败: {price_text}")

                                        # 保存到数据库
                                        await sync_to_async(Token.objects.update_or_create)(
                                            chain=wallet.chain,
                                            address=token_address,
                                            defaults={
                                                'name': token_data['name'],
                                                'symbol': token_data['symbol'],
                                                'decimals': token_data['decimals'],
                                                'logo': token_data['logo'],
                                                'type': 'token',
                                                'contract_type': 'ERC20',
                                                'last_balance': token_data['balance'],
                                                'last_price': token_data['price_usd'],
                                                'last_price_change': token_data['price_change_24h'],
                                                'last_value': token_data['value_usd'],
                                                'updated_at': timezone.now()
                                            }
                                        )

                                        token_list.append(token_data)
                                        logger.info(f"添加代币到列表: {token_data['symbol']}, 余额: {token_data['balance']}, 价格: {token_data['price_usd']}, 价值: {token_data['value_usd']}")
                                    except Exception as e:
                                        logger.error(f"处理代币数据时发生错误: {str(e)}，错误类型: {type(e).__name__}")
                                        continue
                            except json.JSONDecodeError as e:
                                logger.error(f"解析API响应失败: {str(e)}")
                        else:
                            logger.error(f"Moralis API请求失败: 状态码={response.status}, 响应内容={response_text}")

                except Exception as e:
                    logger.error(f"获取代币列表时发生错误: {str(e)}，错误类型: {type(e).__name__}")
                    logger.exception(e)

            # 按价值排序代币列表
            token_list.sort(key=lambda x: float(x.get('value_usd', '0') or '0'), reverse=True)
            logger.info(f"返回代币列表，总数: {len(token_list)}")
            return token_list
        except Exception as e:
            logger.error(f"获取EVM代币时发生错误: {str(e)}，错误类型: {type(e).__name__}")
            return []

    @staticmethod
    async def _get_solana_token_transfers(
        address: str,
        token_address: Optional[str] = None,
        transfer_type: str = 'all',
        page: int = 1,
        page_size: int = 20
    ) -> Dict:
        """获取 Solana 代币转账记录"""
        try:
            # 首先从本地数据库获取交易记录
            db_transfers = []
            try:
                # 构建基础查询
                query = Q(chain='SOL') & Q(status='SUCCESS')
                
                # 添加地址筛选
                if transfer_type == 'in':
                    query &= Q(to_address=address)
                elif transfer_type == 'out':
                    query &= Q(from_address=address)
                else:
                    # 对于 'all' 类型，获取所有相关交易
                    query &= (Q(from_address=address) | Q(to_address=address))
                
                # 添加代币筛选
                if token_address:
                    if token_address.lower() == 'so11111111111111111111111111111111111111112':
                        # 原生 SOL 转账
                        query &= Q(token__isnull=True)
                    else:
                        # SPL 代币转账
                        query &= Q(token__address=token_address.lower())
                
                # 从数据库获取交易记录
                db_transactions = await sync_to_async(list)(
                    Transaction.objects.filter(query)
                    .select_related('token')
                    .order_by('-block_timestamp')
                    [(page - 1) * page_size:page * page_size]
                )
                
                # 转换为统一格式
                for tx in db_transactions:
                    token_info = {
                        'symbol': tx.token.symbol if tx.token else 'SOL',
                        'name': tx.token.name if tx.token else 'Solana',
                        'decimals': tx.token.decimals if tx.token else 9,
                        'logo': tx.token.logo if tx.token else ''
                    }
                    
                    transfer_data = {
                        'transaction_hash': tx.tx_hash,
                        'block_number': str(tx.block_number),
                        'block_timestamp': str(tx.block_timestamp),
                        'from_address': tx.from_address,
                        'to_address': tx.to_address,
                        'token_address': tx.token.address if tx.token else 'So11111111111111111111111111111111111111112',
                        'amount': str(tx.amount),
                        'amount_decimal': str(tx.amount),
                        'token_symbol': token_info['symbol'],
                        'token_name': token_info['name'],
                        'token_decimals': token_info['decimals'],
                        'token_logo': token_info['logo'],
                        'value_usd': '0',  # 历史价值需要单独计算
                        'type': 'in' if tx.to_address == address else 'out'
                    }
                    db_transfers.append(transfer_data)
                
                logger.info(f"从数据库获取到 {len(db_transfers)} 条交易记录")
                
            except Exception as e:
                logger.error(f"从数据库获取交易记录失败: {str(e)}")
            
            # 然后从 Moralis API 获取交易记录
            headers = {
                "accept": "application/json",
                "X-API-Key": MoralisConfig.API_KEY
            }
            
            # 构建基础URL
            base_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{address}/transfers"
            
            # 构建查询参数
            params = {
                "limit": str(page_size),
                "cursor": str((page - 1) * page_size) if page > 1 else None
            }
            
            if token_address:
                params["token_addresses"] = token_address
            
            async with aiohttp.ClientSession() as session:
                async with session.get(base_url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        api_transfers = []
                        
                        for transfer in data.get('result', []):
                            # 跳过已存在于数据库中的交易
                            if any(tx['transaction_hash'] == transfer.get('signature') for tx in db_transfers):
                                continue
                                
                            # 根据转账方向筛选
                            if transfer_type != 'all':
                                is_incoming = transfer.get('to_wallet') == address
                                if (transfer_type == 'in' and not is_incoming) or \
                                   (transfer_type == 'out' and is_incoming):
                                    continue
                            
                            # 构建转账记录
                            transfer_data = {
                                'transaction_hash': str(transfer.get('signature', '')),
                                'block_number': str(transfer.get('block_number', '0')),
                                'block_timestamp': str(transfer.get('block_timestamp', '')),
                                'from_address': str(transfer.get('from_wallet', '')),
                                'to_address': str(transfer.get('to_wallet', '')),
                                'token_address': str(transfer.get('token_address', 'So11111111111111111111111111111111111111112')),
                                'amount': str(transfer.get('amount', '0')),
                                'amount_decimal': str(transfer.get('amount_decimal', '0')),
                                'token_symbol': str(transfer.get('token_symbol', 'SOL')),
                                'token_name': str(transfer.get('token_name', 'Solana')),
                                'token_decimals': int(transfer.get('token_decimals', 9)),
                                'token_logo': str(transfer.get('token_logo', '')),
                                'value_usd': str(transfer.get('value_usd', '0')),
                                'type': 'in' if transfer.get('to_wallet') == address else 'out'
                            }
                            api_transfers.append(transfer_data)
                        
                        # 合并并排序所有转账记录
                        all_transfers = db_transfers + api_transfers
                        all_transfers.sort(key=lambda x: x['block_timestamp'], reverse=True)
                        
                        # 分页处理
                        start_idx = (page - 1) * page_size
                        end_idx = start_idx + page_size
                        paginated_transfers = all_transfers[start_idx:end_idx]
                        
                        return {
                            'result': paginated_transfers,
                            'total': len(all_transfers),
                            'page': page,
                            'page_size': page_size,
                            'cursor': str(data.get('cursor', ''))
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"获取Solana转账记录失败: {error_text}")
                        # 如果API调用失败，至少返回数据库中的记录
                        return {
                            'result': db_transfers,
                            'total': len(db_transfers),
                            'page': page,
                            'page_size': page_size,
                            'cursor': None
                        }
                        
        except Exception as e:
            logger.error(f"获取Solana转账记录时出错: {str(e)}")
            return {
                'result': [],
                'total': 0,
                'page': page,
                'page_size': page_size,
                'cursor': None
            }

    @staticmethod
    async def _get_evm_token_transfers(
        chain: str,
        address: str,
        token_address: Optional[str] = None,
        transfer_type: str = 'all',
        page: int = 1,
        page_size: int = 20
    ) -> Dict:
        """获取 EVM 链代币转账记录"""
        try:
            chain_id = TokenBalanceService.CHAIN_MAPPING.get(Chain(chain))
            if not chain_id:
                raise ValueError(f"不支持的链类型: {chain}")
            
            headers = {
                "accept": "application/json",
                "X-API-Key": MoralisConfig.API_KEY
            }
            
            # 构建基础URL和参数
            if token_address and token_address != 'native':
                # ERC20代币转账
                url = f"{MoralisConfig.BASE_URL}/wallets/{address}/erc20/transfers"
                params = {
                    "chain": str(chain_id),
                    "contract_addresses": [str(token_address)]
                }
            else:
                # 原生代币转账
                url = f"{MoralisConfig.BASE_URL}/wallets/{address}/transfers"
                params = {
                    "chain": str(chain_id)
                }
            
            # 添加分页参数
            params["limit"] = str(page_size)
            if page > 1:
                params["cursor"] = str((page - 1) * page_size)
            
            logger.info(f"请求转账记录: URL={url}, Params={params}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    response_text = await response.text()
                    logger.info(f"API响应: {response_text}")
                    
                    if response.status == 200:
                        data = json.loads(response_text)
                        transfers = []
                        
                        for transfer in data.get('result', []):
                            # 根据转账方向筛选
                            if transfer_type != 'all':
                                is_incoming = transfer.get('to_address', '').lower() == address.lower()
                                if (transfer_type == 'in' and not is_incoming) or \
                                   (transfer_type == 'out' and is_incoming):
                                    continue
                            
                            # 获取代币信息
                            token_data = await TokenBalanceService._get_token_info(
                                session, chain_id, transfer.get('token_address', 'native')
                            )
                            
                            # 构建转账记录，确保所有字段都有默认值
                            transfer_data = {
                                'transaction_hash': str(transfer.get('transaction_hash', '')),
                                'block_number': str(transfer.get('block_number', '0')),
                                'block_timestamp': str(transfer.get('block_timestamp', '')),
                                'from_address': str(transfer.get('from_address', '')),
                                'to_address': str(transfer.get('to_address', '')),
                                'token_address': str(transfer.get('token_address', 'native')),
                                'amount': str(transfer.get('value', '0')),
                                'amount_decimal': str(float(transfer.get('value', '0')) / 10 ** int(token_data.get('decimals', 18))),
                                'token_symbol': str(token_data.get('symbol', 'Unknown')),
                                'token_name': str(token_data.get('name', 'Unknown Token')),
                                'token_decimals': int(token_data.get('decimals', 18)),
                                'token_logo': str(token_data.get('logo', '')),
                                'gas_price': str(transfer.get('gas_price', '0')),
                                'gas_used': str(transfer.get('receipt_gas_used', '0')),
                                'type': 'in' if transfer.get('to_address', '').lower() == address.lower() else 'out'
                            }
                            transfers.append(transfer_data)
                        
                        return {
                            'result': transfers,
                            'total': int(data.get('total', 0)),
                            'page': page,
                            'page_size': page_size,
                            'cursor': str(data.get('cursor', ''))
                        }
                    else:
                        logger.error(f"获取EVM转账记录失败: {response_text}")
                        return {
                            'result': [],
                            'total': 0,
                            'page': page,
                            'page_size': page_size,
                            'cursor': None
                        }
                        
        except Exception as e:
            logger.error(f"获取EVM转账记录时出错: {str(e)}")
            return {
                'result': [],
                'total': 0,
                'page': page,
                'page_size': page_size,
                'cursor': None
            }

    @staticmethod
    async def _get_token_info(session, chain: str, token_address: str) -> Dict:
        """获取代币信息"""
        try:
            if token_address == 'native':
                # 返回原生代币信息
                chain_info = {
                    'ETH': {'symbol': 'ETH', 'name': 'Ethereum', 'decimals': 18},
                    'BSC': {'symbol': 'BNB', 'name': 'BNB', 'decimals': 18},
                    'MATIC': {'symbol': 'MATIC', 'name': 'Polygon', 'decimals': 18},
                    'AVAX': {'symbol': 'AVAX', 'name': 'Avalanche', 'decimals': 18}
                }
                chain_symbol = chain.upper()
                return {
                    'symbol': chain_info.get(chain_symbol, {}).get('symbol', chain_symbol),
                    'name': chain_info.get(chain_symbol, {}).get('name', f"{chain_symbol} Token"),
                    'decimals': chain_info.get(chain_symbol, {}).get('decimals', 18),
                    'logo': f"https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/{chain.lower()}/info/logo.png"
                }
            
            # 从数据库获取代币信息
            token = await sync_to_async(Token.objects.filter(
                chain=chain,
                address=token_address.lower()
            ).first)()
            
            if token:
                return {
                    'symbol': token.symbol,
                    'name': token.name,
                    'decimals': token.decimals,
                    'logo': token.logo
                }
            
            # 如果数据库中没有，从API获取
            headers = {
                "accept": "application/json",
                "X-API-Key": MoralisConfig.API_KEY
            }
            url = f"{MoralisConfig.BASE_URL}/erc20/metadata"
            params = {
                "chain": chain,
                "addresses": [token_address]
            }
            
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        token_data = data[0]
                        return {
                            'symbol': token_data.get('symbol', 'Unknown'),
                            'name': token_data.get('name', 'Unknown Token'),
                            'decimals': int(token_data.get('decimals', '18')),
                            'logo': token_data.get('logo')
                        }
            
            return {
                'symbol': 'Unknown',
                'name': 'Unknown Token',
                'decimals': 18,
                'logo': None
            }
            
        except Exception as e:
            logger.error(f"获取代币信息时出错: {str(e)}")
            return {
                'symbol': 'Unknown',
                'name': 'Unknown Token',
                'decimals': 18,
                'logo': None
            }