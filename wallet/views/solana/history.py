from django.core.paginator import Paginator
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import status, viewsets
from django.shortcuts import get_object_or_404
import logging
from django.core.cache import cache
from functools import lru_cache

from ...models import Wallet, Transaction, Token

logger = logging.getLogger(__name__)

class SolanaHistoryViewSet(viewsets.ViewSet):
    """Solana 交易历史视图集"""
    
    def check_wallet_access(self, wallet: Wallet, device_id: str) -> bool:
        """检查设备是否有权限访问钱包"""
        return wallet.device_id == device_id
    
    # 使用内存缓存装饰器，缓存最近的 100 个查询结果
    @lru_cache(maxsize=100)
    def get_token_info_cached(self, token_address):
        """获取代币信息（带缓存）"""
        return self._get_token_info(token_address)
    
    def _get_token_info(self, token_address):
        """获取代币信息的实际实现"""
        try:
            token = Token.objects.filter(address=token_address).first()
            if token:
                return {
                    'address': token.address,
                    'name': token.name,
                    'symbol': token.symbol,
                    'decimals': token.decimals,
                    'logo': token.logo
                }
        except Exception as e:
            logger.error(f"获取代币信息失败: {str(e)}")
        
        # 如果找不到代币信息，返回默认值
        # 对于常见代币，提供默认信息
        DEFAULT_TOKENS = {
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': {
                'name': 'USD Coin',
                'symbol': 'USDC',
                'decimals': 6,
                'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v/logo.png'
            },
            'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': {
                'name': 'Bonk',
                'symbol': 'BONK',
                'decimals': 5,
                'logo': 'https://d23exngyjlavgo.cloudfront.net/solana_DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'
            },
            'So11111111111111111111111111111111111111112': {
                'name': 'Solana',
                'symbol': 'SOL',
                'decimals': 9,
                'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
            },
            'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': {
                'name': 'dogwifhat',
                'symbol': '$WIF',
                'decimals': 6,
                'logo': 'https://s2.coinmarketcap.com/static/img/coins/64x64/24484.png'
            },
            'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So': {
                'name': 'Marinade staked SOL',
                'symbol': 'mSOL',
                'decimals': 9,
                'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So/logo.png'
            },
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': {
                'name': 'USDT',
                'symbol': 'USDT',
                'decimals': 6,
                'logo': 'https://s2.coinmarketcap.com/static/img/coins/64x64/825.png'
            }
        }
        
        if token_address in DEFAULT_TOKENS:
            token_info = DEFAULT_TOKENS[token_address]
            return {
                'address': token_address,
                'name': token_info['name'],
                'symbol': token_info['symbol'],
                'decimals': token_info['decimals'],
                'logo': token_info['logo']
            }
        
        # 其他未知代币
        return {
            'address': token_address,
            'name': 'Unknown Token',
            'symbol': 'Unknown',
            'decimals': 0,
            'logo': ''
        }
    
    def get_token_info(self, token_address):
        """获取代币信息的公共接口"""
        if not token_address:
            return {
                'address': '',
                'name': 'Unknown Token',
                'symbol': 'Unknown',
                'decimals': 0,
                'logo': ''
            }
        
        return self.get_token_info_cached(token_address)
    
    def batch_get_token_info(self, token_addresses):
        """批量获取代币信息"""
        # 去重
        unique_addresses = set(filter(None, token_addresses))
        
        # 从数据库批量查询
        db_tokens = {
            token.address: {
                'address': token.address,
                'name': token.name,
                'symbol': token.symbol,
                'decimals': token.decimals,
                'logo': token.logo
            }
            for token in Token.objects.filter(address__in=unique_addresses)
        }
        
        # 对于数据库中没有的代币，使用默认信息或缓存
        result = {}
        for address in unique_addresses:
            if address in db_tokens:
                result[address] = db_tokens[address]
            else:
                result[address] = self.get_token_info(address)
        
        return result
    
    # 注意这里使用 list 方法，而不是 action 装饰器
    def list(self, request, wallet_id=None):
        """获取代币转账记录"""
        logger.info("======== SolanaHistoryViewSet.list 方法被调用 ========")
        logger.info(f"wallet_id: {wallet_id}, request.path: {request.path}")
        try:
            device_id = request.query_params.get('device_id')
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            
            if not device_id:
                return Response(
                    {'status': 'error', 'message': '缺少设备ID'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # 获取钱包
            wallet = get_object_or_404(Wallet, id=wallet_id)
            if not self.check_wallet_access(wallet, device_id):
                return Response(
                    {'status': 'error', 'message': '无权访问该钱包'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # 添加日志记录
            logger.info(f"查询钱包 {wallet_id} 的交易记录，钱包地址: {wallet.address}")
            
            # 直接查询数据库
            transactions = Transaction.objects.filter(
                wallet=wallet
            ).order_by('-block_timestamp')
            
            # 记录查询到的总交易数
            total_count = transactions.count()
            logger.info(f"查询到总共 {total_count} 条交易记录")
            
            # 分页
            paginator = Paginator(transactions, page_size)
            current_page = paginator.page(page)
            
            # 收集所有需要查询的代币地址
            token_addresses = []
            for tx in current_page.object_list:
                # 收集交易中的代币地址
                if tx.token:
                    token_addresses.append(tx.token.address)
                elif tx.token_info and 'from_token' in tx.token_info:
                    token_address = tx.token_info['from_token'].get('address', '')
                    if token_address:
                        token_addresses.append(token_address)
                elif tx.tx_type == 'TRANSFER':
                    token_addresses.append('So11111111111111111111111111111111111111112')  # SOL
                
                # 收集 SWAP 交易的目标代币地址
                if tx.tx_type == 'SWAP' and tx.to_token_address:
                    token_addresses.append(tx.to_token_address)
            
            # 批量获取代币信息
            token_info_map = self.batch_get_token_info(token_addresses)
            
            # 序列化交易记录
            serialized_transactions = []
            for tx in current_page.object_list:
                # 记录每条交易的类型
                logger.info(f"处理交易: tx_hash={tx.tx_hash}, tx_type={tx.tx_type}")
                
                # 基本交易信息
                tx_data = {
                    'tx_hash': tx.tx_hash,
                    'tx_type': tx.tx_type,
                    'status': tx.status,
                    'from_address': tx.from_address,
                    'to_address': tx.to_address,
                    'amount': float(tx.amount),
                    'direction': 'SENT' if tx.from_address == wallet.address else 'RECEIVED',
                    'gas_price': float(tx.gas_price),
                    'gas_used': float(tx.gas_used),
                    'gas_fee': str(tx.gas_price * tx.gas_used),
                    'block_number': tx.block_number,
                    'block_timestamp': tx.block_timestamp,
                    'created_at': tx.created_at,
                }
                
                # 添加代币信息
                token_address = None
                if tx.token:
                    token_address = tx.token.address
                    if token_address in token_info_map:
                        tx_data['token'] = token_info_map[token_address]
                    else:
                        tx_data['token'] = {
                            'address': tx.token.address,
                            'name': tx.token.name,
                            'symbol': tx.token.symbol,
                            'decimals': tx.token.decimals,
                            'logo': tx.token.logo
                        }
                elif tx.token_info and 'from_token' in tx.token_info:
                    from_token = tx.token_info['from_token']
                    token_address = from_token.get('address', '')
                    if token_address and token_address in token_info_map:
                        tx_data['token'] = token_info_map[token_address]
                    else:
                        tx_data['token'] = self.get_token_info(token_address)
                else:
                    # 如果是 SOL 原生代币转账，添加默认信息
                    if tx.tx_type == 'TRANSFER' and not tx.token:
                        sol_address = 'So11111111111111111111111111111111111111112'
                        if sol_address in token_info_map:
                            tx_data['token'] = token_info_map[sol_address]
                        else:
                            tx_data['token'] = self.get_token_info(sol_address)
                
                # 为 SWAP 类型添加目标代币信息
                if tx.tx_type == 'SWAP' and tx.to_token_address:
                    # 获取目标代币信息
                    to_token_address = tx.to_token_address
                    if to_token_address in token_info_map:
                        to_token_info = token_info_map[to_token_address]
                    else:
                        to_token_info = self.get_token_info(to_token_address)
                    
                    tx_data['swap_info'] = {
                        'to_token_address': to_token_address,
                        'to_token_symbol': to_token_info['symbol'],
                        'to_token_name': to_token_info['name'],
                        'to_token_decimals': to_token_info['decimals'],
                        'to_token_logo': to_token_info['logo']
                    }
                    
                    # 记录 SWAP 交易的额外信息
                    logger.info(f"添加 SWAP 信息: to_token_address={to_token_address}")
                
                serialized_transactions.append(tx_data)
            
            # 记录最终返回的交易数量
            logger.info(f"返回 {len(serialized_transactions)} 条交易记录")
            
            # 直接返回结果，不使用缓存
            return Response({
                'status': 'success',
                'data': {
                    'total': paginator.count,
                    'page': page,
                    'page_size': page_size,
                    'transactions': serialized_transactions
                }
            })
            
        except Exception as e:
            logger.error(f"获取代币转账记录失败: {str(e)}")
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            ) 