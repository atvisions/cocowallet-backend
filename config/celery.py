import os
from celery import Celery
from django.conf import settings

# 设置 Django 默认设置模块
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('cocowallet')

# 使用 Django 的设置文件配置 Celery
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动发现任务
app.autodiscover_tasks(['wallet'])

# 配置定时任务 - 修改这里的任务路径
app.conf.beat_schedule = {
    'check-pending-swaps': {
        'task': 'wallet.tasks.check_pending_swap_transactions',
        'schedule': 10.0,
    },
}

# 添加一些基本配置
app.conf.update(
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 分钟
    worker_prefetch_multiplier=1
) 