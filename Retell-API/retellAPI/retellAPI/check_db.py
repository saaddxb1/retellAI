import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'retellAPI.settings')
django.setup()

print("Current DATABASES setting:")
print(settings.DATABASES['default'])