
from pathlib import Path
import os
import environ

# 1. Base Directory Setup
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. Environment Variables Configuration
env = environ.Env()
# This line tells Django to look for the .env file in the same folder as manage.py
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# 3. Security Settings
# Values are pulled from your .env file for security
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG', default=False)

# Combined your Azure Public IP and local development addresses
allowed_hosts_str = env('ALLOWED_HOSTS', default='chesscraft.me,www.chesscraft.me,20.189.112.196,localhost,127.0.0.1')
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_str.split(',')]

# CSRF Trusted Origins (Required for Django 4.0+ in production)
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=['https://chesscraft.me', 'https://www.chesscraft.me'])


# Analysis engine settings used by analysis.engine.StockfishManager
ANALYSIS_ENGINE_MODE = env('ANALYSIS_ENGINE_MODE', default='local')
ANALYSIS_ENGINE_URL = env('ANALYSIS_ENGINE_URL', default='')
ANALYSIS_ENGINE_TOKEN = env('ANALYSIS_ENGINE_TOKEN', default='')
# Full game review depth (batch review only). Live/single-position endpoints still use ANALYSIS_ENGINE_DEPTH.
ANALYSIS_GAME_REVIEW_DEPTH = env.int('ANALYSIS_GAME_REVIEW_DEPTH', default=20)

# 4. Site Identification
SITE_ID = env.int('SITE_ID', default=1)
SITE_URL = env('SITE_URL', default='http://localhost:8000')

# 5. Application Definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'authentication',
    'main',
    'user',
    'analysis',
    'insights',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'main.middleware.ErrorLoggingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# 6. Production Security Hardening
# These kick in only when DEBUG=False, keeping local dev easy
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
    CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
    
    # HSTS settings
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_PRELOAD = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    
    # Required if you're behind an Nginx reverse proxy
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# 7. Templates and WSGI
ROOT_URLCONF = 'ChessCraft.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'libraries': {
                'game_extras': 'user.templatetags.game_extras',
            },
        },
    },
]

WSGI_APPLICATION = 'ChessCraft.wsgi.application'

# 8. Database Configuration
# Default stays PostgreSQL. Set DB_ENGINE=sqlite on laptop for offline/local fallback.
db_engine = env('DB_ENGINE', default='postgres').lower()

if db_engine in {'sqlite', 'sqlite3'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME'),
            'USER': env('DB_USER'),
            'PASSWORD': env('DB_PASSWORD'),
            'HOST': env('DB_HOST', default='localhost'),
            'PORT': env('DB_PORT', default='5432'),
            'OPTIONS': {
                'connect_timeout': env.int('DB_CONNECT_TIMEOUT', default=6),
            },
        }
    }

# 7. User & Authentication
AUTH_USER_MODEL = 'user.User'
LOGIN_URL = '/auth/login/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 8. Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# 9. Static and Media Files
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfile')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

# Use CompressedStaticFilesStorage locally for better reliability; manifest for prod
if DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# 10. Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')

# Stockfish Configuration
# Auto-detect stockfish path
# def find_stockfish():
#     """Try to find the Stockfish executable."""
#     # Check project-local stockfish directory first
#     local_paths = list((BASE_DIR / 'stockfish').rglob('stockfish*.exe'))
#     if local_paths:
#         return str(local_paths[0])
    
#     # Common Windows installation paths
#     common_paths = [
#         r'C:\stockfish\stockfish.exe',
#         r'C:\Program Files\Stockfish\stockfish.exe',
#         r'C:\Program Files (x86)\Stockfish\stockfish.exe',
#     ]
#     for p in common_paths:
#         if os.path.isfile(p):
#             return p
    
#     # Check PATH
#     import shutil
#     sf = shutil.which('stockfish')
#     if sf:
#         return sf
    
#     return None

# STOCKFISH_PATH = os.environ.get('STOCKFISH_PATH') or find_stockfish()
# STOCKFISH_DEPTH = int(os.environ.get('STOCKFISH_DEPTH', '18'))

# # Email Configuration
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True

# EMAIL_HOST_USER = env('EMAIL_HOST_USER')
# EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
# DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')

ANALYSIS_GAME_REVIEW_DEPTH = 16