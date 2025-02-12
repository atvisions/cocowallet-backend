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
import base58
import json
import base64

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
        self.jup_api_url = "https://quote-api.jup.ag/v6"
        
        # 设置 aiohttp 会话配置
        self.timeout = aiohttp.ClientTimeout(
            total=30,
            connect=5,
            sock_connect=5,
            sock_read=10
        )
        
        # 请求头
        self.headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers
            )
        return self.session
    
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
            slippage: 滑点容忍度(可选)
            
        Returns:
            Dict[str, Any]: 兑换报价信息
        """
        try:
            async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
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
                url = f"{self.jup_api_url}/quote"
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
                        try:
                            error_data = await response.json()
                            logger.error(f"获取报价失败 - 状态码: {response.status}, 错误信息: {error_data}")
                            raise SwapError(f"获取报价失败: {error_data.get('message', '未知错误')}")
                        except json.JSONDecodeError:
                            logger.error(f"获取报价失败 - 状态码: {response.status}, 响应内容: {response_text}")
                            raise SwapError(f"获取报价失败: 无效的响应格式")
                        
        except aiohttp.ClientError as e:
            logger.error(f"请求报价接口失败: {str(e)}")
            raise SwapError(f"请求报价接口失败: {str(e)}")
        except Exception as e:
            logger.error(f"获取兑换报价失败: {str(e)}")
            raise SwapError(f"获取兑换报价失败: {str(e)}")
    
    async def execute_swap(self,
        quote_id: str,
        from_token: str,
        to_token: str,
        amount: Decimal,
        from_address: str,
        private_key: str,
        slippage: Optional[Decimal] = None
    ) -> Dict[str, Any]:
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
            
            async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
                # 构建请求参数
                swap_params = {
                    'quoteResponse': quote_data,  # 使用解析后的quote_data而不是原始的quote_id字符串
                    'userPublicKey': from_address,
                    'wrapAndUnwrapSol': True
                }
                
                # 获取交易数据
                url = f"{self.jup_api_url}/swap"
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
                                logger.debug(f"原始交易数据: {swap_transaction[:100]}...")
                                
                                # 验证base64格式
                                try:
                                    transaction_bytes = base64.b64decode(swap_transaction)
                                except Exception as e:
                                    logger.error(f"Base64解码失败: {str(e)}")
                                    raise SwapError(f"交易数据格式无效: {str(e)}")
                                
                                if not transaction_bytes:
                                    raise SwapError("交易数据解码后为空")
                                
                                # 添加详细的日志记录
                                logger.debug(f"解码后的交易数据长度: {len(transaction_bytes)}")
                                logger.debug(f"解码后的交易数据前100字节: {transaction_bytes[:100].hex()}")
                                
                                # 创建交易并添加错误处理
                                try:
                                    transaction = Transaction.deserialize(transaction_bytes)
                                    logger.debug(f"反序列化后的交易信息: {transaction}")
                                except ValueError as ve:
                                    logger.error(f"交易数据值错误: {str(ve)}")
                                    if "expected a value in the range [0, 65535]" in str(ve):
                                        raise SwapError("交易数据包含无效的数值范围，请稍后重试")
                                    raise SwapError(f"交易数据值错误: {str(ve)}")
                                except Exception as e:
                                    logger.error(f"交易数据反序列化失败: {str(e)}，数据长度: {len(transaction_bytes)}")
                                    raise SwapError(f"交易数据无效: {str(e)}")
                                    
                                # 验证交易基本信息
                                if not transaction.signatures:
                                    raise SwapError("交易缺少签名字段")
                                if not transaction.message:
                                    raise SwapError("交易缺少消息字段")
                                    
                                logger.debug("交易数据验证通过，准备签名")
                            except SwapError:
                                raise
                            except Exception as e:
                                logger.error(f"交易数据处理失败: {str(e)}")
                                raise SwapError(f"交易数据处理失败: {str(e)}")
                            
                            # 签名交易
                            transaction.sign(keypair)
                            
                            # 发送交易
                            client = AsyncClient(
                                endpoint=RPCConfig.SOLANA_MAINNET_RPC_URL,
                                commitment=Commitment("confirmed")
                            )
                            
                            logger.debug(f"准备发送交易到RPC节点: {RPCConfig.SOLANA_MAINNET_RPC_URL}")
                            result = await client.send_raw_transaction(
                                transaction.serialize(),
                                opts={'skip_preflight': True} # type: ignore
                            )
                            logger.debug(f"RPC响应结果: {result}")
                            
                            if 'error' in result:
                                error_msg = result.get('error', {})
                                if isinstance(error_msg, dict):
                                    error_msg = error_msg.get('message', str(error_msg))
                                raise SwapError(f"发送交易失败: {error_msg}")
                            
                            tx_hash = result.get('result')
                            if not tx_hash:
                                raise SwapError("无法获取交易哈希")
                            
                            return {
                                'status': 'success',
                                'tx_hash': tx_hash,
                                'from_token': from_token,
                                'to_token': to_token,
                                'amount_in': str(amount),
                                'amount_out': swap_data.get('outAmount'),
                                'price_impact': swap_data.get('priceImpactPct'),
                                'exchange': 'Jupiter'
                            }
                            
                        except Exception as e:
                            logger.error(f"处理交易失败: {str(e)}")
                            raise SwapError(f"处理交易失败: {str(e)}")
                    else:
                        logger.error(f"获取报价失败 - 状态码: {response.status}, 响应内容: {response_text}")
                        raise SwapError(f"获取报价失败: 无效的响应格式")
                        
        except aiohttp.ClientError as e:
            logger.error(f"请求兑换接口失败: {str(e)}")
            raise SwapError(f"请求兑换接口失败: {str(e)}")
        except Exception as e:
            logger.error(f"执行代币兑换失败: {str(e)}")
            raise SwapError(f"执行代币兑换失败: {str(e)}")