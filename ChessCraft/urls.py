from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [

    path('', include('main.urls')),
    path('admin/', admin.site.urls),
    path('auth/', include('authentication.urls')),
    path('user/', include('user.urls')),
    path('analysis/', include('analysis.urls')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# if settings.DEBUG:
#     urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)