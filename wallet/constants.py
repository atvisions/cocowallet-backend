from enum import Enum

class ChainType(str, Enum):
    """区块链类型枚举"""
    BITCOIN = 'BTC'
    ETHEREUM = 'ETH'
    BINANCE = 'BNB'
    POLYGON = 'MATIC'
    AVALANCHE = 'AVAX'
    SOLANA = 'SOL'
    BASE = 'BASE'
    ARBITRUM = 'ARBITRUM'
    OPTIMISM = 'OPTIMISM'

class TransactionType(str, Enum):
    """交易类型枚举"""
    TRANSFER = 'TRANSFER'
    SWAP = 'SWAP'
    MINT = 'MINT'
    BURN = 'BURN'
    STAKE = 'STAKE'
    UNSTAKE = 'UNSTAKE'
    APPROVE = 'APPROVE'
    UNKNOWN = 'UNKNOWN'

class TransactionStatus(str, Enum):
    """交易状态枚举"""
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'
    UNKNOWN = 'UNKNOWN'

class TransactionDirection(str, Enum):
    """交易方向枚举"""
    SENT = 'SENT'
    RECEIVED = 'RECEIVED'
    SELF = 'SELF'

# 代币分类列表
TOKEN_CATEGORIES = [
    {
        'name': '稳定币',
        'code': 'stablecoin',
        'description': '与法定货币或其他资产挂钩的代币',
        'priority': 10,
    },
    {
        'name': 'Meme 币',
        'code': 'meme',
        'description': '以迷因文化为主题的代币',
        'priority': 20,
    },
    {
        'name': 'DeFi',
        'code': 'defi',
        'description': '去中心化金融相关代币',
        'priority': 30,
    },
    {
        'name': 'GameFi',
        'code': 'gamefi',
        'description': '游戏相关代币',
        'priority': 40,
    },
    {
        'name': 'NFT',
        'code': 'nft',
        'description': 'NFT 相关代币',
        'priority': 50,
    },
    {
        'name': '跨链资产',
        'code': 'wrapped',
        'description': '跨链包装的资产',
        'priority': 60,
    },
    {
        'name': '流动性质押',
        'code': 'liquid_staking',
        'description': '流动性质押代币',
        'priority': 70,
    },
    {
        'name': '原生代币',
        'code': 'native',
        'description': '区块链原生代币',
        'priority': 5,
    },
    {
        'name': '其他',
        'code': 'other',
        'description': '其他类型代币',
        'priority': 100,
    },
]

# 常用代币列表
COMMON_TOKENS = [
    # 原生代币
    {
        'chain': ChainType.SOLANA,
        'address': 'So11111111111111111111111111111111111111112',
        'name': 'Solana',
        'symbol': 'SOL',
        'decimals': 9,
        'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png',
        'category_code': 'native',
        'is_native': True,
        'is_visible': True,
        'is_recommended': True
    },
    # 稳定币
    {
        'chain': ChainType.SOLANA,
        'address': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
        'name': 'USD Coin',
        'symbol': 'USDC',
        'decimals': 6,
        'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v/logo.png',
        'category_code': 'stablecoin',
        'is_native': False,
        'is_visible': True,
        'is_recommended': True
    },
    {
        'chain': ChainType.SOLANA,
        'address': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
        'name': 'USDT',
        'symbol': 'USDT',
        'decimals': 6,
        'logo': 'https://s2.coinmarketcap.com/static/img/coins/64x64/825.png',
        'category_code': 'stablecoin',
        'is_native': False,
        'is_visible': True,
        'is_recommended': True
    },
    # Meme 币
    {
        'chain': ChainType.SOLANA,
        'address': 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
        'name': 'Bonk',
        'symbol': 'BONK',
        'decimals': 5,
        'logo': 'https://d23exngyjlavgo.cloudfront.net/solana_DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
        'category_code': 'meme',
        'is_native': False,
        'is_visible': True,
        'is_recommended': True
    },
    {
        'chain': ChainType.SOLANA,
        'address': 'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',
        'name': 'dogwifhat',
        'symbol': '$WIF',
        'decimals': 6,
        'logo': 'https://s2.coinmarketcap.com/static/img/coins/64x64/24484.png',
        'category_code': 'meme',
        'is_native': False,
        'is_visible': True,
        'is_recommended': True
    },
    # 流动性质押
    {
        'chain': ChainType.SOLANA,
        'address': 'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So',
        'name': 'Marinade staked SOL',
        'symbol': 'mSOL',
        'decimals': 9,
        'logo': 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So/logo.png',
        'category_code': 'liquid_staking',
        'is_native': False,
        'is_visible': True,
        'is_recommended': True
    },
    # DeFi
    {
        'chain': ChainType.SOLANA,
        'address': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
        'name': 'Jupiter',
        'symbol': 'JUP',
        'decimals': 6,
        'logo': 'https://s2.coinmarketcap.com/static/img/coins/64x64/24658.png',
        'category_code': 'defi',
        'is_native': False,
        'is_visible': True,
        'is_recommended': True
    },
]

# 代币分类代码到名称的映射
CATEGORY_CODE_TO_NAME = {cat['code']: cat['name'] for cat in TOKEN_CATEGORIES}

# 获取分类信息的函数
def get_category_by_code(code):
    """根据代码获取分类信息"""
    for category in TOKEN_CATEGORIES:
        if category['code'] == code:
            return category
    return None 