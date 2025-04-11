"""自定义异常模块"""

class TaskError(Exception):
    """任务基础异常类"""
    pass

class TaskNotFoundError(TaskError):
    """任务不存在异常"""
    pass

class TaskAlreadyCompletedError(TaskError):
    """任务已完成异常"""
    pass

class TaskNotActiveError(TaskError):
    """任务未激活异常"""
    pass

class TaskDailyLimitExceededError(TaskError):
    """任务每日限制超出异常"""
    pass

class TaskExpiredError(TaskError):
    """任务已过期异常"""
    pass

class TaskValidationError(TaskError):
    """任务数据验证错误异常"""
    pass

class PointsError(TaskError):
    """积分基础异常类"""
    pass

class InsufficientPointsError(PointsError):
    """积分不足异常"""
    pass

class PointsHistoryError(PointsError):
    """积分历史记录错误异常"""
    pass

class ShareTaskError(TaskError):
    """分享任务基础异常类"""
    pass

class ShareTaskNotFoundError(ShareTaskError):
    """分享任务不存在异常"""
    pass

class ShareTaskNotActiveError(ShareTaskError):
    """分享任务未激活异常"""
    pass

class ShareTaskDailyLimitExceededError(ShareTaskError):
    """分享任务每日限制超出异常"""
    pass