"""EVM 转账服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from asgiref.sync import sync_to_async
from django.utils import timezone

from ...models import Wallet, Transaction, Token
from ..evm_config import RPCConfig
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

    async def transfer(
        self,
        from_address: str,
        to_address: str,
        amount: str,
        private_key: str,
        gas_limit: Optional[int] = None,
        gas_price: Optional[int] = None,
        max_priority_fee: Optional[int] = None,
        max_fee: Optional[int] = None
    ) -> Dict:
        """转账原生代币
        
        Args:
            from_address: 发送方地址
            to_address: 接收方地址
            amount: 转账金额(已包含精度)
            private_key: 发送方私钥
            gas_limit: 可选，自定义 gas limit
            gas_price: 可选，自定义 gas price (Legacy)
            max_priority_fee: 可选，最大优先费用 (EIP-1559)
            max_fee: 可选，最大总费用 (EIP-1559)
            
        Returns:
            Dict: {
                'status': 'success' | 'error',
                'message': str,
                'data': {
                    'tx_hash': str,
                    'block_number': int,
                    'gas_used': int,
                    'effective_gas_price': int,
                    'explorer_url': str
                }
            }
        """
        try:
            # 验证地址
            if not EVMUtils.validate_address(from_address):
                return {
                    'status': 'error',
                    'message': f'无效的发送方地址: {from_address}'
                }
            if not EVMUtils.validate_address(to_address):
                return {
                    'status': 'error', 
                    'message': f'无效的接收方地址: {to_address}'
                }
                
            # 获取 nonce
            nonce = self.web3.eth.get_transaction_count(
                Web3.to_checksum_address(from_address),
                'pending'
            )
            
            # 准备交易参数
            tx_params = {
                'nonce': nonce,
                'from': Web3.to_checksum_address(from_address),
                'to': Web3.to_checksum_address(to_address),
                'value': EVMUtils.to_wei(amount),
                'chainId': self.chain_config['chain_id']
            }
            
            # 设置 gas limit
            if gas_limit:
                tx_params['gas'] = gas_limit
            else:
                # 估算 gas limit
                tx_params['gas'] = EVMUtils.estimate_gas_limit(
                    self.chain,
                    to_address,
                    value=int(amount)
                )
            
            # 检查是否支持 EIP-1559
            if self.web3.eth.get_block('latest').get('baseFeePerGas') is not None:
                # 使用 EIP-1559 费用
                if max_priority_fee and max_fee:
                    tx_params['maxPriorityFeePerGas'] = max_priority_fee
                    tx_params['maxFeePerGas'] = max_fee
                else:
                    # 获取建议费用
                    fee_data = EVMUtils.get_gas_price(self.chain)
                    tx_params['maxPriorityFeePerGas'] = fee_data['max_priority_fee']
                    tx_params['maxFeePerGas'] = fee_data['max_fee']
            else:
                # 使用传统 gas price
                if gas_price:
                    tx_params['gasPrice'] = gas_price
                else:
                    tx_params['gasPrice'] = self.web3.eth.gas_price
            
            # 签名交易
            signed_tx = self.web3.eth.account.sign_transaction(
                tx_params,
                private_key=private_key
            )
            
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
            
            # 获取交易浏览器链接
            explorer_url = EVMUtils.get_explorer_url(self.chain, receipt['transactionHash'].hex())
            
            # 保存交易记录
            try:
                # 获取发送方钱包
                sender_wallet = await sync_to_async(Wallet.objects.get)(
                    address=from_address,
                    chain=self.chain,
                    is_active=True
                )
                
                # 获取接收方钱包（如果存在）
                receiver_wallet = await sync_to_async(lambda: Wallet.objects.filter(
                    address=to_address,
                    chain=self.chain,
                    is_active=True
                ).first())()
                
                # 获取区块时间
                block = await sync_to_async(lambda: self.web3.eth.get_block(receipt['blockNumber']))()
                block_timestamp = block.get('timestamp', None)
                
                # 获取原生代币信息
                native_token = self.chain_config['native_token']
                token_info = {
                    'name': native_token['name'],
                    'symbol': native_token['symbol'],
                    'decimals': native_token['decimals'],
                    'logo': native_token.get('logo', ''),
                    'address': native_token['address'],
                    'thumbnail': native_token.get('thumbnail', ''),
                    'verified': True
                }
                
                # 创建交易记录，使用 get_or_create 避免重复
                tx_data = {
                    'tx_type': 'TRANSFER',
                    'status': 'SUCCESS' if receipt['status'] == 1 else 'FAILED',
                    'from_address': from_address,
                    'to_address': to_address,
                    'amount': EVMUtils.from_wei(int(amount)),
                    'token_info': token_info,
                    'gas_price': EVMUtils.from_wei(receipt.get('effectiveGasPrice', 0)),
                    'gas_used': receipt['gasUsed'],
                    'block_number': receipt['blockNumber'],
                    'block_timestamp': timezone.datetime.fromtimestamp(block_timestamp, tz=timezone.utc) if block_timestamp else None
                }
                
                # 为发送方创建交易记录
                await sync_to_async(Transaction.objects.get_or_create)(
                    chain=self.chain,
                    tx_hash=receipt['transactionHash'].hex(),
                    wallet=sender_wallet,
                    defaults=tx_data
                )
                logger.info(f"保存发送方交易记录成功: tx_hash={receipt['transactionHash'].hex()}, amount={EVMUtils.from_wei(int(amount))}")
                
                # 如果接收方钱包存在，也创建交易记录
                if receiver_wallet:
                    await sync_to_async(Transaction.objects.get_or_create)(
                        chain=self.chain,
                        tx_hash=receipt['transactionHash'].hex(),
                        wallet=receiver_wallet,
                        defaults=tx_data
                    )
                    logger.info(f"保存接收方交易记录成功: tx_hash={receipt['transactionHash'].hex()}, amount={EVMUtils.from_wei(int(amount))}")
                
            except Exception as e:
                logger.error(f"保存交易记录失败: {str(e)}")
                # 不影响转账结果，继续返回成功
            
            return {
                'status': 'success',
                'message': '转账成功',
                'data': {
                    'tx_hash': receipt['transactionHash'].hex(),
                    'block_number': receipt['blockNumber'],
                    'gas_used': receipt['gasUsed'],
                    'effective_gas_price': receipt.get('effectiveGasPrice', 0),
                    'explorer_url': explorer_url
                }
            }
            
        except Exception as e:
            logger.error(f"转账失败: {str(e)}")
            return {
                'status': 'error',
                'message': f"转账失败: {str(e)}"
            }

    async def transfer_token(
        self,
        from_address: str,
        to_address: str,
        token_address: str,
        amount: str,
        private_key: str,
        gas_limit: Optional[int] = None,
        gas_price: Optional[int] = None,
        max_priority_fee: Optional[int] = None,
        max_fee: Optional[int] = None
    ) -> Dict:
        """转账 ERC20 代币
        
        Args:
            from_address: 发送方地址
            to_address: 接收方地址
            token_address: 代币合约地址
            amount: 转账金额(已包含精度)
            private_key: 发送方私钥
            gas_limit: 可选，自定义 gas limit
            gas_price: 可选，自定义 gas price (Legacy)
            max_priority_fee: 可选，最大优先费用 (EIP-1559)
            max_fee: 可选，最大总费用 (EIP-1559)
            
        Returns:
            Dict: {
                'status': 'success' | 'error',
                'message': str,
                'data': {
                    'tx_hash': str,
                    'block_number': int,
                    'gas_used': int,
                    'effective_gas_price': int,
                    'explorer_url': str
                }
            }
        """
        try:
            # 验证地址
            if not EVMUtils.validate_address(from_address):
                return {
                    'status': 'error',
                    'message': f'无效的发送方地址: {from_address}'
                }
            if not EVMUtils.validate_address(to_address):
                return {
                    'status': 'error',
                    'message': f'无效的接收方地址: {to_address}'
                }
            if not EVMUtils.validate_address(token_address):
                return {
                    'status': 'error',
                    'message': f'无效的代币地址: {token_address}'
                }
                
            # 获取代币合约
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=[{
                    "constant": False,
                    "inputs": [{
                        "name": "_to",
                        "type": "address"
                    }, {
                        "name": "_value",
                        "type": "uint256"
                    }],
                    "name": "transfer",
                    "outputs": [{
                        "name": "",
                        "type": "bool"
                    }],
                    "type": "function"
                }, {
                    "constant": True,
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{
                        "name": "",
                        "type": "uint8"
                    }],
                    "type": "function"
                }]
            )
            
            # 获取代币精度
            decimals = contract.functions.decimals().call()
            logger.info(f"代币精度: {decimals}, 原始金额: {amount}")
            
            # 将输入金额转换为链上金额
            chain_amount = EVMUtils.to_wei(amount, decimals)
            logger.info(f"链上金额: {chain_amount}")
            
            # 构建交易数据
            tx_data = contract.encodeABI(
                fn_name="transfer",
                args=[Web3.to_checksum_address(to_address), chain_amount]
            )
            
            # 获取 nonce
            nonce = self.web3.eth.get_transaction_count(
                Web3.to_checksum_address(from_address),
                'pending'
            )
            
            # 准备交易参数
            tx_params = {
                'nonce': nonce,
                'from': Web3.to_checksum_address(from_address),
                'to': Web3.to_checksum_address(token_address),
                'data': tx_data,
                'chainId': self.chain_config['chain_id']
            }
            
            # 设置 gas limit
            if gas_limit:
                tx_params['gas'] = gas_limit
            else:
                # 估算 gas limit
                tx_params['gas'] = EVMUtils.estimate_gas_limit(
                    self.chain,
                    token_address,
                    data=tx_data
                )
            
            # 检查是否支持 EIP-1559
            if self.web3.eth.get_block('latest').get('baseFeePerGas') is not None:
                # 使用 EIP-1559 费用
                if max_priority_fee and max_fee:
                    tx_params['maxPriorityFeePerGas'] = max_priority_fee
                    tx_params['maxFeePerGas'] = max_fee
                else:
                    # 获取建议费用
                    fee_data = EVMUtils.get_gas_price(self.chain)
                    tx_params['maxPriorityFeePerGas'] = fee_data['max_priority_fee']
                    tx_params['maxFeePerGas'] = fee_data['max_fee']
            else:
                # 使用传统 gas price
                if gas_price:
                    tx_params['gasPrice'] = gas_price
                else:
                    tx_params['gasPrice'] = self.web3.eth.gas_price
            
            # 签名交易
            signed_tx = self.web3.eth.account.sign_transaction(
                tx_params,
                private_key=private_key
            )
            
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
            
            # 获取交易浏览器链接
            explorer_url = EVMUtils.get_explorer_url(self.chain, receipt['transactionHash'].hex())
            
            # 保存交易记录
            try:
                # 获取发送方钱包
                sender_wallet = await sync_to_async(Wallet.objects.get)(
                    address=from_address,
                    chain=self.chain,
                    is_active=True
                )
                
                # 获取接收方钱包（如果存在）
                receiver_wallet = await sync_to_async(lambda: Wallet.objects.filter(
                    address=to_address,
                    chain=self.chain,
                    is_active=True
                ).first())()
                
                # 获取代币信息
                token_metadata = await self._get_token_metadata(token_address)
                
                # 获取或创建Token记录
                token_tuple = await sync_to_async(lambda: Token.objects.get_or_create(
                    chain=self.chain,
                    address=token_address,
                    defaults={
                        'name': token_metadata.get('name', ''),
                        'symbol': token_metadata.get('symbol', ''),
                        'decimals': decimals,
                        'logo': token_metadata.get('logo', ''),
                        'thumbnail': token_metadata.get('thumbnail', ''),
                        'verified': token_metadata.get('verified', False),
                        'type': 'token',
                        'contract_type': 'ERC20'
                    }
                ))()
                token = token_tuple[0]
                
                # 构建 token_info
                token_info = {
                    'name': token_metadata.get('name', ''),
                    'symbol': token_metadata.get('symbol', ''),
                    'decimals': decimals,
                    'logo': token_metadata.get('logo', ''),
                    'address': token_address,
                    'thumbnail': token_metadata.get('thumbnail', ''),
                    'verified': token_metadata.get('verified', False)
                }
                
                # 获取区块时间
                block = await sync_to_async(lambda: self.web3.eth.get_block(receipt['blockNumber']))()
                block_timestamp = block.get('timestamp', None)
                
                # 计算实际金额
                actual_amount = float(amount)  # 使用原始输入金额
                logger.info(f"格式化后金额: {actual_amount}")
                
                # 创建交易记录，使用 get_or_create 避免重复
                tx_data = {
                    'tx_type': 'TRANSFER',
                    'status': 'SUCCESS' if receipt['status'] == 1 else 'FAILED',
                    'from_address': from_address,
                    'to_address': to_address,
                    'amount': actual_amount,
                    'token': token,
                    'token_info': token_info,
                    'gas_price': EVMUtils.from_wei(receipt.get('effectiveGasPrice', 0)),
                    'gas_used': receipt['gasUsed'],
                    'block_number': receipt['blockNumber'],
                    'block_timestamp': timezone.datetime.fromtimestamp(block_timestamp, tz=timezone.utc) if block_timestamp else None
                }
                
                # 为发送方创建交易记录
                await sync_to_async(Transaction.objects.get_or_create)(
                    chain=self.chain,
                    tx_hash=receipt['transactionHash'].hex(),
                    wallet=sender_wallet,
                    defaults=tx_data
                )
                logger.info(f"保存发送方交易记录成功: tx_hash={receipt['transactionHash'].hex()}, amount={actual_amount}")
                
                # 如果接收方钱包存在，也创建交易记录
                if receiver_wallet:
                    await sync_to_async(Transaction.objects.get_or_create)(
                        chain=self.chain,
                        tx_hash=receipt['transactionHash'].hex(),
                        wallet=receiver_wallet,
                        defaults=tx_data
                    )
                    logger.info(f"保存接收方交易记录成功: tx_hash={receipt['transactionHash'].hex()}, amount={actual_amount}")
                
            except Exception as e:
                logger.error(f"保存交易记录失败: {str(e)}")
                # 不影响转账结果，继续返回成功
            
            return {
                'status': 'success',
                'message': '转账成功',
                'data': {
                    'tx_hash': receipt['transactionHash'].hex(),
                    'block_number': receipt['blockNumber'],
                    'gas_used': receipt['gasUsed'],
                    'effective_gas_price': receipt.get('effectiveGasPrice', 0),
                    'explorer_url': explorer_url
                }
            }
            
        except Exception as e:
            logger.error(f"代币转账失败: {str(e)}")
            return {
                'status': 'error',
                'message': f"转账失败: {str(e)}"
            }

    async def _get_token_metadata(self, token_address: str) -> Dict:
        """获取代币元数据"""
        try:
            # 首先尝试从数据库获取代币信息
            token = await sync_to_async(lambda: Token.objects.filter(
                chain=self.chain,
                address=token_address
            ).first())()
            
            if token:
                return {
                    'name': token.name,
                    'symbol': token.symbol,
                    'decimals': token.decimals,
                    'logo': token.logo or '',
                    'thumbnail': token.thumbnail or '',
                    'verified': token.verified
                }
            
            # 如果数据库中没有，则从合约获取基本信息
            name = await self._get_token_name(token_address)
            symbol = await self._get_token_symbol(token_address)
            
            return {
                'name': name,
                'symbol': symbol,
                'decimals': 18,  # 使用默认精度
                'logo': '',
                'thumbnail': '',
                'verified': False
            }
            
        except Exception as e:
            logger.error(f"获取代币元数据失败: {str(e)}")
            # 如果获取失败，返回基本信息
            return {
                'name': await self._get_token_name(token_address),
                'symbol': await self._get_token_symbol(token_address),
                'decimals': 18,
                'logo': '',
                'thumbnail': '',
                'verified': False
            }

    async def _get_token_name(self, token_address: str) -> str:
        """从合约获取代币名称"""
        try:
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=[{
                    "constant": True,
                    "inputs": [],
                    "name": "name",
                    "outputs": [{"name": "", "type": "string"}],
                    "type": "function"
                }]
            )
            return contract.functions.name().call()
        except Exception as e:
            logger.error(f"获取代币名称失败: {str(e)}")
            return ''

    async def _get_token_symbol(self, token_address: str) -> str:
        """从合约获取代币符号"""
        try:
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=[{
                    "constant": True,
                    "inputs": [],
                    "name": "symbol",
                    "outputs": [{"name": "", "type": "string"}],
                    "type": "function"
                }]
            )
            return contract.functions.symbol().call()
        except Exception as e:
            logger.error(f"获取代币符号失败: {str(e)}")
            return ''

    async def estimate_fee(
        self,
        from_address: str,
        to_address: str,
        amount: str,
        token_address: Optional[str] = None
    ) -> Dict:
        """估算转账费用
        
        Args:
            from_address: 发送方地址
            to_address: 接收方地址
            amount: 转账金额(已包含精度)
            token_address: 可选，代币合约地址，如果为 None 则估算原生代币转账费用
            
        Returns:
            Dict: {
                'status': 'success' | 'error',
                'message': str,
                'data': {
                    'gas_limit': int,
                    'gas_price': int | None,
                    'max_priority_fee': int | None,
                    'max_fee': int | None,
                    'estimated_fee': int
                }
            }
        """
        try:
            # 验证地址
            if not EVMUtils.validate_address(from_address):
                return {
                    'status': 'error',
                    'message': f'无效的发送方地址: {from_address}'
                }
            if not EVMUtils.validate_address(to_address):
                return {
                    'status': 'error',
                    'message': f'无效的接收方地址: {to_address}'
                }
            if token_address and not EVMUtils.validate_address(token_address):
                return {
                    'status': 'error',
                    'message': f'无效的代币地址: {token_address}'
                }
                
            if token_address:
                # 代币转账
                contract = self.web3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=[{
                        "constant": False,
                        "inputs": [{
                            "name": "_to",
                            "type": "address"
                        }, {
                            "name": "_value",
                            "type": "uint256"
                        }],
                        "name": "transfer",
                        "outputs": [{
                            "name": "",
                            "type": "bool"
                        }],
                        "type": "function"
                    }]
                )
                
                # 构建交易数据
                tx_data = contract.encodeABI(
                    fn_name="transfer",
                    args=[Web3.to_checksum_address(to_address), int(amount)]
                )
                
                # 估算 gas limit
                gas_limit = EVMUtils.estimate_gas_limit(
                    self.chain,
                    token_address,
                    data=tx_data
                )
            else:
                # 原生代币转账
                gas_limit = EVMUtils.estimate_gas_limit(
                    self.chain,
                    to_address,
                    value=int(amount)
                )
            
            # 获取 gas 价格
            if self.web3.eth.get_block('latest').get('baseFeePerGas') is not None:
                # 使用 EIP-1559 费用
                fee_data = EVMUtils.get_gas_price(self.chain)
                max_priority_fee = fee_data['max_priority_fee']
                max_fee = fee_data['max_fee']
                estimated_fee = gas_limit * max_fee
                
                return {
                    'status': 'success',
                    'message': '估算费用成功',
                    'data': {
                        'gas_limit': gas_limit,
                        'gas_price': None,
                        'max_priority_fee': max_priority_fee,
                        'max_fee': max_fee,
                        'estimated_fee': estimated_fee
                    }
                }
            else:
                # 使用传统 gas price
                gas_price = self.web3.eth.gas_price
                estimated_fee = gas_limit * gas_price
                
                return {
                    'status': 'success',
                    'message': '估算费用成功',
                    'data': {
                        'gas_limit': gas_limit,
                        'gas_price': gas_price,
                        'max_priority_fee': None,
                        'max_fee': None,
                        'estimated_fee': estimated_fee
                    }
                }
            
        except Exception as e:
            logger.error(f"估算转账费用失败: {str(e)}")
            return {
                'status': 'error',
                'message': f"估算费用失败: {str(e)}"
            }

    async def _save_transaction(self, wallet_address: str, to_address: str, amount: Decimal,
                              token_address: Optional[str], tx_hash: str, tx_info: Dict[str, Any]) -> None:
        """保存交易记录"""
        try:
            # 获取钱包
            sender_wallet = await sync_to_async(Wallet.objects.filter(
                chain=self.chain,
                address__iexact=wallet_address,
                is_active=True
            ).first)()
            
            if not sender_wallet:
                logger.error(f"未找到发送方钱包: {wallet_address}")
                return
            
            # 获取接收方钱包（如果存在）
            receiver_wallet = await sync_to_async(Wallet.objects.filter(
                chain=self.chain,
                address__iexact=to_address,
                is_active=True
            ).first)()
            
            # 获取代币信息
            token = None
            if token_address:
                token = await sync_to_async(Token.objects.filter(
                    chain=self.chain,
                    address__iexact=token_address
                ).first)()
            
            # 创建交易记录
            await sync_to_async(Transaction.objects.create)(
                wallet=sender_wallet,
                chain=self.chain,
                tx_hash=tx_hash,
                tx_type='TRANSFER',
                status='SUCCESS',
                from_address=wallet_address.lower(),
                to_address=to_address.lower(),
                amount=Decimal(str(amount)),  # 确保使用 Decimal 转换
                token=token,
                gas_price=Decimal(str(tx_info.get('effectiveGasPrice', 0))),
                gas_used=Decimal(str(tx_info.get('gasUsed', 0))),
                block_number=tx_info.get('blockNumber', 0),
                block_timestamp=timezone.now()
            )
            
        except Exception as e:
            logger.error(f"保存交易记录失败: {str(e)}")
            raise 