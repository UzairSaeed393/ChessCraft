from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup_view, name="signup"),
    path('login/', views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("verify/<int:user_id>/", views.verify_otp_view, name="verify"),
    path("resend/<int:user_id>/", views.resend_otp, name="resend_otp"),
    path("forgot-password/", views.forgot_password_view, name="forgot_password"),
    path("forgot-verify/<int:user_id>/", views.forgot_verify_view, name="forgot_verify"),
    path("reset-password/<int:user_id>/", views.reset_password_view, name="reset_password"),
]
