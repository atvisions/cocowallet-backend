from enum import Enum

class TaskActionType(str, Enum):
    """任务动作类型枚举"""
    COMPLETE_TASK = 'COMPLETE_TASK'  # 完成任务
    SHARE_TOKEN = 'SHARE_TOKEN'      # 分享代币
    REFER_USER = 'REFER_USER'        # 推荐用户
    DAILY_CHECK = 'DAILY_CHECK'      # 每日签到

class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = 'PENDING'      # 待完成
    COMPLETED = 'COMPLETED'  # 已完成
    EXPIRED = 'EXPIRED'      # 已过期
    FAILED = 'FAILED'        # 失败

# 任务类型列表
TASK_TYPES = [
    {
        'name': '每日任务',
        'code': 'DAILY',
        'description': '每天可以完成一次的任务',
        'priority': 10,
    },
    {
        'name': '一次性任务',
        'code': 'ONE_TIME',
        'description': '只能完成一次的任务',
        'priority': 20,
    },
    {
        'name': '分享任务',
        'code': 'SHARE',
        'description': '分享代币获得积分的任务',
        'priority': 30,
    },
    {
        'name': '推荐任务',
        'code': 'REFER',
        'description': '推荐新用户获得积分的任务',
        'priority': 40,
    },
]

# 任务类型代码到名称的映射
TASK_CODE_TO_NAME = {task['code']: task['name'] for task in TASK_TYPES}

# 获取任务类型信息的函数
def get_task_type_by_code(code):
    """根据代码获取任务类型信息"""
    for task_type in TASK_TYPES:
        if task_type['code'] == code:
            return task_type
    return None 