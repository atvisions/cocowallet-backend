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
from website.views import home, download_app  # 确保从website导入
from django.views.decorators.csrf import csrf_exempt
from wallet.admin import admin_site
from django.views.generic import TemplateView

urlpatterns = [
    path('', csrf_exempt(home), name='home'),  # 主页视图
    path('download/app', csrf_exempt(download_app), name='download_app'),  # 下载视图
    path('admin/', admin_site.urls),  # 管理后台
    path('api/v1/', include('wallet.urls')),  # 钱包API路径
    path('api/v1/tasks/', include('tasks.urls')),  # 任务API路径
    path('', TemplateView.as_view(template_name='index.html')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 在开发环境中提供静态文件
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)