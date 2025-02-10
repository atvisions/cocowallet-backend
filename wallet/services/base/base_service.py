import aiohttp
import asyncio
import logging
import time
from typing import Dict, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class ServiceStats:
    """服务统计数据"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_response_time: float = 0.0
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    start_time: datetime = field(default_factory=datetime.now)

    @property
    def average_response_time(self) -> float:
        """计算平均响应时间"""
        if self.total_requests == 0:
            return 0.0
        return self.total_response_time / self.total_requests

    @property
    def success_rate(self) -> float:
        """计算成功率"""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def uptime(self) -> timedelta:
        """计算运行时间"""
        return datetime.now() - self.start_time

class BaseService(ABC):
    """基础服务类"""

    def __init__(self):
        self.headers = {}
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.stats = ServiceStats()

    async def check_health(self) -> Dict:
        """检查服务健康状态"""
        try:
            start_time = time.time()
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # 尝试一个基本的API调用
                async with session.get(self.get_health_check_url(), headers=self.headers) as response:
                    response_time = time.time() - start_time
                    is_healthy = response.status == 200
                    
                    # 更新统计信息
                    self._update_stats(is_healthy, response_time)
                    
                    return {
                        'status': 'healthy' if is_healthy else 'unhealthy',
                        'latency': f"{response_time:.3f}s",
                        'message': 'Service is responding normally' if is_healthy else f'Service returned status {response.status}',
                        'stats': self.get_stats()
                    }
        except Exception as e:
            logger.error(f"健康检查失败: {str(e)}")
            self._update_stats(False, 0, str(e))
            return {
                'status': 'unhealthy',
                'latency': 'unknown',
                'message': f'Health check failed: {str(e)}',
                'stats': self.get_stats()
            }

    @abstractmethod
    def get_health_check_url(self) -> str:
        """获取健康检查URL，子类需要实现此方法"""
        raise NotImplementedError("Subclasses must implement get_health_check_url()")

    def get_stats(self) -> Dict:
        """获取服务统计信息"""
        return {
            'total_requests': self.stats.total_requests,
            'successful_requests': self.stats.successful_requests,
            'failed_requests': self.stats.failed_requests,
            'success_rate': f"{self.stats.success_rate:.2f}%",
            'average_response_time': f"{self.stats.average_response_time:.3f}s",
            'uptime': str(self.stats.uptime),
            'last_error': self.stats.last_error,
            'last_error_time': self.stats.last_error_time.isoformat() if self.stats.last_error_time else None
        }

    def _update_stats(self, success: bool, response_time: float, error: Optional[str] = None) -> None:
        """更新统计信息"""
        self.stats.total_requests += 1
        self.stats.total_response_time += response_time
        
        if success:
            self.stats.successful_requests += 1
        else:
            self.stats.failed_requests += 1
            self.stats.last_error = error
            self.stats.last_error_time = datetime.now()

    async def _fetch_with_retry(self, session, url, method="get", **kwargs) -> Optional[Dict]:
        """带重试和统计的HTTP请求函数"""
        start_time = time.time()
        try:
            kwargs['headers'] = self.headers
            for attempt in range(3):
                try:
                    async with getattr(session, method)(url, **kwargs) as response:
                        if response.status == 200:
                            response_time = time.time() - start_time
                            self._update_stats(True, response_time)
                            return await response.json()
                        elif response.status == 429:  # Rate limit
                            retry_after = int(response.headers.get('Retry-After', 2))
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            logger.error(f"请求失败: {url}, 状态码: {response.status}")
                            response_time = time.time() - start_time
                            self._update_stats(False, response_time, f"HTTP {response.status}")
                            return None
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    raise e
        except Exception as e:
            response_time = time.time() - start_time
            self._update_stats(False, response_time, str(e))
            logger.error(f"请求失败: {url}, 错误: {str(e)}")
            return None 