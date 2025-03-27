from django.core.management.base import BaseCommand
from django.conf import settings
from wallet.models import Task

class Command(BaseCommand):
    help = '同步任务配置到数据库'

    def handle(self, *args, **options):
        for task_type, config in settings.TASK_REWARDS.items():
            task, created = Task.objects.get_or_create(
                code=task_type,
                defaults={
                    'name': config['name'],
                    'task_type': task_type,
                    'description': config['description'],
                    'points': config['points'],
                    'is_repeatable': config['is_repeatable'],
                    'stages_config': config.get('stages_config', {})
                }
            )
            
            if not created:
                # 更新现有任务的配置
                task.points = config['points']
                task.name = config['name']
                task.description = config['description']
                task.is_repeatable = config['is_repeatable']
                task.stages_config = config.get('stages_config', {})
                task.save()
                
                self.stdout.write(
                    self.style.SUCCESS(f'Updated task: {task.name}')
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f'Created new task: {task.name}')
                ) 