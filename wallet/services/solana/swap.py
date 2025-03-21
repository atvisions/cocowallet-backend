"""Solana 代币兑换服务"""
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, List
import asyncio
import aiohttp
from django.utils import timezone
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solders.transaction import Transaction as SoldersTransaction
from solders.keypair import Keypair as SoldersKeypair
from solders.pubkey import Pubkey
from solana.rpc.types import TxOpts
from solana.transaction import Transaction
from solana.keypair import Keypair
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
import base58
import json
import base64
import ssl
import time

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
        self.max_retries = 3
        self.retry_delay = 1
        
        # 初始化价格服务
        self.price_service = SolanaPriceService()
        
        # Alchemy RPC 客户端
        self.rpc_client = AsyncClient(RPCConfig.SOLANA_MAINNET_RPC_URL)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(
                ssl=False,
                force_close=True
            )
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers,
                connector=connector
            )
        return self.session
    
    async def _get_next_api_url(self) -> str:
        """获取下一个可用的 API URL"""
        self.current_api_url_index = (self.current_api_url_index + 1) % len(self.jup_api_urls)
        return self.jup_api_urls[self.current_api_url_index]
    
    async def _get_token_decimals(self, token_address: str) -> int:
        """获取代币精度
        
        Args:
            token_address: 代币地址
            
        Returns:
            int: 代币精度
        """
        try:
            # 如果是 SOL
            if token_address == "So11111111111111111111111111111111111111112":
                return 9
                
            # 从 Jupiter API 获取代币信息
            session = await self._get_session()
            url = f"{self.jup_api_urls[2]}/{token_address}"
            
            async with session.get(url) as response:
                if response.status == 200:
                    token_data = await response.json()
                    if isinstance(token_data, dict) and 'decimals' in token_data:
                        return int(token_data['decimals'])
                        
                logger.error(f"获取代币信息失败: HTTP {response.status}")
                response_text = await response.text()
                logger.error(f"响应内容: {response_text}")
                
            # 如果获取失败，尝试从 RPC 获取
            token_account_info = await self.rpc_client.get_token_supply(token_address)
            if token_account_info and 'result' in token_account_info:
                return int(token_account_info['result']['value']['decimals'])
                
            raise SwapError(f"无法获取代币 {token_address} 的精度信息")
            
        except Exception as e:
            logger.error(f"获取代币精度失败: {str(e)}")
            raise SwapError(f"获取代币精度失败: {str(e)}")

    async def get_swap_quote(self, 
        from_token: str,
        to_token: str,
        amount: Decimal,
        slippage: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """获取兑换报价"""
        last_error = None
        session = None
        
        logger.info("==================== 开始获取兑换报价 ====================")
        logger.info(f"交易信息: {from_token} -> {to_token}, 金额: {amount}, 滑点: {slippage}")
        
        for retry in range(self.max_retries):
            try:
                logger.info(f"第 {retry + 1} 次尝试获取报价")
                session = await self._get_session()
                
                # 获取代币精度并转换金额
                try:
                    # 将输入的字符串转换为 Decimal，确保精确计算
                    amount_decimal = Decimal(str(amount))
                    
                    if from_token == "So11111111111111111111111111111111111111112":
                        # SOL 的精度是 9，将 SOL 转换为 lamports
                        decimals = 9
                        amount_in_lamports = int(amount_decimal * Decimal('1000000000'))
                        amount_str = str(amount_in_lamports)
                        logger.info(f"SOL 金额转换: {amount_decimal} SOL = {amount_str} lamports")
                    else:
                        # 获取其他代币的精度
                        decimals = await self._get_token_decimals(from_token)
                        amount_in_units = int(amount_decimal * Decimal(10) ** decimals)
                        amount_str = str(amount_in_units)
                        logger.info(f"代币金额转换: {amount_decimal} -> {amount_str} (精度: {decimals})")
                    
                    logger.info(f"金额转换详情: {{\n" +
                              f"  原始金额: {amount_decimal},\n" +
                              f"  代币类型: {'SOL' if from_token == 'So11111111111111111111111111111111111111112' else 'Other'},\n" +
                              f"  精度: {decimals},\n" +
                              f"  转换后金额: {amount_str}\n" +
                              f"}}")
                    
                except Exception as e:
                    logger.error(f"金额转换错误: {{\n" +
                               f"  错误: {str(e)},\n" +
                               f"  原始金额: {amount},\n" +
                               f"  金额类型: {type(amount)}\n" +
                               f"}}")
                    raise SwapError(f"金额转换失败: {str(e)}")
                
                # 构建请求参数
                params = {
                    'inputMint': from_token,
                    'outputMint': to_token,
                    'amount': amount_str,
                    'slippageBps': str(int(slippage * 100)) if slippage else '50',
                    'onlyDirectRoutes': 'false',
                    'asLegacyTransaction': 'true',
                    'platformFeeBps': '0'
                }
                
                url = f"{self.jup_api_urls[0]}/quote"
                logger.info(f"Jupiter API请求详情: {{\n" +
                          f"  URL: {url},\n" +
                          f"  参数: {json.dumps(params, indent=2)},\n" +
                          f"  Headers: {json.dumps(dict(self.headers), indent=2)}\n" +
                          f"}}")
                
                async with session.get(url, params=params) as response:
                    response_text = await response.text()
                    logger.info(f"Jupiter API响应详情: {{\n" +
                              f"  状态码: {response.status},\n" +
                              f"  响应头: {dict(response.headers)},\n" +
                              f"  响应体: {response_text}\n" +
                              f"}}")
                    
                    if response.status != 200:
                        error_msg = f"获取报价失败: HTTP {response.status}"
                        try:
                            error_data = json.loads(response_text)
                            logger.error(f"错误响应解析: {{\n" +
                                       f"  错误码: {error_data.get('errorCode')},\n" +
                                       f"  错误信息: {error_data.get('error')},\n" +
                                       f"  原始响应: {response_text}\n" +
                                       f"}}")
                        except:
                            logger.error(f"无法解析错误响应: {response_text}")
                        
                        if retry < self.max_retries - 1:
                            wait_time = self.retry_delay * (retry + 1)
                            logger.info(f"等待 {wait_time} 秒后重试...")
                            await asyncio.sleep(wait_time)
                            continue
                        raise SwapError(error_msg)
                    
                    try:
                        quote_data = json.loads(response_text)
                        logger.info(f"报价数据解析结果: {{\n" +
                                  f"  输入金额: {quote_data.get('inAmount')},\n" +
                                  f"  输出金额: {quote_data.get('outAmount')},\n" +
                                  f"  价格影响: {quote_data.get('priceImpactPct')},\n" +
                                  f"  最小接收: {quote_data.get('otherAmountThreshold')},\n" +
                                  f"  路由计划: {json.dumps(quote_data.get('routePlan'), indent=2)}\n" +
                                  f"}}")
                    except json.JSONDecodeError as e:
                        logger.error(f"解析报价响应失败: {str(e)}, 响应内容: {response_text}")
                        raise SwapError(f"解析报价数据失败: {str(e)}")
                    
                    # 验证必要的字段
                    required_fields = ['inAmount', 'outAmount', 'otherAmountThreshold']
                    missing_fields = [field for field in required_fields if field not in quote_data]
                    if missing_fields:
                        error_msg = f"报价数据缺少必要字段: {', '.join(missing_fields)}"
                        logger.error(f"{error_msg}, 完整数据: {quote_data}")
                        raise SwapError(error_msg)
                    
                    # 记录解析后的报价数据
                    logger.debug(f"解析后的报价数据: {{\n" +
                                f"  inAmount: {quote_data.get('inAmount')},\n" +
                                f"  outAmount: {quote_data.get('outAmount')},\n" +
                                f"  priceImpact: {quote_data.get('priceImpactPct')},\n" +
                                f"  otherAmountThreshold: {quote_data.get('otherAmountThreshold')}\n" +
                                f"}}")
                    
                    return {
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
                        'quote_id': json.dumps(quote_data)
                    }
                    
            except aiohttp.ClientError as e:
                error_msg = f"API请求错误 (第 {retry + 1} 次尝试): {str(e)}"
                logger.error(error_msg)
                last_error = error_msg
            except SwapError as e:
                error_msg = f"兑换错误 (第 {retry + 1} 次尝试): {str(e)}"
                logger.error(error_msg)
                last_error = error_msg
            except Exception as e:
                error_msg = f"未预期的错误 (第 {retry + 1} 次尝试): {str(e)}, 类型: {type(e)}"
                logger.error(error_msg)
                last_error = error_msg
            finally:
                if session and not session.closed:
                    await session.close()
            
            if retry < self.max_retries - 1:
                wait_time = self.retry_delay * (retry + 1)
                logger.info(f"等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
        
        # 所有重试都失败后抛出最后的错误
        raise SwapError(f"获取报价失败，已重试{self.max_retries}次。最后的错误: {last_error}")

    def _check_route_exists(self, route_map: Dict, from_token: str, to_token: str) -> bool:
        """检查是否存在从源代币到目标代币的路由
        
        Args:
            route_map: 路由图数据
            from_token: 源代币地址
            to_token: 目标代币地址
            
        Returns:
            bool: 是否存在路由
        """
        try:
            # 检查直接路由
            if from_token in route_map and to_token in route_map[from_token]:
                return True
                
            # 检查间接路由（通过 USDC 中转）
            usdc_address = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            if (from_token in route_map and usdc_address in route_map[from_token]) and \
               (usdc_address in route_map and to_token in route_map[usdc_address]):
                return True
                
            return False
        except Exception as e:
            logger.warning(f"检查路由时出错: {str(e)}")
            return True  # 如果检查出错，默认返回 True 继续尝试

    async def _save_transaction(self, wallet_address: str, to_address: str, amount: Decimal,
                              from_token: str, to_token: str, tx_hash: str, tx_info: Dict[str, Any]) -> None:
        """保存交易记录"""
        try:
            logger.info("开始保存 Swap 交易记录...")
            logger.info(f"交易信息: wallet_address={wallet_address}, from_token={from_token}, to_token={to_token}")
            logger.info(f"amount={amount}, tx_hash={tx_hash}")
            
            # 安全地记录交易详情
            try:
                logger.info(f"交易详情: {json.dumps(tx_info, indent=2)}")
            except Exception:
                logger.info(f"交易详情: {str(tx_info)}")
            
            # 获取钱包 - 使用 filter().first() 而不是 get()
            from ...models import Wallet, Transaction as DBTransaction, Token
            wallet = await Wallet.objects.filter(address=wallet_address, chain='SOL', is_active=True).afirst()
            
            if not wallet:
                logger.error(f"找不到匹配的钱包: address={wallet_address}, chain=SOL")
                return
            
            logger.info(f"获取到钱包信息: {wallet.address}, id={wallet.id}")
            
            # 获取代币信息
            from_token_obj = None
            to_token_obj = None
            
            try:
                # 尝试获取源代币
                from_token_obj = await Token.objects.filter(chain='SOL', address=from_token).afirst()
                # 尝试获取目标代币
                to_token_obj = await Token.objects.filter(chain='SOL', address=to_token).afirst()
            except Exception as e:
                logger.warning(f"获取代币信息失败: {str(e)}")
            
            # 准备交易记录数据，使用默认值处理可能缺失的字段
            status = 'SUCCESS'
            if tx_info:
                if isinstance(tx_info, dict):
                    status = 'SUCCESS' if tx_info.get('status') == 'confirmed' else 'PENDING'
                    fee = tx_info.get('fee', 5000)
                    slot = tx_info.get('slot', 0)
                else:
                    fee = 5000
                    slot = 0
            else:
                fee = 5000
                slot = 0
            
            # 提取正确的交易哈希
            if isinstance(tx_hash, dict) and 'result' in tx_hash:
                actual_tx_hash = tx_hash['result']
            elif isinstance(tx_hash, str):
                actual_tx_hash = tx_hash
            else:
                # 尝试从字典中提取
                try:
                    if isinstance(tx_hash, dict):
                        actual_tx_hash = str(tx_hash.get('result', tx_hash))
                    else:
                        actual_tx_hash = str(tx_hash)
                except:
                    actual_tx_hash = str(tx_hash)
            
            # 准备交易数据
            tx_data = {
                'wallet': wallet,
                'chain': 'SOL',
                'tx_hash': actual_tx_hash,
                'tx_type': 'SWAP',
                'status': status,
                'from_address': wallet_address,
                'to_address': wallet_address,  # Swap 通常是同一个钱包地址
                'amount': amount,
                'token': from_token_obj,  # 使用 token 而不是 token_address
                'to_token_address': to_token,  # 这个字段已经添加到模型中
                'gas_price': Decimal(str(fee / 1e9)),
                'gas_used': Decimal('1'),
                'block_number': slot,
                'block_timestamp': timezone.now(),
                'token_info': {  # 添加代币信息
                    'from_token': {
                        'address': from_token,
                        'symbol': from_token_obj.symbol if from_token_obj else 'Unknown',
                        'decimals': from_token_obj.decimals if from_token_obj else 0
                    },
                    'to_token': {
                        'address': to_token,
                        'symbol': to_token_obj.symbol if to_token_obj else 'Unknown',
                        'decimals': to_token_obj.decimals if to_token_obj else 0
                    }
                }
            }
            
            # 安全地记录准备保存的数据
            try:
                logger.info(f"准备保存的交易数据: {json.dumps({k: str(v) for k, v in tx_data.items() if k not in ['wallet', 'token', 'token_info']}, indent=2)}")
            except Exception:
                logger.info(f"准备保存的交易数据: tx_hash={actual_tx_hash}, status={status}")
            
            # 检查交易记录是否已存在
            existing_tx = await DBTransaction.objects.filter(tx_hash=actual_tx_hash, wallet=wallet).afirst()
            if existing_tx:
                logger.info(f"交易记录已存在: id={existing_tx.id}, tx_hash={actual_tx_hash}")
                return
            
            # 创建交易记录
            transaction = await DBTransaction.objects.acreate(**tx_data)
            logger.info(f"交易记录创建成功: id={transaction.id}, tx_hash={actual_tx_hash}")
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            logger.error(f"错误类型: {type(e).__name__}")
            # 不抛出异常，因为交易已经成功了
            pass

    async def execute_swap(self,
        quote_id: str,
        from_token: str,
        to_token: str,
        amount: Decimal,
        from_address: str,
        private_key: str,
        slippage: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """执行代币兑换"""
        session = None
        try:
            logger.info("==================== 开始执行兑换 ====================")
            logger.info(f"交易信息: {{\n" +
                      f"  钱包地址: {from_address},\n" +
                      f"  from_token: {from_token},\n" +
                      f"  to_token: {to_token},\n" +
                      f"  amount: {amount}\n" +
                      f"}}")
            
            # 创建 keypair
            private_key_bytes = base58.b58decode(private_key)
            
            # 验证地址匹配
            try:
                keypair = SoldersKeypair.from_bytes(private_key_bytes)
                pubkey = str(keypair.pubkey())
                logger.info(f"密钥对验证: {{\n" +
                          f"  预期地址: {from_address},\n" +
                          f"  实际地址: {pubkey}\n" +
                          f"}}")
                
                if pubkey != from_address:
                    raise SwapError("私钥与地址不匹配")
            except Exception as e:
                logger.error(f"验证私钥失败: {str(e)}")
                raise SwapError("私钥格式无效")
            
            # 解析报价数据
            quote_data = json.loads(quote_id)
            
            # 构建交易请求
            swap_request = {
                'quoteResponse': quote_data,
                'userPublicKey': from_address,
                'wrapUnwrapSOL': True,
                'computeUnitPriceMicroLamports': 1000,
                'asLegacyTransaction': True  # 使用旧版交易格式
            }
            
            session = await self._get_session()
            url = f"{self.jup_api_urls[0]}/swap"
            
            logger.debug(f"请求交易 URL: {url}")
            logger.debug(f"交易请求数据: {swap_request}")
            
            async with session.post(url, json=swap_request) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise SwapError(f"交易请求失败: {error_text}")
                    
                swap_response = await response.json()
                swap_transaction = swap_response.get('swapTransaction')
                
                if not swap_transaction:
                    raise SwapError("交易响应中缺少交易数据")
                
                # 解码交易数据
                transaction_bytes = base64.b64decode(swap_transaction)
                
                # 获取最新的 blockhash
                blockhash_response = await self.rpc_client.get_latest_blockhash()
                if not blockhash_response:
                    raise SwapError("获取最新 blockhash 失败")
                
                # 从响应中提取 blockhash
                blockhash = blockhash_response['result']['value']['blockhash']
                if not blockhash:
                    raise SwapError("无效的 blockhash")
                
                logger.debug(f"获取到的 blockhash: {blockhash}")
                
                try:
                    # 使用 solana.transaction.Transaction 处理交易
                    transaction = Transaction.deserialize(transaction_bytes)
                    transaction.recent_blockhash = blockhash
                    transaction.sign(Keypair.from_secret_key(private_key_bytes))
                    serialized_transaction = transaction.serialize()
                    
                except Exception as e:
                    logger.error(f"处理交易失败: {str(e)}")
                    raise SwapError(f"处理交易失败: {str(e)}")
                
                # 发送交易到 Solana 网络
                signature = await self.rpc_client.send_raw_transaction(
                    serialized_transaction,
                    opts=TxOpts(skip_preflight=True)
                )
                
                logger.info(f"交易已发送，签名: {signature}")
                
                # 等待交易确认，增加等待时间
                await asyncio.sleep(8)  # 增加等待时间，给交易更多时间确认
                
                # 获取交易详情
                try:
                    tx_details = await self.get_transaction_status(signature)
                    logger.info(f"获取到交易详情: {tx_details}")
                except Exception as e:
                    logger.warning(f"获取交易详情失败，但交易可能已成功: {str(e)}")
                    # 使用基本信息
                    tx_details = {
                        'status': 'pending',
                        'signature': signature,
                        'slot': 0,
                        'timestamp': int(time.time()),
                        'fee': 5000,  # 默认费用
                    }
                
                # 保存交易记录
                try:
                    await self._save_transaction(
                        wallet_address=from_address,
                        to_address=from_address,  # Swap 通常是同一个钱包地址
                        amount=amount,
                        from_token=from_token,
                        to_token=to_token,
                        tx_hash=signature,
                        tx_info=tx_details
                    )
                except Exception as save_error:
                    logger.error(f"保存交易记录失败，但交易可能已成功: {str(save_error)}")
                
                return {
                    'status': 'success',
                    'signature': signature,
                    'from_token': from_token,
                    'to_token': to_token,
                    'amount': str(amount)
                }
                
        except Exception as e:
            logger.error(f"执行兑换失败: {str(e)}")
            raise SwapError(f"执行兑换失败: {str(e)}")
        finally:
            if session and not session.closed:
                await session.close()

    async def get_transaction_status(self, signature: str) -> Dict[str, Any]:
        """获取交易状态"""
        try:
            # 增加重试逻辑
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    tx_info = await self.rpc_client.get_transaction(
                        signature,
                        commitment=Commitment("confirmed")
                    )
                    
                    if not tx_info or not isinstance(tx_info, dict):
                        if attempt < max_retries - 1:
                            logger.warning(f"交易信息为空，等待2秒后重试 (尝试 {attempt+1}/{max_retries})")
                            await asyncio.sleep(2)
                            continue
                        # 如果最后一次尝试仍然失败，返回基本信息
                        return {
                            'status': 'pending',
                            'signature': signature,
                            'slot': 0,
                            'timestamp': int(time.time()),
                            'fee': 5000,  # 默认费用
                        }
                        
                    tx_result = tx_info.get('result', {})
                    if not tx_result:
                        if attempt < max_retries - 1:
                            logger.warning(f"交易结果为空，等待2秒后重试 (尝试 {attempt+1}/{max_retries})")
                            await asyncio.sleep(2)
                            continue
                        # 如果最后一次尝试仍然失败，返回基本信息
                        return {
                            'status': 'pending',
                            'signature': signature,
                            'slot': 0,
                            'timestamp': int(time.time()),
                            'fee': 5000,  # 默认费用
                        }
                    
                    meta = tx_result.get('meta', {})
                    if meta.get('err') is not None:
                        raise SwapError(f"交易失败: {meta.get('err')}")
                        
                    return {
                        'status': 'confirmed',
                        'slot': tx_result.get('slot', 0),
                        'timestamp': tx_result.get('blockTime', int(time.time())),
                        'fee': meta.get('fee', 5000),
                        'logs': meta.get('logMessages', []),
                        'confirmations': tx_result.get('confirmations', 0)
                    }
                except SwapError:
                    # 如果是明确的交易失败，直接抛出
                    raise
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"获取交易状态出错: {str(e)}，等待2秒后重试")
                        await asyncio.sleep(2)
                    else:
                        logger.error(f"多次尝试获取交易状态失败: {str(e)}")
                        # 返回基本信息而不是抛出异常
                        return {
                            'status': 'pending',
                            'signature': signature,
                            'slot': 0,
                            'timestamp': int(time.time()),
                            'fee': 5000,  # 默认费用
                        }
            
        except Exception as e:
            logger.error(f"获取交易状态失败: {str(e)}")
            # 返回基本信息而不是抛出异常
            return {
                'status': 'pending',
                'signature': signature,
                'slot': 0,
                'timestamp': int(time.time()),
                'fee': 5000,  # 默认费用
            }

    def get_transaction_status_sync(self, signature: str) -> Dict[str, Any]:
        """获取交易状态（同步方法）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.get_transaction_status(signature))
        finally:
            loop.close()

    def estimate_fees(self, from_token: str, to_token: str, amount: str, wallet_address: str) -> Dict[str, Any]:
        """估算交易费用（同步方法）
        
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
            logger.info("==================== 开始估算交易费用 ====================")
            logger.info(f"交易信息: {{\n" +
                      f"  钱包地址: {wallet_address},\n" +
                      f"  from_token: {from_token},\n" +
                      f"  to_token: {to_token},\n" +
                      f"  amount: {amount}\n" +
                      f"}}")
            
            # 基础交易费用（lamports）
            base_fee = 5000
            
            # 检查目标代币的关联账户
            try:
                to_token_account = await self._get_associated_token_address(wallet_address, to_token)
                logger.info(f"目标代币账户: {to_token_account}")
                
                # 检查账户是否存在
                account_exists = await self._check_token_account_exists(to_token_account)
                logger.info(f"目标账户状态: {{\n" +
                          f"  地址: {to_token_account},\n" +
                          f"  是否存在: {account_exists}\n" +
                          f"}}")
                
                # 如果需要创建关联账户，添加额外费用
                create_ata_fee = 0
                if not account_exists and to_token != "So11111111111111111111111111111111111111112":
                    create_ata_fee = 2039280  # 创建关联账户的费用
                    logger.info("需要创建关联代币账户")
                
                # 计算总费用
                total_fee = base_fee + create_ata_fee
                
                # 获取 SOL 当前价格
                sol_price = await self._get_sol_price()
                
                # 计算美元价格
                usd_fee = (total_fee / 1e9) * sol_price if sol_price > 0 else 0
                
                result = {
                    'total_fee': total_fee,  # 总费用（lamports）
                    'base_fee': base_fee,    # 基础费用（lamports）
                    'create_ata_fee': create_ata_fee,  # 创建账户费用（如果需要）
                    'total_fee_sol': total_fee / 1e9,  # 总费用（SOL）
                    'total_fee_usd': usd_fee,  # 总费用（USD）
                    'needs_ata_creation': not account_exists and to_token != "So11111111111111111111111111111111111111112"
                }
                
                logger.info(f"费用估算结果: {json.dumps(result, indent=2)}")
                return result
                
            except Exception as e:
                logger.error(f"估算费用时出错: {str(e)}")
                raise SwapError(f"估算交易费用失败: {str(e)}")
            
        except Exception as e:
            logger.error(f"估算交易费用失败: {str(e)}")
            raise SwapError(f"估算交易费用失败: {str(e)}")

    async def _get_sol_price(self) -> float:
        """获取 SOL 当前价格"""
        try:
            session = await self._get_session()
            url = f"{self.jup_api_urls[1]}/token_price?address=So11111111111111111111111111111111111111112"
            
            async with session.get(url, headers={"X-API-KEY": "f5a3c6b3-6c64-4452-a1a9-b8f707b3e98e"}) as response:
                if response.status == 200:
                    price_data = await response.json()
                    if price_data and isinstance(price_data, dict):
                        return float(price_data.get('value', 0))
                logger.warning(f"获取 SOL 价格失败: HTTP {response.status}")
                return 0
        except Exception as e:
            logger.warning(f"获取 SOL 价格失败: {str(e)}")
            return 0

    async def _get_associated_token_address(self, wallet_address: str, token_address: str) -> str:
        """获取关联代币账户地址"""
        try:
            logger.info(f"获取关联代币账户: {{\n" +
                      f"  钱包地址: {wallet_address},\n" +
                      f"  代币地址: {token_address}\n" +
                      f"}}")
            
            # 如果是 SOL，直接返回钱包地址
            if token_address == "So11111111111111111111111111111111111111112":
                logger.info("SOL 代币直接使用钱包地址")
                return wallet_address
            
            try:
                # 转换钱包地址和代币地址为 Pubkey
                wallet_pubkey = Pubkey.from_string(wallet_address)
                token_pubkey = Pubkey.from_string(token_address)
                token_program_id = Pubkey.from_string(str(TOKEN_PROGRAM_ID))
                associated_token_program_id = Pubkey.from_string(str(ASSOCIATED_TOKEN_PROGRAM_ID))
                
                logger.debug(f"公钥转换结果: {{\n" +
                          f"  钱包: {wallet_pubkey},\n" +
                          f"  代币: {token_pubkey},\n" +
                          f"  代币程序: {token_program_id},\n" +
                          f"  关联代币程序: {associated_token_program_id}\n" +
                          f"}}")
                
                # 构建种子
                seeds = [
                    bytes(wallet_pubkey),
                    bytes(token_program_id),
                    bytes(token_pubkey)
                ]
                
                # 查找程序派生地址
                ata, _ = Pubkey.find_program_address(
                    seeds,
                    associated_token_program_id
                )
                
                ata_address = str(ata)
                logger.info(f"关联代币账户地址: {ata_address}")
                return ata_address
                
            except ValueError as e:
                logger.error(f"公钥转换失败: {str(e)}")
                raise SwapError(f"无效的地址格式: {str(e)}")
                
        except Exception as e:
            logger.error(f"获取关联代币账户失败: {str(e)}")
            raise SwapError(f"无法获取关联代币账户: {str(e)}")
            
    async def _check_token_account_exists(self, account_address: str) -> bool:
        """检查代币账户是否存在"""
        try:
            logger.debug(f"检查账户 {account_address} 是否存在")
            
            try:
                # 转换账户地址为 Pubkey
                account_pubkey = Pubkey.from_string(account_address)
                logger.debug(f"账户公钥: {account_pubkey}")
                
                # 获取账户信息
                response = await self.rpc_client.get_account_info(str(account_pubkey))
                
                if response and isinstance(response, dict):
                    value = response.get('result', {}).get('value')
                    exists = value is not None and len(value) > 0
                    logger.debug(f"账户 {account_address} 存在: {exists}")
                    return exists
                return False
                
            except ValueError as e:
                logger.error(f"账户地址转换失败: {str(e)}")
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