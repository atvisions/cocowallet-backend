"""EVM 链通用工具函数"""
import logging
from typing import Dict, Optional, Any, Union
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct
from decimal import Decimal
from hexbytes import HexBytes
from web3.providers.rpc import HTTPProvider
import asyncio

from ..evm_config import RPCConfig

logger = logging.getLogger(__name__)

class EVMUtils:
    """EVM 链通用工具类"""
    
    # 原生代币地址
    NATIVE_TOKEN_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
    
    CHAIN_CONFIG = {
        'ETH': {
            'chain_id': 1,
            'name': 'Ethereum',
            'symbol': 'ETH',
            'decimals': 18,
            'explorer': 'https://etherscan.io',
            'rpc_url': RPCConfig.ETH_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['ETH'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        },
        'BSC': {
            'chain_id': 56,
            'name': 'BNB Smart Chain',
            'symbol': 'BNB',
            'decimals': 18,
            'explorer': 'https://bscscan.com',
            'rpc_url': RPCConfig.BSC_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['BSC'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        },
        'BNB': {
            'chain_id': 56,
            'name': 'BNB Smart Chain',
            'symbol': 'BNB',
            'decimals': 18,
            'explorer': 'https://bscscan.com',
            'rpc_url': RPCConfig.BSC_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['BSC'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        },
        'MATIC': {
            'chain_id': 137,
            'name': 'Polygon',
            'symbol': 'MATIC',
            'decimals': 18,
            'explorer': 'https://polygonscan.com',
            'rpc_url': RPCConfig.POLYGON_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['MATIC'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        },
        'AVAX': {
            'chain_id': 43114,
            'name': 'Avalanche',
            'symbol': 'AVAX',
            'decimals': 18,
            'explorer': 'https://snowtrace.io',
            'rpc_url': RPCConfig.AVAX_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['AVAX'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        },
        'BASE': {
            'chain_id': 8453,
            'name': 'Base',
            'symbol': 'ETH',
            'decimals': 18,
            'explorer': 'https://basescan.org',
            'rpc_url': RPCConfig.BASE_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['BASE'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        },
        'ARBITRUM': {
            'chain_id': 42161,
            'name': 'Arbitrum One',
            'symbol': 'ETH',
            'decimals': 18,
            'explorer': 'https://arbiscan.io',
            'rpc_url': RPCConfig.ARBITRUM_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['ARBITRUM'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        },
        'OPTIMISM': {
            'chain_id': 10,
            'name': 'Optimism',
            'symbol': 'ETH',
            'decimals': 18,
            'explorer': 'https://optimistic.etherscan.io',
            'rpc_url': RPCConfig.OPTIMISM_RPC_URL,
            'native_token': {
                **RPCConfig.NATIVE_TOKENS['OPTIMISM'],
                'address': NATIVE_TOKEN_ADDRESS
            }
        }
    }
    
    @classmethod
    def get_chain_config(cls, chain: str) -> Dict[str, Any]:
        """获取链配置
        
        Args:
            chain: 链标识
            
        Returns:
            Dict: 链配置
        """
        if chain not in cls.CHAIN_CONFIG:
            raise ValueError(f"不支持的链: {chain}")
        return cls.CHAIN_CONFIG[chain]
    
    @classmethod
    def get_web3(cls, chain: str) -> Web3:
        """获取 Web3 实例
        
        Args:
            chain: 链标识
            
        Returns:
            Web3: Web3 实例
        """
        config = cls.get_chain_config(chain)
        web3 = Web3(Web3.HTTPProvider(config['rpc_url']))
        return web3
    
    @staticmethod
    def validate_address(address: str) -> bool:
        """验证地址是否有效
        
        Args:
            address: 地址
            
        Returns:
            bool: 是否有效
        """
        return Web3.is_address(address)
    
    @staticmethod
    def to_checksum_address(address: str) -> str:
        """转换为校验和地址
        
        Args:
            address: 地址
            
        Returns:
            str: 校验和地址
        """
        return Web3.to_checksum_address(address)
    
    @staticmethod
    def to_wei(amount: Union[int, float, str, Decimal], decimals: int = 18) -> int:
        """从标准单位转换为 Wei
        
        Args:
            amount: 标准单位金额
            decimals: 精度
            
        Returns:
            int: Wei 金额
        """
        if isinstance(amount, Decimal):
            amount = float(amount)
        return int(float(amount) * (10 ** decimals))
    
    @staticmethod
    def from_wei(amount: Union[int, float, str, Decimal], decimals: int = 18) -> Decimal:
        """从 Wei 转换为标准单位
        
        Args:
            amount: Wei 金额
            decimals: 精度
            
        Returns:
            Decimal: 标准单位金额
        """
        if isinstance(amount, Decimal):
            amount = int(amount)
        return Decimal(str(int(amount) / (10 ** decimals)))
    
    @staticmethod
    def get_explorer_url(chain: str, tx_hash: str) -> str:
        """获取区块浏览器交易URL"""
        config = EVMUtils.get_chain_config(chain)
        return f"{config['explorer']}/tx/{tx_hash}"
    
    @staticmethod
    def get_address_url(chain: str, address: str) -> str:
        """获取区块浏览器地址URL"""
        config = EVMUtils.get_chain_config(chain)
        return f"{config['explorer']}/address/{address}"
    
    @staticmethod
    def get_token_url(chain: str, token_address: str) -> str:
        """获取区块浏览器代币URL"""
        config = EVMUtils.get_chain_config(chain)
        return f"{config['explorer']}/token/{token_address}"
    
    @staticmethod
    def sign_message(private_key: str, message: str) -> str:
        """签名消息"""
        account = Account.from_key(private_key)
        message_hash = encode_defunct(text=message)
        signed_message = account.sign_message(message_hash)
        return signed_message.signature.hex()
    
    @staticmethod
    def recover_signer(message: str, signature: str) -> str:
        """恢复签名者地址"""
        message_hash = encode_defunct(text=message)
        return Account.recover_message(message_hash, signature=signature)
    
    @staticmethod
    def estimate_gas_limit(chain: str, to_address: str, value: int = 0, data: Union[str, bytes] = b'') -> int:
        """估算 gas limit"""
        web3 = EVMUtils.get_web3(chain)
        to_address = Web3.to_checksum_address(to_address)
        
        if isinstance(data, str):
            if data.startswith('0x'):
                data = HexBytes(data)
            else:
                data = data.encode()
                
        gas_estimate = web3.eth.estimate_gas({
            'to': to_address,
            'value': value, # type: ignore
            'data': data
        })
        # 添加 10% 的缓冲
        return int(gas_estimate * 1.1)
    
    @staticmethod
    def get_gas_price(chain: str) -> Dict[str, int]:
        """获取 gas 价格"""
        web3 = EVMUtils.get_web3(chain)
        
        try:
            # 尝试获取 EIP-1559 费用
            fee_data = web3.eth.fee_history(1, 'latest', [10, 50, 90])
            base_fee = web3.eth.get_block('latest')['baseFeePerGas'] # type: ignore
            
            rewards = fee_data['reward'][-1]
            max_priority_fee = rewards[1]  # 使用中位数优先费用
            
            return {
                'base_fee': base_fee,
                'max_priority_fee': max_priority_fee,
                'max_fee': base_fee + max_priority_fee
            }
        except Exception as e:
            logger.warning(f"获取 EIP-1559 费用失败: {str(e)}")
            # 回退到传统 gas 价格
            gas_price = web3.eth.gas_price
            return {
                'gas_price': gas_price
            }
    
    @staticmethod
    def wait_for_transaction_receipt(
        chain: str,
        tx_hash: Union[str, HexBytes],
        timeout: int = 120,
        poll_interval: float = 0.1
    ) -> Optional[Dict[str, Any]]:
        """等待交易收据"""
        web3 = EVMUtils.get_web3(chain)
        try:
            if isinstance(tx_hash, str):
                if tx_hash.startswith('0x'):
                    tx_hash = HexBytes(tx_hash)
                else:
                    tx_hash = HexBytes('0x' + tx_hash)
                    
            receipt = web3.eth.wait_for_transaction_receipt(
                tx_hash,
                timeout=timeout,
                poll_latency=poll_interval
            )
            return dict(receipt)
        except Exception as e:
            logger.error(f"等待交易收据失败: {str(e)}")
            return None
    
    @staticmethod
    def get_event_loop():
        """获取事件循环"""
        return asyncio.get_event_loop()
    
    @classmethod
    def run_in_event_loop(cls, coro):
        """在事件循环中运行协程"""
        loop = cls.get_event_loop()
        return loop.run_until_complete(coro) 