import logging
from decimal import Decimal
from typing import Dict, Any, Optional, cast
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

from ...api_config import MoralisConfig, RPCConfig
from ...exceptions import SwapError, InsufficientBalanceError # type: ignore
from ..base.swap import BaseSwapService

logger = logging.getLogger(__name__)

class SolanaSwapService(BaseSwapService):
    """Solana 代币兑换服务"""
    
    def get_quote(self, wallet_id: str, device_id: str, from_token: str, to_token: str, amount: str, slippage: Optional[str] = None) -> Dict[str, Any]:
        """获取兑换报价

        Args:
            wallet_id: 钱包ID
            device_id: 设备ID
            from_token: 源代币地址
            to_token: 目标代币地址
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
            "https://quote-api.jup.ag/v6",
            "https://price.jup.ag/v6",
            "https://token.jup.ag/v6"
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
            total=60,  # 增加总超时时间
            connect=10,  # 增加连接超时时间
            sock_connect=10,
            sock_read=20
        )
        
        # 请求头
        self.headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)'  # 添加 User-Agent
        }
        
        # 重试配置
        self.max_retries = 3
        self.retry_delay = 1  # 重试间隔（秒）
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self.session is None or self.session.closed:
            # 创建 SSL 上下文
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = True  # 启用主机名验证
            ssl_context.verify_mode = ssl.CERT_REQUIRED  # 要求验证证书
            
            connector = aiohttp.TCPConnector(
                ssl=ssl_context,
                force_close=True,
                enable_cleanup_closed=True,
                verify_ssl=True
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
    
    async def get_swap_quote(self, 
        from_token: str,
        to_token: str,
        amount: Decimal,
        slippage: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """获取兑换报价
        
        Args:
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 兑换数量
            slippage: 滑点容忍度
            
        Returns:
            Dict[str, Any]: 兑换报价信息
        """
        last_error = None
        # 遍历所有 API 端点
        for api_url in self.jup_api_urls:
            for retry in range(self.max_retries):
                try:
                    session = await self._get_session()
                    
                    # 构建请求参数
                    # 将amount转换为lamports (1 SOL = 10^9 lamports)
                    amount_lamports = int(amount * Decimal('1000000000'))
                    
                    params = {
                        'inputMint': from_token,
                        'outputMint': to_token,
                        'amount': str(amount_lamports),
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
        """执行代币兑换交易"""
        try:
            # 解析并验证 quote_id
            try:
                quote_data = json.loads(quote_id)
                # 验证代币地址是否匹配
                if quote_data.get('inputMint') != from_token:
                    raise SwapError(f"源代币地址不匹配: 期望 {from_token}, 实际 {quote_data.get('inputMint')}")
                if quote_data.get('outputMint') != to_token:
                    raise SwapError(f"目标代币地址不匹配: 期望 {to_token}, 实际 {quote_data.get('outputMint')}")
            except json.JSONDecodeError:
                raise SwapError("无效的报价ID格式")
            
            # 创建 SSL 上下文
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            
            # 检查目标代币的关联账户是否存在
            try:
                # 获取关联账户地址
                to_token_account = await self._get_associated_token_address(from_address, to_token)
                logger.debug(f"目标代币账户地址: {to_token_account}")
                
                # 检查账户是否存在
                account_exists = await self._check_token_account_exists(to_token_account)
                logger.debug(f"账户是否存在: {account_exists}")
                
                if not account_exists and to_token != 'So11111111111111111111111111111111111111112':
                    logger.info(f"目标代币账户不存在，准备创建: {to_token_account}")
                    # 创建关联账户
                    keypair = Keypair.from_seed(base58.b58decode(private_key)[:32])
                    transaction = Transaction()
                    create_ata_ix = create_associated_token_account(
                        payer=keypair.public_key,
                        owner=keypair.public_key,
                        mint=PublicKey(to_token)
                    )
                    transaction.add(create_ata_ix)
                    
                    # 获取最新区块哈希
                    client = AsyncClient(RPCConfig.SOLANA_MAINNET_RPC_URL)
                    recent_blockhash = await client.get_recent_blockhash()
                    if isinstance(recent_blockhash, dict):
                        blockhash = recent_blockhash.get('result', {}).get('value', {}).get('blockhash')
                        if not blockhash:
                            raise SwapError("无法获取区块哈希")
                    else:
                        blockhash = recent_blockhash
                    transaction.recent_blockhash = blockhash
                    
                    # 签名并发送交易
                    transaction.sign(keypair)
                    result = await client.send_raw_transaction(
                        transaction.serialize(),
                        opts=TxOpts(skip_preflight=True, max_retries=3)
                    )
                    
                    # 等待账户创建完成
                    await asyncio.sleep(2)
                    logger.info("目标代币账户创建完成")
                    await client.close()
            except Exception as e:
                logger.error(f"检查或创建代币账户时出错: {str(e)}")
                raise SwapError(f"检查或创建代币账户失败: {str(e)}")
            
            connector = aiohttp.TCPConnector(
                ssl=ssl_context,
                force_close=True,
                enable_cleanup_closed=True,
                verify_ssl=True
            )
            
            async with aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers,
                connector=connector
            ) as session:
                # 构建请求参数
                swap_params = {
                    'quoteResponse': quote_data,
                    'userPublicKey': from_address,
                    'wrapAndUnwrapSol': True,
                    'computeUnitPriceMicroLamports': 1000,  # 添加计算单元价格
                    'asLegacyTransaction': True  # 使用传统交易格式
                }
                
                logger.debug(f"Swap请求参数: {swap_params}")
                
                # 获取交易数据
                url = f"{self.jup_api_urls[0]}/swap"  # 使用主API端点
                logger.debug(f"请求交易数据URL: {url}")
                
                async with session.post(url, json=swap_params) as response:
                    response_text = await response.text()
                    logger.debug(f"Jupiter API响应: {response_text}")
                    
                    if response.status == 200:
                        swap_data = await response.json()
                        logger.debug(f"交换数据: {swap_data}")
                        
                        if not swap_data.get('swapTransaction'):
                            logger.error("缺少swapTransaction数据")
                            raise SwapError("无效的交换数据: 缺少交易信息")
                        
                        # 创建并签名交易
                        try:
                            # 解码私钥
                            keypair = Keypair.from_seed(base58.b58decode(private_key)[:32])
                            
                            # 获取并验证交易数据
                            swap_transaction = swap_data.get('swapTransaction')
                            if not swap_transaction:
                                raise SwapError("交易数据为空")
                            
                            # 解码并验证交易数据
                            try:
                                # 记录原始交易数据
                                logger.debug(f"原始交易数据: {swap_transaction}")
                                
                                # 验证base64格式
                                try:
                                    transaction_bytes = base64.b64decode(swap_transaction)
                                    logger.debug(f"成功解码交易数据，长度: {len(transaction_bytes)}")
                                except Exception as e:
                                    logger.error(f"Base64解码失败: {str(e)}")
                                    raise SwapError(f"交易数据格式无效: {str(e)}")
                                
                                if not transaction_bytes:
                                    raise SwapError("交易数据解码后为空")
                                
                                # 添加详细的日志记录
                                logger.debug(f"解码后的交易数据长度: {len(transaction_bytes)}")
                                logger.debug(f"解码后的交易数据: {transaction_bytes.hex()}")
                                
                                # 创建交易并添加错误处理
                                try:
                                    transaction = Transaction.deserialize(transaction_bytes)
                                    logger.debug(f"成功反序列化交易")
                                except ValueError as ve:
                                    logger.error(f"交易数据值错误: {str(ve)}")
                                    raise SwapError(f"交易数据值错误: {str(ve)}")
                                except Exception as e:
                                    logger.error(f"交易数据反序列化失败: {str(e)}，数据长度: {len(transaction_bytes)}")
                                    raise SwapError(f"交易数据无效: {str(e)}")
                                
                                # 签名交易
                                transaction.sign(keypair)
                                logger.debug("交易签名完成")
                                
                                # 发送交易
                                client = AsyncClient(
                                    endpoint=RPCConfig.SOLANA_MAINNET_RPC_URL,
                                    commitment=Commitment("confirmed")
                                )
                                
                                logger.debug(f"准备发送交易到RPC节点: {RPCConfig.SOLANA_MAINNET_RPC_URL}")
                                
                                # 序列化交易
                                serialized_tx = transaction.serialize()
                                logger.debug(f"交易序列化完成，数据长度: {len(serialized_tx)}")
                                
                                # 发送交易
                                opts = TxOpts(skip_preflight=True, max_retries=3)
                                result = await client.send_raw_transaction(
                                    serialized_tx,
                                    opts=opts
                                )
                                
                                logger.debug(f"RPC响应结果: {result}")
                                
                                if isinstance(result, dict) and 'error' in result:
                                    error_msg = result.get('error', {})
                                    if isinstance(error_msg, dict):
                                        error_msg = error_msg.get('message', str(error_msg))
                                    raise SwapError(f"发送交易失败: {error_msg}")
                                
                                tx_hash = result.get('result') if isinstance(result, dict) else result
                                if not tx_hash:
                                    raise SwapError("无法获取交易哈希")
                                    
                                # 等待交易确认
                                logger.info(f"等待交易确认: {tx_hash}")
                                max_retries = 15  # 增加重试次数
                                for i in range(max_retries):
                                    try:
                                        tx_info = await client.get_transaction(
                                            tx_hash,
                                            commitment=Commitment("confirmed")
                                        )
                                        if tx_info and isinstance(tx_info, dict):
                                            tx_result = tx_info.get('result', {})
                                            if tx_result:
                                                meta = tx_result.get('meta', {})
                                                if meta.get('err') is not None:
                                                    error_msg = meta.get('err')
                                                    logger.error(f"交易执行失败，错误信息: {error_msg}")
                                                    
                                                    # 处理常见错误
                                                    if isinstance(error_msg, dict):
                                                        if 'InstructionError' in error_msg:
                                                            instruction_idx, error_detail = error_msg['InstructionError']
                                                            if isinstance(error_detail, dict):
                                                                if error_detail.get('Custom') == 1:
                                                                    raise SwapError("交易执行失败: 滑点过大或流动性不足，请调整滑点或减少交易数量")
                                                                elif error_detail.get('Custom') == 6000:
                                                                    raise SwapError("交易执行失败: 余额不足")
                                                                else:
                                                                    raise SwapError(f"交易执行失败: 指令错误 (指令 {instruction_idx}, 错误码 {error_detail})")
                                                    
                                                    # 如果不是已知错误，返回原始错误信息
                                                    raise SwapError(f"交易执行失败: {error_msg}")
                                                logger.info("交易已确认")
                                                break
                                        await asyncio.sleep(2)  # 增加等待时间
                                    except SwapError:
                                        raise
                                    except Exception as e:
                                        logger.warning(f"检查交易状态失败: {str(e)}")
                                        if i == max_retries - 1:
                                            logger.error("交易确认超时，请检查交易状态")
                                            raise SwapError("交易确认超时，请在区块浏览器中检查交易状态")
                                        await asyncio.sleep(2)  # 增加等待时间
                                        continue
                                
                                return {
                                    'status': 'success',
                                    'tx_hash': tx_hash,
                                    'from_token': from_token,
                                    'to_token': to_token,
                                    'amount_in': str(amount),
                                    'amount_out': quote_data.get('outAmount'),
                                    'price_impact': quote_data.get('priceImpactPct'),
                                    'exchange': 'Jupiter',
                                    'block_number': tx_result.get('slot', 0) if tx_result else 0,
                                    'block_timestamp': tx_result.get('blockTime', 0) if tx_result else 0,
                                    'token_info': {
                                        'address': from_token,
                                        'name': 'Silly Dragon',
                                        'symbol': 'SILLY',
                                        'decimals': 9,
                                        'logo': 'https://d23exngyjlavgo.cloudfront.net/solana_7EYnhQoR9YM3N7UoaKRoA44Uy8JeaZV3qyouov87awMs',
                                        'to_token': {
                                            'address': to_token,
                                            'name': 'Solana',
                                            'symbol': 'SOL',
                                            'decimals': 9,
                                            'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
                                        }
                                    }
                                }
                                
                            except SwapError:
                                raise
                            except Exception as e:
                                logger.error(f"处理交易数据时发生错误: {str(e)}")
                                raise SwapError(f"处理交易数据时发生错误: {str(e)}")
                            
                        except Exception as e:
                            logger.error(f"处理交易失败: {str(e)}")
                            raise SwapError(f"处理交易失败: {str(e)}")
                    else:
                        error_msg = f"获取交易数据失败 - 状态码: {response.status}, 响应内容: {response_text}"
                        logger.error(error_msg)
                        raise SwapError(error_msg)
                        
        except aiohttp.ClientError as e:
            logger.error(f"请求兑换接口失败: {str(e)}")
            raise SwapError(f"请求兑换接口失败: {str(e)}")
        except Exception as e:
            logger.error(f"执行代币兑换失败: {str(e)}")
            raise SwapError(f"执行代币兑换失败: {str(e)}")

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