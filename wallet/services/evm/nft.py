"""EVM NFT 服务"""
import logging
from typing import Dict, List, Any, Optional
from decimal import Decimal
import aiohttp
from web3 import Web3

from ...api_config import RPCConfig
from .utils import EVMUtils

logger = logging.getLogger(__name__)

class EVMNFTService:
    """EVM NFT 服务实现类"""

    def __init__(self, chain: str):
        """初始化
        
        Args:
            chain: 链标识(ETH/BSC/POLYGON/AVAX/BASE)
        """
        self.chain = chain
        self.chain_config = EVMUtils.get_chain_config(chain)
        self.web3 = EVMUtils.get_web3(chain)
        
        # Alchemy API 配置
        self.api_url = RPCConfig.get_alchemy_url(chain)
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }
        self.timeout = aiohttp.ClientTimeout(total=30) 