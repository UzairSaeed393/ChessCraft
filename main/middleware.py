import traceback

from django.utils.deprecation import MiddlewareMixin

from .models import ErrorLog


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        # XFF can be a comma-separated list. First is original client.
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class ErrorLoggingMiddleware(MiddlewareMixin):
    """Persist unhandled exceptions to the database.

    Note: exceptions caught/handled inside views (e.g. API decorators) will not
    reach this middleware; those should log at the catch site.
    """

    def process_exception(self, request, exception):
        try:
            user = getattr(request, 'user', None)
            if user is not None and not getattr(user, 'is_authenticated', False):
                user = None

            ErrorLog.objects.create(
                kind=ErrorLog.KIND_SERVER,
                user=user,
                path=(getattr(request, 'path', '') or '')[:512],
                method=(getattr(request, 'method', '') or '')[:16],
                status_code=500,
                message=str(exception),
                traceback=traceback.format_exc(),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                ip_address=_client_ip(request),
                extra={
                    'query_string': request.META.get('QUERY_STRING', ''),
                    'is_ajax': request.headers.get('x-requested-with') == 'XMLHttpRequest',
                },
            )
        except Exception:
            # Never break normal error handling.
            pass

        return None
