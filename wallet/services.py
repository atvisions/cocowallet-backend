from typing import Dict, List, Optional, Tuple, Union
import aiohttp
import asyncio
from decimal import Decimal
from django.core.cache import cache
from moralis import evm_api, sol_api
from .api_config import APIConfig, Chain, APIEndpoints
from .models import Wallet, Token
from .constants import QUICKNODE_COIN_IDS, SOLANA_TOKEN_LIST
import logging
import requests
from django.conf import settings
import json
from django.db.models import Q

logger = logging.getLogger(__name__)

class TokenService:
    """代币服务类"""
    
    MORALIS_API_KEY = settings.MORALIS_API_KEY
    
    CHAIN_MAPPING = {
        'ETH': 'eth',
        'BSC': 'bsc',
        'POLYGON': 'polygon',
        'ARBITRUM': 'arbitrum',
        'OPTIMISM': 'optimism',
        'AVALANCHE': 'avalanche',
        'BASE': 'base'
    }

    COINGECKO_MAPPING = {
        'BONK': 'bonk',
        'USDC': 'usd-coin',
        'SOL': 'solana',
        'MSOL': 'msol',
        'JUP': 'jupiter',
        'RAY': 'raydium',
        'ORCA': 'orca'
    }
    
    NATIVE_TOKEN_MAPPING = {
        'eth': {'id': 'ethereum', 'decimals': 18},
        'bsc': {'id': 'binancecoin', 'decimals': 18},
        'polygon': {'id': 'matic-network', 'decimals': 18},
        'arbitrum': {'id': 'ethereum', 'decimals': 18},  # Arbitrum 使用 ETH
        'optimism': {'id': 'ethereum', 'decimals': 18},  # Optimism 使用 ETH
        'avalanche': {'id': 'avalanche-2', 'decimals': 18},
        'base': {'id': 'ethereum', 'decimals': 18}  # Base 使用 ETH
    }
    
    @staticmethod
    async def get_token_list(wallet: Wallet, force_refresh=False) -> List[Dict]:
        """获取钱包的代币列表"""
        logger.info(f"Getting token list for wallet {wallet.address} on chain {wallet.chain}")
        
        cache_key = f'token_list_{wallet.chain}_{wallet.address}'
        if not force_refresh:
            cached_data = cache.get(cache_key)
            if cached_data:
                logger.info("Returning cached token list")
                return cached_data
            
        try:
            tokens = []
            
            # 获取数据库中的代币列表
            db_tokens = Token.objects.filter(chain=wallet.chain).order_by('rank')
            
            if wallet.chain == 'SOL':
                logger.info("Fetching Solana tokens")
                tokens = await TokenService._get_solana_tokens(wallet)
            elif wallet.chain == 'BTC':
                logger.info("Fetching Bitcoin tokens")
                tokens = await TokenService._get_btc_tokens(wallet.address)
            else:
                logger.info(f"Fetching {wallet.chain} tokens")
                tokens = await TokenService._get_evm_tokens(wallet)
                
            # 补充代币信息
            for token in tokens:
                try:
                    db_token = db_tokens.filter(
                        Q(address__iexact=token.get('contract')) | 
                        Q(symbol__iexact=token.get('symbol'))
                    ).first()
                    
                    if db_token:
                        token.update({
                            'name': db_token.name,
                            'symbol': db_token.symbol,
                            'logo': db_token.logo or token.get('logo', ''),
                            'decimals': db_token.decimals,
                            'website': db_token.website,
                            'explorer': db_token.explorer,
                            'twitter': db_token.twitter,
                            'telegram': db_token.telegram
                        })
                except Exception as e:
                    logger.error(f"Error updating token info from DB: {str(e)}")
                    continue
            
            # 获取价格数据
            await TokenService._update_token_prices(tokens)
            
            # 缓存结果
            cache_config = APIConfig.get_cache_config()
            cache.set(cache_key, tokens, cache_config['TIMEOUT'])
            logger.info(f"Found {len(tokens)} tokens")
            return tokens
                
        except Exception as e:
            logger.error(f"Error fetching token list: {str(e)}")
            return []
    
    @staticmethod
    async def _get_solana_tokens(wallet: Wallet) -> List[Dict]:
        """获取 Solana 代币列表"""
        try:
            # 获取代币列表
            url = "https://solana-gateway.moralis.io/account/mainnet/{}/tokens".format(wallet.address)
            headers = {
                "accept": "application/json",
                "X-API-Key": TokenService.MORALIS_API_KEY
            }
            
            logger.info(f"Calling Moralis Solana API: {url}")
            async with aiohttp.ClientSession() as session:
                # 获取原生 SOL 余额
                sol_url = f"https://solana-gateway.moralis.io/account/mainnet/{wallet.address}/balance"
                async with session.get(sol_url, headers=headers) as sol_response:
                    if sol_response.status == 200:
                        sol_data = await sol_response.json()
                        logger.info(f"Raw SOL data: {sol_data}")
                        # 直接使用 solana 字段的值，不需要除以精度
                        sol_balance = Decimal(str(sol_data.get('solana', 0)))
                        logger.info(f"Got SOL balance: {sol_balance}")
                    else:
                        sol_balance = Decimal('0')
                        logger.error(f"Error fetching SOL balance: {await sol_response.text()}")

                # 添加原生 SOL
                token_list = []
                if sol_balance > 0:
                    token_list.append({
                        'symbol': 'SOL',
                        'name': 'Solana',
                        'balance': str(sol_balance),
                        'decimals': 9,
                        'price_usd': '0',
                        'value_usd': '0',
                        'chain': 'SOL',
                        'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
                    })

                # 获取其他代币
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Error fetching Solana tokens: {error_text}")
                        return token_list  # 返回只包含 SOL 的列表
                        
                    tokens = await response.json()
                    logger.info(f"Raw tokens data: {json.dumps(tokens, indent=2)}")

                    for token in tokens:
                        try:
                            mint = token.get('mint')
                            # 直接使用 amount 字段
                            amount = token.get('amount', '0')
                            decimals = int(token.get('decimals', 0))
                            
                            # 记录原始数据
                            logger.info(f"Processing raw token data: mint={mint}, amount={amount}, decimals={decimals}")
                            
                            # 直接使用原始 amount
                            balance = Decimal(str(amount))
                            logger.info(f"Using original amount as balance: {balance}")

                            # 从 SOLANA_TOKEN_LIST 获取代币信息
                            token_info = SOLANA_TOKEN_LIST.get(mint)
                            if token_info:  # 只添加已知代币
                                symbol = token_info.get('symbol', 'Unknown')
                                name = token_info.get('name', 'Unknown Token')
                                logo = token_info.get('logo', '')

                                token_data = {
                                    'symbol': symbol,
                                    'name': name,
                                    'balance': str(balance),
                                    'decimals': decimals,
                                    'price_usd': '0',
                                    'value_usd': '0',
                                    'chain': 'SOL',
                                    'mint': mint,
                                    'logo': logo
                                }
                                token_list.append(token_data)
                                logger.info(f"Added token to list: {json.dumps(token_data, indent=2)}")
                        except Exception as e:
                            logger.error(f"Error processing token data: {str(e)}, token: {token}")
                            continue

                    # 获取价格数据
                    await TokenService._update_token_prices(token_list)
                    
                    # 计算价值
                    for token in token_list:
                        try:
                            balance = Decimal(str(token.get('balance', 0)))
                            price = Decimal(str(token.get('price_usd', 0)))
                            value = balance * price
                            token['value_usd'] = str(value)
                            logger.info(f"Final token data: {json.dumps(token, indent=2)}")
                        except Exception as e:
                            logger.error(f"Error calculating token value: {str(e)}")
                            token['value_usd'] = '0'

                    logger.info(f"Returning {len(token_list)} processed tokens")
                    return token_list
        except Exception as e:
            logger.error(f"Error fetching Solana tokens: {str(e)}")
            return []
    
    @staticmethod
    async def _get_evm_tokens(wallet: Wallet) -> List[Dict]:
        """获取 EVM 链代币列表"""
        try:
            chain = TokenService.CHAIN_MAPPING.get(wallet.chain)
            if not chain:
                logger.error(f"Unsupported chain: {wallet.chain}")
                return []

            token_list = []
            
            # 获取原生代币余额
            try:
                native_params = {
                    "address": wallet.address,
                    "chain": chain
                }
                
                logger.info(f"Getting native balance for chain {chain}")
                native_balance = evm_api.balance.get_native_balance(
                    api_key=TokenService.MORALIS_API_KEY,
                    params=native_params
                )
                
                # 添加原生代币
                if native_balance and float(native_balance.get('balance', '0')) > 0:
                    chain_info = TokenService.NATIVE_TOKEN_MAPPING.get(chain, {'id': None, 'decimals': 18})
                    balance = float(native_balance.get('balance', '0')) / (10 ** chain_info['decimals'])
                    
                    # 获取原生代币价格
                    native_price = 0
                    price_change_24h = 0
                    try:
                        if chain_info['id']:
                            url = f"https://api.coingecko.com/api/v3/simple/price?ids={chain_info['id']}&vs_currencies=usd&include_24hr_change=true"
                            logger.info(f"Fetching native token price from CoinGecko: {url}")
                            async with aiohttp.ClientSession() as session:
                                async with session.get(url) as response:
                                    if response.status == 200:
                                        price_data = await response.json()
                                        if chain_info['id'] in price_data:
                                            native_price = float(price_data[chain_info['id']].get('usd', 0))
                                            price_change_24h = price_data[chain_info['id']].get('usd_24h_change', 0)
                                            logger.info(f"Got native token price: ${native_price} (24h change: {price_change_24h}%)")
                    except Exception as e:
                        logger.error(f"Error getting native token price: {str(e)}")
                    
                    value = balance * native_price
                    
                    # 获取原生代币信息
                    native_token = {
                        'symbol': wallet.chain,  # ETH, BNB, MATIC 等
                        'name': f'{wallet.chain} Token',  # Ethereum, BNB, Polygon 等
                        'balance': str(balance),
                        'decimals': chain_info['decimals'],
                        'price_usd': str(native_price),
                        'price_change_24h': str(price_change_24h),
                        'value_usd': str(value),
                        'chain': wallet.chain,
                        'is_native': True
                    }
                    token_list.append(native_token)
                    logger.info(f"Added native token {wallet.chain} with balance {balance}")
            except Exception as e:
                logger.error(f"Error getting native token balance: {str(e)}")

            # 获取 ERC20 代币
            try:
                params = {
                    "address": wallet.address,
                    "chain": chain
                }

                logger.info(f"Calling Moralis EVM API for chain {chain}")
                result = evm_api.token.get_wallet_token_balances(
                    api_key=TokenService.MORALIS_API_KEY,
                    params=params
                )

                logger.info(f"Got {len(result)} raw tokens from Moralis")

                for token in result:
                    try:
                        balance = float(token.get('balance', 0)) / (10 ** int(token.get('decimals', 18)))
                        if balance <= 0:
                            continue
                            
                        price = float(token.get('usd_price') or 0)
                        value = balance * price

                        token_data = {
                            'symbol': token.get('symbol', 'Unknown'),
                            'name': token.get('name', 'Unknown Token'),
                            'balance': str(balance),
                            'decimals': token.get('decimals', 18),
                            'price_usd': str(price),
                            'value_usd': str(value),
                            'chain': wallet.chain,
                            'contract': token.get('token_address'),
                            'logo': token.get('logo', ''),
                            'is_native': False
                        }
                        token_list.append(token_data)
                        logger.info(f"Processed token {token.get('symbol')} with balance {balance}")
                    except Exception as e:
                        logger.error(f"Error processing token data: {str(e)}, token: {token}")
                        continue
            except Exception as e:
                logger.error(f"Error getting ERC20 tokens: {str(e)}")

            logger.info(f"Returning {len(token_list)} processed tokens")
            return token_list
        except Exception as e:
            logger.error(f"Error fetching EVM tokens: {str(e)}")
            return []
    
    @staticmethod
    async def _get_metadata_pda(mint_address: str) -> str:
        """获取代币元数据账户地址"""
        try:
            import base58
            from hashlib import sha256
            
            # Metaplex 程序 ID
            METADATA_PROGRAM_ID = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
            metadata_seed = "metadata"
            
            # 计算 PDA
            seeds = [
                metadata_seed.encode('utf-8'),
                base58.b58decode(METADATA_PROGRAM_ID),
                base58.b58decode(mint_address)
            ]
            
            # 连接所有种子
            all_seeds = b''.join(seeds)
            
            # 计算哈希
            h = sha256()
            h.update(all_seeds)
            
            # 返回 base58 编码的地址
            return base58.b58encode(h.digest()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error calculating metadata PDA: {str(e)}")
            return None
            
    @staticmethod
    async def _decode_metadata(data: str) -> Dict:
        """解码代币元数据"""
        try:
            import base64
            import struct
            
            # Base64 解码
            decoded = base64.b64decode(data)
            
            # 解析元数据结构
            # 跳过前 1 个字节（用于版本）
            offset = 1
            
            # 读取名称长度和名称
            name_length = struct.unpack("<I", decoded[offset:offset+4])[0]
            offset += 4
            name = decoded[offset:offset+name_length].decode('utf-8')
            offset += name_length
            
            # 读取符号长度和符号
            symbol_length = struct.unpack("<I", decoded[offset:offset+4])[0]
            offset += 4
            symbol = decoded[offset:offset+symbol_length].decode('utf-8')
            offset += symbol_length
            
            # 读取 URI 长度和 URI
            uri_length = struct.unpack("<I", decoded[offset:offset+4])[0]
            offset += 4
            uri = decoded[offset:offset+uri_length].decode('utf-8')
            
            return {
                'name': name,
                'symbol': symbol,
                'uri': uri
            }
        except Exception as e:
            logger.error(f"Error decoding metadata: {str(e)}")
            return {
                'name': 'Unknown Token',
                'symbol': 'Unknown',
                'uri': ''
            }
    
    @staticmethod
    async def _update_solana_token_info(tokens: List[Dict]) -> None:
        """更新 Solana 代币信息和价格"""
        if not tokens:
            return
            
        async with aiohttp.ClientSession() as session:
            base_url = f"{APIConfig.QUICKNODE.SOLANA_URL}/addon/748/v1"
            headers = APIConfig.get_headers(Chain.SOL)
            
            # 更新每个代币的详细信息
            for token in tokens:
                try:
                    if token.get('is_native'):
                        continue
                        
                    mint = token.get('mint')
                    if not mint:
                        continue
                        
                    # 获取代币元数据
                    metadata_url = f"{base_url}/coins/{mint}"
                    async with session.get(
                        metadata_url,
                        headers=headers,
                        timeout=APIConfig.REQUEST_TIMEOUT
                    ) as metadata_response:
                        if metadata_response.status == 200:
                            metadata = await metadata_response.json()
                            token.update({
                                'name': metadata.get('name', 'Unknown Token'),
                                'symbol': metadata.get('symbol', '').upper(),
                                'logo': metadata.get('logo', '')
                            })
                            
                            # 获取价格信息
                            ticker_url = f"{base_url}/tickers/{metadata.get('id')}"
                            async with session.get(
                                ticker_url,
                                headers=headers,
                                timeout=APIConfig.REQUEST_TIMEOUT
                            ) as ticker_response:
                                if ticker_response.status == 200:
                                    ticker_data = await ticker_response.json()
                                    if ticker_data.get('quotes', {}).get('USD'):
                                        usd_data = ticker_data['quotes']['USD']
                                        token.update({
                                            'price_usd': str(usd_data.get('price', 0)),
                                            'price_change_24h': str(usd_data.get('percent_change_24h', 0))
                                        })
                except Exception as e:
                    logger.error(f"Error updating token info: {str(e)}")
                    continue
                    
        # 更新 SOL 的价格
        await TokenService._update_native_sol_price(tokens)

    @staticmethod
    async def _get_btc_tokens(address: str) -> List[Dict]:
        """获取比特币余额"""
        async with aiohttp.ClientSession() as session:
            url = f"{APIConfig.get_btc_api_url()}{APIEndpoints.BTC.GET_BALANCE.format(address=address)}"
            headers = APIConfig.get_headers(Chain.BTC)
            
            async with session.get(
                url,
                headers=headers,
                timeout=APIConfig.REQUEST_TIMEOUT
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # 将 BTC 余额转换为代币列表格式
                    balance = Decimal(str(data.get('balance', 0))) / Decimal('100000000')  # Convert satoshis to BTC
                    return [{
                        'symbol': 'BTC',
                        'name': 'Bitcoin',
                        'balance': str(balance),
                        'decimals': 8,
                        'is_native': True
                    }]
                return []
    
    @staticmethod
    async def _update_token_prices(tokens: List[Dict]) -> None:
        """更新代币价格"""
        try:
            # 收集需要查询价格的代币
            symbols_to_query = set()
            for token in tokens:
                symbol = token.get('symbol', '').upper()
                if symbol in TokenService.COINGECKO_MAPPING:
                    symbols_to_query.add(TokenService.COINGECKO_MAPPING[symbol])

            if not symbols_to_query:
                return

            # 构建 CoinGecko API URL，添加 24h 价格变化
            ids = ','.join(symbols_to_query)
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
            
            logger.info(f"Fetching prices from CoinGecko: {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        prices = await response.json()
                        logger.info(f"Got prices: {prices}")
                        
                        # 更新代币价格
                        for token in tokens:
                            symbol = token.get('symbol', '').upper()
                            if symbol in TokenService.COINGECKO_MAPPING:
                                coin_id = TokenService.COINGECKO_MAPPING[symbol]
                                if coin_id in prices:
                                    price = Decimal(str(prices[coin_id].get('usd', 0)))
                                    price_change_24h = prices[coin_id].get('usd_24h_change', 0)
                                    token['price_usd'] = str(price)
                                    token['price_change_24h'] = str(price_change_24h)
                                    # 计算价值
                                    balance = Decimal(str(token.get('balance', '0')))
                                    value = balance * price
                                    token['value_usd'] = str(value)
                                    logger.info(f"Updated {symbol} price to ${price} (24h change: {price_change_24h}%)")
                    else:
                        logger.error(f"Error fetching prices: {await response.text()}")
        except Exception as e:
            logger.error(f"Error updating token prices: {str(e)}")
    
    @staticmethod
    def _format_price_change(change: str) -> str:
        """格式化价格变化"""
        try:
            value = float(change)
            sign = '+' if value > 0 else ''
            return f"{sign}{value:.2f}%"
        except (ValueError, TypeError):
            return "0.00%"
    
    @staticmethod
    def _format_price(price: str) -> str:
        """格式化价格，保证至少显示6位小数"""
        try:
            value = Decimal(price)
            if value >= 1000:
                return f"${value:,.6f}"
            elif value >= 1:
                return f"${value:.6f}"
            elif value > 0:
                return f"${value:.8f}"
            else:
                return "$0.000000"
        except (ValueError, TypeError):
            return "$0.000000"
    
    @staticmethod
    def _format_value(value: str) -> str:
        """格式化价值，保证至少显示6位小数"""
        try:
            value_decimal = Decimal(value)
            if value_decimal >= 1000000:
                return f"${value_decimal/1000000:.6f}M"
            elif value_decimal >= 1000:
                return f"${value_decimal/1000:.6f}K"
            elif value_decimal >= 1:
                return f"${value_decimal:.6f}"
            elif value_decimal > 0:
                return f"${value_decimal:.8f}"
            else:
                return "$0.000000"
        except (ValueError, TypeError):
            return "$0.000000"

    @staticmethod
    async def get_wallet_tokens(wallet: Wallet) -> Dict:
        """获取钱包代币信息"""
        logger.info(f"Getting formatted wallet tokens for {wallet.address}")
        tokens = await TokenService.get_token_list(wallet)
        
        total_value = Decimal('0')
        formatted_tokens = []
        
        for token in tokens:
            try:
                # 直接使用原始数据，不重新计算
                formatted_token = {
                    'symbol': token.get('symbol', '').upper(),
                    'name': token.get('name', 'Unknown Token'),
                    'balance': TokenService._format_balance(token.get('balance', '0')),
                    'price': TokenService._format_price(token.get('price_usd', '0')),
                    'price_change_24h': TokenService._format_price_change(token.get('price_change_24h', '0')),
                    'value': TokenService._format_value(token.get('value_usd', '0')),
                    'chain': token.get('chain', ''),
                    'logo': token.get('logo', '')
                }
                formatted_tokens.append(formatted_token)
                # 累加总价值
                total_value += Decimal(str(token.get('value_usd', '0')))
                logger.info(f"Formatted token {formatted_token['symbol']}: balance={token.get('balance')}, price=${token.get('price_usd')}, change_24h={token.get('price_change_24h')}%, value=${token.get('value_usd')}")
            except Exception as e:
                logger.error(f"Error formatting token data: {str(e)}, token: {token}")
                continue
        
        # 按价值排序（从高到低）
        formatted_tokens.sort(
            key=lambda x: float(x.get('value', '$0.00').replace('$', '').replace(',', '').replace('M', '000000').replace('K', '000')),
            reverse=True
        )
        
        result = {
            'tokens': formatted_tokens,
            'total_value': TokenService._format_value(str(total_value)),
            'token_count': len(formatted_tokens)
        }
        logger.info(f"Returning wallet summary: {result}")
        return result

    @staticmethod
    async def _update_native_sol_price(tokens: List[Dict]) -> None:
        """更新原生 SOL 的价格"""
        if not tokens:
            return
            
        async with aiohttp.ClientSession() as session:
            base_url = f"{APIConfig.QUICKNODE.SOLANA_URL}/addon/748/v1"
            headers = APIConfig.get_headers(Chain.SOL)
            
            for token in tokens:
                if not token.get('is_native'):
                    continue
                    
                try:
                    # 获取 SOL 价格信息
                    ticker_url = f"{base_url}/tickers/sol-solana"
                    async with session.get(
                        ticker_url,
                        headers=headers,
                        timeout=APIConfig.REQUEST_TIMEOUT
                    ) as ticker_response:
                        if ticker_response.status == 200:
                            ticker_data = await ticker_response.json()
                            if ticker_data.get('quotes', {}).get('USD'):
                                usd_data = ticker_data['quotes']['USD']
                                token.update({
                                    'price_usd': str(usd_data.get('price', 0)),
                                    'price_change_24h': str(usd_data.get('percent_change_24h', 0))
                                })
                except Exception as e:
                    logger.error(f"Error updating SOL price: {str(e)}")
                    continue

    @staticmethod
    def _format_balance(balance: str) -> str:
        """格式化余额，保证至少显示6位小数"""
        try:
            value = Decimal(balance)
            if value >= 1000000:  # 百万以上
                return f"{value:.2f}"  # 不再转换为 M
            elif value >= 1000:  # 千以上
                return f"{value:.2f}"  # 不再转换为 K
            elif value >= 1:  # 1以上
                return f"{value:.2f}"
            elif value >= 0.01:  # 0.01以上
                return f"{value:.6f}"
            elif value > 0:  # 大于0
                return f"{value:.8f}"
            else:
                return "0.000000"
        except (ValueError, TypeError):
            return "0.000000"

class WalletService:
    """钱包服务类"""
    
    @staticmethod
    async def get_wallet_value(wallet: Wallet) -> Decimal:
        """获取钱包总价值（USD）"""
        tokens = await TokenService.get_token_list(wallet)
        return sum(Decimal(str(token.get('value_usd', '0'))) for token in tokens)
    
    @staticmethod
    async def get_wallet_tokens(wallet: Wallet) -> Dict:
        """获取钱包代币信息"""
        tokens = await TokenService.get_token_list(wallet)
        
        total_value = Decimal('0')
        
        # 格式化代币信息
        formatted_tokens = []
        for token in tokens:
            # 计算代币价值
            balance = Decimal(str(token.get('balance', '0')))
            price = Decimal(str(token.get('price_usd', '0')))
            value = balance * price
            total_value += value
            
            formatted_token = {
                'symbol': token.get('symbol', '').upper(),
                'name': token.get('name', ''),
                'balance': token.get('balance', '0'),
                'price': TokenService._format_price(token.get('price_usd', '0')),
                'price_change_24h': TokenService._format_price_change(token.get('price_change_24h', '0')),
                'value': TokenService._format_value(str(value)),
                'logo': token.get('logo', ''),
                'is_native': token.get('is_native', False)
            }
            formatted_tokens.append(formatted_token)
        
        # 按价值排序（从高到低）
        formatted_tokens.sort(
            key=lambda x: float(x.get('value', '$0.00').replace('$', '').replace('M', '000000').replace('K', '000')),
            reverse=True
        )
        
        return {
            'tokens': formatted_tokens,
            'total_value': TokenService._format_value(str(total_value)),
            'token_count': len(tokens)
        }

class NFTService:
    """NFT 服务类"""
    
    MORALIS_API_KEY = settings.MORALIS_API_KEY
    
    CHAIN_MAPPING = {
        'ETH': 'eth',
        'BSC': 'bsc',
        'POLYGON': 'polygon',
        'ARBITRUM': 'arbitrum',
        'OPTIMISM': 'optimism',
        'AVALANCHE': 'avalanche',
        'BASE': 'base'
    }

    @staticmethod
    async def get_nft_collections(wallet: Wallet, force_refresh=False) -> List[Dict]:
        """获取钱包的 NFT 合集列表"""
        logger.info(f"Getting NFT collections for wallet {wallet.address} on chain {wallet.chain}")
        
        cache_key = f'nft_collections_{wallet.chain}_{wallet.address}'
        if not force_refresh:
            cached_data = cache.get(cache_key)
            if cached_data:
                logger.info("Returning cached NFT collections")
                return cached_data
            
        try:
            if wallet.chain == 'SOL':
                logger.info("Fetching Solana NFT collections")
                collections = await NFTService._get_solana_nft_collections(wallet)
            else:
                logger.info(f"Fetching {wallet.chain} NFT collections")
                collections = await NFTService._get_evm_nft_collections(wallet)
                
            # 缓存结果
            cache_config = APIConfig.get_cache_config()
            cache.set(cache_key, collections, cache_config['TIMEOUT'])
            logger.info(f"Found {len(collections)} NFT collections")
            return collections
                
        except Exception as e:
            logger.error(f"Error fetching NFT collections: {str(e)}")
            return []

    @staticmethod
    async def _get_solana_nft_collections(wallet: Wallet) -> List[Dict]:
        """获取 Solana NFT 合集"""
        try:
            url = f"https://solana-gateway.moralis.io/account/mainnet/{wallet.address}/nft"
            headers = {
                "accept": "application/json",
                "X-API-Key": NFTService.MORALIS_API_KEY
            }
            
            logger.info(f"Calling Moralis Solana NFT API: {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Error fetching Solana NFTs: {error_text}")
                        return []
                        
                    nfts = await response.json()
                    logger.info(f"Raw NFTs data: {json.dumps(nfts, indent=2)}")

                    # 按 symbol 分组
                    collections = {}
                    for nft in nfts:
                        try:
                            metadata = nft.get('metadata', {})
                            if isinstance(metadata, str):
                                try:
                                    metadata = json.loads(metadata)
                                except:
                                    metadata = {}
                            
                            symbol = nft.get('symbol', '')
                            if not symbol:
                                continue

                            # 根据 symbol 确定集合名称
                            collection_name = None
                            if symbol == 'DIGIKONG':
                                collection_name = 'DigiKong'
                            elif symbol == 'IM':
                                collection_name = 'Infected Mob'
                            elif symbol == 'RC':
                                collection_name = 'RadCats'
                            elif symbol == 'BB':
                                collection_name = 'BUSY BOAR'
                            elif symbol == 'FRTS':
                                collection_name = 'Froots'
                            elif symbol == 'SOR':
                                collection_name = 'Sorcie'
                            elif symbol == 'meerkazter':
                                collection_name = 'meerkazter Collection'
                            elif symbol == 'NFT':
                                collection_name = 'NFT Collection'
                            else:
                                # 尝试从 NFT 名称中提取集合名称
                                nft_name = nft.get('name', '')
                                if nft_name and '#' in nft_name:
                                    collection_name = nft_name.split('#')[0].strip()
                                else:
                                    collection_name = f'{symbol} Collection'
                            
                            if symbol not in collections:
                                collections[symbol] = {
                                    'name': collection_name,
                                    'symbol': symbol,
                                    'chain': 'SOL',
                                    'nft_count': 0,
                                    'image': metadata.get('image', ''),
                                    'collection_keys': set()  # 使用集合存储所有相关的 collection_key
                                }
                            
                            # 添加 collection_key 到集合中
                            collection_key = metadata.get('collection', {}).get('key') or nft.get('mint', '')
                            collections[symbol]['collection_keys'].add(collection_key)
                            collections[symbol]['nft_count'] += 1
                            
                        except Exception as e:
                            logger.error(f"Error processing NFT collection data: {str(e)}, nft: {nft}")
                            continue

                    # 转换结果为列表,并移除 collection_keys 集合
                    result = []
                    for collection in collections.values():
                        collection_keys = collection.pop('collection_keys')
                        # 使用第一个 collection_key 作为代表
                        collection['collection_key'] = next(iter(collection_keys)) if collection_keys else ''
                        result.append(collection)

                    return result
                    
        except Exception as e:
            logger.error(f"Error fetching Solana NFT collections: {str(e)}")
            return []

    @staticmethod
    async def _get_evm_nft_collections(wallet: Wallet) -> List[Dict]:
        """获取 EVM 链 NFT 合集"""
        try:
            chain = NFTService.CHAIN_MAPPING.get(wallet.chain)
            if not chain:
                logger.error(f"Unsupported chain: {wallet.chain}")
                return []

            params = {
                "address": wallet.address,
                "chain": chain,
                "format": "decimal",
                "limit": 100,
                "token_addresses": [],
                "cursor": "",
                "normalizeMetadata": True
            }

            logger.info(f"Calling Moralis EVM NFT API for chain {chain}")
            result = evm_api.nft.get_wallet_nfts(
                api_key=NFTService.MORALIS_API_KEY,
                params=params
            )

            logger.info(f"Got {len(result.get('result', []))} raw NFTs from Moralis")
            
            # 按合集分组
            collections = {}
            for nft in result.get('result', []):
                try:
                    contract = nft.get('token_address')
                    if not contract:
                        continue
                        
                    if contract not in collections:
                        collections[contract] = {
                            'name': nft.get('name', 'Unknown Collection'),
                            'symbol': nft.get('symbol', ''),
                            'chain': wallet.chain,
                            'nft_count': 0,
                            'contract': contract,
                            'image': nft.get('normalized_metadata', {}).get('image', '')
                        }
                    collections[contract]['nft_count'] += 1
                    
                except Exception as e:
                    logger.error(f"Error processing NFT collection data: {str(e)}, nft: {nft}")
                    continue

            return list(collections.values())
            
        except Exception as e:
            logger.error(f"Error fetching EVM NFT collections: {str(e)}")
            return []

    @staticmethod
    async def get_collection_nfts(wallet: Wallet, collection_id: str) -> List[Dict]:
        """获取合集内的 NFT 列表"""
        logger.info(f"Getting NFTs for collection {collection_id}")
        
        try:
            if wallet.chain == 'SOL':
                return await NFTService._get_solana_collection_nfts(wallet, collection_id)
            else:
                return await NFTService._get_evm_collection_nfts(wallet, collection_id)
                
        except Exception as e:
            logger.error(f"Error fetching collection NFTs: {str(e)}")
            return []

    @staticmethod
    async def _get_solana_collection_nfts(wallet: Wallet, collection_key: str) -> List[Dict]:
        """获取 Solana NFT 合集内的 NFT"""
        try:
            url = f"https://solana-gateway.moralis.io/account/mainnet/{wallet.address}/nft"
            headers = {
                "accept": "application/json",
                "X-API-Key": NFTService.MORALIS_API_KEY
            }
            
            logger.info(f"Fetching NFTs for collection {collection_key}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Error fetching Solana NFTs: {error_text}")
                        return []
                        
                    nfts = await response.json()
                    logger.info(f"Raw NFTs data: {json.dumps(nfts, indent=2)}")
                    collection_nfts = []

                    # 首先找到目标 NFT 的 symbol
                    target_symbol = None
                    for nft in nfts:
                        logger.info(f"Checking NFT: {json.dumps(nft, indent=2)}")
                        metadata = nft.get('metadata', {})
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                                logger.info(f"Parsed metadata: {json.dumps(metadata, indent=2)}")
                            except Exception as e:
                                logger.error(f"Error parsing metadata: {str(e)}")
                                metadata = {}
                                
                        nft_collection_key = metadata.get('collection', {}).get('key')
                        nft_mint = nft.get('mint', '')
                        
                        if nft_collection_key == collection_key or nft_mint == collection_key:
                            target_symbol = nft.get('symbol', '')
                            logger.info(f"Found target symbol: {target_symbol}")
                            break

                    if not target_symbol:
                        logger.error(f"Could not find target symbol for collection {collection_key}")
                        return []

                    # 然后收集所有具有相同 symbol 的 NFT
                    for nft in nfts:
                        try:
                            current_symbol = nft.get('symbol', '')
                            logger.info(f"Checking NFT with symbol: {current_symbol} against target symbol: {target_symbol}")
                            
                            if current_symbol != target_symbol:
                                continue

                            # 获取 metadata
                            metadata = nft.get('metadata', {})
                            if isinstance(metadata, str):
                                try:
                                    metadata = json.loads(metadata)
                                    logger.info(f"Processing NFT metadata: {json.dumps(metadata, indent=2)}")
                                except Exception as e:
                                    logger.error(f"Error parsing metadata: {str(e)}")
                                    metadata = {}

                            # 如果 metadata 为空,尝试从 uri 获取
                            if not metadata and nft.get('uri'):
                                try:
                                    uri = nft['uri']
                                    # 如果是 IPFS URI,转换为 HTTPS
                                    if uri.startswith('ipfs://'):
                                        uri = f'https://ipfs.io/ipfs/{uri[7:]}'
                                    # 如果是 Arweave URI,添加 https:
                                    elif uri.startswith('//arweave.net/'):
                                        uri = f'https:{uri}'
                                    # 如果是完整的 Arweave URI
                                    elif 'arweave.net' in uri and not uri.startswith('http'):
                                        uri = f'https://{uri}'
                                    
                                    logger.info(f"Fetching metadata from URI: {uri}")
                                    async with session.get(uri) as metadata_response:
                                        if metadata_response.status == 200:
                                            metadata = await metadata_response.json()
                                            logger.info(f"Fetched metadata from URI: {json.dumps(metadata, indent=2)}")
                                except Exception as e:
                                    logger.error(f"Error fetching metadata from URI: {str(e)}")

                            # 记录完整的 NFT 数据
                            logger.info(f"Full NFT data: {json.dumps(nft, indent=2)}")
                            logger.info(f"Full metadata: {json.dumps(metadata, indent=2)}")

                            # 处理图片 URL
                            image_url = ''
                            
                            # 1. 尝试从 metadata.image 获取
                            raw_image_url = metadata.get('image', '')
                            logger.info(f"Raw image URL from metadata.image: {raw_image_url}")
                            
                            # 2. 如果没有,尝试从 metadata.properties.files 获取
                            if not raw_image_url and metadata.get('properties', {}).get('files'):
                                files = metadata['properties']['files']
                                if isinstance(files, list) and len(files) > 0:
                                    first_file = files[0]
                                    if isinstance(first_file, dict):
                                        raw_image_url = first_file.get('uri', '')
                                    elif isinstance(first_file, str):
                                        raw_image_url = first_file
                                logger.info(f"Raw image URL from metadata.properties.files: {raw_image_url}")
                            
                            # 3. 如果还没有,尝试从 nft.image 获取
                            if not raw_image_url:
                                raw_image_url = nft.get('image', '')
                                logger.info(f"Raw image URL from nft.image: {raw_image_url}")
                            
                            # 4. 如果还没有,尝试从 metadata.uri 获取
                            if not raw_image_url:
                                raw_image_url = metadata.get('uri', '')
                                logger.info(f"Raw image URL from metadata.uri: {raw_image_url}")
                            
                            if raw_image_url:
                                image_url = raw_image_url
                                # 如果是 IPFS URL,转换为 HTTPS URL
                                if image_url.startswith('ipfs://'):
                                    ipfs_hash = image_url.replace('ipfs://', '')
                                    image_url = f'https://ipfs.io/ipfs/{ipfs_hash}'
                                    logger.info(f"Converted IPFS URL to: {image_url}")
                                # 如果是 Arweave URL,添加 https:
                                elif image_url.startswith('//arweave.net/'):
                                    image_url = f'https:{image_url}'
                                    logger.info(f"Converted Arweave URL to: {image_url}")
                                # 如果是完整的 Arweave URL
                                elif 'arweave.net' in image_url and not image_url.startswith('http'):
                                    image_url = f'https://{image_url}'
                                    logger.info(f"Added https:// to Arweave URL: {image_url}")
                                # 如果是相对 URL,添加 https://
                                elif not image_url.startswith('http'):
                                    image_url = f'https://{image_url}'
                                    logger.info(f"Added https:// to relative URL: {image_url}")
                                    
                            logger.info(f"Final image URL: {image_url}")
                                
                            nft_data = {
                                'name': nft.get('name', 'Unknown NFT'),
                                'symbol': nft.get('symbol', ''),
                                'mint': nft.get('mint', ''),
                                'chain': 'SOL',
                                'image': image_url,
                                'attributes': metadata.get('attributes', []),
                                'collection_key': metadata.get('collection', {}).get('key') or nft.get('mint', '')
                            }
                            collection_nfts.append(nft_data)
                            logger.info(f"Found matching NFT: {json.dumps(nft_data, indent=2)}")
                        except Exception as e:
                            logger.error(f"Error processing collection NFT: {str(e)}")
                            continue

                    logger.info(f"Found {len(collection_nfts)} NFTs in collection {collection_key}")
                    return collection_nfts
                    
        except Exception as e:
            logger.error(f"Error fetching Solana collection NFTs: {str(e)}")
            return []

    @staticmethod
    async def _get_evm_collection_nfts(wallet: Wallet, collection_key: str) -> List[Dict]:
        """获取 EVM NFT 合集内的 NFT"""
        try:
            chain = NFTService.CHAIN_MAPPING.get(wallet.chain)
            if not chain:
                return []

            params = {
                "address": wallet.address,
                "chain": chain,
                "format": "decimal",
                "token_addresses": [collection_key],
                "normalizeMetadata": True
            }

            logger.info(f"Fetching NFTs for collection {collection_key}")
            result = evm_api.nft.get_wallet_nfts(
                api_key=NFTService.MORALIS_API_KEY,
                params=params
            )

            logger.info(f"Raw NFTs data: {json.dumps(result, indent=2)}")
            collection_nfts = []

            for nft in result.get('result', []):
                try:
                    if nft.get('token_address', '').lower() != collection_key.lower():
                        continue

                    # 获取元数据
                    metadata = {}
                    token_uri = nft.get('token_uri', '')
                    logger.info(f"Token URI: {token_uri}")
                    
                    # 1. 首先尝试从 normalized_metadata 获取
                    if nft.get('normalized_metadata'):
                        metadata = nft['normalized_metadata']
                        logger.info(f"Using normalized metadata: {json.dumps(metadata, indent=2)}")
                    
                    # 2. 如果没有，尝试从 metadata 字段获取
                    elif nft.get('metadata'):
                        try:
                            if isinstance(nft['metadata'], str):
                                metadata = json.loads(nft['metadata'])
                            else:
                                metadata = nft['metadata']
                            logger.info(f"Using metadata field: {json.dumps(metadata, indent=2)}")
                        except:
                            metadata = {}
                    
                    # 3. 如果还没有，并且有 token_uri，尝试从 token_uri 获取
                    elif token_uri:
                        try:
                            # 处理 IPFS URI
                            if token_uri.startswith('ipfs://'):
                                token_uri = f'https://ipfs.io/ipfs/{token_uri[7:]}'
                            
                            async with aiohttp.ClientSession() as session:
                                async with session.get(token_uri) as response:
                                    if response.status == 200:
                                        metadata = await response.json()
                                        logger.info(f"Fetched metadata from token_uri: {json.dumps(metadata, indent=2)}")
                        except Exception as e:
                            logger.error(f"Error fetching metadata from token_uri: {str(e)}")
                            metadata = {}

                    # 处理图片 URL
                    image_url = ''
                    raw_image_url = metadata.get('image', '')
                    logger.info(f"Raw image URL: {raw_image_url}")
                    
                    if raw_image_url:
                        image_url = raw_image_url
                        # 如果是 IPFS URL，转换为 HTTPS URL
                        if image_url.startswith('ipfs://'):
                            ipfs_hash = image_url.replace('ipfs://', '')
                            image_url = f'https://ipfs.io/ipfs/{ipfs_hash}'
                            logger.info(f"Converted IPFS URL to: {image_url}")
                        # 如果是 Arweave URL，添加 https:
                        elif image_url.startswith('//arweave.net/'):
                            image_url = f'https:{image_url}'
                            logger.info(f"Converted Arweave URL to: {image_url}")
                        # 如果是完整的 Arweave URL
                        elif 'arweave.net' in image_url and not image_url.startswith('http'):
                            image_url = f'https://{image_url}'
                            logger.info(f"Added https:// to Arweave URL: {image_url}")
                        # 如果是相对 URL，添加 https://
                        elif not image_url.startswith('http'):
                            image_url = f'https://{image_url}'
                            logger.info(f"Added https:// to relative URL: {image_url}")
                            
                    logger.info(f"Final image URL: {image_url}")

                    nft_data = {
                        'name': metadata.get('name', nft.get('name', 'Unknown NFT')),
                        'symbol': nft.get('symbol', ''),
                        'mint': nft.get('token_id', ''),
                        'chain': 'EVM',
                        'image': image_url,
                        'attributes': metadata.get('attributes', []),
                        'collection_key': nft.get('token_address', ''),
                        'token_uri': token_uri
                    }
                    collection_nfts.append(nft_data)
                    logger.info(f"Found matching NFT: {json.dumps(nft_data, indent=2)}")
                except Exception as e:
                    logger.error(f"Error processing collection NFT: {str(e)}")
                    continue

            logger.info(f"Found {len(collection_nfts)} NFTs in collection {collection_key}")
            return collection_nfts
                    
        except Exception as e:
            logger.error(f"Error fetching EVM collection NFTs: {str(e)}")
            return []

    @staticmethod
    async def get_wallet_nft_summary(wallet: Wallet) -> Dict:
        """获取钱包 NFT 概要信息"""
        logger.info(f"Getting NFT summary for wallet {wallet.address}")
        collections = await NFTService.get_nft_collections(wallet)
        
        total_nfts = sum(collection.get('nft_count', 0) for collection in collections)
        
        return {
            'collections': collections,
            'total_collections': len(collections),
            'total_nfts': total_nfts
        }

    @staticmethod
    async def get_nft_detail(wallet: Wallet, collection_id: str, mint: str) -> Optional[Dict]:
        """获取单个 NFT 的详细信息"""
        logger.info(f"Getting NFT detail for mint {mint} in collection {collection_id}")
        
        try:
            if wallet.chain == 'SOL':
                url = f"https://solana-gateway.moralis.io/account/mainnet/{wallet.address}/nft"
                headers = {
                    "accept": "application/json",
                    "X-API-Key": NFTService.MORALIS_API_KEY
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"Error fetching Solana NFTs: {error_text}")
                            return None
                            
                        nfts = await response.json()
                        logger.info(f"Raw NFTs data: {json.dumps(nfts, indent=2)}")
                        
                        # 查找指定的 NFT
                        for nft in nfts:
                            try:
                                if nft.get('mint') != mint:
                                    continue
                                    
                                metadata = nft.get('metadata', {})
                                if isinstance(metadata, str):
                                    try:
                                        metadata = json.loads(metadata)
                                        logger.info(f"Processing NFT metadata: {json.dumps(metadata, indent=2)}")
                                    except:
                                        metadata = {}
                                
                                # 处理图片 URL
                                image_url = ''
                                
                                # 1. 尝试从 metadata.image 获取
                                raw_image_url = metadata.get('image', '')
                                logger.info(f"Raw image URL from metadata.image: {raw_image_url}")
                                
                                # 2. 如果没有，尝试从 metadata.properties.files 获取
                                if not raw_image_url and metadata.get('properties', {}).get('files'):
                                    files = metadata['properties']['files']
                                    if isinstance(files, list) and len(files) > 0:
                                        first_file = files[0]
                                        if isinstance(first_file, dict):
                                            raw_image_url = first_file.get('uri', '')
                                        elif isinstance(first_file, str):
                                            raw_image_url = first_file
                                    logger.info(f"Raw image URL from metadata.properties.files: {raw_image_url}")
                                
                                # 3. 如果还没有，尝试从 nft.image 获取
                                if not raw_image_url:
                                    raw_image_url = nft.get('image', '')
                                    logger.info(f"Raw image URL from nft.image: {raw_image_url}")
                                
                                # 4. 如果还没有，尝试从 metadata.uri 获取
                                if not raw_image_url:
                                    raw_image_url = metadata.get('uri', '')
                                    logger.info(f"Raw image URL from metadata.uri: {raw_image_url}")
                                
                                if raw_image_url:
                                    image_url = raw_image_url
                                    # 如果是 IPFS URL，转换为 HTTPS URL
                                    if image_url.startswith('ipfs://'):
                                        ipfs_hash = image_url.replace('ipfs://', '')
                                        image_url = f'https://ipfs.io/ipfs/{ipfs_hash}'
                                        logger.info(f"Converted IPFS URL to: {image_url}")
                                    # 如果是 Arweave URL，添加 https:
                                    elif image_url.startswith('//arweave.net/'):
                                        image_url = f'https:{image_url}'
                                        logger.info(f"Converted Arweave URL to: {image_url}")
                                    # 如果是完整的 Arweave URL
                                    elif 'arweave.net' in image_url and not image_url.startswith('http'):
                                        image_url = f'https://{image_url}'
                                        logger.info(f"Added https:// to Arweave URL: {image_url}")
                                    # 如果是相对 URL，添加 https://
                                    elif not image_url.startswith('http'):
                                        image_url = f'https://{image_url}'
                                        logger.info(f"Added https:// to relative URL: {image_url}")
                                        
                                logger.info(f"Final image URL: {image_url}")
                                
                                # 构建详细信息
                                nft_detail = {
                                    'name': nft.get('name', 'Unknown NFT'),
                                    'symbol': nft.get('symbol', ''),
                                    'mint': mint,
                                    'chain': 'SOL',
                                    'image': image_url,
                                    'description': metadata.get('description', ''),
                                    'attributes': metadata.get('attributes', []),
                                    'collection_key': metadata.get('collection', {}).get('key') or mint,
                                    'external_url': metadata.get('external_url', ''),
                                    'animation_url': metadata.get('animation_url', ''),
                                    'properties': metadata.get('properties', {}),
                                    'royalty': metadata.get('seller_fee_basis_points', 0) / 100,  # 转换为百分比
                                    'creators': metadata.get('properties', {}).get('creators', []),
                                    'token_standard': 'Metaplex NFT Standard',
                                    'associated_token_address': nft.get('associatedTokenAddress', ''),
                                    'owner': wallet.address
                                }
                                
                                logger.info(f"Found NFT detail: {json.dumps(nft_detail, indent=2)}")
                                return nft_detail
                                
                            except Exception as e:
                                logger.error(f"Error processing NFT detail: {str(e)}")
                                continue
                                
                        logger.error(f"NFT with mint {mint} not found")
                        return None
                        
            else:
                # EVM 链的 NFT 详情获取逻辑
                chain = NFTService.CHAIN_MAPPING.get(wallet.chain)
                if not chain:
                    return None

                params = {
                    "address": wallet.address,
                    "chain": chain,
                    "format": "decimal",
                    "token_addresses": [collection_id],
                    "normalizeMetadata": True
                }

                result = evm_api.nft.get_wallet_nfts(
                    api_key=NFTService.MORALIS_API_KEY,
                    params=params
                )

                for nft in result.get('result', []):
                    try:
                        if nft.get('token_id') != mint:  # 对于 EVM，使用 token_id 作为标识
                            continue
                            
                        # 获取元数据
                        metadata = {}
                        token_uri = nft.get('token_uri', '')
                        logger.info(f"Token URI: {token_uri}")
                        
                        # 1. 首先尝试从 normalized_metadata 获取
                        if nft.get('normalized_metadata'):
                            metadata = nft['normalized_metadata']
                            logger.info(f"Using normalized metadata: {json.dumps(metadata, indent=2)}")
                        
                        # 2. 如果没有，尝试从 metadata 字段获取
                        elif nft.get('metadata'):
                            try:
                                if isinstance(nft['metadata'], str):
                                    metadata = json.loads(nft['metadata'])
                                else:
                                    metadata = nft['metadata']
                                logger.info(f"Using metadata field: {json.dumps(metadata, indent=2)}")
                            except:
                                metadata = {}
                        
                        # 3. 如果还没有，并且有 token_uri，尝试从 token_uri 获取
                        elif token_uri:
                            try:
                                # 处理 IPFS URI
                                if token_uri.startswith('ipfs://'):
                                    token_uri = f'https://ipfs.io/ipfs/{token_uri[7:]}'
                                
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(token_uri) as response:
                                        if response.status == 200:
                                            metadata = await response.json()
                                            logger.info(f"Fetched metadata from token_uri: {json.dumps(metadata, indent=2)}")
                            except Exception as e:
                                logger.error(f"Error fetching metadata from token_uri: {str(e)}")
                            metadata = {}
                        
                        # 处理图片 URL
                        image_url = ''
                        raw_image_url = metadata.get('image', '')
                        logger.info(f"Raw image URL: {raw_image_url}")
                        
                        if raw_image_url:
                            image_url = raw_image_url
                            # 如果是 IPFS URL，转换为 HTTPS URL
                            if image_url.startswith('ipfs://'):
                                ipfs_hash = image_url.replace('ipfs://', '')
                                image_url = f'https://ipfs.io/ipfs/{ipfs_hash}'
                                logger.info(f"Converted IPFS URL to: {image_url}")
                            # 如果是 Arweave URL，添加 https:
                            elif image_url.startswith('//arweave.net/'):
                                image_url = f'https:{image_url}'
                                logger.info(f"Converted Arweave URL to: {image_url}")
                            # 如果是完整的 Arweave URL
                            elif 'arweave.net' in image_url and not image_url.startswith('http'):
                                image_url = f'https://{image_url}'
                                logger.info(f"Added https:// to Arweave URL: {image_url}")
                            # 如果是相对 URL，添加 https://
                            elif not image_url.startswith('http'):
                                image_url = f'https://{image_url}'
                                logger.info(f"Added https:// to relative URL: {image_url}")
                                
                        logger.info(f"Final image URL: {image_url}")
                        
                        nft_detail = {
                            'name': metadata.get('name', nft.get('name', 'Unknown NFT')),
                            'symbol': nft.get('symbol', ''),
                            'token_id': mint,
                            'contract': collection_id,
                            'chain': wallet.chain,
                            'image': image_url,
                            'description': metadata.get('description', ''),
                            'attributes': metadata.get('attributes', []),
                            'external_url': metadata.get('external_url', ''),
                            'animation_url': metadata.get('animation_url', ''),
                            'properties': metadata.get('properties', {}),
                            'token_standard': nft.get('contract_type', 'ERC721'),
                            'owner': wallet.address,
                            'token_uri': token_uri
                        }
                        
                        logger.info(f"Found NFT detail: {json.dumps(nft_detail, indent=2)}")
                        return nft_detail
                        
                    except Exception as e:
                        logger.error(f"Error processing NFT detail: {str(e)}")
                        continue
                        
                logger.error(f"NFT with token_id {mint} not found")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching NFT detail: {str(e)}")
            return None 