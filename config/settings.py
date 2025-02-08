"""
Django settings for coco_wallet project.
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-your-secret-key'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

# Application definition
INSTALLED_APPS = [
    'simpleui',  # 必须在 django.contrib.admin 之前
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'wallet',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

# SimpleUI 配置
SIMPLEUI_CONFIG = {
    'system_keep': False,
    'menu_display': ['钱包管理', '代币管理', 'NFT管理', '交易记录', '认证和授权'],
    'dynamic': True,
    'menus': [{
        'name': '钱包管理',
        'icon': 'fas fa-wallet',
        'models': [{
            'name': '钱包',
            'icon': 'fas fa-wallet',
            'url': 'wallet/wallet/'
        }, {
            'name': '助记词备份',
            'icon': 'fas fa-key',
            'url': 'wallet/mnemonicbackup/'
        }, {
            'name': '支付密码',
            'icon': 'fas fa-lock',
            'url': 'wallet/paymentpassword/'
        }]
    }, {
        'name': '代币管理',
        'icon': 'fas fa-coins',
        'models': [{
            'name': '代币',
            'icon': 'fas fa-coin',
            'url': 'wallet/token/'
        }, {
            'name': '代币索引',
            'icon': 'fas fa-list',
            'url': 'wallet/tokenindex/'
        }]
    }, {
        'name': 'NFT管理',
        'icon': 'fas fa-images',
        'models': [{
            'name': 'NFT合集',
            'icon': 'fas fa-image',
            'url': 'wallet/nftcollection/'
        }]
    }, {
        'name': '交易记录',
        'icon': 'fas fa-exchange-alt',
        'models': [{
            'name': '交易',
            'icon': 'fas fa-exchange-alt',
            'url': 'wallet/transaction/'
        }]
    }]
}

# SimpleUI 设置
SIMPLEUI_DEFAULT_THEME = 'element'  # 使用 Element UI 主题
SIMPLEUI_HOME_TITLE = 'Coco Wallet 管理后台'  # 首页标题
SIMPLEUI_LOGO = 'https://example.com/path/to/your/logo.png'  # 替换成您的 logo URL
SIMPLEUI_HOME_INFO = False  # 关闭首页的快捷导航
SIMPLEUI_ANALYSIS = False  # 关闭使用分析
SIMPLEUI_STATIC_OFFLINE = True  # 使用离线模式

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

# Moralis API配置
MORALIS_API_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6IjZiNGRlNzlkLTc3YzctNGM1Ny04MDE4LTNmYzk1OGUxOTBiYSIsIm9yZ0lkIjoiNDI4MzE0IiwidXNlcklkIjoiNDQwNTc1IiwidHlwZUlkIjoiNDE4MjdjY2UtYmNhMi00YjZiLTgzMmUtMDE1ZWNmZGMwODZkIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3MzgyNDY2NDYsImV4cCI6NDg5NDAwNjY0Nn0.fj9LXbkQcSLMLIjoeD6IXkLLVigPQx3wNaSiUzfQkl8'  # 请替换为您的实际API密钥
MORALIS_API_URL = 'https://deep-index.moralis.io/api/v2'

# 日志配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': 'logs/debug.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'wallet': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}