import os
import logging
from typing import Dict, Optional
from decimal import Decimal, InvalidOperation
import json
import asyncio
import aiohttp
import base64  # 添加base64模块导入
from eth_account import Account
from eth_account.messages import encode_defunct
from . import BaseTokenService
from ..models import Wallet, Token, Transaction as DBTransaction
from ..api_config import MoralisConfig, Chain
from django.utils import timezone
from asgiref.sync import sync_to_async
import base58

logger = logging.getLogger(__name__)

class TransferService(BaseTokenService):
    """转账服务类,处理代币转账相关的功能"""

    # RPC节点配置
    RPC_ENDPOINTS = {
        # EVM链RPC节点
        'ETH': os.getenv('ETH_RPC_URL', 'https://eth-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7'),
        'BSC': os.getenv('BSC_RPC_URL', 'https://bsc-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7'),
        'MATIC': os.getenv('POLYGON_RPC_URL', 'https://polygon-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7'),
        'AVAX': os.getenv('AVAX_RPC_URL', 'https://avalanche-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7'),
        'ARBITRUM': os.getenv('ARBITRUM_RPC_URL', 'https://arb-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7'),
        'OPTIMISM': os.getenv('OPTIMISM_RPC_URL', 'https://opt-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7'),
        'BASE': os.getenv('BASE_RPC_URL', 'https://base-mainnet.g.alchemy.com/v2/4IbTHF9NVzEGTHGZjKZNwjF5J9nhlmH7'),
        
        # Solana链RPC节点
        'SOL': {
            'mainnet': os.getenv('SOLANA_MAINNET_RPC_URL', 'https://api.mainnet-beta.solana.com'),  # 使用公共RPC节点
            'testnet': os.getenv('SOLANA_TESTNET_RPC_URL', 'https://api.testnet.solana.com'),
            'devnet': os.getenv('SOLANA_DEVNET_RPC_URL', 'https://api.devnet.solana.com'),
            'backup': [  # 备用RPC节点列表
                'https://solana-api.projectserum.com',
                'https://rpc.ankr.com/solana',
                'https://mainnet.rpcpool.com',
            ]
        }
    }

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
            from solana.transaction import Transaction, AccountMeta, TransactionInstruction
            from solana.keypair import Keypair
            from solana.system_program import transfer, TransferParams
            from spl.token.instructions import (
                get_associated_token_address,
                transfer_checked,
                TransferCheckedParams,
                create_associated_token_account
            )
            from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
            from solana.publickey import PublicKey
            import base58
            from solana.rpc.commitment import Confirmed
            from solana.rpc.types import TxOpts

            # 验证地址格式
            def validate_solana_address(address: str) -> bool:
                try:
                    # 检查地址长度
                    if len(address) != 32 and len(address) != 44:
                        return False
                    # 尝试解码base58地址
                    decoded = base58.b58decode(address)
                    return len(decoded) == 32
                except Exception:
                    return False

            # 验证地址
            if not validate_solana_address(to_address):
                raise ValueError(f"无效的Solana接收地址: {to_address}")
            if token_address and not validate_solana_address(token_address):
                raise ValueError(f"无效的代币地址: {token_address}")

            # 1. 初始化RPC客户端
            rpc_url = TransferService.RPC_ENDPOINTS['SOL']['mainnet']
            if not rpc_url or 'your-api-key' in rpc_url:
                raise ValueError("请配置有效的Solana RPC API密钥")
            
            # 初始化 RPC 客户端
            client = AsyncClient(rpc_url)
            
            # 2. 解密私钥并创建密钥对
            private_key_bytes = wallet.decrypt_private_key()
            
            try:
                # 直接使用私钥创建密钥对
                keypair = Keypair.from_secret_key(private_key_bytes)
                
                # 验证生成的公钥是否匹配钱包地址
                if str(keypair.public_key) != wallet.address:
                    logger.error(f"生成的公钥与钱包地址不匹配: {str(keypair.public_key)} != {wallet.address}")
                    raise ValueError("私钥与钱包地址不匹配")
                    
                logger.info("密钥对创建成功")
                
            except Exception as e:
                logger.error(f"创建密钥对失败: {str(e)}")
                raise ValueError("无法创建有效的密钥对")

            # 3. 获取最新的区块哈希
            recent_blockhash = await client.get_latest_blockhash()
            if not recent_blockhash or 'result' not in recent_blockhash:
                raise ValueError("获取最新区块哈希失败")
            
            # 4. 创建交易
            transaction = Transaction()
            transaction.recent_blockhash = recent_blockhash['result']['value']['blockhash']
            transaction.fee_payer = keypair.public_key
            
            # 5. 添加转账指令
            if token_address:  # SPL代币转账
                # 获取代币信息
                try:
                    token = await sync_to_async(Token.objects.get)(
                        chain='SOL',
                        address=token_address.lower()
                    )
                except Token.DoesNotExist:
                    # 如果是原生SOL的包装代币地址
                    if token_address.lower() == 'so11111111111111111111111111111111111111112':
                        token = type('Token', (), {
                            'decimals': 9,
                            'symbol': 'SOL',
                            'name': 'Solana'
                        })
                    else:
                        # 尝试从链上获取代币信息
                        try:
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
                                if decimals > 20:  # 设置一个合理的上限
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
                                            if decimals > 20:  # 设置一个合理的上限
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
                
            else:  # SOL转账
                # 计算转账金额(SOL精度为9)
                try:
                    # 移除字符串中的所有空白字符
                    amount = str(amount).strip()
                    decimal_amount = Decimal(amount)
                    
                    # 基础验证
                    if decimal_amount <= 0:
                        raise ValueError("转账金额必须大于0")
                    
                    # 检查小数位数是否超过精度限制
                    decimal_places = abs(decimal_amount.as_tuple().exponent)
                    if decimal_places > 9:  # SOL的精度是9
                        raise ValueError("小数位数不能超过9位")
                    
                    # 计算最小单位的金额，使用字符串确保精度
                    decimal_factor = Decimal('1000000000')  # 9位精度
                    amount_in_lamports = int(decimal_amount * decimal_factor)
                    
                    # 检查金额是否超出 u64 范围
                    if amount_in_lamports > 18446744073709551615:  # 2^64 - 1
                        raise ValueError(f"转账金额超出范围，最大支持 {18446744073709551615 / decimal_factor} SOL")
                    
                    if amount_in_lamports <= 0:
                        raise ValueError("转账金额太小")
                    
                    logger.info(f"SOL转账金额计算: 原始金额={amount}, 最小单位金额={amount_in_lamports}")
                        
                except (ValueError, InvalidOperation) as e:
                    logger.error(f"转账金额计算错误: {str(e)}")
                    if "小数位数不能超过" in str(e):
                        raise ValueError(str(e))
                    raise ValueError(f"无效的转账金额: {amount}，请输入一个有效的数字，例如：1.23")
                
                # 创建转账指令
                transfer_ix = transfer(
                    TransferParams(
                        from_pubkey=PublicKey(wallet.address),
                        to_pubkey=PublicKey(to_address),
                        lamports=amount_in_lamports
                    )
                )
                transaction.add(transfer_ix)
            
            # 6. 签名和广播交易
            try:
                # 签名交易
                logger.info("开始签名交易...")
                try:
                    transaction.sign(keypair)
                    logger.info("交易签名成功")
                except Exception as sign_error:
                    logger.error(f"交易签名失败: {str(sign_error)}")
                    raise ValueError(f"交易签名失败: {str(sign_error)}")
                
                # 序列化交易
                logger.info("序列化交易...")
                try:
                    serialized_tx = base64.b64encode(transaction.serialize()).decode('utf-8')
                    logger.info("交易序列化成功")
                except Exception as serialize_error:
                    logger.error(f"交易序列化失败: {str(serialize_error)}")
                    raise ValueError(f"交易序列化失败: {str(serialize_error)}")
                
                # 发送交易
                logger.info("广播交易...")
                try:
                    # 设置交易选项
                    opts = TxOpts(
                        skip_preflight=True,
                        preflight_commitment=Confirmed,
                        max_retries=5  # 增加重试次数
                    )
                    logger.info(f"交易选项: {opts}")
                    
                    # 使用多个RPC节点尝试发送交易
                    response = await TransferService._try_rpc_nodes(client, transaction, keypair, opts)
                    
                    if not response or 'result' not in response:
                        raise ValueError("交易响应格式错误")
                    
                    tx_signature = response['result']
                    logger.info(f"获取到交易签名: {tx_signature}")
                    
                    # 等待交易确认
                    logger.info("等待交易确认...")
                    max_confirmation_retries = 10  # 增加重试次数
                    confirmation_retry_count = 0
                    
                    while confirmation_retry_count < max_confirmation_retries:
                        try:
                            # 先获取交易状态
                            tx_status = await client.get_transaction(
                                tx_signature,
                                commitment=Confirmed
                            )
                            
                            if tx_status and isinstance(tx_status, dict):
                                result = tx_status.get('result')
                                if result:
                                    if result.get('meta', {}).get('err') is None:
                                        logger.info("交易已确认成功")
                                        break
                                    else:
                                        error_detail = result.get('meta', {}).get('err')
                                        logger.error(f"交易执行失败: {error_detail}")
                                        raise ValueError(f"交易执行失败: {error_detail}")
                            
                            # 如果获取不到交易状态，尝试确认交易
                            confirmation = await client.confirm_transaction(
                                tx_signature,
                                commitment=Confirmed
                            )
                            
                            if confirmation and isinstance(confirmation, dict):
                                result = confirmation.get('result', {})
                                if isinstance(result, dict) and result.get('value', False):
                                    logger.info("交易已确认")
                                    break
                            
                            confirmation_retry_count += 1
                            await asyncio.sleep(2)  # 增加等待时间
                        except Exception as e:
                            logger.warning(f"第 {confirmation_retry_count + 1} 次确认失败: {str(e)}")
                            confirmation_retry_count += 1
                            await asyncio.sleep(2)  # 增加等待时间
                    
                    if confirmation_retry_count >= max_confirmation_retries:
                        # 在最后一次尝试时，再次检查交易状态
                        final_status = await client.get_transaction(
                            tx_signature,
                            commitment=Confirmed
                        )
                        if final_status and isinstance(final_status, dict):
                            result = final_status.get('result')
                            if result and result.get('meta', {}).get('err') is None:
                                logger.info("最终确认：交易成功")
                            else:
                                error_detail = result.get('meta', {}).get('err') if result else "Unknown error"
                                logger.error(f"最终确认：交易失败: {error_detail}")
                                raise ValueError(f"交易执行失败: {error_detail}")
                        else:
                            raise ValueError("交易确认超时")

                    # 创建交易记录
                    token_obj = None
                    if token_address:
                        try:
                            token_obj = await sync_to_async(Token.objects.get)(
                                chain='SOL',
                                address=token_address.lower()
                            )
                        except Token.DoesNotExist:
                            # 如果代币不存在，创建一个新的记录
                            token_obj = await sync_to_async(Token.objects.create)(
                                chain='SOL',
                                address=token_address.lower(),
                                name=getattr(token, 'name', 'Unknown Token'),
                                symbol=getattr(token, 'symbol', 'Unknown'),
                                decimals=getattr(token, 'decimals', 9)
                            )

                    # 获取区块信息
                    slot = await client.get_slot(commitment=Confirmed)
                    slot_number = slot.get('result', 0)  # 获取实际的 slot 数字
                    block_info = await client.get_block(slot_number)  # 使用 slot 数字
                    block_time = block_info.get('result', {}).get('blockTime', 0)
                    block_number = block_info.get('result', {}).get('parentSlot', 0)

                    await sync_to_async(DBTransaction.objects.create)(
                        wallet=wallet,
                        chain='SOL',
                        tx_hash=tx_signature,
                        tx_type='TRANSFER',
                        status='SUCCESS',
                        from_address=wallet.address,
                        to_address=to_address,
                        amount=amount,
                        token=token_obj,
                        gas_price=0,  # Solana 的 gas 价格计算方式不同
                        gas_used=0,  # Solana 的 gas 使用量计算方式不同
                        block_number=block_number,
                        block_timestamp=timezone.datetime.fromtimestamp(block_time, tz=timezone.utc)
                    )
                    
                    return {
                        'success': True,
                        'tx_hash': tx_signature,
                        'message': '交易已确认'
                    }
                
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
            
        except Exception as e:
            logger.error(f"Solana转账失败: {str(e)}")
            raise

    @staticmethod
    async def test_rpc_connection() -> Dict:
        """测试 RPC 连接状态"""
        try:
            # 导入所需模块
            from solana.rpc.async_api import AsyncClient
            
            # 初始化 RPC 客户端
            rpc_url = TransferService.RPC_ENDPOINTS['SOL']['mainnet']
            if not rpc_url or 'your-api-key' in rpc_url:
                return {
                    'success': False,
                    'message': '未配置有效的 Solana RPC API 密钥'
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
    async def _try_rpc_nodes(client, transaction, keypair, opts):
        """尝试使用不同的RPC节点发送交易"""
        from solana.rpc.async_api import AsyncClient
        from solana.rpc.commitment import Confirmed
        
        errors = []
        
        # 首先尝试主节点
        try:
            logger.info("尝试使用主节点发送交易...")
            serialized_tx = base64.b64encode(transaction.serialize()).decode('utf-8')
            response = await client.send_raw_transaction(
                serialized_tx,
                opts=opts
            )
            if response and 'result' in response:
                logger.info("主节点交易发送成功")
                return response
        except Exception as e:
            error_msg = str(e)
            errors.append(f"主节点错误: {error_msg}")
            logger.warning(f"主节点发送交易失败: {error_msg}")

        # 如果主节点失败，尝试备用节点
        for backup_url in TransferService.RPC_ENDPOINTS['SOL']['backup']:
            backup_client = None
            try:
                logger.info(f"尝试使用备用节点 {backup_url}")
                backup_client = AsyncClient(backup_url)
                
                # 重新获取最新的区块哈希
                new_blockhash = await backup_client.get_latest_blockhash()
                if new_blockhash and 'result' in new_blockhash:
                    transaction.recent_blockhash = new_blockhash['result']['value']['blockhash']
                    # 重新签名交易
                    transaction.sign(keypair)
                    # 重新序列化交易
                    serialized_tx = base64.b64encode(transaction.serialize()).decode('utf-8')
                    
                response = await backup_client.send_raw_transaction(
                    serialized_tx,
                    opts=opts
                )
                if response and 'result' in response:
                    logger.info(f"备用节点 {backup_url} 交易发送成功")
                    return response
            except Exception as e:
                error_msg = str(e)
                errors.append(f"备用节点 {backup_url} 错误: {error_msg}")
                logger.warning(f"备用节点 {backup_url} 发送交易失败: {error_msg}")
            finally:
                if backup_client:
                    await backup_client.close()
        
        # 如果所有节点都失败，抛出异常
        error_msg = "所有RPC节点都失败:\n" + "\n".join(errors)
        logger.error(error_msg)
        raise ValueError(error_msg)

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