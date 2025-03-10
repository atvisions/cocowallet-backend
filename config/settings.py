"""
Django settings for coco_wallet project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
import logging

# 加载 .env 文件
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path)

# 获取 API keys
MORALIS_API_KEY = os.getenv('MORALIS_API_KEY')
ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY')
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY')

# 确保必要的 API key 存在
if not MORALIS_API_KEY:
    raise Exception("MORALIS_API_KEY not found in environment variables")

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
    'jet.dashboard',  # 必须在 jet 之前
    'jet',  # 必须在 django.contrib.admin 之前
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'drf_yasg',
    'wallet',
    'channels',
]

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
CORS_ALLOWED_ORIGINS = [
    "http://192.168.3.16:8081",  # Expo Go
    "http://192.168.3.3",
]
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
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django Jet 配置
JET_DEFAULT_THEME = 'light-blue'
JET_THEMES = [
    {
        'theme': 'default',
        'color': '#47bac1',
        'title': '默认'
    },
    {
        'theme': 'green',
        'color': '#44b78b',
        'title': '绿色'
    },
    {
        'theme': 'light-green',
        'color': '#2faa60',
        'title': '浅绿色'
    },
    {
        'theme': 'light-violet',
        'color': '#a464c4',
        'title': '浅紫色'
    },
    {
        'theme': 'light-blue',
        'color': '#5EADDE',
        'title': '浅蓝色'
    },
    {
        'theme': 'light-gray',
        'color': '#222',
        'title': '浅灰色'
    }
]
JET_SIDE_MENU_COMPACT = True  # 紧凑的侧边栏
JET_CHANGE_FORM_SIBLING_LINKS = True  # 显示上一个/下一个链接

# Jet 菜单配置
JET_SIDE_MENU_ITEMS = [
    {'label': '认证和授权', 'items': [
        {'name': 'auth.user'},
        {'name': 'auth.group'},
    ]},
    {'label': '钱包管理', 'items': [
        {'name': 'wallet.wallet'},
        {'name': 'wallet.mnemonicbackup'},
        {'name': 'wallet.paymentpassword'},
    ]},
    {'label': '代币管理', 'items': [
        {'name': 'wallet.tokenindex'},
        {'name': 'wallet.token'},
    ]},
    {'label': 'NFT管理', 'items': [
        {'name': 'wallet.nftcollection'},
    ]},
    {'label': '交易记录', 'items': [
        {'name': 'wallet.transaction'},
    ]},
]

# 登录界面配置
SIMPLEUI_LOGIN_TITLE = 'Coco Wallet 管理后台'  # 登录页标题
SIMPLEUI_LOGIN_BACKGROUND = None  # 使用默认背景

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
        'level': 'DEBUG',
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