"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from wallet.views.website import home, download_app
from django.views.decorators.csrf import csrf_exempt

urlpatterns = [
    path('', csrf_exempt(home), name='home'),  # 仅为主页视图豁免CSRF
    path('download/app', download_app, name='download_app'),
    path('admin/', admin.site.urls),  # 管理后台保持CSRF保护
    path('api/v1/', include('wallet.urls')),  # API视图路径保持不变
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 在开发环境中提供静态文件
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)