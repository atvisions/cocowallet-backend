import aiohttp
import logging
from typing import Dict, List
from decimal import Decimal
from moralis import evm_api, sol_api
from . import BaseTokenService
from ..models import Wallet, Token
from ..api_config import MoralisConfig, APIConfig, Chain
from ..constants import SOLANA_TOKEN_LIST
import json
from asgiref.sync import sync_to_async
from django.utils import timezone
from datetime import timedelta
import asyncio
import async_timeout

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

            # 检查缓存是否有效
            has_valid_cache = bool(cached_tokens) and any(
                token.get('is_native', False) and float(token.get('last_balance', '0') or '0') > 0
                for token in cached_tokens
            )

            tokens = []
            if has_valid_cache:
                logger.info("使用缓存数据")
                for token in cached_tokens:
                    if float(token.get('last_balance', '0') or '0') > 0:
                        token_data = {
                            'symbol': token['symbol'],
                            'name': token['name'],
                            'balance': token.get('last_balance', '0'),
                            'decimals': token['decimals'],
                            'logo': token['logo'],
                            'price_usd': token.get('last_price', '0'),
                            'price_change_24h': token.get('last_price_change', '0'),
                            'value_usd': token.get('last_value', '0'),
                            'chain': wallet.chain,
                            'contract': token['address'],
                            'is_native': token.get('is_native', False)
                        }
                        tokens.append(token_data)
            else:
                logger.info("从API获取最新数据")
                if wallet.chain == 'SOL':
                    tokens = await TokenBalanceService._get_solana_balances(wallet)
                elif wallet.chain == 'BTC':
                    tokens = await TokenBalanceService._get_btc_balances(wallet.address)
                else:
                    tokens = await TokenBalanceService._get_evm_balances(wallet)

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
                    
                    # 1. 使用 /tokens 端点
                    tokens_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{wallet.address}/tokens"
                    tokens_result = await TokenBalanceService.fetch_with_retry(session, tokens_url, headers=headers) or []
                    if isinstance(tokens_result, list):
                        tokens_data.extend(tokens_result)
                    
                    # 2. 使用 /spl 端点
                    spl_tokens_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{wallet.address}/spl"
                    spl_tokens_result = await TokenBalanceService.fetch_with_retry(session, spl_tokens_url, headers=headers) or []
                    if isinstance(spl_tokens_result, list):
                        tokens_data.extend(spl_tokens_result)
                    
                    # 3. 使用 /portfolio 端点
                    portfolio_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{wallet.address}/portfolio"
                    portfolio_result = await TokenBalanceService.fetch_with_retry(session, portfolio_url, headers=headers)
                    if portfolio_result and isinstance(portfolio_result.get('tokens'), list):
                        tokens_data.extend(portfolio_result['tokens'])
                    
                    # 4. 使用 /nft 端点（某些代币可能被错误分类为NFT）
                    nft_url = f"{MoralisConfig.SOLANA_URL}/account/mainnet/{wallet.address}/nft"
                    nft_result = await TokenBalanceService.fetch_with_retry(session, nft_url, headers=headers)
                    if nft_result and isinstance(nft_result, list):
                        for nft in nft_result:
                            if nft.get('decimals', 0) > 0:  # 如果有小数位，可能是代币
                                tokens_data.append(nft)
                    
                    # 合并所有代币数据，使用字典去重
                    all_tokens = {}
                    for token in tokens_data:
                        # 尝试获取代币地址
                        mint = (token.get('mint') or 
                               token.get('token_address') or 
                               token.get('address') or 
                               token.get('contract'))
                        
                        if not mint:
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
                        semaphore = asyncio.Semaphore(3)  # 降低并发数
                        
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
                                    'contract': None,
                                    'is_native': True,
                                    'price_usd': '0',
                                    'price_change_24h': '0',
                                    'value_usd': '0'
                                }
                                
                                # 获取原生代币价格和价格变化
                                native_price_url = MoralisConfig.EVM_TOKEN_PRICE_BATCH_URL.format(chain)
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
                                                price_change = price_data.get('24hPercentChange', 0)
                                                native_token_data['price_change_24h'] = str(price_change)
                                                value_usd = float(balance) * float(price_usd)
                                                native_token_data['value_usd'] = str(value_usd)
                                                
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
                                        except json.JSONDecodeError as e:
                                            logger.error(f"解析原生代币价格数据失败: {str(e)}")
                                
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
                                            'symbol': token.get('symbol', 'Unknown'),
                                            'name': token.get('name', 'Unknown Token'),
                                            'balance': token.get('balance_formatted', '0'),
                                            'decimals': token.get('decimals', 18),
                                            'chain': wallet.chain,
                                            'contract': token_address,
                                            'logo': token.get('logo') or token.get('thumbnail'),
                                            'is_native': False,
                                            'price_usd': '0',
                                            'price_change_24h': '0',
                                            'value_usd': '0'
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
                                                        price_change = price_data.get('24hPercentChange', 0)
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