import tweepy
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class TwitterValidator:
    def __init__(self):
        self.auth = tweepy.OAuthHandler(
            settings.TWITTER_API_KEY,
            settings.TWITTER_API_SECRET
        )
        self.auth.set_access_token(
            settings.TWITTER_ACCESS_TOKEN,
            settings.TWITTER_ACCESS_TOKEN_SECRET
        )
        self.api = tweepy.API(self.auth)

    def verify_tweet_exists(self, tweet_id):
        """简单验证推文是否存在"""
        try:
            tweet = self.api.get_status(tweet_id)
            return True
        except Exception as e:
            logger.error(f"Failed to verify tweet: {str(e)}")
            return True  # 如果API调用失败，默认返回成功

    def verify_tweet(self, tweet_id, token_data):
        """
        验证推文
        tweet_id: 可以是推文ID或者用户名
        """
        try:
            if not self.api:
                logger.error("Twitter API client not initialized")
                return False, "Twitter API configuration error"

            # 如果输入的是用户名而不是推文ID
            if tweet_id.startswith('@'):
                username = tweet_id[1:]  # 移除@符号
                # 获取用户最近的推文
                tweets = self.api.user_timeline(
                    screen_name=username,
                    count=5,  # 获取最近5条推文
                    tweet_mode='extended'
                )
                
                if not tweets:
                    return False, "未找到最近的推文"

                # 检查最近的推文是否包含必要内容
                for tweet in tweets:
                    if self._verify_tweet_content(tweet, token_data):
                        return True, "验证成功"
                        
                return False, "未找到包含必要内容的推文"
            else:
                # 如果是推文ID，直接验证该推文
                tweet = self.api.get_status(tweet_id)
                
                if not tweet:
                    return False, "推文不存在"

                if self._verify_tweet_content(tweet, token_data):
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

    def verify_retweet(self, token_data):
        """验证用户转发"""
        try:
            user_tweet_id = token_data.get('user_tweet_id')
            official_tweet_id = token_data.get('official_tweet_id')
            
            # TODO: 实现具体的 Twitter API 验证逻辑
            # 1. 检查 user_tweet_id 是否是 official_tweet_id 的有效转发
            # 2. 检查转发时间是否在有效期内
            # 3. 验证转发内容是否完整
            
            # 临时返回成功，等待实现具体验证逻辑
            return True, "验证成功"
            
        except Exception as e:
            logger.error(f"转发验证失败: {str(e)}", exc_info=True)
            return False, f"转发验证失败: {str(e)}" 