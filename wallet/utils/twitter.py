import tweepy
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class TwitterValidator:
    def __init__(self):
        self.client = None
        self.setup_client()

    def setup_client(self):
        """初始化 Twitter API 客户端"""
        try:
            self.client = tweepy.Client(
                bearer_token=settings.TWITTER_BEARER_TOKEN,
                consumer_key=settings.TWITTER_API_KEY,
                consumer_secret=settings.TWITTER_API_SECRET,
                access_token=settings.TWITTER_ACCESS_TOKEN,
                access_token_secret=settings.TWITTER_ACCESS_TOKEN_SECRET
            )
            logger.info("Twitter API client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Twitter API client: {str(e)}")
            self.client = None

    def verify_tweet(self, tweet_id, token_data):
        """
        验证推文
        tweet_id: 可以是推文ID或者用户名
        """
        try:
            if not self.client:
                logger.error("Twitter API client not initialized")
                return False, "Twitter API configuration error"

            # 如果输入的是用户名而不是推文ID
            if tweet_id.startswith('@'):
                username = tweet_id[1:]  # 移除@符号
                # 获取用户最近的推文
                tweets = self.client.get_users_tweets(
                    username,
                    max_results=5,  # 获取最近5条推文
                    tweet_fields=['created_at', 'text']
                )
                
                if not tweets or not tweets.data:
                    return False, "未找到最近的推文"

                # 检查最近的推文是否包含必要内容
                for tweet in tweets.data:
                    if self._verify_tweet_content(tweet, token_data):
                        return True, "验证成功"
                        
                return False, "未找到包含必要内容的推文"
            else:
                # 如果是推文ID，直接验证该推文
                tweet = self.client.get_tweet(
                    tweet_id,
                    tweet_fields=['created_at', 'text']
                )
                
                if not tweet or not tweet.data:
                    return False, "推文不存在"

                if self._verify_tweet_content(tweet.data, token_data):
                    return True, "验证成功"
                
                return False, "推文内容不符合要求"

        except Exception as e:
            logger.error(f"验证推文失败: {str(e)}")
            return False, str(e)

    def _verify_tweet_content(self, tweet, token_data):
        """验证推文内容"""
        tweet_text = tweet.text.lower()
        required_content = [
            token_data['symbol'].lower(),
            '#cocoswap'
        ]
        
        return all(content in tweet_text for content in required_content) 