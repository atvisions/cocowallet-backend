"""自定义异常模块"""

class WalletError(Exception):
    """钱包基础异常类"""
    pass

class InsufficientBalanceError(WalletError):
    """余额不足异常"""
    pass

class InvalidAddressError(WalletError):
    """无效地址异常"""
    pass

class TransferError(WalletError):
    """转账失败异常"""
    pass

class InvalidMnemonicError(WalletError):
    """无效助记词异常"""
    pass

class InvalidPrivateKeyError(WalletError):
    """无效私钥异常"""
    pass

class PaymentPasswordError(WalletError):
    """支付密码错误异常"""
    pass

class ServiceUnavailableError(WalletError):
    """服务不可用异常"""
    pass

class ValidationError(WalletError):
    """数据验证错误异常"""
    pass

class SwapError(WalletError):
    """代币兑换异常"""
    pass

class WalletNotFoundError(WalletError):
    """钱包不存在异常"""
    pass

class ChainNotSupportError(WalletError):
    """不支持的链异常"""
    pass

class GetBalanceError(WalletError):
    """获取余额失败异常"""
    pass

class GetTokenInfoError(WalletError):
    """获取代币信息失败异常"""
    pass

class SwapTokensError(WalletError):
    """代币兑换失败异常"""
    pass

class GetSupportedTokensError(WalletError):
    """获取支持的代币列表失败异常"""
    pass