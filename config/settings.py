"""
Django settings for coco_wallet project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
import logging
import mimetypes

# 加载 .env 文件
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path)

# 获取 API keys
MORALIS_API_KEY = os.getenv('MORALIS_API_KEY')
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')
REFERRAL_SECRET_KEY = os.getenv('REFERRAL_SECRET_KEY', '7fedd4558bc93349105de9b05b86c3ac58fa51eb516ced7dddd563b63c3f25c1')

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-your-secret-key'

# 钱包加密密钥 (32位)
WALLET_ENCRYPTION_KEY = b'mAQJ/L2HaZOZ4Ix7+g4WNA00zVGEr5XQ66ICVhwMKGk='

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'wallet',
    'channels',
]

# 中间件顺序很重要
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS 和 CSRF 设置
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    'http://192.168.3.16:8000',
    'http://localhost:8000',
    'https://www.cocowallet.io',
    'https://cocowallet.io',
    'app://cocowallet.io'
]

# 添加允许的请求头和方法
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'device-id',
]

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# 安全设置
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = False  # 开发环境设为 False
SESSION_COOKIE_SECURE = False  # 开发环境设为 False
CSRF_COOKIE_SECURE = False  # 开发环境设为 False

if not DEBUG:
    ALLOWED_HOSTS = [
        '192.168.3.16',
        'localhost',
        '.cocowallet.io',
        'www.cocowallet.io',
        'api.cocowallet.io',
    ]
    
    # 生产环境的安全设置
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'wallet/templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'coco_wallet',
        'USER': 'root',
        'PASSWORD': '@Liuzhao-9575@',
        'HOST': 'localhost',
        'PORT': '3306',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 登录界面配置
# SIMPLEUI_LOGIN_TITLE = 'Coco Wallet 管理后台'  # 登录页标题
# SIMPLEUI_LOGIN_BACKGROUND = None  # 使用默认背景

# 支持的区块链配置
SUPPORTED_CHAINS = {
    'BTC': {
        'name': '比特币',
        'path': "m/44'/0'/0'/0/0",
        'symbol': 'BTC'
    },
    'ETH': {
        'name': '以太坊',
        'path': "m/44'/60'/0'/0/0",
        'symbol': 'ETH'
    },
    'BNB': {
        'name': '币安智能链',
        'path': "m/44'/60'/0'/0/0",
        'symbol': 'BNB'
    },
    'MATIC': {
        'name': 'Polygon',
        'path': "m/44'/60'/0'/0/0",
        'symbol': 'MATIC'
    },
    'AVAX': {
        'name': 'Avalanche',
        'path': "m/44'/60'/0'/0/0",
        'symbol': 'AVAX'
    },
    'SOL': {
        'name': 'Solana',
        'path': "m/44'/501'/0'/0'",
        'symbol': 'SOL'
    }
}

# 日志配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'wallet': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': True,
        },
    }
}

# 在 settings.py 中添加调试日志
logger = logging.getLogger(__name__)

logger.debug(f"Loading .env from: {env_path}")
logger.debug(f"MORALIS_API_KEY loaded: {'*' * len(MORALIS_API_KEY) if MORALIS_API_KEY else 'Not found'}")

# ASGI 配置
ASGI_APPLICATION = 'config.asgi.application'

# 异步设置
ASYNC_TIMEOUT = 30  # 30秒全局超时
CONCURRENT_REQUESTS_PER_WORKER = 3

# Channels 配置
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}

# 使用绝对路径
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# 添加这个配置
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

# 添加APK文件的MIME类型
mimetypes.add_type('application/vnd.android.package-archive', '.apk')

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [],
}

# 添加CSRF配置
CSRF_TRUSTED_ORIGINS = [
    'https://www.cocowallet.io',
    'https://cocowallet.io',
    'http://localhost:8000',
    'http://192.168.3.16:8000',
]

# 如果你的前端在不同域名下，确保设置正确的CSRF cookie
CSRF_COOKIE_DOMAIN = '.cocowallet.io'  # 允许所有子域名共享CSRF cookie
CSRF_USE_SESSIONS = False  # 使用cookie存储CSRF而非session
CSRF_COOKIE_SAMESITE = 'Lax'  # 或根据需要设置为'None'，但必须确保HTTPS
