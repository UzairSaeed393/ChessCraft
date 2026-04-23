from django.contrib import admin
from .models import ContactMessage, ErrorLog

admin.site.index_template = 'admin/dashboard.html'

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'subject', 'created_at')
    search_fields = ('first_name', 'last_name', 'email', 'subject')
    list_filter = ('created_at',)
    ordering = ('-created_at',)


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'kind', 'user', 'path', 'message')
    list_filter = ('kind', 'created_at')
    search_fields = ('path', 'message', 'traceback', 'source', 'user__username')
    ordering = ('-created_at',)
