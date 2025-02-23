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