from django.db import connection, DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_safe
from .logging_utils import operation_failure


@require_safe
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        response = JsonResponse({'status': 'ok'})
    except DatabaseError as exc:
        operation_failure('health_database_failed', exc)
        response = JsonResponse({'status': 'unavailable'}, status=503)
    response['Cache-Control'] = 'no-store'
    return response
