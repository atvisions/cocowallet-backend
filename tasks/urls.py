from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views.task_system import TaskSystemViewSet

router = DefaultRouter()
router.register('', TaskSystemViewSet, basename='task')

urlpatterns = [
    path('', include(router.urls)),
]