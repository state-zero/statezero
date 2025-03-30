from contextlib import contextmanager
from django.db import connection

@contextmanager
def query_timeout(timeout_ms):
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute(f'SET LOCAL statement_timeout = {timeout_ms};')
            yield
    else:
        # For SQLite or others, no operation
        yield
