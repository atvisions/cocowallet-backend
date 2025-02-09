import os
import logging
from typing import Dict, Optional
from decimal import Decimal, InvalidOperation
import json
import asyncio
import aiohttp
import base64
from eth_account import Account
from eth_account.messages import encode_defunct
from solana.rpc.commitment import Confirmed, Finalized, Processed
from . import BaseTokenService
from ..models import Wallet, Token, Transaction as DBTransaction
from ..api_config import MoralisConfig, Chain, APIConfig, RPCConfig
from django.utils import timezone
from asgiref.sync import sync_to_async
import base58
import time

logger = logging.getLogger(__name__)

class TransferService(BaseTokenService):
    """转账服务类,处理代币转账相关的功能"""

    # RPC节点配置
    RPC_ENDPOINTS = APIConfig.RPC.get_rpc_endpoints()

    # ERC20代币标准ABI
    ERC20_ABI = [
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        },
        {
            "constant": False,
            "inputs": [
                {"name": "_to", "type": "address"},
                {"name": "_value", "type": "uint256"}
            ],
            "name": "transfer",
            "outputs": [{"name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]

    @staticmethod
    async def transfer_token(
        wallet: Wallet,
        to_address: str,
        amount: str,
        token_address: Optional[str] = None,
        gas_price: Optional[str] = None,
        gas_limit: Optional[int] = None
    ) -> Dict:
        """
        转账代币
        :param wallet: 钱包对象
        :param to_address: 接收地址
        :param amount: 转账金额
        :param token_address: 代币合约地址(为None时转账原生代币)
        :param gas_price: Gas价格(可选)
        :param gas_limit: Gas限制(可选)
        :return: 交易结果
        """
        try:
            if wallet.chain == 'SOL':
                return await TransferService._transfer_solana_token(
                    wallet, to_address, amount, token_address
                )
            else:
                return await TransferService._transfer_evm_token(
                    wallet, to_address, amount, token_address, gas_price, gas_limit
                )
        except Exception as e:
            logger.error(f"转账失败: {str(e)}")
            raise

    @staticmethod
    async def _transfer_evm_token(
        wallet: Wallet,
        to_address: str,
        amount: str,
        token_address: Optional[str] = None,
        gas_price: Optional[str] = None,
        gas_limit: Optional[int] = None
    ) -> Dict:
        """
        EVM链代币转账
        """
        try:
            # 导入 web3 相关模块
            from web3 import Web3
            from web3.middleware import geth_poa_middleware
            
            # 1. 初始化web3
            rpc_url = TransferService.RPC_ENDPOINTS.get(wallet.chain)
            if not rpc_url:
                raise ValueError(f"不支持的链类型: {wallet.chain}")
            
            # 检查RPC URL是否包含有效的API密钥
            if 'your-api-key' in rpc_url or 'your-alchemy-api-key' in rpc_url:
                raise ValueError(f"请配置有效的{wallet.chain} RPC API密钥")
            
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                
                # 验证RPC连接
                if not w3.is_connected():
                    raise ConnectionError(f"无法连接到{wallet.chain}网络，请检查RPC配置")
            except Exception as e:
                logger.error(f"初始化Web3失败: {str(e)}")
                raise ValueError(f"连接{wallet.chain}网络失败: {str(e)}")
            
            # 2. 解密私钥
            private_key = wallet.decrypt_private_key()
            account = Account.from_key(private_key)
            
            # 检查ETH余额是否足够支付gas费
            eth_balance = w3.eth.get_balance(Web3.to_checksum_address(wallet.address))
            estimated_gas = int(gas_limit or (100000 if token_address else 21000))
            gas_price_wei = w3.eth.gas_price if wallet.chain == 'BSC' else w3.to_wei(gas_price or '5', 'gwei')
            required_eth = int(estimated_gas) * int(gas_price_wei)
            
            if eth_balance < required_eth:
                raise ValueError(f"ETH余额不足以支付gas费用，需要至少 {w3.from_wei(required_eth, 'ether')} ETH")
            
            # 3. 获取nonce
            nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(wallet.address))
            
            # 4. 准备交易数据
            if token_address:  # ERC20代币转账
                # 获取代币合约
                token_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=TransferService.ERC20_ABI
                )
                
                # 获取代币精度
                decimals = await sync_to_async(token_contract.functions.decimals().call)()
                
                # 构建交易数据
                amount_in_wei = int(Decimal(amount) * 10 ** decimals)
                tx_data = token_contract.functions.transfer(
                    Web3.to_checksum_address(to_address),
                    amount_in_wei
                ).build_transaction({
                    'chainId': w3.eth.chain_id,
                    'gas': int(gas_limit or 100000),
                    'maxFeePerGas': w3.to_wei(gas_price or '5', 'gwei') if wallet.chain != 'BSC' else w3.eth.gas_price,
                    'nonce': nonce,
                })
            else:  # 原生代币转账
                tx_data = {
                    'nonce': nonce,
                    'to': Web3.to_checksum_address(to_address),
                    'value': w3.to_wei(amount, 'ether'),
                    'gas': int(gas_limit or 21000),
                    'maxFeePerGas': w3.to_wei(gas_price or '5', 'gwei') if wallet.chain != 'BSC' else w3.eth.gas_price,
                    'chainId': w3.eth.chain_id
                }
            
            # 5. 签名交易
            signed_tx = w3.eth.account.sign_transaction(tx_data, private_key)
            
            # 6. 广播交易
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # 7. 创建交易记录
            token = None
            if token_address:
                token = await sync_to_async(Token.objects.get)(
                    chain=wallet.chain,
                    address=token_address.lower()
                )
            
            await sync_to_async(DBTransaction.objects.create)(
                wallet=wallet,
                chain=wallet.chain,
                tx_hash=tx_hash.hex(),
                tx_type='TRANSFER',
                status='PENDING',
                from_address=wallet.address,
                to_address=to_address,
                amount=amount,
                token=token,
                gas_price=w3.from_wei(int(tx_data.get('maxFeePerGas', tx_data.get('gasPrice', 0))), 'gwei'),
                gas_used=tx_data.get('gas', 0),
                block_number=0,  # 待更新
                block_timestamp=timezone.now()
            )
            
            return {
                'success': True,
                'tx_hash': tx_hash.hex(),
                'message': '交易已提交'
            }
            
        except Exception as e:
            logger.error(f"EVM转账失败: {str(e)}")
            raise

        
    @staticmethod
    async def _transfer_solana_token(
        wallet: Wallet,
        to_address: str,
        amount: str,
        token_address: Optional[str] = None
    ) -> Dict:
        try:
            # 导入所需模块
            from solana.rpc.async_api import AsyncClient
            from solana.transaction import Transaction
            from solana.keypair import Keypair
            from solana.system_program import transfer, TransferParams
            from spl.token.instructions import (
                get_associated_token_address,
                transfer_checked,
                TransferCheckedParams,
                create_associated_token_account
            )
            from spl.token.constants import TOKEN_PROGRAM_ID
            from solana.publickey import PublicKey
            from solana.rpc.commitment import Confirmed
            from solana.rpc.types import TxOpts

            logger.info(f"开始 Solana 转账: 从 {wallet.address} 到 {to_address}, 金额: {amount}, 代币: {token_address or 'SOL'}")

            # 验证地址格式
            def validate_solana_address(address: str) -> bool:
                try:
                    # 检查地址是否为空
                    if not address:
                        logger.error("地址为空")
                        return False
                    
                    # 检查地址长度是否在合理范围内
                    if len(address) < 32 or len(address) > 44:
                        logger.error(f"地址长度无效: {len(address)}")
                        return False
                    
                    try:
                        # 尝试解码base58地址
                        decoded = base58.b58decode(address)
                        # 检查解码后的字节长度是否为32字节
                        if len(decoded) != 32:
                            logger.error(f"解码后地址长度无效: {len(decoded)} bytes")
                            return False
                        return True
                    except ValueError as e:
                        logger.error(f"Base58解码失败: {str(e)}")
                        return False
                except Exception as e:
                    logger.error(f"地址验证失败: {str(e)}")
                    return False

            # 验证地址
            if not validate_solana_address(to_address):
                logger.error(f"接收地址格式无效: {to_address}")
                raise ValueError(f"无效的Solana接收地址: {to_address}")

            # 1. 初始化RPC客户端
            rpc_url = TransferService.RPC_ENDPOINTS['SOL']['mainnet']
            if not rpc_url:
                logger.error("未配置Solana RPC节点URL")
                raise ValueError("未配置Solana RPC节点URL")
            
            logger.info(f"使用RPC节点: {rpc_url}")
            
            # 初始化 RPC 客户端，添加超时设置
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_connect=10, sock_read=10)
            client = AsyncClient(rpc_url, commitment=Confirmed)
            
            try:
                # 测试RPC连接
                version = await client.get_version()
                logger.info(f"RPC节点版本: {version}")
                if not version or 'result' not in version:
                    logger.error("RPC节点连接测试失败")
                    raise ValueError("RPC节点连接失败")
            except Exception as e:
                logger.error(f"RPC节点连接失败: {str(e)}")
                raise ValueError(f"RPC节点连接失败: {str(e)}")
            
            # 2. 解密私钥并创建密钥对
            try:
                private_key_bytes = wallet.decrypt_private_key()
                logger.info(f"私钥解密成功，长度: {len(private_key_bytes)}")
                
                # 直接使用私钥创建密钥对
                keypair = Keypair.from_secret_key(private_key_bytes)
                
                # 验证生成的公钥是否匹配钱包地址
                if str(keypair.public_key) != wallet.address:
                    logger.error(f"公钥不匹配: 期望={wallet.address}, 实际={str(keypair.public_key)}")
                    raise ValueError("私钥与钱包地址不匹配")
                    
                logger.info("密钥对创建成功")
                
            except Exception as e:
                logger.error(f"创建密钥对失败: {str(e)}")
                raise ValueError(f"创建密钥对失败: {str(e)}")

            # 3. 获取最新的区块哈希
            try:
                recent_blockhash = await client.get_latest_blockhash()
                if not recent_blockhash or 'result' not in recent_blockhash:
                    logger.error(f"获取区块哈希失败: {recent_blockhash}")
                    raise ValueError("获取最新区块哈希失败")
                logger.info(f"获取区块哈希成功: {recent_blockhash['result']['value']['blockhash']}")
            except Exception as e:
                logger.error(f"获取区块哈希时出错: {str(e)}")
                raise ValueError(f"获取区块哈希失败: {str(e)}")
            
            # 4. 创建交易
            transaction = Transaction()
            transaction.recent_blockhash = recent_blockhash['result']['value']['blockhash']
            transaction.fee_payer = keypair.public_key

            # 设置交易选项
            tx_opts = TxOpts(
                skip_preflight=False,  # 改为 False，启用预检
                preflight_commitment=Confirmed,
                max_retries=3  # 减少重试次数
            )
            logger.info(f"交易选项: {tx_opts}")
            
            # 5. 添加转账指令
            if token_address:  # SPL代币转账
                # 如果是原生SOL的包装代币地址，直接使用原生SOL转账
                if token_address.lower() == 'so11111111111111111111111111111111111111112':
                    logger.info("检测到wSOL地址，使用原生SOL转账")
                    # 创建一个 token 对象用于记录
                    token = type('Token', (), {
                        'decimals': 9,
                        'symbol': 'SOL',
                        'name': 'Wrapped SOL'
                    })
                    # 计算转账金额(SOL精度为9)
                    try:
                        # 移除字符串中的所有空白字符
                        amount = str(amount).strip()
                        logger.info(f"原始转账金额: {amount}")
                        decimal_amount = Decimal(amount)
                        logger.info(f"转换为Decimal后的金额: {decimal_amount}")
                        
                        # 基础验证
                        if decimal_amount <= 0:
                            logger.error(f"转账金额必须大于0，当前金额: {decimal_amount}")
                            raise ValueError("转账金额必须大于0")
                        
                        # 检查小数位数是否超过精度限制
                        decimal_str = str(decimal_amount)
                        if '.' in decimal_str:
                            decimal_places = len(decimal_str.split('.')[1])
                            if decimal_places > 9:  # SOL的精度是9
                                logger.error(f"小数位数超过限制: {decimal_places} > 9")
                                raise ValueError("小数位数不能超过9位")
                        
                        # 计算 lamports 金额（1 SOL = 1e9 lamports）
                        decimal_factor = Decimal('1000000000')  # 1e9
                        amount_in_lamports = int(decimal_amount * decimal_factor)
                        logger.info(f"SOL转账金额计算: {decimal_amount} SOL = {amount_in_lamports} lamports")
                        
                        # 检查金额是否超出 u64 范围
                        if amount_in_lamports > 18446744073709551615:  # 2^64 - 1
                            logger.error(f"转账金额超出范围: {amount_in_lamports} > 18446744073709551615")
                            raise ValueError(f"转账金额超出范围，最大支持 {18446744073709551615 / decimal_factor} SOL")
                        
                        if amount_in_lamports <= 0:
                            logger.error("转账金额太小，转换为lamports后为0")
                            raise ValueError("转账金额太小")
                        
                        # 创建转账指令
                        transfer_ix = transfer(
                            TransferParams(
                                from_pubkey=PublicKey(wallet.address),
                                to_pubkey=PublicKey(to_address),
                                lamports=amount_in_lamports
                            )
                        )
                        transaction.add(transfer_ix)
                        logger.info("SOL转账指令创建成功")
                        
                        # 签名交易
                        transaction.sign(keypair)
                        logger.info("交易签名成功")
                        
                        # 直接返回，不需要继续执行SPL代币转账逻辑
                        return await TransferService._sign_and_send_transaction(
                            client,
                            transaction,
                            keypair,
                            tx_opts,
                            token,
                            wallet,
                            to_address,
                            amount
                        )
                        
                    except Exception as e:
                        logger.error(f"创建SOL转账指令失败: {str(e)}")
                        raise ValueError(f"创建转账指令失败: {str(e)}")
                
                # 其他SPL代币转账逻辑
                else:
                    # 验证代币地址
                    if not validate_solana_address(token_address):
                        logger.error(f"代币地址格式无效: {token_address}")
                        raise ValueError(f"无效的代币地址: {token_address}")

                    # 获取代币信息
                    try:
                        # 尝试从链上获取代币信息
                        mint_account = await client.get_account_info(
                            token_address,
                            commitment=Confirmed,
                            encoding="base64"
                        )
                        
                        if mint_account and mint_account.get('result', {}).get('value'):
                            # 解析代币信息
                            mint_data = mint_account['result']['value']['data'][0]
                            # 解码base64数据
                            decoded_data = base64.b64decode(mint_data)
                            # SPL代币的精度在数据的第4个字节
                            decimals = decoded_data[4] if len(decoded_data) > 4 else 9
                            
                            # 验证精度在合理范围内
                            if decimals > 20 or decimals < 0:  # 设置一个更严格的上限
                                logger.warning(f"代币精度异常: {decimals}，使用默认精度9")
                                decimals = 9
                            
                            # 记录日志
                            logger.info(f"从链上获取到代币精度: {decimals}")
                            
                            token = type('Token', (), {
                                'decimals': int(decimals),  # 确保转换为整数
                                'symbol': 'Unknown',
                                'name': 'Unknown Token'
                            })
                        else:
                            # 尝试从 Moralis API 获取代币信息
                            headers = {"X-API-Key": MoralisConfig.API_KEY}
                            metadata_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_address}/metadata"
                            
                            async with aiohttp.ClientSession() as session:
                                async with session.get(metadata_url, headers=headers) as response:
                                    if response.status == 200:
                                        metadata = await response.json()
                                        decimals = int(metadata.get('decimals', 9))  # 确保转换为整数
                                        
                                        # 验证精度在合理范围内
                                        if decimals > 20 or decimals < 0:  # 设置一个更严格的上限
                                            logger.warning(f"代币精度异常: {decimals}，使用默认精度9")
                                            decimals = 9
                                            
                                        logger.info(f"从Moralis获取到代币精度: {decimals}")
                                        token = type('Token', (), {
                                            'decimals': decimals,
                                            'symbol': metadata.get('symbol', 'Unknown'),
                                            'name': metadata.get('name', 'Unknown Token')
                                        })
                                    else:
                                        logger.warning(f"无法从Moralis获取代币信息，使用默认精度9")
                                        token = type('Token', (), {
                                            'decimals': 9,
                                            'symbol': 'Unknown',
                                            'name': 'Unknown Token'
                                        })
                    except Exception as e:
                        logger.error(f"获取代币信息失败: {str(e)}")
                        logger.warning("使用默认精度9")
                        token = type('Token', (), {
                            'decimals': 9,
                            'symbol': 'Unknown',
                            'name': 'Unknown Token'
                        })

                    # 计算转账金额
                    try:
                        # 移除字符串中的所有空白字符
                        amount = str(amount).strip()
                        decimal_amount = Decimal(str(amount))  # 确保使用字符串构造Decimal
                        
                        # 基础验证
                        if decimal_amount <= 0:
                            raise ValueError("转账金额必须大于0")
                        
                        # 获取代币精度
                        token_decimals = getattr(token, 'decimals', 9)  # 默认使用9位精度
                        logger.info(f"使用代币精度: {token_decimals}")
                        
                        # 检查小数位数是否超过精度限制
                        decimal_str = str(decimal_amount)
                        if '.' in decimal_str:
                            decimal_places = len(decimal_str.split('.')[1])
                            if decimal_places > token_decimals:
                                raise ValueError(f"小数位数不能超过{token_decimals}位")
                        
                        # 计算最小单位金额
                        decimal_factor = Decimal(str(10 ** token_decimals))
                        logger.info(f"计算因子: {decimal_factor}")
                        
                        # 检查金额是否超出 u64 范围 (2^64 - 1)
                        max_uint64 = Decimal('18446744073709551615')
                        max_token_amount = max_uint64 / decimal_factor
                        
                        if decimal_amount > max_token_amount:
                            raise ValueError(f"转账金额超出范围，最大支持 {max_token_amount:.{token_decimals}f} {getattr(token, 'symbol', 'Unknown')}")
                        
                        amount_in_smallest = int(decimal_amount * decimal_factor)
                        logger.info(f"最小单位金额: {amount_in_smallest}")
                        
                        if amount_in_smallest <= 0:
                            raise ValueError("转账金额太小")
                        
                        logger.info(f"转账金额计算: 原始金额={amount}, 精度={token_decimals}, 最小单位金额={amount_in_smallest}")
                        
                    except (ValueError, InvalidOperation) as e:
                        logger.error(f"转账金额计算错误: {str(e)}")
                        if "小数位数不能超过" in str(e) or "转账金额超出范围" in str(e):
                            raise ValueError(str(e))
                        raise ValueError(f"无效的转账金额: {amount}，请输入一个有效的数字")
                    
                    # 获取源和目标代币账户
                    try:
                        mint_pubkey = PublicKey(token_address)
                        owner_pubkey = PublicKey(wallet.address)
                        to_pubkey = PublicKey(to_address)
                    except Exception as e:
                        logger.error(f"创建公钥对象失败: {str(e)}")
                        raise ValueError("无效的地址格式")
                    
                    # 获取关联代币账户地址
                    try:
                        source_account = get_associated_token_address(owner_pubkey, mint_pubkey)
                        dest_account = get_associated_token_address(to_pubkey, mint_pubkey)
                    except Exception as e:
                        logger.error(f"获取关联代币账户失败: {str(e)}")
                        raise ValueError("无法获取关联代币账户地址")
                    
                    # 检查源账户是否存在
                    source_account_info = await client.get_account_info(str(source_account))
                    if not source_account_info or not source_account_info.get('result', {}).get('value'):
                        raise ValueError("源账户不存在，请先创建关联代币账户")
                    
                    # 检查目标账户是否存在，如果不存在则创建
                    dest_account_info = await client.get_account_info(str(dest_account))
                    if not dest_account_info or not dest_account_info.get('result', {}).get('value'):
                        # 创建目标账户的指令
                        create_dest_account_ix = create_associated_token_account(
                            payer=owner_pubkey,
                            owner=to_pubkey,
                            mint=mint_pubkey
                        )
                        # 先添加创建账户指令
                        transaction.add(create_dest_account_ix)
                    
                    # 创建转账指令
                    transfer_ix = transfer_checked(
                        TransferCheckedParams(
                            program_id=TOKEN_PROGRAM_ID,
                            source=source_account,
                            mint=mint_pubkey,
                            dest=dest_account,
                            owner=owner_pubkey,
                            amount=amount_in_smallest,
                            decimals=token_decimals,  # 使用之前获取的精度
                            signers=[]  # 移除这里的签名者列表
                        )
                    )
                    # 然后添加转账指令
                    transaction.add(transfer_ix)
                    
                    # 签名交易
                    transaction.sign(keypair)
                    logger.info("交易签名成功")
            
            else:  # 原生SOL转账
                # 创建一个 token 对象用于记录
                token = type('Token', (), {
                    'decimals': 9,
                    'symbol': 'SOL',
                    'name': 'Solana'
                })
                
                # 计算转账金额(SOL精度为9)
                try:
                    # 移除字符串中的所有空白字符
                    amount = str(amount).strip()
                    logger.info(f"原始转账金额: {amount}")
                    decimal_amount = Decimal(amount)
                    logger.info(f"转换为Decimal后的金额: {decimal_amount}")
                    
                    # 基础验证
                    if decimal_amount <= 0:
                        logger.error(f"转账金额必须大于0，当前金额: {decimal_amount}")
                        raise ValueError("转账金额必须大于0")
                    
                    # 检查小数位数是否超过精度限制
                    decimal_str = str(decimal_amount)
                    if '.' in decimal_str:
                        decimal_places = len(decimal_str.split('.')[1])
                        if decimal_places > 9:  # SOL的精度是9
                            logger.error(f"小数位数超过限制: {decimal_places} > 9")
                            raise ValueError("小数位数不能超过9位")
                    
                    # 计算 lamports 金额（1 SOL = 1e9 lamports）
                    decimal_factor = Decimal('1000000000')  # 1e9
                    amount_in_lamports = int(decimal_amount * decimal_factor)
                    logger.info(f"SOL转账金额计算: {decimal_amount} SOL = {amount_in_lamports} lamports")
                    
                    # 检查金额是否超出 u64 范围
                    if amount_in_lamports > 18446744073709551615:  # 2^64 - 1
                        logger.error(f"转账金额超出范围: {amount_in_lamports} > 18446744073709551615")
                        raise ValueError(f"转账金额超出范围，最大支持 {18446744073709551615 / decimal_factor} SOL")
                    
                    if amount_in_lamports <= 0:
                        logger.error("转账金额太小，转换为lamports后为0")
                        raise ValueError("转账金额太小")
                    
                    # 创建转账指令
                    transfer_ix = transfer(
                        TransferParams(
                            from_pubkey=PublicKey(wallet.address),
                            to_pubkey=PublicKey(to_address),
                            lamports=amount_in_lamports
                        )
                    )
                    transaction.add(transfer_ix)
                    logger.info("SOL转账指令创建成功")
                    
                    # 签名交易
                    transaction.sign(keypair)
                    logger.info("交易签名成功")
                    
                except (ValueError, InvalidOperation) as e:
                    logger.error(f"转账金额计算错误: {str(e)}")
                    if "小数位数不能超过" in str(e):
                        raise ValueError(str(e))
                    raise ValueError(f"无效的转账金额: {amount}，请输入一个有效的数字，例如：1.23")
            
            # 6. 签名和广播交易
            return await TransferService._sign_and_send_transaction(
                client,
                transaction,
                keypair,
                tx_opts,
                token,
                wallet,
                to_address,
                amount
            )
            
        except Exception as e:
            logger.error(f"Solana转账失败: {str(e)}")
            raise ValueError(str(e))

    @staticmethod
    async def _sign_and_send_transaction(client, transaction, keypair, opts, token, wallet, to_address, amount):
        """签名并发送交易"""
        try:
            # 序列化交易
            try:
                serialized_tx = base64.b64encode(transaction.serialize()).decode('utf-8')
                logger.info("交易序列化成功，长度: " + str(len(serialized_tx)))
            except Exception as serialize_error:
                logger.error(f"交易序列化失败: {str(serialize_error)}")
                if hasattr(serialize_error, '__dict__'):
                    logger.error(f"序列化错误详情: {serialize_error.__dict__}")
                raise ValueError(f"交易序列化失败: {str(serialize_error)}")
            
            # 发送交易
            logger.info("开始广播交易...")
            try:
                # 使用多个RPC节点尝试发送交易
                response = await TransferService._try_rpc_nodes(client, transaction, keypair, opts)
                
                if not response:
                    logger.error("交易响应为空")
                    raise ValueError("交易响应为空")
                
                if 'result' not in response:
                    logger.error(f"交易响应格式错误: {response}")
                    raise ValueError("交易响应格式错误")
                
                tx_signature = response['result']
                logger.info(f"交易广播成功，签名: {tx_signature}")
                
                # 等待交易确认
                logger.info("等待交易确认...")
                max_confirmation_retries = 30  # 增加最大重试次数
                confirmation_retry_count = 0
                
                # 使用指数退避策略
                base_sleep_time = 1.0  # 基础等待时间（秒）
                max_sleep_time = 10.0  # 最大等待时间（秒）
                
                # 创建一个RPC节点池
                rpc_nodes = [client._provider.endpoint_uri]
                backup_nodes = TransferService.RPC_ENDPOINTS['SOL'].get('backup', [])
                if isinstance(backup_nodes, property):
                    backup_nodes = backup_nodes.fget(APIConfig)
                rpc_nodes.extend(backup_nodes)
                
                while confirmation_retry_count < max_confirmation_retries:
                    try:
                        # 计算当前等待时间（指数增长）
                        sleep_time = min(base_sleep_time * (2 ** (confirmation_retry_count // 3)), max_sleep_time)
                        
                        if confirmation_retry_count > 0:
                            logger.info(f"等待 {sleep_time:.1f} 秒后进行第 {confirmation_retry_count + 1} 次确认尝试...")
                            await asyncio.sleep(sleep_time)
                        
                        # 轮询使用不同的RPC节点
                        current_node = rpc_nodes[confirmation_retry_count % len(rpc_nodes)]
                        
                        # 使用 aiohttp 直接发送请求获取交易状态
                        async with aiohttp.ClientSession() as session:
                            headers = {
                                "Content-Type": "application/json"
                            }
                            payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "getTransaction",
                                "params": [
                                    tx_signature,
                                    {
                                        "commitment": str(Confirmed),
                                        "encoding": "json"
                                    }
                                ]
                            }
                            
                            try:
                                async with session.post(current_node, json=payload, headers=headers, timeout=10) as resp:
                                    if resp.status == 429:  # Rate limit
                                        logger.warning(f"节点 {current_node} 达到速率限制，切换到下一个节点")
                                        confirmation_retry_count += 1
                                        continue
                                        
                                    tx_status = await resp.json()
                                    
                                    if tx_status and 'result' in tx_status:
                                        if tx_status['result']:
                                            # 交易已确认
                                            logger.info("交易已确认")
                                            
                                            # 创建交易记录
                                            await TransferService._create_transaction_record(
                                                client,
                                                wallet,
                                                tx_signature,
                                                to_address,
                                                amount,
                                                token
                                            )
                                            
                                            return {
                                                'success': True,
                                                'message': '交易已确认',
                                                'tx_hash': tx_signature
                                            }
                                        else:
                                            logger.info("交易尚未被确认，继续等待...")
                                    elif 'error' in tx_status:
                                        error_msg = tx_status['error'].get('message', str(tx_status['error']))
                                        logger.warning(f"获取交易状态失败: {error_msg}")
                                        # 如果是节点错误，尝试下一个节点
                                        confirmation_retry_count += 1
                                        continue
                                    
                            except asyncio.TimeoutError:
                                logger.warning(f"节点 {current_node} 响应超时，切换到下一个节点")
                                confirmation_retry_count += 1
                                continue
                            except Exception as e:
                                logger.error(f"查询交易状态时出错: {str(e)}")
                                confirmation_retry_count += 1
                                continue
                    
                    except Exception as e:
                        logger.error(f"确认交易时出错: {str(e)}")
                        confirmation_retry_count += 1
                        continue
                    
                    confirmation_retry_count += 1
                
                # 如果达到最大重试次数仍未确认
                raise ValueError(f"交易确认超时，请检查交易哈希: {tx_signature}")
            
            except Exception as send_error:
                error_details = str(send_error)
                if hasattr(send_error, '__dict__'):
                    error_details = f"{str(send_error)}, 详细信息: {send_error.__dict__}"
                logger.error(f"交易广播失败，详细错误: {error_details}")
                
                # 检查常见错误
                error_lower = str(send_error).lower()
                if "insufficient funds" in error_lower:
                    raise ValueError("SOL余额不足，无法支付交易费用")
                elif "blockhash" in error_lower:
                    raise ValueError("交易区块哈希已过期，请重试")
                elif "rpc" in error_lower or "connection" in error_lower:
                    raise ValueError("网络连接错误，请稍后重试")
                else:
                    raise ValueError(f"交易广播失败: {error_details}")
            
        except Exception as e:
            logger.error(f"交易处理失败: {str(e)}")
            # 获取更详细的错误信息
            error_msg = str(e)
            if hasattr(e, 'args') and len(e.args) > 0:
                error_msg = str(e.args[0])
            raise ValueError(f"交易失败: {error_msg}")
        finally:
            await client.close()

    @staticmethod
    async def _create_transaction_record(client, wallet, tx_signature, to_address, amount, token):
        """
        创建交易记录
        """
        try:
            # 获取交易详情
            tx_info = None
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    tx_response = await client.get_transaction(
                        tx_signature,
                        commitment="confirmed"
                    )
                    
                    if tx_response and 'result' in tx_response and tx_response['result']:
                        tx_info = tx_response['result']
                        break
                    
                    retry_count += 1
                    if retry_count < max_retries:
                        await asyncio.sleep(1 * (retry_count + 1))
                except Exception as e:
                    logger.error(f"获取交易详情失败(尝试 {retry_count + 1}/{max_retries}): {str(e)}")
                    retry_count += 1
                    if retry_count < max_retries:
                        await asyncio.sleep(1 * (retry_count + 1))
            
            if not tx_info:
                logger.error(f"无法获取交易 {tx_signature} 的详细信息")
                # 使用当前时间作为备选
                block_time = int(timezone.now().timestamp())
                block_number = 0
            else:
                # 从交易详情中获取区块信息
                block_time = tx_info.get('blockTime', int(timezone.now().timestamp()))
                block_number = tx_info.get('slot', 0)
                logger.info(f"获取到交易详情 - 区块时间: {block_time}, 区块高度: {block_number}")

                # 如果是代币交易，从交易详情中获取代币地址
                if tx_info.get('meta', {}).get('preTokenBalances') or tx_info.get('meta', {}).get('postTokenBalances'):
                    token_balances = tx_info['meta'].get('postTokenBalances', [])
                    if token_balances:
                        token_mint = token_balances[0].get('mint')
                        if token_mint:
                            logger.info(f"从交易详情中获取到代币地址: {token_mint}")
                            # 尝试从数据库获取代币信息
                            db_token = None
                            try:
                                db_token = await sync_to_async(Token.objects.get)(chain='SOL', address=token_mint.lower())
                                logger.info(f"从数据库获取到代币信息: {db_token.symbol}")
                            except Token.DoesNotExist:
                                # 如果数据库中没有，从API获取代币信息
                                try:
                                    headers = {
                                        "accept": "application/json",
                                        "X-API-Key": MoralisConfig.API_KEY
                                    }
                                    metadata_url = f"{MoralisConfig.SOLANA_URL}/token/mainnet/{token_mint}/metadata"
                                    async with aiohttp.ClientSession() as session:
                                        async with session.get(metadata_url, headers=headers) as response:
                                            if response.status == 200:
                                                metadata = await response.json()
                                                if metadata:
                                                    db_token = await sync_to_async(Token.objects.create)(
                                                        chain='SOL',
                                                        address=token_mint.lower(),
                                                        name=metadata.get('name', 'Unknown Token'),
                                                        symbol=metadata.get('symbol', 'Unknown'),
                                                        decimals=metadata.get('decimals', 9),
                                                        logo=metadata.get('logo', '')
                                                    )
                                                    logger.info(f"创建新的代币记录: {db_token.symbol}")
                                except Exception as e:
                                    logger.error(f"获取代币元数据失败: {str(e)}")
                            
                            if db_token:
                                token = db_token

            # 创建交易记录
            try:
                await sync_to_async(DBTransaction.objects.create)(
                    wallet=wallet,
                    chain=wallet.chain,
                    tx_hash=tx_signature,
                    tx_type='TRANSFER',
                    status='SUCCESS',
                    from_address=wallet.address,
                    to_address=to_address,
                    amount=amount,
                    token=token,
                    gas_price=Decimal('0'),  # Solana的gas price
                    gas_used=Decimal('0'),   # Solana的gas used
                    block_number=block_number,
                    block_timestamp=timezone.datetime.fromtimestamp(block_time, tz=timezone.utc)
                )
                logger.info(f"创建交易记录成功: {tx_signature}")
            except Exception as e:
                logger.error(f"创建交易记录失败: {str(e)}")
                raise
            
        except Exception as e:
            logger.error(f"处理交易记录时出错: {str(e)}")
            raise

    @staticmethod
    async def test_rpc_connection() -> Dict:
        """测试 RPC 连接状态"""
        try:
            # 导入所需模块
            from solana.rpc.async_api import AsyncClient
            
            # 初始化 RPC 客户端
            rpc_url = TransferService.RPC_ENDPOINTS['SOL']['mainnet']
            if not rpc_url:
                return {
                    'success': False,
                    'message': '未配置 Solana RPC 节点URL'
                }
            
            client = AsyncClient(rpc_url)
            try:
                # 1. 尝试获取最新的区块高度
                slot_response = await client.get_slot()
                if not slot_response or 'result' not in slot_response:
                    return {
                        'success': False,
                        'message': 'RPC 节点响应异常',
                        'details': slot_response
                    }
                
                # 2. 尝试获取最新的区块哈希
                blockhash_response = await client.get_latest_blockhash()
                if not blockhash_response or 'result' not in blockhash_response:
                    return {
                        'success': False,
                        'message': '无法获取最新区块哈希',
                        'details': blockhash_response
                    }
                
                # 3. 尝试获取网络版本
                version_response = await client.get_version()
                
                return {
                    'success': True,
                    'message': 'RPC 节点连接正常',
                    'details': {
                        'slot': slot_response.get('result'),
                        'blockhash': blockhash_response.get('result', {}).get('value', {}).get('blockhash'),
                        'version': version_response.get('result', {}).get('solana-core')
                    }
                }
                
            except Exception as e:
                return {
                    'success': False,
                    'message': f'RPC 请求失败: {str(e)}',
                    'error': str(e)
                }
            finally:
                await client.close()
                
        except Exception as e:
            return {
                'success': False,
                'message': f'RPC 连接初始化失败: {str(e)}',
                'error': str(e)
            }

    @staticmethod
    async def check_node_health(client) -> bool:
        """检查节点健康状态"""
        try:
            # 1. 检查版本
            version = await client.get_version()
            if not version or not isinstance(version, dict) or 'result' not in version:
                logger.warning(f"无法获取节点版本信息: {version}")
                return False
            
            version_str = version.get('result', {}).get('solana-core', 'unknown')
            logger.info(f"节点版本: {version_str}")
            
            # 2. 检查最新区块高度
            start_time = time.time()
            slot = await client.get_slot()
            slot_latency = time.time() - start_time
            
            if not slot or not isinstance(slot, dict) or 'result' not in slot:
                logger.warning(f"无法获取最新区块高度: {slot}")
                return False
            
            slot_number = slot.get('result', 'unknown')
            logger.info(f"当前区块高度: {slot_number}")
            
            # 检查区块高度延迟
            if slot_latency > 2:  # 如果获取区块高度延迟超过2秒
                logger.warning(f"获取区块高度延迟较高: {slot_latency:.2f}秒")
                return False
                
            # 3. 检查最新区块哈希
            start_time = time.time()
            blockhash = await client.get_latest_blockhash()
            blockhash_latency = time.time() - start_time
            
            if not blockhash or not isinstance(blockhash, dict) or 'result' not in blockhash:
                logger.warning(f"无法获取最新区块哈希: {blockhash}")
                return False
            
            blockhash_str = blockhash.get('result', {}).get('value', {}).get('blockhash', 'unknown')
            logger.info(f"当前区块哈希: {blockhash_str}")
            
            # 检查获取区块哈希的延迟
            if blockhash_latency > 2:  # 如果获取区块哈希延迟超过2秒
                logger.warning(f"获取区块哈希延迟较高: {blockhash_latency:.2f}秒")
                return False
            
            # 4. 尝试获取最近的确认区块
            start_time = time.time()
            confirmed_blocks = await client.get_blocks(slot_number - 10, slot_number)
            blocks_latency = time.time() - start_time
            
            if not confirmed_blocks or not isinstance(confirmed_blocks, dict) or 'result' not in confirmed_blocks:
                logger.warning(f"无法获取确认区块: {confirmed_blocks}")
                return False
            
            # 检查获取确认区块的延迟
            if blocks_latency > 3:  # 如果获取确认区块延迟超过3秒
                logger.warning(f"获取确认区块延迟较高: {blocks_latency:.2f}秒")
                return False
            
            # 所有检查都通过
            logger.info(f"节点健康检查通过，总延迟: {slot_latency + blockhash_latency + blocks_latency:.2f}秒")
            return True
            
        except Exception as e:
            logger.error(f"节点健康检查失败: {str(e)}")
            if hasattr(e, '__dict__'):
                logger.error(f"错误详情: {e.__dict__}")
            return False

    @staticmethod
    async def _try_rpc_nodes(client, transaction, keypair, opts):
        """尝试使用不同的RPC节点发送交易"""
        from solana.rpc.async_api import AsyncClient
        from solana.rpc.commitment import Confirmed
        
        errors = []
        
        # 首先检查主节点健康状态
        logger.info("开始检查主节点健康状态...")
        is_healthy = await TransferService.check_node_health(client)
        
        if is_healthy:
            try:
                logger.info("主节点健康状态正常，准备发送交易...")
                serialized_tx = base64.b64encode(transaction.serialize()).decode('utf-8')
                logger.info(f"交易序列化成功，长度: {len(serialized_tx)}")
                
                # 获取主节点 URL
                main_rpc_url = TransferService.RPC_ENDPOINTS['SOL']['mainnet']
                if not main_rpc_url:
                    raise ValueError("未配置主节点 URL")
                
                # 增加重试次数
                for retry in range(3):
                    try:
                        logger.info(f"主节点第{retry + 1}次尝试发送交易...")
                        
                        # 构建标准的 JSON-RPC 2.0 请求
                        payload = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "sendTransaction",
                            "params": [
                                serialized_tx,
                                {
                                    "encoding": "base64",
                                    "skipPreflight": opts.skip_preflight,
                                    "preflightCommitment": str(opts.preflight_commitment),
                                    "maxRetries": opts.max_retries
                                }
                            ]
                        }
                        
                        # 使用 aiohttp 发送请求
                        async with aiohttp.ClientSession() as session:
                            headers = {
                                "Content-Type": "application/json"
                            }
                            async with session.post(main_rpc_url, json=payload, headers=headers) as resp:
                                response = await resp.json()
                                
                                if response and 'result' in response:
                                    logger.info(f"主节点交易发送成功: {response['result']}")
                                    return response
                                elif 'error' in response:
                                    error_msg = response['error'].get('message', str(response['error']))
                                    logger.warning(f"主节点发送交易失败: {error_msg}")
                                    errors.append(error_msg)
                                    if retry < 2:  # 如果还有重试机会
                                        await asyncio.sleep(1 * (retry + 1))  # 指数退避
                                        continue
                                    break  # 重试次数用完，尝试备用节点
                                
                    except Exception as e:
                        logger.error(f"主节点发送交易出错: {str(e)}")
                        errors.append(str(e))
                        if retry < 2:  # 如果还有重试机会
                            await asyncio.sleep(1 * (retry + 1))
                            continue
                        break  # 重试次数用完，尝试备用节点
            
            except Exception as e:
                logger.error(f"主节点处理失败: {str(e)}")
                errors.append(str(e))
        
        # 如果主节点失败，尝试备用节点
        backup_nodes = TransferService.RPC_ENDPOINTS['SOL'].get('backup', [])
        if isinstance(backup_nodes, property):
            backup_nodes = backup_nodes.fget(APIConfig)
        
        if not backup_nodes:
            logger.error("没有配置备用节点")
            if errors:
                raise ValueError(f"交易发送失败，错误: {'; '.join(errors)}")
            raise ValueError("交易发送失败，没有可用的RPC节点")
        
        # 遍历所有备用节点
        for i, backup_url in enumerate(backup_nodes):
            try:
                logger.info(f"尝试使用备用节点 {backup_url}")
                
                # 对每个备用节点尝试3次
                for retry in range(3):
                    try:
                        # 构建标准的 JSON-RPC 2.0 请求
                        payload = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "sendTransaction",
                            "params": [
                                serialized_tx,
                                {
                                    "encoding": "base64",
                                    "skipPreflight": opts.skip_preflight,
                                    "preflightCommitment": str(opts.preflight_commitment),
                                    "maxRetries": opts.max_retries
                                }
                            ]
                        }
                        
                        # 使用 aiohttp 发送请求
                        async with aiohttp.ClientSession() as session:
                            headers = {
                                "Content-Type": "application/json"
                            }
                            async with session.post(backup_url, json=payload, headers=headers) as resp:
                                response = await resp.json()
                                
                                if response and 'result' in response:
                                    logger.info(f"备用节点 {backup_url} 交易发送成功: {response['result']}")
                                    return response
                                elif 'error' in response:
                                    error_msg = response['error'].get('message', str(response['error']))
                                    logger.warning(f"备用节点 {backup_url} 发送交易失败: {error_msg}")
                                    errors.append(error_msg)
                                    if retry < 2:  # 如果还有重试机会
                                        await asyncio.sleep(1 * (retry + 1))
                                        continue
                                    break  # 重试次数用完，尝试下一个节点
                                    
                    except Exception as e:
                        logger.error(f"备用节点 {backup_url} 发送交易出错: {str(e)}")
                        errors.append(str(e))
                        if retry < 2:
                            await asyncio.sleep(1 * (retry + 1))
                            continue
                        break
                        
            except Exception as e:
                logger.error(f"备用节点 {backup_url} 处理失败: {str(e)}")
                errors.append(str(e))
                continue
        
        # 如果所有节点都失败了
        error_msg = '; '.join(errors) if errors else "未知错误"
        raise ValueError(f"所有RPC节点都无法发送交易: {error_msg}")