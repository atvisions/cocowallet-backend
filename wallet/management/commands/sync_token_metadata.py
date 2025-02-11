from django.core.management.base import BaseCommand
import aiohttp
import asyncio
import json
import logging
from datetime import datetime
from django.utils import timezone
from wallet.models import Token, TokenIndex
from django.core.cache import cache
from wallet.services.solana.token_info import SolanaTokenInfoService
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '从 Jupiter 和 Solscan 同步代币元数据'

    def __init__(self):
        super().__init__()
        self.cache_key = 'token_metadata_sync_status'
        self.token_info_service = SolanaTokenInfoService()

    def add_arguments(self, parser):
        parser.add_argument(
            '--async-mode',
            action='store_true',
            help='在异步模式下运行',
        )
        parser.add_argument(
            '--source',
            type=str,
            default='jupiter',
            help='数据源: jupiter, solscan (默认: jupiter)'
        )

    def handle(self, *args, **options):
        if options.get('async_mode'):
            # 异步模式下，启动任务并立即返回
            asyncio.create_task(self._sync_metadata())
            self.stdout.write(self.style.SUCCESS('同步任务已启动'))
        else:
            # 同步模式下，等待任务完成
            asyncio.run(self.handle_async(*args, **options))
            self.stdout.write(self.style.SUCCESS('同步完成'))

    def update_sync_status(self, status='running', progress=0, message=''):
        try:
            cache.set(self.cache_key, {
                'status': status,
                'progress': progress,
                'message': message,
                'timestamp': timezone.now().isoformat()
            }, timeout=3600)  # 1小时超时
            logger.debug(f"更新同步状态: status={status}, progress={progress}, message={message}")
        except Exception as e:
            logger.error(f"更新同步状态失败: {str(e)}")

    def get_sync_status(self):
        try:
            status = cache.get(self.cache_key, {
                'status': 'idle',
                'progress': 0,
                'message': '',
                'timestamp': timezone.now().isoformat()
            })
            logger.debug(f"获取同步状态: {status}")
            return status
        except Exception as e:
            logger.error(f"获取同步状态失败: {str(e)}")
            return {
                'status': 'error',
                'message': f'获取状态失败: {str(e)}'
            }

    async def _sync_metadata(self):
        try:
            self.update_sync_status(status='running', progress=0, message='正在获取 Jupiter 代币列表...')
            
            # 获取 Jupiter 代币列表
            async with aiohttp.ClientSession() as session:
                async with session.get('https://token.jup.ag/all') as response:
                    if response.status != 200:
                        raise Exception('无法获取 Jupiter 代币列表')
                    tokens = await response.json()

            total_tokens = len(tokens)
            processed = 0

            for token in tokens:
                try:
                    # 更新进度
                    progress = int((processed / total_tokens) * 100)
                    self.update_sync_status(
                        status='running',
                        progress=progress,
                        message=f'正在处理 {token.get("symbol", "未知")} ({processed}/{total_tokens})'
                    )

                    # 获取代币详细信息
                    token_info = await self.token_info_service.get_token_info(token['address'])
                    if not token_info:
                        continue

                    # 更新或创建代币记录
                    Token.objects.update_or_create(
                        chain='SOL',
                        address=token['address'],
                        defaults={
                            'name': token_info.get('name'),
                            'symbol': token_info.get('symbol'),
                            'decimals': token_info.get('decimals'),
                            'logo': token_info.get('logo'),
                            'metaplex_data': token_info.get('metaplex_data'),
                            'is_native': token_info.get('is_native', False),
                            'is_visible': True
                        }
                    )

                except Exception as e:
                    self.stderr.write(f'处理代币 {token.get("address")} 时出错: {str(e)}')

                processed += 1

            self.update_sync_status(status='success', progress=100, message='同步完成')

        except Exception as e:
            self.update_sync_status(status='error', progress=0, message=str(e))
            raise

    async def fetch_jupiter_tokens(self):
        """从 Jupiter 获取热门代币列表"""
        url = "https://token.jup.ag/all"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"Jupiter API 返回数据: {data}")
                        # Jupiter API 直接返回代币列表，不需要 .get('tokens')
                        if isinstance(data, list):
                            return data
                        else:
                            logger.error(f"Jupiter API 返回了意外的数据格式: {type(data)}")
                            return []
                    else:
                        logger.error(f"获取Jupiter代币列表失败: {response.status}")
                        return []
            except Exception as e:
                logger.error(f"请求Jupiter API时出错: {str(e)}")
                return []

    async def fetch_solscan_token_metadata(self, token_address: str):
        """从 Solscan 获取代币元数据"""
        url = f"https://api.solscan.io/token/meta?token={token_address}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('data', {})
                    else:
                        logger.error(f"获取Solscan代币元数据失败: {response.status}")
                        return {}
            except Exception as e:
                logger.error(f"请求Solscan API时出错: {str(e)}")
                return {}

    async def handle_async(self, *args, **options):
        try:
            logger.info("开始同步代币元数据")
            self.update_sync_status(status='running', progress=0, message='正在获取数据统计信息...')
            
            # 获取当前数据库中的代币数量和统计信息
            current_tokens = await sync_to_async(Token.objects.filter(chain='SOL').count)()
            current_indices = await sync_to_async(TokenIndex.objects.filter(chain='SOL').count)()
            
            # 显示当前数据库状态
            db_status = (
                f"当前数据库统计:\n"
                f"- 代币索引数: {current_indices}\n"
                f"- 代币详情数: {current_tokens}"
            )
            logger.info(db_status)
            
            # 获取 Jupiter 代币列表
            self.update_sync_status(status='running', progress=0, message='正在从 Jupiter 获取代币列表...')
            tokens = await self.fetch_jupiter_tokens()
            if not tokens:
                raise Exception("无法获取代币列表")
                
            total_tokens = len(tokens)
            logger.info(f"从 Jupiter 获取到 {total_tokens} 个代币")
            
            # 初始化统计信息
            stats = {
                'total': total_tokens,
                'processed': 0,
                'updated': 0,
                'created': 0,
                'failed': 0,
                'skipped': 0,
                'index_created': 0,
                'index_updated': 0
            }
            
            # 更新状态信息
            initial_status = (
                f"同步信息统计:\n"
                f"数据库现有索引: {current_indices}\n"
                f"数据库现有详情: {current_tokens}\n"
                f"Jupiter 代币总数: {total_tokens}\n"
                f"\n开始同步..."
            )
            
            self.update_sync_status(
                status='running',
                progress=0,
                message=initial_status
            )
            
            # 并发处理代币
            chunk_size = 10  # 每次处理10个代币
            for i in range(0, total_tokens, chunk_size):
                chunk = tokens[i:i + chunk_size]
                tasks = []
                for token in chunk:
                    if isinstance(token, dict) and 'address' in token:
                        tasks.append(self.process_token(token, stats))
                    else:
                        logger.warning(f"跳过无效的代币数据: {token}")
                        stats['skipped'] += 1
                if tasks:
                    await asyncio.gather(*tasks)
                
                stats['processed'] = i + len(chunk)
                progress = int((stats['processed'] / total_tokens) * 100)
                
                # 更新详细的进度信息
                status_message = (
                    f"同步进度:\n"
                    f"总数: {total_tokens} 个代币\n"
                    f"已处理: {stats['processed']} ({progress}%)\n"
                    f"索引新增: {stats['index_created']}\n"
                    f"索引更新: {stats['index_updated']}\n"
                    f"详情新增: {stats['created']}\n"
                    f"详情更新: {stats['updated']}\n"
                    f"失败: {stats['failed']}\n"
                    f"跳过: {stats['skipped']}\n"
                    f"剩余: {total_tokens - stats['processed']}"
                )
                
                self.update_sync_status(
                    status='running',
                    progress=progress,
                    message=status_message
                )
                logger.info(status_message)
            
            # 完成后的统计信息
            final_message = (
                f"同步完成！\n"
                f"总计处理: {stats['processed']}/{total_tokens}\n"
                f"索引新增: {stats['index_created']}\n"
                f"索引更新: {stats['index_updated']}\n"
                f"详情新增: {stats['created']}\n"
                f"详情更新: {stats['updated']}\n"
                f"失败: {stats['failed']}\n"
                f"跳过: {stats['skipped']}\n\n"
                f"最终数据库统计:\n"
                f"同步前索引数: {current_indices}\n"
                f"同步后索引数: {current_indices + stats['index_created']}\n"
                f"同步前详情数: {current_tokens}\n"
                f"同步后详情数: {current_tokens + stats['created']}"
            )
            
            self.update_sync_status(status='success', progress=100, message=final_message)
            logger.info(final_message)
            
        except Exception as e:
            error_msg = f"同步失败: {str(e)}"
            logger.error(error_msg)
            self.update_sync_status(status='error', progress=0, message=error_msg)
            raise

    async def process_token(self, token_info, stats):
        """处理单个代币的元数据"""
        try:
            token_address = token_info.get('address')
            if not token_address:
                logger.warning(f"跳过无效代币: {token_info}")
                stats['skipped'] += 1
                return
            
            logger.debug(f"开始处理代币: {token_address}")
            
            # 首先更新或创建代币索引
            index_defaults = {
                'name': token_info.get('name', 'Unknown Token'),
                'symbol': token_info.get('symbol', 'Unknown'),
                'decimals': token_info.get('decimals', 0),
                'is_native': token_address == 'So11111111111111111111111111111111111111112',
                'is_verified': bool(token_info.get('verified', False))
            }
            
            token_index, created = await sync_to_async(TokenIndex.objects.update_or_create)(
                chain='SOL',
                address=token_address,
                defaults=index_defaults
            )
            
            if created:
                stats['index_created'] += 1
                logger.info(f"创建新代币索引: {token_index.symbol} ({token_address})")
            else:
                stats['index_updated'] += 1
                logger.info(f"更新代币索引: {token_index.symbol} ({token_address})")
            
            # 获取详细元数据
            metadata = await self.token_info_service.get_token_metadata(token_address)
            if not metadata:
                logger.warning(f"无法获取代币元数据: {token_address}")
                stats['failed'] += 1
                return
            
            # 更新代币详细信息
            defaults = {
                'name': metadata.get('name', token_index.name),
                'symbol': metadata.get('symbol', token_index.symbol),
                'decimals': metadata.get('decimals', token_index.decimals),
                'logo': metadata.get('logo', ''),
                'type': 'token',
                'contract_type': 'SPL',
                'description': metadata.get('description', ''),
                'website': metadata.get('website', ''),
                'twitter': metadata.get('twitter', ''),
                'telegram': metadata.get('telegram', ''),
                'discord': metadata.get('discord', ''),
                'github': metadata.get('github', ''),
                'medium': metadata.get('medium', ''),
                'total_supply': metadata.get('total_supply', '0'),
                'total_supply_formatted': metadata.get('total_supply_formatted', '0'),
                'security_score': metadata.get('security_score', 0),
                'verified': metadata.get('verified', token_index.is_verified),
                'possible_spam': metadata.get('possible_spam', False),
                'is_native': token_index.is_native,
                'updated_at': timezone.now()
            }
            
            token, created = await sync_to_async(Token.objects.update_or_create)(
                chain='SOL',
                address=token_address,
                defaults=defaults
            )
            
            if created:
                stats['created'] += 1
                logger.info(f"创建新代币: {token.symbol} ({token_address})")
            else:
                stats['updated'] += 1
                logger.info(f"更新代币: {token.symbol} ({token_address})")
            
        except Exception as e:
            logger.error(f"处理代币 {token_info.get('address')} 时出错: {str(e)}")
            stats['failed'] += 1 