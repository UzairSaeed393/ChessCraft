from django.db import models
import random
from django.utils import timezone
from datetime import timedelta
from django.conf import settings


class PendingRegistration(models.Model):
    username = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=128)

    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True)

    def generate_otp(self):
        self.otp_code = str(random.randint(100000, 999999))
        self.expires_at = timezone.now() + timedelta(minutes=5)
        self.save(update_fields=["otp_code", "expires_at"])

    def is_expired(self):
        return bool(self.expires_at) and timezone.now() > self.expires_at

class UserOTP(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
    )
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True)

    def generate_otp(self):
        self.otp_code = str(random.randint(100000, 999999))
        self.expires_at = timezone.now() + timedelta(minutes=5)  # OTP EXPIRES IN 5 MINUTES
        self.save()

    def is_expired(self):
        return timezone.now() > self.expires_at
