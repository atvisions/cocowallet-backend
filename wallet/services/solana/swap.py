import logging
from decimal import Decimal
from typing import Dict, Any, Optional, cast
import asyncio
import aiohttp
from django.utils import timezone
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment
from solana.transaction import Transaction, TransactionInstruction, Message
from solana.keypair import Keypair
from solana.publickey import PublicKey
import base58
import json
import base64
from solana.rpc.types import TxOpts

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
                amount_lamports = str(int(amount * Decimal('1000000000')))
                logger.debug(f"转换后的lamports数量: {amount_lamports}")
                
                params = {
                    'inputMint': from_token,
                    'outputMint': to_token,
                    'amount': amount_lamports,
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
            # 基础参数验证
            if float(amount) <= 0:
                raise SwapError("兑换金额必须大于0")
            
            if slippage is not None and (float(slippage) <= 0 or float(slippage) > 100):
                raise SwapError("滑点必须在0-100之间")

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
            
            # 解码私钥
            try:
                decoded_private_key = base58.b58decode(private_key)
                if len(decoded_private_key) != 64:
                    raise SwapError("无效的私钥长度")
                
                keypair = Keypair.from_seed(decoded_private_key[:32])
                
                # 验证公钥是否匹配
                if str(keypair.public_key) != from_address:
                    logger.error(f"私钥公钥不匹配: 期望地址 {from_address}, 实际地址 {str(keypair.public_key)}")
                    raise SwapError("私钥与钱包地址不匹配")
                    
                logger.debug(f"私钥验证通过，公钥: {str(keypair.public_key)}")
            except ValueError as e:
                logger.error(f"私钥格式错误: {str(e)}")
                raise SwapError("无效的私钥格式")
            except Exception as e:
                logger.error(f"私钥处理失败: {str(e)}")
                raise SwapError("私钥验证失败")
            
            # 检查账户余额
            try:
                client = AsyncClient(
                    endpoint=RPCConfig.SOLANA_MAINNET_RPC_URL,
                    commitment=Commitment("confirmed")
                )
                
                # 获取目标代币的关联账户地址
                try:
                    associated_token_address = PublicKey.find_program_address(
                        [
                            bytes(PublicKey(from_address)),
                            bytes(PublicKey("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")),
                            bytes(PublicKey(to_token))
                        ],
                        PublicKey("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
                    )[0]
                    
                    # 检查代币账户是否存在
                    account_info = await client.get_account_info(
                        pubkey=str(associated_token_address),
                        commitment=Commitment("confirmed")
                    )
                    
                    token_account_exists = account_info.get('result', {}).get('value') is not None
                    logger.debug(f"目标代币账户是否存在: {token_account_exists}")
                    
                except Exception as e:
                    logger.error(f"检查代币账户失败: {str(e)}")
                    token_account_exists = False
                
                # 获取账户余额
                balance_response = await client.get_balance(
                    pubkey=from_address,
                    commitment=Commitment("confirmed")
                )
                
                if 'error' in balance_response:
                    raise SwapError("获取账户余额失败")
                
                balance = balance_response.get('result', {}).get('value', 0)
                balance_in_sol = balance / 1000000000
                logger.debug(f"账户余额: {balance} lamports ({balance_in_sol:.9f} SOL)")
                
                # 根据是否需要创建代币账户来设置最低余额要求
                min_required_balance = 2300000 if token_account_exists else 500000000  # 0.0023 SOL 或 0.5 SOL
                min_required_sol = min_required_balance / 1000000000
                
                if balance < min_required_balance:
                    raise InsufficientBalanceError(
                        f"账户余额不足。当前余额: {balance_in_sol:.4f} SOL，"
                        f"需要至少 {min_required_sol:.4f} SOL "
                        f"{'用于支付交易费用' if token_account_exists else '用于创建代币账户和支付交易费用'}，"
                        f"实际兑换金额: {float(amount):.4f} SOL"
                    )
                
            except Exception as e:
                logger.error(f"检查余额失败: {str(e)}")
                raise SwapError(f"检查余额失败: {str(e)}")
            finally:
                await client.close()
            
            async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
                # 构建请求参数
                swap_params = {
                    'quoteResponse': quote_data,
                    'userPublicKey': from_address,
                    'asLegacyTransaction': True,
                    'useSharedAccounts': True,
                    'wrapAndUnwrapSol': True,
                    'restrictIntermediateTokens': False,
                    'computeUnitLimit': 1400000  # 设置计算单位限制
                }
                
                # 获取交易数据
                url = f"{self.jup_api_url}/swap"
                async with session.post(url, json=swap_params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Jupiter API请求失败: 状态码 {response.status}, 响应: {error_text}")
                        raise SwapError(f"获取交易数据失败: HTTP {response.status}")

                    response_text = await response.text()
                    logger.debug(f"Jupiter API响应: {response_text}")
                    
                    try:
                        swap_data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logger.error(f"解析Jupiter API响应失败: {str(e)}")
                        raise SwapError("无效的API响应格式")

                    logger.debug(f"交换数据: {swap_data}")
                    
                    if not swap_data.get('swapTransaction'):
                        logger.error("缺少swapTransaction数据")
                        raise SwapError("无效的交换数据: 缺少交易信息")

                    try:
                        # 解码并签名交易
                        transaction_bytes = base64.b64decode(swap_data['swapTransaction'])
                        transaction = Transaction.deserialize(transaction_bytes)
                        
                        # 设置签名者
                        transaction.sign_partial(keypair)
                        logger.debug("交易已签名")
                        
                        # 序列化签名后的交易
                        signed_transaction = base64.b64encode(transaction.serialize()).decode('utf-8')
                        logger.debug(f"签名后的交易数据长度: {len(signed_transaction)}")
                        
                        # 发送交易
                        client = AsyncClient(
                            endpoint=RPCConfig.SOLANA_MAINNET_RPC_URL,
                            commitment=Commitment("confirmed")
                        )
                        
                        try:
                            # 创建正确的 TxOpts 对象
                            tx_opts = TxOpts(
                                skip_preflight=False,  # 启用预检
                                max_retries=3
                            )
                            
                            # 发送签名后的交易
                            result = await client.send_raw_transaction(
                                signed_transaction,
                                opts=tx_opts
                            )
                            
                            logger.debug(f"RPC响应结果: {result}")
                            
                            if 'error' in result:
                                error_msg = result.get('error', {})
                                if isinstance(error_msg, dict):
                                    error_msg = error_msg.get('message', str(error_msg))
                                raise SwapError(f"发送交易失败: {error_msg}")
                            
                            signature = result.get('result')
                            if not signature or signature == '1' * 64:
                                raise SwapError("获取到无效的交易签名")
                            
                            # 等待交易确认
                            try:
                                # 设置更长的确认超时时间，并添加重试
                                for attempt in range(3):  # 最多重试3次
                                    try:
                                        await asyncio.wait_for(
                                            client.confirm_transaction(
                                                signature,
                                                commitment=Commitment("confirmed")
                                            ),
                                            timeout=30.0  # 30秒超时
                                        )
                                        logger.debug("交易已确认")
                                        break
                                    except asyncio.TimeoutError:
                                        if attempt == 2:  # 最后一次尝试
                                            raise SwapError("交易确认超时，请检查交易状态")
                                        logger.warning(f"确认超时，正在重试 ({attempt + 1}/3)")
                                        continue
                                    except Exception as e:
                                        if attempt == 2:  # 最后一次尝试
                                            raise
                                        logger.warning(f"确认失败，正在重试 ({attempt + 1}/3): {str(e)}")
                                        continue
                            except Exception as e:
                                logger.error(f"交易确认失败: {str(e)}")
                                raise SwapError(f"交易确认失败: {str(e)}")
                            
                            # 交易成功，返回结果
                            return {
                                'success': True,
                                'tx_hash': signature,
                                'quote': quote_data,
                                'amount': str(amount),
                                'amount_in': quote_data.get('inAmount'),
                                'amount_out': quote_data.get('outAmount'),
                                'from_token': from_token,
                                'to_token': to_token,
                                'exchange': 'Jupiter'
                            }
                            
                        except Exception as e:
                            logger.error(f"发送交易失败: {str(e)}")
                            raise SwapError(f"发送交易失败: {str(e)}")
                        finally:
                            await client.close()
                            
                    except Exception as e:
                        logger.error(f"处理交易失败: {str(e)}")
                        raise SwapError(f"处理交易失败: {str(e)}")
                    
        except SwapError:
            raise
        except Exception as e:
            logger.error(f"执行兑换失败: {str(e)}")
            raise SwapError(f"执行兑换失败: {str(e)}")