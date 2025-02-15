"""EVM 转账服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from asgiref.sync import sync_to_async

from ...models import Wallet, Transaction
from ...api_config import RPCConfig
from ...exceptions import InsufficientBalanceError, InvalidAddressError, TransferError
from .utils import EVMUtils

logger = logging.getLogger(__name__)

class EVMTransferService:
    """EVM 转账服务实现类"""

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        
        # Alchemy API 配置
        self.api_url = RPCConfig.get_alchemy_url(chain)
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def transfer_native(self, from_address: str, to_address: str, amount: Decimal, private_key: str) -> Dict[str, Any]:
        """转账原生代币
        
        Args:
            from_address: 发送地址
            to_address: 接收地址
            amount: 金额
            private_key: 私钥
            
        Returns:
            Dict: {
                'success': 是否成功,
                'transaction_hash': 交易哈希,
                'block_hash': 区块哈希,
                'fee': 手续费
            }
        """
        try:
            # 验证地址
            if not EVMUtils.validate_address(to_address):
                raise InvalidAddressError("无效的接收地址")
                
            # 获取账户余额
            balance = await self.web3.eth.get_balance(from_address)
            balance_eth = EVMUtils.from_wei(balance)
            logger.info(f"账户余额: {balance_eth} {self.chain_config['symbol']}")
            
            # 检查余额是否足够
            amount_wei = EVMUtils.to_wei(amount)
            if balance < amount_wei:
                raise InsufficientBalanceError("余额不足")
                
            # 获取 nonce
            nonce = await self.web3.eth.get_transaction_count(from_address)
            
            # 获取 gas 价格
            gas_price = await self.web3.eth.gas_price
            
            # 估算 gas limit
            gas_limit = EVMUtils.estimate_gas_limit(
                self.chain,
                to_address,
                amount_wei
            )
            
            # 构建交易
            transaction = {
                'nonce': nonce,
                'gasPrice': gas_price,
                'gas': gas_limit,
                'to': to_address,
                'value': amount_wei,
                'data': b'',
                'chainId': self.chain_config['chain_id']
            }
            
            # 签名交易
            signed = self.web3.eth.account.sign_transaction(transaction, private_key)
            
            # 发送交易
            tx_hash = await self.web3.eth.send_raw_transaction(signed.rawTransaction)
            
            # 等待交易确认
            receipt = await self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            # 保存交易记录
            await self._save_transaction(
                wallet_address=from_address,
                to_address=to_address,
                amount=amount,
                token_address=None,
                tx_hash=tx_hash.hex(),
                tx_info={
                    'block_hash': receipt['blockHash'].hex(),
                    'gas_used': receipt['gasUsed'],
                    'gas_price': gas_price,
                    'status': receipt['status']
                }
            )
            
            return {
                'success': receipt['status'] == 1,
                'transaction_hash': tx_hash.hex(),
                'block_hash': receipt['blockHash'].hex(),
                'fee': str(EVMUtils.from_wei(gas_price * receipt['gasUsed']))
            }
            
        except Exception as e:
            logger.error(f"转账失败: {str(e)}")
            raise TransferError(f"转账失败: {str(e)}")

    async def transfer_token(self, from_address: str, to_address: str, token_address: str, amount: Decimal, private_key: str) -> Dict[str, Any]:
        """转账代币
        
        Args:
            from_address: 发送地址
            to_address: 接收地址
            token_address: 代币合约地址
            amount: 金额
            private_key: 私钥
            
        Returns:
            Dict: {
                'success': 是否成功,
                'transaction_hash': 交易哈希,
                'block_hash': 区块哈希,
                'fee': 手续费
            }
        """
        try:
            # 验证地址
            if not EVMUtils.validate_address(to_address):
                raise InvalidAddressError("无效的接收地址")
            if not EVMUtils.validate_address(token_address):
                raise InvalidAddressError("无效的代币地址")
                
            # 获取代币合约
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=[{
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
                }]
            )
            
            # 获取代币精度
            decimals = await contract.functions.decimals().call()
            
            # 获取代币余额
            balance = await contract.functions.balanceOf(from_address).call()
            balance_token = EVMUtils.from_wei(balance, decimals)
            logger.info(f"代币余额: {balance_token}")
            
            # 检查余额是否足够
            amount_wei = EVMUtils.to_wei(amount, decimals)
            if balance < amount_wei:
                raise InsufficientBalanceError("代币余额不足")
                
            # 获取 nonce
            nonce = await self.web3.eth.get_transaction_count(from_address)
            
            # 获取 gas 价格
            gas_price = await self.web3.eth.gas_price
            
            # 构建交易数据
            transfer_data = contract.encodeABI(
                fn_name="transfer",
                args=[to_address, amount_wei]
            )
            
            # 估算 gas limit
            gas_limit = EVMUtils.estimate_gas_limit(
                self.chain,
                token_address,
                0,
                transfer_data
            )
            
            # 构建交易
            transaction = {
                'nonce': nonce,
                'gasPrice': gas_price,
                'gas': gas_limit,
                'to': token_address,
                'value': 0,
                'data': transfer_data,
                'chainId': self.chain_config['chain_id']
            }
            
            # 签名交易
            signed = self.web3.eth.account.sign_transaction(transaction, private_key)
            
            # 发送交易
            tx_hash = await self.web3.eth.send_raw_transaction(signed.rawTransaction)
            
            # 等待交易确认
            receipt = await self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            # 保存交易记录
            await self._save_transaction(
                wallet_address=from_address,
                to_address=to_address,
                amount=amount,
                token_address=token_address,
                tx_hash=tx_hash.hex(),
                tx_info={
                    'block_hash': receipt['blockHash'].hex(),
                    'gas_used': receipt['gasUsed'],
                    'gas_price': gas_price,
                    'status': receipt['status']
                }
            )
            
            return {
                'success': receipt['status'] == 1,
                'transaction_hash': tx_hash.hex(),
                'block_hash': receipt['blockHash'].hex(),
                'fee': str(EVMUtils.from_wei(gas_price * receipt['gasUsed']))
            }
            
        except Exception as e:
            logger.error(f"代币转账失败: {str(e)}")
            raise TransferError(f"代币转账失败: {str(e)}")

    async def estimate_native_transfer_fee(self, from_address: str, to_address: str, amount: Decimal) -> Decimal:
        """估算原生代币转账费用"""
        try:
            # 获取 gas 价格
            gas_price = await self.web3.eth.gas_price
            
            # 估算 gas limit
            gas_limit = EVMUtils.estimate_gas_limit(
                self.chain,
                to_address,
                EVMUtils.to_wei(amount)
            )
            
            # 计算费用
            fee = gas_price * gas_limit
            return EVMUtils.from_wei(fee)
            
        except Exception as e:
            logger.error(f"估算转账费用失败: {str(e)}")
            return Decimal('0')

    async def estimate_token_transfer_fee(self, from_address: str, to_address: str, token_address: str, amount: Decimal) -> Decimal:
        """估算代币转账费用"""
        try:
            # 获取代币合约
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=[{
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
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "type": "function"
                }]
            )
            
            # 获取代币精度
            decimals = await contract.functions.decimals().call()
            
            # 构建交易数据
            transfer_data = contract.encodeABI(
                fn_name="transfer",
                args=[to_address, EVMUtils.to_wei(amount, decimals)]
            )
            
            # 获取 gas 价格
            gas_price = await self.web3.eth.gas_price
            
            # 估算 gas limit
            gas_limit = EVMUtils.estimate_gas_limit(
                self.chain,
                token_address,
                0,
                transfer_data
            )
            
            # 计算费用
            fee = gas_price * gas_limit
            return EVMUtils.from_wei(fee)
            
        except Exception as e:
            logger.error(f"估算代币转账费用失败: {str(e)}")
            return Decimal('0')

    async def _save_transaction(self, wallet_address: str, to_address: str, amount: Decimal,
                              token_address: Optional[str], tx_hash: str, tx_info: Dict[str, Any]) -> None:
        """保存交易记录"""
        try:
            # 获取钱包
            wallet = await sync_to_async(Wallet.objects.get)(
                address=wallet_address,
                chain=self.chain,
                is_active=True
            )
            
            # 创建交易记录
            await sync_to_async(Transaction.objects.create)(
                wallet=wallet,
                chain=self.chain,
                tx_hash=tx_hash,
                tx_type='TRANSFER',
                status='SUCCESS' if tx_info.get('status') == 1 else 'FAILED',
                from_address=wallet_address,
                to_address=to_address,
                amount=amount,
                token_address=token_address,
                gas_price=EVMUtils.from_wei(tx_info['gas_price']),
                gas_used=tx_info['gas_used'],
                block_number=0,  # TODO: 添加区块号
                block_timestamp=None  # TODO: 添加区块时间
            )
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            # 不抛出异常，因为转账已经成功了 