from django.conf import settings
from django.db import models

# Create your models here.
class ContactMessage(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.subject}"


class ErrorLog(models.Model):
    KIND_SERVER = 'server'
    KIND_CLIENT = 'client'
    KIND_CHOICES = (
        (KIND_SERVER, 'Server'),
        (KIND_CLIENT, 'Client'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='error_logs',
    )

    path = models.CharField(max_length=512, blank=True)
    method = models.CharField(max_length=16, blank=True)
    status_code = models.PositiveIntegerField(null=True, blank=True)

    message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)

    source = models.CharField(max_length=256, blank=True)
    lineno = models.IntegerField(null=True, blank=True)
    colno = models.IntegerField(null=True, blank=True)

    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        who = self.user.username if self.user_id else 'anon'
        return f"{self.kind} {who} {self.path}"