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
            return JsonResponse({
                'error': 'Internal Error',
                'message': 'An unexpected error occurred. Please report this together with the error details to chesscraftinfo@gmail.com.',
                'details': str(e)
            }, status=500)
    return _wrapped_view
