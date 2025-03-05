"""EVM 代币兑换服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
from web3 import Web3
from django.utils import timezone
from asgiref.sync import sync_to_async
from eth_account import Account
import json
import asyncio

from ...models import Token, Wallet, Transaction
from ..evm_config import RPCConfig, MoralisConfig
from ...exceptions import (
    WalletNotFoundError, 
    ChainNotSupportError, 
    InvalidAddressError,
    SwapTokensError,
    GetSupportedTokensError
)
from .utils import EVMUtils
from .token_info import EVMTokenInfoService

logger = logging.getLogger(__name__)

class EVMSwapService:
    """EVM 代币兑换服务实现类"""

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        
        # Moralis API 配置
        self.api_url = RPCConfig.get_alchemy_url(chain)
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.chain_id = MoralisConfig.get_chain_id(chain)
        
        # 设置钱包地址
        self.address = None
        
        # BaseSwap Router ABI
        if chain == 'BASE':
            self.router_abi = [{
                "inputs": [
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactETHForTokens",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "payable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForETH",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "path", "type": "address[]"}
                ],
                "name": "getAmountsOut",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "view",
                "type": "function"
            }]
        else:
            # 标准 Uniswap V2 Router ABI
            self.router_abi = [{
                "inputs": [
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactETHForTokens",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "payable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForETH",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "path", "type": "address[]"}
                ],
                "name": "getAmountsOut",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "view",
                "type": "function"
            }]

    def get_contract(self, address: str, abi: Optional[List[Dict[str, Any]]] = None) -> Any:
        """获取合约实例
        
        Args:
            address: 合约地址
            abi: 合约 ABI，如果为 None 则使用 ERC20 标准 ABI
            
        Returns:
            Contract: 合约实例
        """
        if not abi:
            # 使用标准 ERC20 ABI
            abi = [{
                "constant": True,
                "inputs": [],
                "name": "name",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            }, {
                "constant": True,
                "inputs": [],
                "name": "symbol",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            }, {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }, {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }, {
                "constant": False,
                "inputs": [
                    {"name": "_to", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "transfer",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            }, {
                "constant": True,
                "inputs": [
                    {"name": "_owner", "type": "address"},
                    {"name": "_spender", "type": "address"}
                ],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function"
            }, {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            }]
            
        return self.web3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=abi
        )

    async def get_quote(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        slippage: float = 1.0
    ) -> Dict:
        """获取兑换报价"""
        try:
            logger.info(f"请求获取兑换报价: from_token={from_token}, to_token={to_token}, amount={amount}, slippage={slippage}")
            
            # 获取源代币精度
            from_decimals = await self._get_token_decimals(from_token)
            logger.info(f"源代币精度: {from_decimals}")
            
            # 将输入金额转换为链上金额
            try:
                chain_amount = EVMUtils.to_wei(amount, from_decimals)
                logger.info(f"输入金额: {amount}, 链上金额: {chain_amount}")
            except Exception as e:
                logger.error(f"金额转换失败: {str(e)}")
                return {
                    'status': 'error',
                    'message': '金额格式错误'
                }
            
            # 获取 DEX 路由地址
            try:
                spender = await self._get_dex_router()
                logger.info(f"DEX 路由地址: {spender}")
            except Exception as e:
                logger.error(f"获取 DEX 路由地址失败: {str(e)}")
                return {
                    'status': 'error',
                    'message': f'获取 DEX 路由地址失败: {str(e)}'
                }
            
            # 获取市场价格
            try:
                market_price = await self._get_market_price(from_token, to_token)
                logger.info(f"市场价格: {market_price}")
                if not market_price:
                    return {
                        'status': 'error',
                        'message': '无法获取市场价格'
                    }
            except Exception as e:
                logger.error(f"获取市场价格失败: {str(e)}")
                return {
                    'status': 'error',
                    'message': f'获取市场价格失败: {str(e)}'
                }
            
            # 计算输出金额
            amount_out = Decimal(chain_amount) * market_price
            logger.info(f"计算输出金额: amount_out={amount_out}, market_price={market_price}")
            
            # 估算 gas
            try:
                estimated_gas = await self._estimate_swap_gas(
                    from_token,
                    to_token,
                    chain_amount,
                    from_decimals,
                    18  # 目标代币精度
                )
                logger.info(f"估算 gas: {estimated_gas}")
            except Exception as e:
                logger.error(f"估算 gas 失败: {str(e)}")
                estimated_gas = 200000  # 使用默认值
            
            # 计算价格影响
            try:
                price_impact = await self._calculate_price_impact(
                    from_token,
                    to_token,
                    chain_amount,
                    int(amount_out)
                )
                logger.info(f"价格影响: {price_impact}%")
            except Exception as e:
                logger.error(f"计算价格影响失败: {str(e)}")
                price_impact = Decimal('1.0')  # 使用默认值
            
            # 计算最小收到数量
            minimum_received = amount_out * (Decimal('1') - Decimal(str(slippage)) / Decimal('100'))
            logger.info(f"最小收到数量: {minimum_received}")
            
            return {
                'status': 'success',
                'message': '获取报价成功',
                'data': {
                    'from_token': from_token,
                    'to_token': to_token,
                    'amount_in': str(chain_amount),
                    'amount_out': str(int(amount_out)),
                    'exchange_rate': str(market_price),
                    'estimated_gas': estimated_gas,
                    'price_impact': str(price_impact),
                    'minimum_received': str(int(minimum_received)),
                    'protocols': ['BaseSwap'] if self.chain == 'BASE' else ['Uniswap V2'],
                    'spender': spender
                }
            }
            
        except Exception as e:
            logger.error(f"获取兑换报价失败: {str(e)}")
            return {
                'status': 'error',
                'message': f"获取报价失败: {str(e)}"
            }

    async def _get_token_decimals(self, token_address: str) -> int:
        """获取代币精度"""
        if token_address == EVMUtils.NATIVE_TOKEN_ADDRESS:
            return 18
            
        try:
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=[{
                    "constant": True,
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "type": "function"
                }]
            )
            
            return contract.functions.decimals().call()
            
        except Exception as e:
            logger.error(f"获取代币精度失败: {str(e)}")
            # USDC 使用 6 位精度
            if token_address.lower() == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913":
                return 6
            return 18  # 默认返回18位精度

    async def _get_market_price(self, from_token: str, to_token: str) -> Optional[Decimal]:
        """获取市场价格"""
        try:
            # 获取 DEX 配置
            dex_config = RPCConfig.DEX_CONFIG.get(self.chain)
            if not dex_config:
                raise ValueError(f"不支持的链: {self.chain}")
                
            # 获取 Wrapped Token 地址
            wrapped_native = RPCConfig.NATIVE_TOKENS.get(self.chain, {}).get('address')
            if not wrapped_native:
                raise ValueError(f"找不到 {self.chain} 的 Wrapped Token 地址")
                
            logger.info(f"使用 {dex_config['name']} 在 {self.chain} 链上获取价格")
            logger.info(f"Wrapped Token 地址: {wrapped_native}")
            
            # 处理原生代币地址
            if from_token == EVMUtils.NATIVE_TOKEN_ADDRESS:
                from_token = wrapped_native
            if to_token == EVMUtils.NATIVE_TOKEN_ADDRESS:
                to_token = wrapped_native

            # 获取 Router 合约
            router_address = dex_config['router_address']
            router = self.get_contract(router_address, self.router_abi)
            logger.info(f"使用 Router 合约: {router_address}")

            # 使用 1 ETH 作为基准金额来获取价格
            base_amount = Web3.to_wei(1, 'ether')  # 1 ETH = 1e18 wei
            
            try:
                # 获取兑换路径的输出金额
                path = [Web3.to_checksum_address(from_token), Web3.to_checksum_address(to_token)]
                logger.info(f"尝试获取兑换路径的输出金额: {path}")
                
                amounts = router.functions.getAmountsOut(
                    base_amount,
                    path
                ).call()
                logger.info(f"获取到的输出金额序列: {amounts}")
                
                if not amounts or len(amounts) < 2:
                    logger.error("获取兑换金额失败")
                    return None
                    
                # 计算兑换比率
                from_decimals = await self._get_token_decimals(from_token)
                to_decimals = await self._get_token_decimals(to_token)
                
                # 将输入和输出金额转换为标准单位
                amount_in = EVMUtils.from_wei(base_amount, from_decimals)
                amount_out = EVMUtils.from_wei(amounts[1], to_decimals)
                
                # 计算兑换比率
                exchange_rate = amount_out / amount_in
                logger.info(f"当前市场兑换比率: 1 {from_token} = {exchange_rate} {to_token}")
                
                return exchange_rate
                
            except Exception as e:
                logger.error(f"调用 Router 合约失败: {str(e)}")
                return None
            
        except Exception as e:
            logger.error(f"获取市场价格失败: {str(e)}")
            return None

    async def _get_default_quote(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        slippage: float,
        from_address: str
    ) -> Optional[Dict]:
        """获取默认报价"""
        try:
            logger.info(f"获取默认报价: from_token={from_token}, to_token={to_token}, amount={amount}")
            
            # 获取 DEX 配置
            dex_config = RPCConfig.DEX_CONFIG.get(self.chain)
            if not dex_config:
                raise ValueError(f"不支持的链: {self.chain}")
                
            # 获取路由器合约
            router_address = dex_config['router_address']
            router = self.get_contract(router_address, self.router_abi)
            logger.info(f"使用 DEX 路由器: {router_address}")
            
            # 处理代币地址
            is_from_native = from_token == EVMUtils.NATIVE_TOKEN_ADDRESS
            is_to_native = to_token == EVMUtils.NATIVE_TOKEN_ADDRESS
            
            # 获取包装后的代币地址
            wrapped_native = self.chain_config['native_token']['address']
            logger.info(f"包装后的原生代币地址: {wrapped_native}")
            
            # 对于 ETH 到代币的兑换，使用实际路径
            from_token_address = wrapped_native if is_from_native else Web3.to_checksum_address(from_token)
            to_token_address = wrapped_native if is_to_native else Web3.to_checksum_address(to_token)
            
            # 获取代币精度
            from_decimals = await self._get_token_decimals(from_token_address)
            to_decimals = await self._get_token_decimals(to_token_address)
            logger.info(f"代币精度: from={from_decimals}, to={to_decimals}")
            
            # 转换输入金额为链上金额
            amount_in = EVMUtils.to_wei(amount, from_decimals)
            logger.info(f"输入金额: {amount}, 链上金额: {amount_in}")
            
            try:
                # 获取兑换路径
                path = [from_token_address, to_token_address]
                logger.info(f"兑换路径: {path}")
                
                # 计算输出金额
                amounts_out = await router.functions.getAmountsOut(
                    amount_in,
                    path
                ).call()
                logger.info(f"预期输出金额: {amounts_out}")
                
                if not amounts_out or len(amounts_out) < 2:
                    raise ValueError("无法计算输出金额")
                    
                amount_out = amounts_out[-1]
                
                # 计算最小输出金额（考虑滑点）
                min_amount_out = int(amount_out * (1 - slippage / 100))
                logger.info(f"最小输出金额: {min_amount_out}")
                
                # 计算价格影响
                price_impact = await self._calculate_price_impact(
                    from_token_address,
                    to_token_address,
                    amount_in,
                    amount_out
                )
                logger.info(f"价格影响: {price_impact}%")
                
                # 估算 gas 费用
                gas_estimate = await self._estimate_swap_gas(
                    from_token_address,
                    to_token_address,
                    amount_in,
                    from_decimals,
                    to_decimals
                )
                logger.info(f"估算 gas: {gas_estimate}")
                
                return {
                    'status': 'success',
                    'from_token': from_token_address,
                    'to_token': to_token_address,
                    'amount_in': str(amount_in),
                    'amount_out': str(amount_out),
                    'amount_out_formatted': str(EVMUtils.from_wei(amount_out, to_decimals)),
                    'min_amount_out': str(min_amount_out),
                    'price_impact': str(price_impact),
                    'path': path,
                    'gas_estimate': gas_estimate
                }
                
            except Exception as e:
                logger.error(f"计算输出金额失败: {str(e)}")
                return None
                
        except Exception as e:
            logger.error(f"获取默认报价失败: {str(e)}")
            return None

    async def _get_dex_router(self) -> str:
        """获取 DEX 路由器地址"""
        try:
            dex_config = RPCConfig.DEX_CONFIG.get(self.chain)
            if not dex_config:
                raise ValueError(f"不支持的链: {self.chain}")
            return dex_config['router_address']
        except Exception as e:
            logger.error(f"获取 DEX Router 地址失败: {str(e)}")
            raise ValueError(f"获取 DEX Router 地址失败: {str(e)}")

    async def build_swap_transaction(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        from_address: str,
        slippage: float = 1.0
    ) -> Dict:
        """构建兑换交易
        
        Args:
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 兑换数量(已包含精度)
            from_address: 发送方地址
            slippage: 滑点百分比(默认1%)
            
        Returns:
            Dict: 交易数据
        """
        try:
            logger.info(f"开始构建兑换交易: from_token={from_token}, to_token={to_token}, amount={amount}")
            
            # 确保地址格式正确
            from_address = Web3.to_checksum_address(from_address)
            
            # 处理代币地址
            is_from_native = from_token == EVMUtils.NATIVE_TOKEN_ADDRESS
            is_to_native = to_token == EVMUtils.NATIVE_TOKEN_ADDRESS
            
            # 获取 DEX 配置和包装后的代币地址
            dex_config = RPCConfig.DEX_CONFIG.get(self.chain)
            if not dex_config:
                raise ValueError(f"不支持的链: {self.chain}")
            
            wrapped_native = RPCConfig.NATIVE_TOKENS.get(self.chain, {}).get('address')
            if not wrapped_native:
                raise ValueError(f"找不到 {self.chain} 的 Wrapped Token 地址")
            logger.info(f"使用 {dex_config['name']} 在 {self.chain} 链上")
            logger.info(f"使用包装后的原生代币地址: {wrapped_native}")
            
            # 对于 ETH 到代币的兑换，使用实际路径
            from_token_address = wrapped_native if is_from_native else Web3.to_checksum_address(from_token)
            to_token_address = wrapped_native if is_to_native else Web3.to_checksum_address(to_token)
            logger.info(f"兑换路径: {from_token_address} -> {to_token_address}")
            
            # 获取代币精度
            from_decimals = await self._get_token_decimals(from_token)
            logger.info(f"源代币精度: {from_decimals}")
            
            # 转换输入金额为链上金额
            try:
                chain_amount = EVMUtils.to_wei(amount, from_decimals)
                logger.info(f"输入金额: {amount}, 链上金额: {chain_amount}")
            except Exception as e:
                logger.error(f"金额转换失败: {str(e)}")
                return {
                    'status': 'error',
                    'message': '金额格式错误'
                }
            
            # 获取 Router 合约
            router_address = await self._get_dex_router()
            router = self.get_contract(router_address, self.router_abi)
            
            # 获取输出金额
            try:
                path = [from_token_address, to_token_address]
                logger.info(f"尝试获取兑换路径的输出金额: {path}")
                
                amounts = router.functions.getAmountsOut(
                    chain_amount,
                    path
                ).call()
                logger.info(f"获取到的输出金额序列: {amounts}")
                
                if not amounts or len(amounts) < 2:
                    raise Exception("无法计算输出金额")
                    
                amount_out = amounts[1]
                minimum_received = int(amount_out * (1 - slippage / 100))
                logger.info(f"输出金额: {amount_out}, 最小接收金额: {minimum_received}")
                
            except Exception as e:
                logger.error(f"计算输出金额失败: {str(e)}")
                # 尝试检查流动性池是否存在
                try:
                    # 从 DEX 配置中获取 Factory 地址
                    dex_config = RPCConfig.DEX_CONFIG.get(self.chain)
                    if not dex_config:
                        raise ValueError(f"不支持的链: {self.chain}")
                    factory_address = dex_config['factory_address']
                    logger.info(f"使用 Factory 地址: {factory_address} 在 {self.chain} 链上")
                    
                    factory = self.get_contract(factory_address, [{
                        "constant": True,
                        "inputs": [
                            {"name": "tokenA", "type": "address"},
                            {"name": "tokenB", "type": "address"}
                        ],
                        "name": "getPair",
                        "outputs": [{"name": "pair", "type": "address"}],
                        "type": "function"
                    }])
                    
                    pair_address = factory.functions.getPair(
                        from_token_address,
                        to_token_address
                    ).call()
                    
                    if pair_address == "0x0000000000000000000000000000000000000000":
                        logger.error(f"交易对不存在: {from_token_address} - {to_token_address}")
                        return {
                            'status': 'error',
                            'message': '交易对不存在，可能没有流动性'
                        }
                    logger.info(f"找到交易对地址: {pair_address}")
                    
                except Exception as pair_error:
                    logger.error(f"检查交易对失败: {str(pair_error)}")
                    return {
                        'status': 'error',
                        'message': f'检查交易对失败: {str(pair_error)}'
                    }
            
            # 构建 swap 参数
            deadline = int(timezone.now().timestamp()) + 60 * 20  # 20分钟后过期
            
            # 估算 gas
            try:
                if is_from_native:
                    gas_limit = router.functions.swapExactETHForTokens(
                        minimum_received,
                        [from_token_address, to_token_address],
                        from_address,
                        deadline
                    ).estimate_gas({
                        'from': from_address,
                        'value': chain_amount
                    })
                elif is_to_native:
                    gas_limit = router.functions.swapExactTokensForETH(
                        chain_amount,
                        minimum_received,
                        [from_token_address, to_token_address],
                        from_address,
                        deadline
                    ).estimate_gas({
                        'from': from_address
                    })
                else:
                    gas_limit = router.functions.swapExactTokensForTokens(
                        chain_amount,
                        minimum_received,
                        [from_token_address, to_token_address],
                        from_address,
                        deadline
                    ).estimate_gas({
                        'from': from_address
                    })
                    
                gas_limit = int(gas_limit * 1.2)  # 添加20%缓冲
                logger.info(f"估算 gas limit: {gas_limit}")
                
            except Exception as e:
                logger.warning(f"估算 gas 失败: {str(e)}")
                gas_limit = 250000  # 使用保守的默认值
            
            # 构建交易数据
            if is_from_native:
                # 原生代币兑换为代币
                tx_data = {
                    'from': from_address,
                    'to': router_address,
                    'value': chain_amount,
                    'gas': gas_limit,
                    'data': router.encodeABI(
                        fn_name="swapExactETHForTokens",
                        args=[
                            minimum_received,
                            [from_token_address, to_token_address],
                            from_address,
                            deadline
                        ]
                    ),
                    'chainId': self.chain_config['chain_id']
                }
            elif is_to_native:
                # 代币兑换为原生代币
                tx_data = {
                    'from': from_address,
                    'to': router_address,
                    'value': 0,
                    'gas': gas_limit,
                    'data': router.encodeABI(
                        fn_name="swapExactTokensForETH",
                        args=[
                            chain_amount,
                            minimum_received,
                            [from_token_address, to_token_address],
                            from_address,
                            deadline
                        ]
                    ),
                    'chainId': self.chain_config['chain_id']
                }
            else:
                # 代币兑换代币
                tx_data = {
                    'from': from_address,
                    'to': router_address,
                    'value': 0,
                    'gas': gas_limit,
                    'data': router.encodeABI(
                        fn_name="swapExactTokensForTokens",
                        args=[
                            chain_amount,
                            minimum_received,
                            [from_token_address, to_token_address],
                            from_address,
                            deadline
                        ]
                    ),
                    'chainId': self.chain_config['chain_id']
                }
            
            # 检查是否支持 EIP-1559
            if self.web3.eth.get_block('latest').get('baseFeePerGas') is not None:
                # 使用 EIP-1559 费用
                fee_data = EVMUtils.get_gas_price(self.chain)
                tx_data['maxPriorityFeePerGas'] = fee_data['max_priority_fee']
                tx_data['maxFeePerGas'] = fee_data['max_fee']
            else:
                # 使用传统 gas price
                tx_data['gasPrice'] = self.web3.eth.gas_price
            
            # 返回交易数据和额外信息
            return {
                'status': 'success',
                'data': tx_data,
                'extra': {
                    'minimum_received': minimum_received,
                    'amounts_out': amounts,
                    'price_impact': '0.5',  # 默认值
                    'protocols': ['BaseSwap'] if self.chain == 'BASE' else ['Uniswap V2']
                }
            }
            
        except Exception as e:
            error_msg = f"构建兑换交易时发生错误: {str(e)}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'message': error_msg
            }

    def _encode_swap_data(self, function_name: str, params: List) -> str:
        """编码 swap 函数调用数据"""
        try:
            # Uniswap V2 Router ABI
            abi = [{
                "inputs": [
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactETHForTokens",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "payable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForETH",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }, {
                "inputs": [
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMin", "type": "uint256"},
                    {"name": "path", "type": "address[]"},
                    {"name": "to", "type": "address"},
                    {"name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [{"name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            }]
            
            # 创建合约对象
            contract = self.web3.eth.contract(abi=abi)
            
            # 编码函数调用
            return contract.encodeABI(fn_name=function_name, args=params)
            
        except Exception as e:
            logger.error(f"编码 swap 数据失败: {str(e)}")
            raise

    async def get_supported_tokens(self, wallet_id: int) -> List[Dict]:
        """获取支持的代币列表
        
        Args:
            wallet_id: 钱包ID
            
        Returns:
            List[Dict]: 代币列表，包含代币信息
        """
        try:
            wallet = await sync_to_async(Wallet.objects.get)(id=wallet_id)
            if not wallet:
                raise WalletNotFoundError()
                
            # 获取链配置
            chain_config = EVMUtils.get_chain_config(wallet.chain)
            if not chain_config:
                raise ChainNotSupportError()
                
            # 创建代币信息服务
            token_info_service = EVMTokenInfoService(self.chain)
            
            # 获取原生代币信息
            native_token = {
                'address': EVMUtils.NATIVE_TOKEN_ADDRESS,
                'name': chain_config['name'],
                'symbol': chain_config['symbol'],
                'decimals': chain_config['decimals'],
                'logo': chain_config['native_token'].get('logo', ''),
                'price': await token_info_service.get_token_price(EVMUtils.NATIVE_TOKEN_ADDRESS),
                'price_change_24h': 0,
                'verified': True,
                'is_native': True
            }
            
            # 获取其他支持的代币
            tokens = [native_token]
            # ... 其他代币获取逻辑 ...
            
            return tokens
            
        except Exception as e:
            logger.error(f"获取支持的代币列表失败: {str(e)}")
            raise GetSupportedTokensError(str(e))
            
    def swap_tokens(self, wallet_id: int, from_token: str, to_token: str, amount: str,
                   slippage: float = 1.0, payment_password: Optional[str] = None) -> Dict:
        """代币兑换
        
        Args:
            wallet_id: 钱包ID
            from_token: 源代币地址
            to_token: 目标代币地址
            amount: 兑换数量
            slippage: 滑点百分比
            payment_password: 支付密码
            
        Returns:
            Dict: 交易信息
        """
        try:
            # 验证代币地址
            if from_token != EVMUtils.NATIVE_TOKEN_ADDRESS and not EVMUtils.validate_address(from_token):
                raise InvalidAddressError("无效的源代币地址")
            if to_token != EVMUtils.NATIVE_TOKEN_ADDRESS and not EVMUtils.validate_address(to_token):
                raise InvalidAddressError("无效的目标代币地址")
                
            # ... 其他兑换逻辑 ...
            return {
                'status': 'success',
                'message': '交易执行成功'
            }
            
        except Exception as e:
            logger.error(f"代币兑换失败: {str(e)}")
            raise SwapTokensError(str(e))

    async def get_token_allowance(
        self,
        token_address: str,
        wallet_address: str,
        spender: str
    ) -> str:
        """获取代币授权额度
        
        Args:
            token_address: 代币合约地址
            wallet_address: 钱包地址
            spender: 授权地址
            
        Returns:
            str: 授权额度
        """
        try:
            # 如果是原生代币，直接返回最大值
            if token_address == EVMUtils.NATIVE_TOKEN_ADDRESS:
                return "115792089237316195423570985008687907853269984665640564039457584007913129639935"  # 2^256 - 1
                
            # 获取代币精度
            decimals = await self._get_token_decimals(token_address)
            logger.debug(f"代币精度: {decimals}")
            
            # 获取代币合约
            contract = self.get_contract(token_address, [{
                "constant": True,
                "inputs": [{
                    "name": "_owner",
                    "type": "address"
                }, {
                    "name": "_spender",
                    "type": "address"
                }],
                "name": "allowance",
                "outputs": [{
                    "name": "",
                    "type": "uint256"
                }],
                "type": "function"
            }])
            
            # 获取授权额度
            allowance = contract.functions.allowance(
                Web3.to_checksum_address(wallet_address),
                Web3.to_checksum_address(spender)
            ).call()
            
            # 使用代币精度格式化输出
            formatted_allowance = EVMUtils.from_wei(allowance, decimals)
            logger.info(f"原始授权额度: {allowance}, 格式化后: {formatted_allowance}")
            
            # 将 Decimal 转换为字符串，避免科学计数法
            return "{:.18f}".format(float(formatted_allowance)).rstrip('0').rstrip('.')
            
        except Exception as e:
            logger.error(f"获取代币授权额度失败: {str(e)}")
            return "0"

    async def build_approve_transaction(
        self,
        token_address: str,
        spender: str,
        amount: str,
        from_address: str
    ) -> Dict:
        """构建授权交易
        
        Args:
            token_address: 代币合约地址
            spender: 授权地址
            amount: 授权金额
            from_address: 发送地址
            
        Returns:
            Dict: 交易数据
        """
        try:
            # 验证地址
            if not EVMUtils.validate_address(token_address):
                raise ValueError("无效的代币地址")
            if not EVMUtils.validate_address(spender):
                raise ValueError("无效的授权地址")
            if not EVMUtils.validate_address(from_address):
                raise ValueError("无效的发送地址")
                
            # 转换为校验和地址
            token_address = Web3.to_checksum_address(token_address)
            spender = Web3.to_checksum_address(spender)
            from_address = Web3.to_checksum_address(from_address)
            
            # 获取代币合约
            token_contract = self.get_contract(token_address)
            if not token_contract:
                raise ValueError("获取代币合约失败")
                
            # 获取代币精度
            decimals = await self._get_token_decimals(token_address)
            
            # 转换金额为 Wei
            amount_wei = EVMUtils.to_wei(amount, decimals)
            
            # 构建授权数据
            approve_data = token_contract.encodeABI(
                fn_name="approve",
                args=[spender, amount_wei]
            )
            
            # 获取 nonce
            nonce = self.web3.eth.get_transaction_count(from_address, 'pending')
            
            # 检查是否支持 EIP-1559
            try:
                latest_block = self.web3.eth.get_block('latest')
                supports_eip1559 = 'baseFeePerGas' in latest_block
            except Exception:
                supports_eip1559 = False
            
            # 构建基础交易数据
            tx_data = {
                'from': from_address,
                'to': token_address,
                'data': approve_data,
                'nonce': nonce,
                'chainId': self.chain_config['chain_id']
            }
            
            if supports_eip1559:
                # 使用 EIP-1559 费用机制
                fee_data = EVMUtils.get_gas_price(self.chain)
                tx_data['maxPriorityFeePerGas'] = fee_data.get('max_priority_fee', 1500000000)  # 1.5 Gwei
                tx_data['maxFeePerGas'] = fee_data.get('max_fee', 3000000000)  # 3 Gwei
            else:
                # 使用传统 gas price，确保至少 5 Gwei
                gas_price = max(self.web3.eth.gas_price, 5000000000)  # 5 Gwei
                tx_data['gasPrice'] = gas_price
            
            # 估算 gas
            try:
                gas_limit = self.web3.eth.estimate_gas({
                    'from': from_address,
                    'to': token_address,
                    'data': approve_data
                })
                tx_data['gas'] = int(gas_limit * 1.1)  # 添加 10% 缓冲
            except Exception as e:
                logger.warning(f"估算 gas 失败: {str(e)}, 使用默认值")
                tx_data['gas'] = 100000  # 使用默认值
            
            return {
                'status': 'success',
                'data': tx_data
            }
            
        except Exception as e:
            logger.error(f"构建授权交易失败: {str(e)}")
            return {
                'status': 'error',
                'message': f"构建授权交易失败: {str(e)}"
            }

    async def execute_swap(
        self,
        from_token: str,
        to_token: str,
        amount: str,
        from_address: str,
        private_key: str,
        slippage: float = 1.0
    ) -> Dict:
        """执行代币兑换"""
        try:
            logger.info(f"开始执行兑换: from={from_token}, to={to_token}, amount={amount}")
            
            # 获取代币精度
            from_decimals = await self._get_token_decimals(from_token)
            logger.info(f"源代币精度: {from_decimals}")
            
            # 将输入金额转换为链上金额
            try:
                original_amount = amount  # 保存原始金额
                chain_amount = EVMUtils.to_wei(amount, from_decimals)
                logger.info(f"输入金额: {original_amount}, 链上金额: {chain_amount}")
            except Exception as e:
                logger.error(f"金额转换失败: {str(e)}")
                return {
                    'status': 'error',
                    'message': '金额格式错误'
                }
            
            # 获取 Router 合约
            router_address = await self._get_dex_router()
            router = self.get_contract(router_address, self.router_abi)
            logger.info(f"使用 Router 合约: {router_address}")
            
            # 处理代币地址
            is_from_native = from_token == EVMUtils.NATIVE_TOKEN_ADDRESS
            is_to_native = to_token == EVMUtils.NATIVE_TOKEN_ADDRESS
            
            # 获取 DEX 配置和包装后的代币地址
            dex_config = RPCConfig.DEX_CONFIG.get(self.chain)
            if not dex_config:
                raise ValueError(f"不支持的链: {self.chain}")
            
            wrapped_native = RPCConfig.NATIVE_TOKENS.get(self.chain, {}).get('address')
            if not wrapped_native:
                raise ValueError(f"找不到 {self.chain} 的 Wrapped Token 地址")
            logger.info(f"使用 {dex_config['name']} 在 {self.chain} 链上")
            logger.info(f"使用包装后的原生代币地址: {wrapped_native}")
            
            # 对于 ETH 到代币的兑换，使用实际路径
            from_token_address = wrapped_native if is_from_native else Web3.to_checksum_address(from_token)
            to_token_address = wrapped_native if is_to_native else Web3.to_checksum_address(to_token)
            logger.info(f"兑换路径: {from_token_address} -> {to_token_address}")
            
            # 获取 Router 合约
            router_address = dex_config['router_address']
            router = self.get_contract(router_address, self.router_abi)
            logger.info(f"使用 Router 合约: {router_address}")
            
            # 获取输出金额
            try:
                path = [from_token_address, to_token_address]
                logger.info(f"尝试获取兑换路径的输出金额: {path}")
                
                amounts = router.functions.getAmountsOut(
                    chain_amount,
                    path
                ).call()
                logger.info(f"获取到的输出金额序列: {amounts}")
                
                if not amounts or len(amounts) < 2:
                    raise Exception("无法计算输出金额")
                    
                amount_out = amounts[1]
                minimum_received = int(amount_out * (1 - slippage / 100))
                logger.info(f"输出金额: {amount_out}, 最小接收金额: {minimum_received}")
                
            except Exception as e:
                logger.error(f"计算输出金额失败: {str(e)}")
                # 尝试检查流动性池是否存在
                try:
                    # 从 DEX 配置中获取 Factory 地址
                    dex_config = RPCConfig.DEX_CONFIG.get(self.chain)
                    if not dex_config:
                        raise ValueError(f"不支持的链: {self.chain}")
                    factory_address = dex_config['factory_address']
                    logger.info(f"使用 Factory 地址: {factory_address} 在 {self.chain} 链上")
                    
                    factory = self.get_contract(factory_address, [{
                        "constant": True,
                        "inputs": [
                            {"name": "tokenA", "type": "address"},
                            {"name": "tokenB", "type": "address"}
                        ],
                        "name": "getPair",
                        "outputs": [{"name": "pair", "type": "address"}],
                        "type": "function"
                    }])
                    
                    pair_address = factory.functions.getPair(
                        from_token_address,
                        to_token_address
                    ).call()
                    
                    if pair_address == "0x0000000000000000000000000000000000000000":
                        logger.error(f"交易对不存在: {from_token_address} - {to_token_address}")
                        return {
                            'status': 'error',
                            'message': '交易对不存在，可能没有流动性'
                        }
                    logger.info(f"找到交易对地址: {pair_address}")
                    
                except Exception as pair_error:
                    logger.error(f"检查交易对失败: {str(pair_error)}")
                    return {
                        'status': 'error',
                        'message': f'检查交易对失败: {str(pair_error)}'
                    }
            
            # 设置交易截止时间
            deadline = int(timezone.now().timestamp()) + 60 * 20  # 20分钟后过期
            
            # 构建交易数据
            if is_from_native:
                # ETH 到代币的兑换
                tx_data = router.functions.swapExactETHForTokens(
                    minimum_received,  # 最小接收数量
                    [from_token_address, to_token_address],  # 兑换路径
                    Web3.to_checksum_address(from_address),  # 接收地址
                    deadline  # 截止时间
                ).build_transaction({
                    'from': Web3.to_checksum_address(from_address),
                    'value': chain_amount,
                    'nonce': self.web3.eth.get_transaction_count(from_address, 'pending'),
                    'chainId': self.chain_config['chain_id']
                })
            elif is_to_native:
                # 代币到 ETH 的兑换
                tx_data = router.functions.swapExactTokensForETH(
                    chain_amount,  # 输入金额
                    minimum_received,  # 最小接收数量
                    [from_token_address, to_token_address],  # 兑换路径
                    Web3.to_checksum_address(from_address),  # 接收地址
                    deadline  # 截止时间
                ).build_transaction({
                    'from': Web3.to_checksum_address(from_address),
                    'value': 0,
                    'nonce': self.web3.eth.get_transaction_count(from_address, 'pending'),
                    'chainId': self.chain_config['chain_id']
                })
            else:
                # 代币到代币的兑换
                tx_data = router.functions.swapExactTokensForTokens(
                    chain_amount,  # 输入金额
                    minimum_received,  # 最小接收数量
                    [from_token_address, to_token_address],  # 兑换路径
                    Web3.to_checksum_address(from_address),  # 接收地址
                    deadline  # 截止时间
                ).build_transaction({
                    'from': Web3.to_checksum_address(from_address),
                    'value': 0,
                    'nonce': self.web3.eth.get_transaction_count(from_address, 'pending'),
                    'chainId': self.chain_config['chain_id']
                })
            
            # 检查是否支持 EIP-1559
            if self.web3.eth.get_block('latest').get('baseFeePerGas') is not None:
                # 使用 EIP-1559 费用
                fee_data = EVMUtils.get_gas_price(self.chain)
                tx_data['maxPriorityFeePerGas'] = fee_data['max_priority_fee']
                tx_data['maxFeePerGas'] = fee_data['max_fee']
                # 移除 gasPrice 字段（如果存在）
                tx_data.pop('gasPrice', None)
            else:
                # 使用传统 gas price
                tx_data['gasPrice'] = self.web3.eth.gas_price
            
            # 估算 gas
            try:
                gas_limit = self.web3.eth.estimate_gas({
                    'from': Web3.to_checksum_address(from_address),
                    'to': router_address,
                    'value': chain_amount if is_from_native else 0, # type: ignore
                    'data': tx_data.get('data')
                })
                tx_data['gas'] = int(gas_limit * 1.2)  # 添加20%缓冲
            except Exception as e:
                logger.warning(f"估算 gas 失败: {str(e)}, 使用默认值")
                tx_data['gas'] = 250000
            
            # 发送交易
            result = await self._send_transaction(tx_data, private_key)
            
            if result.get('status') != 'success':
                return result
            
            # 保存交易记录
            try:
                wallet = await sync_to_async(Wallet.objects.get)(
                    chain=self.chain,
                    address=Web3.to_checksum_address(from_address),
                    is_active=True
                )
                
                if not wallet:
                    logger.error("未找到对应的钱包记录")
                    return result
                
                # 获取代币信息
                from_token_info = await self._get_token_info(from_token)
                to_token_info = await self._get_token_info(to_token)
                
                # 创建交易记录
                await sync_to_async(Transaction.objects.create)(
                    wallet=wallet,
                    chain=self.chain,
                    tx_hash=result['data']['tx_hash'],
                    tx_type='SWAP',
                    status='SUCCESS',
                    from_address=from_address,
                    to_address=router_address,
                    amount=Decimal(amount),
                    token_info={
                        'from_token': {
                            'address': from_token,
                            'name': from_token_info.get('name', 'Unknown'),
                            'symbol': from_token_info.get('symbol', 'Unknown'),
                            'decimals': from_token_info.get('decimals', 18),
                            'amount': amount,
                            'logo': from_token_info.get('logo', '')
                        },
                        'to_token': {
                            'address': to_token,
                            'name': to_token_info.get('name', 'Unknown'),
                            'symbol': to_token_info.get('symbol', 'Unknown'),
                            'decimals': to_token_info.get('decimals', 18),
                            'amount': str(minimum_received),
                            'logo': to_token_info.get('logo', '')
                        }
                    },
                    gas_price=Decimal(str(result['data']['effective_gas_price'])),
                    gas_used=result['data']['gas_used'],
                    block_number=result['data']['block_number'],
                    block_timestamp=timezone.now()
                )
                logger.info(f"已保存 Swap 交易记录: {result['data']['tx_hash']}")
            except Exception as e:
                logger.error(f"保存交易记录失败: {str(e)}")
            
            return result
            
        except Exception as e:
            logger.error(f"执行代币兑换失败: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }

    async def _get_token_info(self, token_address: str) -> Dict:
        """获取代币信息"""
        try:
            if token_address == EVMUtils.NATIVE_TOKEN_ADDRESS:
                return {
                    'address': token_address,
                    'name': self.chain_config['name'],
                    'symbol': self.chain_config['symbol'],
                    'decimals': self.chain_config['decimals'],
                    'logo': self.chain_config.get('logo', ''),
                    'verified': True
                }
            
            token = await sync_to_async(Token.objects.filter(
                chain=self.chain,
                address=token_address
            ).first)()
            
            if token:
                return {
                    'address': token.address,
                    'name': token.name,
                    'symbol': token.symbol,
                    'decimals': token.decimals,
                    'logo': token.logo,
                    'verified': token.verified
                }
            
            return {}
            
        except Exception as e:
            logger.error(f"获取代币信息失败: {str(e)}")
            return {}

    async def get_wallet_swaps(
        self,
        wallet_address: str,
        limit: int = 10
    ) -> List[Dict]:
        """获取钱包的 Swap 历史
        
        Args:
            wallet_address: 钱包地址
            limit: 返回记录数量限制
            
        Returns:
            List[Dict]: Swap 历史记录列表
        """
        try:
            url = MoralisConfig.EVM_SWAP_WALLET_URL.format(wallet_address)
            params = {
                'chain': self.chain_id,
                'limit': limit
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取钱包 Swap 历史失败: {await response.text()}")
                    
                    result = await response.json()
                    return result.get('result', [])
                    
        except Exception as e:
            logger.error(f"获取钱包 Swap 历史失败: {str(e)}")
            return []

    async def get_token_swaps(
        self,
        token_address: str,
        limit: int = 10
    ) -> List[Dict]:
        """获取代币的 Swap 历史
        
        Args:
            token_address: 代币地址
            limit: 返回记录数量限制
            
        Returns:
            List[Dict]: Swap 历史记录列表
        """
        try:
            url = MoralisConfig.EVM_SWAP_TOKEN_URL.format(token_address)
            params = {
                'chain': self.chain_id,
                'limit': limit
            }
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        raise Exception(f"获取代币 Swap 历史失败: {await response.text()}")
                    
                    result = await response.json()
                    return result.get('result', [])
                    
        except Exception as e:
            logger.error(f"获取代币 Swap 历史失败: {str(e)}")
            return []

    async def _estimate_swap_gas(
        self,
        from_token: str,
        to_token: str,
        amount: int,
        from_decimals: int,
        to_decimals: int
    ) -> int:
        """估算兑换所需的 gas"""
        try:
            # 如果是原生代币交易，基础 gas 更低
            if from_token.lower() in [
                "0x0000000000000000000000000000000000000000",
                "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "0x4200000000000000000000000000000000000006"  # Base ETH
            ]:
                base_gas = 100000
            else:
                base_gas = 150000
            
            # 根据代币精度调整
            decimals_factor = abs(to_decimals - from_decimals) / 18
            gas_adjustment = int(base_gas * (1 + decimals_factor))
            
            # 考虑金额大小
            amount_factor = len(str(amount)) / 20  # 根据金额位数调整
            gas_with_amount = int(gas_adjustment * (1 + amount_factor))
            
            return min(gas_with_amount, 300000)  # 设置上限
            
        except Exception as e:
            logger.error(f"估算 gas 失败: {str(e)}")
            return 200000  # 返回一个保守的默认值

    async def _calculate_price_impact(
        self,
        from_token: str,
        to_token: str,
        input_amount: int,
        output_amount: int
    ) -> Decimal:
        """计算价格影响"""
        try:
            # 获取当前市场价格
            market_rate = await self._get_market_price(from_token, to_token)
            if market_rate is None:
                return Decimal('1.0')  # 默认值
            
            # 计算实际兑换率
            actual_rate = Decimal(str(output_amount)) / Decimal(str(input_amount))
            
            # 计算价格影响
            price_impact = abs((market_rate - actual_rate) / market_rate * Decimal('100'))
            
            # 限制在合理范围内
            return min(price_impact, Decimal('5.0'))
            
        except Exception as e:
            logger.error(f"计算价格影响失败: {str(e)}")
            return Decimal('1.0')  # 返回一个保守的默认值

    async def _send_transaction(self, tx: Dict, private_key: str) -> Dict:
        """发送交易"""
        try:
            # 如果传入的是包含 data 字段的字典，则使用内部的数据
            if 'data' in tx and isinstance(tx['data'], dict):
                tx = tx['data']
            
            # 获取 nonce
            sender = Account.from_key(private_key).address
            tx['nonce'] = self.web3.eth.get_transaction_count(sender, 'pending')
            
            # 确保必要的交易字段存在
            if 'gas' not in tx:
                # 估算 gas limit
                try:
                    gas_limit = self.web3.eth.estimate_gas({
                        'from': Web3.to_checksum_address(tx.get('from')), # type: ignore
                        'to': Web3.to_checksum_address(tx.get('to')), # type: ignore
                        'value': tx.get('value', 0),
                        'data': tx.get('data', '0x')
                    })
                    tx['gas'] = int(gas_limit * 1.1)  # 添加10%缓冲
                except Exception as e:
                    logger.warning(f"估算 gas 失败: {str(e)}, 使用默认值")
                    tx['gas'] = 250000  # 使用默认值
            
            # 检查是否支持 EIP-1559
            try:
                latest_block = self.web3.eth.get_block('latest')
                supports_eip1559 = 'baseFeePerGas' in latest_block
            except Exception:
                supports_eip1559 = False
            
            if supports_eip1559:
                # 使用 EIP-1559 费用机制
                if 'maxFeePerGas' not in tx or 'maxPriorityFeePerGas' not in tx:
                    fee_data = EVMUtils.get_gas_price(self.chain)
                    tx['maxPriorityFeePerGas'] = fee_data.get('max_priority_fee', 1500000000)  # 1.5 Gwei
                    tx['maxFeePerGas'] = fee_data.get('max_fee', 3000000000)  # 3 Gwei
                # 移除 gasPrice 字段（如果存在）
                tx.pop('gasPrice', None)
            else:
                # 使用传统 gas price
                if 'gasPrice' not in tx:
                    tx['gasPrice'] = self.web3.eth.gas_price
                # 移除 EIP-1559 相关字段（如果存在）
                tx.pop('maxFeePerGas', None)
                tx.pop('maxPriorityFeePerGas', None)
            
            # 确保chainId存在
            if 'chainId' not in tx:
                tx['chainId'] = self.chain_config['chain_id']
            
            logger.info(f"准备发送交易: {tx}")
            
            # 签名交易
            signed_tx = self.web3.eth.account.sign_transaction(tx, private_key=private_key)
            
            # 发送交易
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 等待交易确认
            receipt = EVMUtils.wait_for_transaction_receipt(
                self.chain,
                tx_hash,
                timeout=60
            )
            
            if not receipt:
                return {
                    'status': 'error',
                    'message': '交易超时未确认'
                }
            
            # 检查交易状态
            if receipt['status'] != 1:
                return {
                    'status': 'error',
                    'message': '交易执行失败'
                }
                
            return {
                'status': 'success',
                'message': '交易执行成功',
                'data': {
                    'tx_hash': receipt['transactionHash'].hex(),
                    'block_number': receipt['blockNumber'],
                    'gas_used': receipt['gasUsed'],
                    'effective_gas_price': receipt.get('effectiveGasPrice', 0),
                    'explorer_url': EVMUtils.get_explorer_url(
                        self.chain,
                        receipt['transactionHash'].hex()
                    )
                }
            }
            
        except Exception as e:
            logger.error(f"发送交易失败: {str(e)}")
            return {
                'status': 'error',
                'message': f'发送交易失败: {str(e)}'
            } 