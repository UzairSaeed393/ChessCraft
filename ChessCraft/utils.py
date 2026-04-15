from functools import wraps
from django.http import JsonResponse

def api_error_handler(view_func):
    """
    Common decorator for API views to catch exceptions and return a consistent
    JSON error response with reporting instructions.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Exception as e:
            import traceback
            traceback.print_exc()

            # Persist to DB for later inspection (best-effort)
            try:
                from main.models import ErrorLog
                user = getattr(request, 'user', None)
                if user is not None and not getattr(user, 'is_authenticated', False):
                    user = None

                ip = request.META.get('HTTP_X_FORWARDED_FOR')
                if ip:
                    ip = ip.split(',')[0].strip()
                else:
                    ip = request.META.get('REMOTE_ADDR')

                ErrorLog.objects.create(
                    kind=ErrorLog.KIND_SERVER,
                    user=user,
                    path=(getattr(request, 'path', '') or '')[:512],
                    method=(getattr(request, 'method', '') or '')[:16],
                    status_code=500,
                    message=str(e),
                    traceback=traceback.format_exc(),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    ip_address=ip,
                    extra={'via': 'api_error_handler'},
                )
            except Exception:
                pass

            return JsonResponse({
                'error': 'Internal Error',
                'message': 'An unexpected error occurred. Please report this together with the error details to chesscraftinfo@gmail.com.',
                'details': str(e)
            }, status=500)
    return _wrapped_view
