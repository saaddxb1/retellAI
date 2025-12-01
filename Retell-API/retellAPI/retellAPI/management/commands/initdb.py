from django.core.management.base import BaseCommand
from retellAPI.models import create_dummy_data

class Command(BaseCommand):
    help = 'Initialize the database with dummy data'

    def handle(self, *args, **options):
        create_dummy_data()
        self.stdout.write(self.style.SUCCESS('Successfully initialized database with dummy data'))