"""Solana 代币兑换服务"""
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, List
import asyncio
import aiohttp
from django.utils import timezone
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.transaction import Transaction
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.rpc.types import TxOpts
from spl.token.instructions import create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
import base58
import json
import base64
import ssl

from ...services.solana_config import MoralisConfig, RPCConfig
from ...exceptions import SwapError, InsufficientBalanceError
from .price import SolanaPriceService

logger = logging.getLogger(__name__)

class SolanaSwapService:
    """Solana 代币兑换服务"""
    
    async def get_supported_tokens(self) -> List[Dict[str, Any]]:
        """获取支持的代币列表

        Returns:
            List[Dict[str, Any]]: 支持的代币列表
        """
        last_error = None
        session = None
        
        for retry in range(self.max_retries):
            try:
                if session is None or session.closed:
                    session = await self._get_session()
                
                # 从Jupiter API获取代币列表
                token_url = self.jup_api_urls[2]  # 使用代币API端点
                logger.debug(f"正在从 {token_url} 获取代币列表 (第 {retry + 1} 次尝试)")
                
                # 添加请求参数和额外的头部信息
                headers = {
                    **self.headers,
                    'Origin': 'https://jup.ag',
                    'Referer': 'https://jup.ag/'
                }
                
                async with session.get(token_url, headers=headers, timeout=self.timeout) as response:
                    response_text = await response.text()
                    logger.debug(f"API响应状态码: {response.status}")
                    logger.debug(f"API响应头: {response.headers}")
                    logger.debug(f"API响应内容: {response_text[:200]}...")  # 记录响应内容的前200个字符
                    
                    if response.status == 200:
                        try:
                            tokens_data = json.loads(response_text)
                            logger.debug(f"解析到的代币数据类型: {type(tokens_data)}")
                            
                            # 处理代币数据
                            supported_tokens = []
                            
                            # 根据响应格式处理数据
                            if isinstance(tokens_data, dict):
                                # 新版API格式
                                for token_address, token_data in tokens_data.items():
                                    try:
                                        if isinstance(token_data, dict):
                                            token_info = {
                                                'address': token_address,
                                                'symbol': token_data.get('symbol'),
                                                'name': token_data.get('name'),
                                                'decimals': token_data.get('decimals'),
                                                'logo': token_data.get('logoURI'),
                                                'tags': token_data.get('tags', [])
                                            }
                                            if all([token_info['address'], token_info['symbol'], token_info['name']]):
                                                supported_tokens.append(token_info)
                                    except Exception as e:
                                        logger.warning(f"处理代币 {token_address} 时出错: {str(e)}")
                                        continue
                            elif isinstance(tokens_data, list):
                                # 旧版API格式
                                for token in tokens_data:
                                    try:
                                        if isinstance(token, dict):
                                            token_info = {
                                                'address': token.get('address'),
                                                'symbol': token.get('symbol'),
                                                'name': token.get('name'),
                                                'decimals': token.get('decimals'),
                                                'logo': token.get('logoURI'),
                                                'tags': token.get('tags', [])
                                            }
                                            if all([token_info['address'], token_info['symbol'], token_info['name']]):
                                                supported_tokens.append(token_info)
                                    except Exception as e:
                                        logger.warning(f"处理代币数据时出错: {str(e)}")
                                        continue
                            else:
                                raise SwapError(f"未知的代币数据格式: {type(tokens_data)}")
                            
                            # 确保SOL代币在列表中且在第一位
                            if not any(token['address'] == self.sol_token_info['address'] for token in supported_tokens):
                                supported_tokens.insert(0, self.sol_token_info)
                            
                            logger.debug(f"成功获取到 {len(supported_tokens)} 个代币")
                            if len(supported_tokens) == 0:
                                logger.error("没有找到任何有效的代币数据")
                                raise SwapError("没有找到任何有效的代币数据")
                                
                            return supported_tokens
                            
                        except json.JSONDecodeError as e:
                            error_msg = f"解析代币数据失败: {str(e)}"
                            logger.error(f"{error_msg}, 响应内容: {response_text[:200]}...")
                            last_error = error_msg
                    else:
                        error_msg = f"获取代币列表失败: HTTP {response.status}"
                        logger.error(f"{error_msg}, 响应内容: {response_text}")
                        last_error = error_msg
                
                # 如果到达这里，说明需要重试
                retry_wait = self.retry_delay * (retry + 1)  # 使用指数退避
                logger.warning(f"获取代币列表失败，{retry_wait}秒后重试...")
                await asyncio.sleep(retry_wait)
                
            except aiohttp.ClientError as e:
                error_msg = f"请求代币列表失败: {str(e)}"
                logger.error(error_msg)
                last_error = error_msg
                if retry < self.max_retries - 1:
                    retry_wait = self.retry_delay * (retry + 1)
                    await asyncio.sleep(retry_wait)
            except Exception as e:
                error_msg = f"获取代币列表时发生错误: {str(e)}"
                logger.error(f"{error_msg}, 错误类型: {type(e)}")
                last_error = error_msg
                if retry < self.max_retries - 1:
                    retry_wait = self.retry_delay * (retry + 1)
                    await asyncio.sleep(retry_wait)
            finally:
                if session and not session.closed:
                    await session.close()
                    session = None
        
        # 如果所有重试都失败了
        raise SwapError(f"获取代币列表失败，已重试{self.max_retries}次。最后的错误: {last_error}")

    def get_tokens(self) -> List[Dict[str, Any]]:
        """获取支持的代币列表（同步方法）

        Returns:
            List[Dict[str, Any]]: 支持的代币列表
        """
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 调用异步方法获取代币列表
            tokens = loop.run_until_complete(self.get_supported_tokens())
            return tokens
            
        except Exception as e:
            logger.error(f"获取代币列表失败: {str(e)}")
            raise SwapError(f"获取代币列表失败: {str(e)}")
            
        finally:
            loop.close()

    def get_quote(self, wallet_id: str, device_id: str, from_token: str, to_token: str, amount: str, slippage: Optional[str] = None) -> Dict[str, Any]:
        """获取兑换报价

        Args:
            wallet_id: 钱包ID
            device_id: 设备ID
            from_token: 支付代币地址
            to_token: 接收代币地址
            amount: 兑换数量
            slippage: 滑点容忍度（可选）

        Returns:
            Dict[str, Any]: 报价信息
        """
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 转换数量为 Decimal
            amount_decimal = Decimal(amount)
            
            # 转换滑点为 Decimal（如果提供）
            slippage_decimal = Decimal(slippage) if slippage else None
            
            # 调用异步方法获取报价
            quote = loop.run_until_complete(
                self.get_swap_quote(
                    from_token=from_token,
                    to_token=to_token,
                    amount=amount_decimal,
                    slippage=slippage_decimal
                )
            )
            
            return quote
            
        except Exception as e:
            logger.error(f"获取兑换报价失败: {str(e)}")
            raise SwapError(f"获取兑换报价失败: {str(e)}")
            
        finally:
            loop.close()
    
    def __init__(self):
        """初始化 Solana 代币兑换服务"""
        self.session = None
        # 更新 API 端点列表
        self.jup_api_urls = [
            "https://quote-api.jup.ag/v6",  # 报价API
            "https://public-api.birdeye.so/public",  # Birdeye API
            "https://token.jup.ag/strict"    # 使用 strict 端点替代 all 端点
        ]
        self.current_api_url_index = 0
        
        # SOL 代币信息
        self.sol_token_info = {
            'address': 'So11111111111111111111111111111111111111112',
            'name': 'Solana',
            'symbol': 'SOL',
            'decimals': 9,
            'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
        }
        
        # 设置 aiohttp 会话配置
        self.timeout = aiohttp.ClientTimeout(
            total=60,     # 总超时时间
            connect=20,   # 连接超时时间
            sock_connect=20,
            sock_read=30  # 读取超时时间
        )
        
        # 请求头
        self.headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        # 重试配置
        self.max_retries = 5
        self.retry_delay = 2
        
        # 初始化价格服务
        self.price_service = SolanaPriceService()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self.session is None or self.session.closed:
            # 配置代理
            connector = aiohttp.TCPConnector(
                ssl=False,  # 禁用SSL验证
                force_close=True,
                enable_cleanup_closed=True,
                use_dns_cache=False  # 禁用DNS缓存
            )
            
            # 创建会话时添加代理支持
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers,
                connector=connector,
                trust_env=True  # 允许从环境变量读取代理设置
            )
        return self.session
    
    async def _get_next_api_url(self) -> str:
        """获取下一个可用的 API URL"""
        self.current_api_url_index = (self.current_api_url_index + 1) % len(self.jup_api_urls)
        return self.jup_api_urls[self.current_api_url_index]
    
    async def get_swap_quote(self, 
        from_token: str,
        to_token: str,
        amount: Decimal,
        slippage: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """获取兑换报价
        
        Args:
            from_token: 支付代币地址
            to_token: 接收代币地址
            amount: 兑换数量
            slippage: 滑点容忍度
            
        Returns:
            Dict[str, Any]: 兑换报价信息
        """
        # 首先获取代币精度信息
        from_decimals = 9  # 默认使用 SOL 的精度
        
        try:
            # 常见代币精度映射
            token_decimals_map = {
                'So11111111111111111111111111111111111111112': 9,  # SOL
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 6,  # USDC
                'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 5,  # Bonk
            }
            
            # 首先检查是否是常见代币
            if from_token in token_decimals_map:
                from_decimals = token_decimals_map[from_token]
                logger.debug(f"从常见代币映射中获取代币 {from_token} 的精度: {from_decimals}")
            else:
                # 尝试从代币列表获取精度
                tokens_session = await self._get_session()
                try:
                    tokens = await self.get_supported_tokens()
                    
                    # 查找源代币的精度
                    for token in tokens:
                        if token.get('address') == from_token:
                            from_decimals = token.get('decimals')
                            logger.debug(f"找到源代币 {from_token} 的精度: {from_decimals}")
                            break
                finally:
                    # 确保关闭tokens_session
                    if tokens_session and not tokens_session.closed:
                        await tokens_session.close()
        except Exception as e:
            logger.error(f"获取代币精度时出错: {str(e)}")
            # 继续使用默认精度
        
        # 根据代币精度正确转换金额
        amount_in_smallest_unit = int(amount * Decimal(f'1{"0" * from_decimals}'))
        
        logger.debug(f"代币 {from_token} 精度: {from_decimals}, 原始金额: {amount}, 转换后金额: {amount_in_smallest_unit}")
        
        last_error = None
        # 遍历所有 API 端点
        for api_url in self.jup_api_urls:
            for retry in range(self.max_retries):
                session = None
                try:
                    session = await self._get_session()
                    
                    # 构建请求参数
                    params = {
                        'inputMint': from_token,
                        'outputMint': to_token,
                        'amount': str(amount_in_smallest_unit),
                        'slippageBps': str(int(slippage * 100)) if slippage else '50'
                    }
                    
                    logger.debug(f"请求参数: {params}")
                    
                    # 发送请求获取报价
                    url = f"{api_url}/quote"
                    logger.debug(f"请求URL: {url}")
                    
                    async with session.get(url, params=params) as response:
                        response_text = await response.text()
                        logger.debug(f"Jupiter API响应: {response_text}")
                        
                        if response.status == 200:
                            quote_data = await response.json()
                            logger.debug(f"报价数据: {quote_data}")
                            
                            # 格式化报价数据
                            formatted_quote = {
                                'from_token': {
                                    'address': from_token,
                                    'amount': quote_data.get('inAmount')
                                },
                                'to_token': {
                                    'address': to_token,
                                    'amount': quote_data.get('outAmount')
                                },
                                'price_impact': quote_data.get('priceImpactPct'),
                                'minimum_received': quote_data.get('otherAmountThreshold'),
                                'route': quote_data.get('routePlan'),
                                'quote_id': json.dumps(quote_data),  # 将整个报价数据作为quote_id
                                'exchange': 'Jupiter'
                            }
                            
                            return formatted_quote
                        else:
                            error_msg = f"API端点 {api_url} 返回错误状态码: {response.status}"
                            logger.warning(error_msg)
                            last_error = error_msg
                            continue
                            
                except aiohttp.ClientError as e:
                    error_msg = f"请求API端点 {api_url} 失败: {str(e)}"
                    logger.warning(error_msg)
                    last_error = error_msg
                    if retry < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay * (retry + 1))
                    continue
                except Exception as e:
                    error_msg = f"请求API端点 {api_url} 时发生错误: {str(e)}"
                    logger.warning(error_msg)
                    last_error = error_msg
                    continue
                finally:
                    if session and not session.closed:
                        await session.close()
        
        # 如果所有 API 端点都失败了，抛出最后一个错误
        raise SwapError(f"所有 API 端点都失败了。最后的错误: {last_error}")
    
    async def execute_swap(self,
        quote_id: str,
        from_token: str,
        to_token: str,
        amount: Decimal,
        from_address: str,
        private_key: str,
        slippage: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """执行代币兑换
        
        Args:
            quote_id: 报价ID
            from_token: 支付代币地址
            to_token: 接收代币地址
            amount: 兑换数量
            from_address: 发送方地址
            private_key: 私钥
            slippage: 滑点容忍度
            
        Returns:
            Dict[str, Any]: 交易结果
        """
        # 首先获取代币精度信息
        from_decimals = 9  # 默认使用 SOL 的精度
        
        try:
            # 常见代币精度映射
            token_decimals_map = {
                'So11111111111111111111111111111111111111112': 9,  # SOL
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 6,  # USDC
                'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 5,  # Bonk
            }
            
            # 首先检查是否是常见代币
            if from_token in token_decimals_map:
                from_decimals = token_decimals_map[from_token]
                logger.debug(f"从常见代币映射中获取代币 {from_token} 的精度: {from_decimals}")
            else:
                # 尝试从代币列表获取精度
                tokens_session = await self._get_session()
                try:
                    tokens = await self.get_supported_tokens()
                    
                    # 查找源代币的精度
                    for token in tokens:
                        if token.get('address') == from_token:
                            from_decimals = token.get('decimals')
                            logger.debug(f"找到源代币 {from_token} 的精度: {from_decimals}")
                            break
                finally:
                    # 确保关闭tokens_session
                    if tokens_session and not tokens_session.closed:
                        await tokens_session.close()
        except Exception as e:
            logger.error(f"获取代币精度时出错: {str(e)}")
            # 继续使用默认精度
        
        # 根据代币精度正确转换金额
        amount_in_smallest_unit = int(amount * Decimal(f'1{"0" * from_decimals}'))
        
        logger.debug(f"执行兑换 - 代币 {from_token} 精度: {from_decimals}, 原始金额: {amount}, 转换后金额: {amount_in_smallest_unit}")
        
        try:
            # 解析报价数据
            try:
                quote_data = json.loads(quote_id)
            except json.JSONDecodeError:
                raise SwapError("无效的报价ID")
                
            # 获取 API URL
            api_url = await self._get_next_api_url()
            session = await self._get_session()
            
            # 检查接收方代币账户是否存在，如果不存在则创建
            to_token_account = await self._get_associated_token_address(from_address, to_token)
            to_token_account_exists = await self._check_token_account_exists(to_token_account)
            
            # 构建交易请求
            swap_request = {
                'quoteResponse': quote_data,
                'userPublicKey': from_address,
                'wrapUnwrapSOL': True,
                'feeAccount': None,
                'computeUnitPriceMicroLamports': 1000,  # 设置计算单元价格
                'asLegacyTransaction': False,  # 使用新版交易格式
            }
            
            if not to_token_account_exists:
                swap_request['destinationTokenAccount'] = to_token_account
                
            # 发送交易请求
            url = f"{api_url}/swap"
            logger.debug(f"交易请求URL: {url}")
            logger.debug(f"交易请求数据: {swap_request}")
            
            async with session.post(url, json=swap_request) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"交易请求失败: {error_text}")
                    raise SwapError(f"交易请求失败: {error_text}")
                    
                swap_response = await response.json()
                logger.debug(f"交易响应: {swap_response}")
                
                # 获取交易数据
                swap_transaction = swap_response.get('swapTransaction')
                if not swap_transaction:
                    raise SwapError("交易响应中缺少交易数据")
                    
                # 解码交易
                try:
                    # 解码 base64 编码的交易
                    transaction_bytes = base64.b64decode(swap_transaction)
                    
                    # 创建交易对象
                    transaction = Transaction.deserialize(transaction_bytes)
                    
                    # 使用私钥签名交易
                    private_key_bytes = base58.b58decode(private_key)
                    keypair = Keypair.from_secret_key(private_key_bytes)
                    transaction.sign([keypair])
                    
                    # 序列化签名后的交易
                    signed_transaction = transaction.serialize()
                    
                    # 发送交易到 Solana 网络
                    solana_client = AsyncClient("https://api.mainnet-beta.solana.com")
                    signature = await solana_client.send_raw_transaction(signed_transaction)
                    
                    logger.info(f"交易已发送，签名: {signature}")
                    
                    # 返回交易结果
                    return {
                        'status': 'success',
                        'signature': signature,
                        'from_token': from_token,
                        'to_token': to_token,
                        'amount': str(amount)
                    }
                    
                except Exception as e:
                    logger.error(f"处理交易时出错: {str(e)}")
                    raise SwapError(f"处理交易时出错: {str(e)}")
                    
        except Exception as e:
            logger.error(f"执行兑换失败: {str(e)}")
            raise SwapError(f"执行兑换失败: {str(e)}")

    async def _get_associated_token_address(self, wallet_address: str, token_address: str) -> str:
        """获取关联代币账户地址"""
        try:
            wallet_pubkey = PublicKey(wallet_address)
            token_pubkey = PublicKey(token_address)
            
            # 使用 find_program_address 查找关联代币账户地址
            seeds = [
                bytes(wallet_pubkey),
                bytes(TOKEN_PROGRAM_ID),
                bytes(token_pubkey)
            ]
            ata, _ = PublicKey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
            return str(ata)
        except Exception as e:
            logger.error(f"获取关联代币账户失败: {str(e)}")
            raise SwapError("无法获取关联代币账户")

    async def _check_token_account_exists(self, account_address: str) -> bool:
        """检查代币账户是否存在"""
        try:
            logger.debug(f"检查账户 {account_address} 是否存在")
            client = AsyncClient(RPCConfig.SOLANA_MAINNET_RPC_URL)
            response = await client.get_account_info(account_address)
            
            if response and isinstance(response, dict):
                value = response.get('result', {}).get('value')
                exists = value is not None and len(value) > 0
                logger.debug(f"账户 {account_address} 存在: {exists}")
                return exists
            return False
        except Exception as e:
            error_msg = f"检查代币账户失败: {str(e)}"
            if hasattr(e, '__class__'):
                error_msg += f" ({e.__class__.__name__})"
            logger.error(error_msg)
            return False

    async def get_token_prices_async(self, token_addresses: List[str]) -> Dict[str, Any]:
        """获取代币价格信息（异步方法）

        Args:
            token_addresses: 代币地址列表

        Returns:
            Dict[str, Any]: 代币价格信息
        """
        try:
            session = await self._get_session()
            formatted_prices = {}
            
            for token_address in token_addresses:
                try:
                    # 使用代币详情接口获取价格
                    url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/price"
                    logger.debug(f"正在从 {url} 获取代币 {token_address} 的价格")
                    
                    async with session.get(url, headers={"X-API-Key": MoralisConfig.API_KEY}) as response:
                        if response.status == 200:
                            price_data = await response.json()
                            if price_data and 'usdPrice' in price_data:
                                formatted_prices[token_address] = {
                                    'price': float(price_data['usdPrice']),
                                    'price_change_24h': 0,  # Moralis API 不提供这些数据
                                    'volume_24h': 0,
                                    'market_cap': 0,
                                    'total_supply': 0,
                                    'vs_token': 'USD'
                                }
                        else:
                            logger.error(f"获取代币 {token_address} 价格失败: HTTP {response.status}")
                            try:
                                error_data = await response.text()
                                logger.error(f"错误响应: {error_data}")
                            except:
                                pass
                except Exception as e:
                    logger.error(f"获取代币 {token_address} 价格时发生错误: {str(e)}")
                    continue
                
                await asyncio.sleep(0.2)  # 添加短暂延迟，避免请求过于频繁
            
            if formatted_prices:
                return formatted_prices
            
            raise SwapError("未能获取任何代币的价格信息")
            
        except Exception as e:
            logger.error(f"获取代币价格失败: {str(e)}")
            raise SwapError(f"获取代币价格失败: {str(e)}")
        finally:
            if session and not session.closed:
                await session.close()

    def get_token_prices(self, token_addresses: List[str]) -> Dict[str, Any]:
        """获取代币价格信息（同步方法）

        Args:
            token_addresses: 代币地址列表

        Returns:
            Dict[str, Any]: 代币价格信息
        """
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 调用异步方法获取价格
            prices = loop.run_until_complete(self.get_token_prices_async(token_addresses))
            return prices
            
        except Exception as e:
            logger.error(f"获取代币价格失败: {str(e)}")
            raise SwapError(f"获取代币价格失败: {str(e)}")
            
        finally:
            loop.close()

    async def get_transaction_status(self, signature: str) -> Dict[str, Any]:
        """获取交易状态
        
        Args:
            signature: 交易签名
            
        Returns:
            Dict[str, Any]: 交易状态信息
        """
        try:
            client = AsyncClient(
                endpoint=RPCConfig.SOLANA_MAINNET_RPC_URL,
                commitment=Commitment("confirmed")
            )
            
            # 获取交易信息
            tx_info = await client.get_transaction(
                signature,
                commitment=Commitment("confirmed")
            )
            
            if not tx_info or not isinstance(tx_info, dict):
                raise SwapError("无法获取交易信息")
                
            tx_result = tx_info.get('result', {})
            if not tx_result:
                raise SwapError("交易信息为空")
                
            meta = tx_result.get('meta', {})
            if meta.get('err') is not None:
                error_msg = meta.get('err')
                # 处理常见错误
                if isinstance(error_msg, dict):
                    if 'InstructionError' in error_msg:
                        instruction_idx, error_detail = error_msg['InstructionError']
                        if isinstance(error_detail, dict):
                            if error_detail.get('Custom') == 1:
                                raise SwapError("交易失败: 滑点过大或流动性不足")
                            elif error_detail.get('Custom') == 6000:
                                raise SwapError("交易失败: 余额不足")
                            else:
                                raise SwapError(f"交易失败: 指令错误 (指令 {instruction_idx}, 错误码 {error_detail})")
                raise SwapError(f"交易失败: {error_msg}")
                
            # 获取交易状态
            status = {
                'status': 'confirmed',
                'slot': tx_result.get('slot', 0),
                'timestamp': tx_result.get('blockTime', 0),
                'fee': meta.get('fee', 0),
                'logs': meta.get('logMessages', []),
                'confirmations': tx_result.get('confirmations', 0)
            }
            
            return status
            
        except SwapError as e:
            raise
        except Exception as e:
            logger.error(f"获取交易状态失败: {str(e)}")
            raise SwapError(f"获取交易状态失败: {str(e)}")
            
    def get_transaction_status_sync(self, signature: str) -> Dict[str, Any]:
        """获取交易状态（同步方法）
        
        Args:
            signature: 交易签名
            
        Returns:
            Dict[str, Any]: 交易状态信息
        """
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 调用异步方法
            return loop.run_until_complete(
                self.get_transaction_status(signature)
            )
        finally:
            loop.close()

    def estimate_fees(self, from_token: str, to_token: str, amount: str, wallet_address: str) -> Dict[str, Any]:
        """估算交易费用
        
        Args:
            from_token: 支付代币地址
            to_token: 接收代币地址
            amount: 兑换数量
            wallet_address: 钱包地址
            
        Returns:
            Dict[str, Any]: 费用信息
        """
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 调用异步方法
            return loop.run_until_complete(
                self._estimate_fees_async(
                    from_token=from_token,
                    to_token=to_token,
                    amount=amount,
                    wallet_address=wallet_address
                )
            )
        finally:
            loop.close()
            
    async def _estimate_fees_async(self, from_token: str, to_token: str, amount: str, wallet_address: str) -> Dict[str, Any]:
        """估算交易费用（异步方法）"""
        try:
            # 检查目标代币的关联账户是否存在
            to_token_account = await self._get_associated_token_address(wallet_address, to_token)
            account_exists = await self._check_token_account_exists(to_token_account)
            
            # 基础交易费用（lamports）
            base_fee = 5000
            
            # 如果需要创建关联账户，添加额外费用
            create_ata_fee = 0
            if not account_exists and to_token != 'So11111111111111111111111111111111111111112':
                create_ata_fee = 2039280  # 创建关联账户的费用（约0.002039 SOL）
            
            # 计算总费用
            total_fee = base_fee + create_ata_fee
            
            # 获取 SOL 当前价格
            sol_price = 0
            try:
                session = await self._get_session()
                url = f"{self.jup_api_urls[1]}/token_price?address=So11111111111111111111111111111111111111112"
                async with session.get(url, headers={"X-API-KEY": "f5a3c6b3-6c64-4452-a1a9-b8f707b3e98e"}) as response:
                    if response.status == 200:
                        price_data = await response.json()
                        if price_data and isinstance(price_data, dict):
                            sol_price = float(price_data.get('value', 0))
            except Exception as e:
                logger.warning(f"获取SOL价格失败: {str(e)}")
            
            # 计算美元价格
            usd_fee = (total_fee / 1e9) * sol_price if sol_price > 0 else 0
            
            return {
                'total_fee': total_fee,  # 总费用（lamports）
                'base_fee': base_fee,    # 基础费用（lamports）
                'create_ata_fee': create_ata_fee,  # 创建账户费用（如果需要）（lamports）
                'total_fee_sol': total_fee / 1e9,  # 总费用（SOL）
                'total_fee_usd': usd_fee,  # 总费用（USD）
                'needs_ata_creation': not account_exists and to_token != 'So11111111111111111111111111111111111111112'
            }
            
        except Exception as e:
            logger.error(f"估算交易费用失败: {str(e)}")
            raise SwapError(f"估算交易费用失败: {str(e)}")