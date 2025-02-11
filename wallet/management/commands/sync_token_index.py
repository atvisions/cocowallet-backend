from django.core.management.base import BaseCommand
import aiohttp
import asyncio
import logging
from django.utils import timezone
from wallet.models import TokenIndex, TokenIndexSource, TokenIndexMetrics, TokenIndexGrade, TokenIndexReport
from asgiref.sync import sync_to_async
from django.core.cache import cache
from decimal import Decimal
import json
from django.db import transaction

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '从多个数据源同步代币索引数据并进行分级'

    def __init__(self):
        self.cache_key = 'token_index_sync_status'
        self.stats = {
            'total': 0,
            'processed': 0,
            'created': 0,
            'updated': 0,
            'failed': 0,
            'skipped': 0,
            'grade_a': 0,
            'grade_b': 0,
            'grade_c': 0,
        }
        super().__init__()

    def get_sync_status(self):
        """获取同步状态"""
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

    def update_sync_status(self, status='running', progress=0, message=''):
        try:
            cache.set(self.cache_key, {
                'status': status,
                'progress': progress,
                'message': message,
                'timestamp': timezone.now().isoformat()
            }, timeout=3600)
            logger.debug(f"更新同步状态: status={status}, progress={progress}, message={message}")
        except Exception as e:
            logger.error(f"更新同步状态失败: {str(e)}")

    def add_arguments(self, parser):
        parser.add_argument(
            '--grade',
            choices=['A', 'B', 'C', 'ALL'],
            default='ALL',
            help='指定更新的代币等级'
        )
        parser.add_argument(
            '--source',
            choices=['jupiter', 'solscan', 'coingecko', 'all'],
            default='all',
            help='指定数据源'
        )
        parser.add_argument(
            '--mode',
            choices=['auto', 'manual'],
            default='auto',
            help='更新模式'
        )

    async def fetch_jupiter_tokens(self, session):
        """从 Jupiter 获取代币列表"""
        url = "https://token.jup.ag/all"
        max_retries = 5
        
        for attempt in range(max_retries):
            try:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, list):
                            return data
                        logger.error(f"Jupiter API 返回了意外的数据格式: {type(data)}")
                    else:
                        logger.error(f"获取Jupiter代币列表失败: {response.status}")
                        
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # 指数退避
                        
            except Exception as e:
                logger.error(f"请求Jupiter API时出错: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    
        return []

    async def fetch_metrics_batch(self, session, token_addresses):
        """批量获取代币指标"""
        try:
            # 分批处理,每批20个代币
            batch_size = 20
            all_metrics = {}
            
            for i in range(0, len(token_addresses), batch_size):
                batch = token_addresses[i:i + batch_size]
                
                # 并发获取价格和持有人数据
                price_tasks = []
                holder_tasks = []
                
                # 创建价格查询任务
                for addr_batch in [batch[j:j+5] for j in range(0, len(batch), 5)]:
                    price_url = f"https://price.jup.ag/v4/price?ids={','.join(addr_batch)}"
                    price_tasks.append(self.fetch_with_retry(session, price_url))
                
                # 创建持有人查询任务
                for addr in batch:
                    url = f"https://api.solscan.io/token/holders?token={addr}"
                    holder_tasks.append(self.fetch_with_retry(session, url))
                
                # 等待所有任务完成
                price_results = await asyncio.gather(*price_tasks, return_exceptions=True)
                holder_results = await asyncio.gather(*holder_tasks, return_exceptions=True)
                
                # 处理价格数据
                for result in price_results:
                    if isinstance(result, dict) and 'data' in result:
                        all_metrics.update(result['data'])
                
                # 处理持有人数据
                for addr, holder_result in zip(batch, holder_results):
                    if isinstance(holder_result, dict):
                        if addr not in all_metrics:
                            all_metrics[addr] = {}
                        all_metrics[addr]['holder_count'] = holder_result.get('total', 0)
                
                await asyncio.sleep(1)  # 请求间隔
                
            return all_metrics
            
        except Exception as e:
            logger.error(f"批量获取代币指标时出错: {str(e)}")
            return {}

    async def fetch_with_retry(self, session, url, max_retries=3):
        """带重试的请求方法"""
        for attempt in range(max_retries):
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:  # Rate limit
                        wait_time = int(response.headers.get('Retry-After', 5))
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(f"请求失败: {url}, 状态码: {response.status}")
                        
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"请求失败: {url}, 错误: {str(e)}")
                    return None
                await asyncio.sleep(2 ** attempt)
        return None

    async def process_tokens(self, session, tokens):
        """处理代币数据"""
        try:
            # 准备批量更新的数据
            token_addresses = []
            token_data = {}
            
            for token in tokens:
                if not isinstance(token, dict) or 'address' not in token:
                    self.stats['skipped'] += 1
                    continue
                    
                addr = token['address']
                token_addresses.append(addr)
                token_data[addr] = {
                    'name': token.get('name', 'Unknown Token'),
                    'symbol': token.get('symbol', 'Unknown'),
                    'decimals': token.get('decimals', 0),
                    'is_native': addr == 'So11111111111111111111111111111111111111112',
                    'is_verified': bool(token.get('verified', False))
                }

            if not token_addresses:
                return

            # 批量获取指标
            metrics = await self.fetch_metrics_batch(session, token_addresses)
            
            # 准备批量更新数据
            token_updates = []
            metrics_updates = []
            grade_updates = []
            
            for addr in token_addresses:
                try:
                    token_metrics = {
                        'daily_volume': Decimal(str(metrics.get(addr, {}).get('volume24h', '0'))),
                        'holder_count': metrics.get(addr, {}).get('holder_count', 0),
                        'liquidity': Decimal('0'),
                        'market_cap': Decimal('0'),
                        'price': Decimal(str(metrics.get(addr, {}).get('price', '0')))
                    }
                    
                    # 评估等级
                    grade, score, reason = self.evaluate_token_grade(token_metrics)
                    
                    # 更新统计
                    if grade == 'A':
                        self.stats['grade_a'] += 1
                    elif grade == 'B':
                        self.stats['grade_b'] += 1
                    else:
                        self.stats['grade_c'] += 1
                        
                    # 准备更新数据
                    token_updates.append({
                        'chain': 'SOL',
                        'address': addr,
                        **token_data[addr]
                    })
                    
                    metrics_updates.append({
                        'address': addr,
                        **token_metrics
                    })
                    
                    grade_updates.append({
                        'address': addr,
                        'grade': grade,
                        'score': score,
                        'evaluation_reason': reason
                    })
                    
                except Exception as e:
                    logger.error(f"处理代币 {addr} 时出错: {str(e)}")
                    self.stats['failed'] += 1
                    
            # 批量更新数据库
            try:
                async with asyncio.Lock():
                    await sync_to_async(self.bulk_update_tokens)(token_updates, metrics_updates, grade_updates)
            except Exception as e:
                logger.error(f"批量更新数据库时出错: {str(e)}")
                self.stats['failed'] += len(token_addresses)
                
        except Exception as e:
            logger.error(f"处理代币批次时出错: {str(e)}")
            self.stats['failed'] += len(tokens)

    @transaction.atomic
    def bulk_update_tokens(self, token_updates, metrics_updates, grade_updates):
        """批量更新数据库"""
        # 批量创建或更新代币
        for update in token_updates:
            token, created = TokenIndex.objects.update_or_create(
                chain=update['chain'],
                address=update['address'],
                defaults={
                    'name': update['name'],
                    'symbol': update['symbol'],
                    'decimals': update['decimals'],
                    'is_native': update['is_native'],
                    'is_verified': update['is_verified']
                }
            )
            
            # 更新指标
            metrics = next((m for m in metrics_updates if m['address'] == update['address']), None)
            if metrics:
                TokenIndexMetrics.objects.update_or_create(
                    token=token,
                    defaults={
                        'daily_volume': metrics['daily_volume'],
                        'holder_count': metrics['holder_count'],
                        'liquidity': metrics['liquidity'],
                        'market_cap': metrics['market_cap'],
                        'price': metrics['price']
                    }
                )
            
            # 更新等级
            grade = next((g for g in grade_updates if g['address'] == update['address']), None)
            if grade:
                TokenIndexGrade.objects.update_or_create(
                    token=token,
                    defaults={
                        'grade': grade['grade'],
                        'score': grade['score'],
                        'evaluation_reason': grade['evaluation_reason']
                    }
                )

    def evaluate_token_grade(self, metrics: dict) -> tuple:
        """评估代币等级"""
        score = 0
        grade = 'C'
        reason = []
        
        # 评分标准
        if metrics['holder_count'] >= 10000:
            score += 30
            reason.append("持有人数>=10000")
        elif metrics['holder_count'] >= 1000:
            score += 20
            reason.append("持有人数>=1000")
        elif metrics['holder_count'] >= 100:
            score += 10
            reason.append("持有人数>=100")
            
        if metrics['daily_volume'] >= Decimal('100000'):
            score += 30
            reason.append("日交易量>=100000 USD")
        elif metrics['daily_volume'] >= Decimal('10000'):
            score += 20
            reason.append("日交易量>=10000 USD")
        elif metrics['daily_volume'] >= Decimal('1000'):
            score += 10
            reason.append("日交易量>=1000 USD")
            
        if metrics['liquidity'] >= Decimal('1000000'):
            score += 40
            reason.append("流动性>=1000000 USD")
        elif metrics['liquidity'] >= Decimal('100000'):
            score += 30
            reason.append("流动性>=100000 USD")
        elif metrics['liquidity'] >= Decimal('10000'):
            score += 20
            reason.append("流动性>=10000 USD")
            
        if score >= 80:
            grade = 'A'
        elif score >= 50:
            grade = 'B'
            
        return grade, score, ", ".join(reason)

    async def handle_async(self, *args, **options):
        """异步处理主函数"""
        try:
            logger.info("开始同步代币索引")
            self.update_sync_status(status='running', progress=0, message='正在获取数据...')
            
            # 创建 aiohttp 会话
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            connector = aiohttp.TCPConnector(limit=50, force_close=True)
            
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                # 获取代币列表
                tokens = await self.fetch_jupiter_tokens(session)
                if not tokens:
                    raise Exception("无法获取代币列表")
                    
                self.stats['total'] = len(tokens)
                
                # 批量处理代币
                batch_size = 50
                for i in range(0, len(tokens), batch_size):
                    batch = tokens[i:i + batch_size]
                    await self.process_tokens(session, batch)
                    
                    # 更新进度
                    self.stats['processed'] = min(i + batch_size, self.stats['total'])
                    progress = int((self.stats['processed'] / self.stats['total']) * 100)
                    
                    status_message = (
                        f"同步进度:\n"
                        f"总数: {self.stats['total']} 个代币\n"
                        f"已处理: {self.stats['processed']} ({progress}%)\n"
                        f"A级代币: {self.stats['grade_a']}\n"
                        f"B级代币: {self.stats['grade_b']}\n"
                        f"C级代币: {self.stats['grade_c']}\n"
                        f"新增: {self.stats['created']}\n"
                        f"更新: {self.stats['updated']}\n"
                        f"失败: {self.stats['failed']}\n"
                        f"跳过: {self.stats['skipped']}"
                    )
                    
                    self.update_sync_status(
                        status='running',
                        progress=progress,
                        message=status_message
                    )
                
                # 创建同步报告
                await sync_to_async(TokenIndexReport.objects.create)(
                    total_tokens=self.stats['total'],
                    grade_a_count=self.stats['grade_a'],
                    grade_b_count=self.stats['grade_b'],
                    grade_c_count=self.stats['grade_c'],
                    new_tokens=self.stats['created'],
                    removed_tokens=0,
                    details=self.stats
                )
                
                final_message = (
                    f"同步完成！\n"
                    f"总计处理: {self.stats['processed']}/{self.stats['total']}\n"
                    f"A级代币: {self.stats['grade_a']}\n"
                    f"B级代币: {self.stats['grade_b']}\n"
                    f"C级代币: {self.stats['grade_c']}\n"
                    f"新增: {self.stats['created']}\n"
                    f"更新: {self.stats['updated']}\n"
                    f"失败: {self.stats['failed']}\n"
                    f"跳过: {self.stats['skipped']}"
                )
                
                self.update_sync_status(status='success', progress=100, message=final_message)
                logger.info(final_message)
            
        except Exception as e:
            error_msg = f"同步失败: {str(e)}"
            logger.error(error_msg)
            self.update_sync_status(status='error', progress=0, message=error_msg)
            raise

    def handle(self, *args, **options):
        """命令入口点"""
        asyncio.run(self.handle_async(*args, **options)) 