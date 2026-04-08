from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.conf import settings
from .forms import RegisterForm, LoginForm
from .models import UserOTP, PendingRegistration
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.shortcuts import get_object_or_404
from django.urls import reverse

# Get the User class dynamically
User = get_user_model()

def signup_view(request):
    form = RegisterForm()
    # form = RegisterForm()
    if request.method == "POST":
        user_name = request.POST.get("user_name")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("signup")
                
        if len(password) < 5:
            messages.error(request, "Password must contain at least one number & 5 characters long.")
            return redirect("signup")
        
        if not any(char.isdigit() for char in password):
            messages.error(request, "Password must contain at least one number & 5 characters long.")
            return redirect("signup")
        
        if User.objects.filter(username=user_name).exists():
            messages.error(request, "Username already exists.")
            return redirect("signup")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered.")
            return redirect("signup")

        pending, _ = PendingRegistration.objects.update_or_create(
            email=email,
            defaults={
                "username": user_name,
                "password_hash": make_password(password),
            },
        )
        pending.generate_otp()

        # Send OTP email
        send_mail(
            subject="Your ChessCraft Verification Code",
            message=(
                f"Your OTP For ChessCraft is {pending.otp_code}. It will expire in 5 min. "
                "If you did not ask for otp ignore it"
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
        )

        messages.success(request, "OTP sent to your email. Please verify your account.")
        return redirect("verify", pending_id=pending.id)
    return render(request, "auth/register.html", {"form": form})

def verify_otp_view(request, pending_id):
    pending = get_object_or_404(PendingRegistration, id=pending_id)
    resend_url = reverse("resend_signup_otp", kwargs={"pending_id": pending_id})

    if request.method == "POST":
        entered_otp = request.POST.get("otp")

        if pending.is_expired():
            messages.error(request, "OTP expired. Please request a new one.")
            return redirect("verify", pending_id=pending_id)

        if entered_otp == pending.otp_code:
            if User.objects.filter(username=pending.username).exists():
                messages.error(request, "Username already exists. Please sign up again with a different username.")
                pending.delete()
                return redirect("signup")

            if User.objects.filter(email=pending.email).exists():
                messages.error(request, "Email already registered. Please log in.")
                pending.delete()
                return redirect("login")

            user = User(
                username=pending.username,
                email=pending.email,
                is_active=True,
            )
            user.password = pending.password_hash
            user.save()
            pending.delete()

            messages.success(request, "Account verified! You can now log in.")
            return redirect("login")

        messages.error(request, "Invalid OTP. Try again.")

    return render(request, "auth/verify.html", {"resend_url": resend_url})


def resend_signup_otp(request, pending_id):
    pending = get_object_or_404(PendingRegistration, id=pending_id)

    pending.generate_otp()

    send_mail(
        subject="Your New ChessCraft Verification Code",
        message=f"Your new OTP for ChessCraft is {pending.otp_code}. It expires in 5 minutes.",
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[pending.email],
    )

    messages.success(request, "A new OTP has been sent to your email.")
    return redirect("verify", pending_id=pending_id)

def resend_otp(request, user_id):
    user = User.objects.get(id=user_id)
    otp_obj = UserOTP.objects.get(user=user)

    otp_obj.generate_otp()

    send_mail(
        subject="Your New ChessCraft Verification Code",
        message=f"Your new OTP for ChessCraft is {otp_obj.otp_code}. It expires in 5 minutes.",
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[user.email],
    )

    messages.success(request, "A new OTP has been sent to your email.")
    return redirect("forgot_verify", user_id=user_id)


#   LOGIN VIEW

def login_view(request):
    form = LoginForm()
    if not request.user.is_authenticated and request.GET.get('next'):
        messages.info(request, "Please log in to access that page.")
    if request.method == "POST":
        form = LoginForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]

            # Check if email exists
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                messages.error(request, "User with this email does not exist.")
                return render(request, "auth/login.html", {"form": form})
                
            if not user.is_active:
                messages.error(request, "Account inactive. Please verify your email.")
                return redirect("login")

            user = authenticate(request, username=user.username, password=password)

            if user is not None:
                login(request, user)
                messages.success(request, f"Welcome {user.username}!")
                return redirect("home")
            else:
                messages.error(request, "Incorrect password.")
                return render(request, "auth/login.html", {"form": form})

    return render(request, "auth/login.html", {"form": form})

#   LOGOUT VIEW

def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    # messages.success(request, "Good bye {{user.username}}")

    return redirect("/")

def forgot_password_view(request):
    if request.method == "POST":
        email = request.POST.get("email")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, "Email not registered.")
            return redirect("forgot_password")

        otp_obj, created = UserOTP.objects.get_or_create(user=user)
        otp_obj.generate_otp()

        send_mail(
            subject="ChessCraft Password Reset OTP",
            message=f"Your password reset OTP from ChessCraft is {otp_obj.otp_code}. OTP code will expire in 5 min. If you did not ask for otp ignore it",
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
        )

        messages.success(request, "OTP sent to your email.")
        return redirect("forgot_verify", user_id=user.id)

    return render(request, "auth/forgot_password.html")

def forgot_verify_view(request, user_id):
    user = User.objects.get(id=user_id)
    otp_obj = UserOTP.objects.get(user=user)
    resend_url = reverse("resend_otp", kwargs={"user_id": user_id})

    if request.method == "POST":
        entered_otp = request.POST.get("otp")

        if otp_obj.is_expired():
            messages.error(request, "OTP expired.")
            return redirect("forgot_password")

        if entered_otp == otp_obj.otp_code:
            return redirect("reset_password", user_id=user.id)

        messages.error(request, "Invalid OTP.")

    return render(request, "auth/verify.html", {"resend_url": resend_url})

def reset_password_view(request, user_id):
    user = User.objects.get(id=user_id)

    if request.method == "POST":
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("reset_password", user_id=user.id)

        if len(password) < 5:
            messages.error(request, "Password must be at least 5 characters.")
            return redirect("reset_password", user_id=user.id)
        if not any(char.isdigit() for char in password):
            messages.error(request, "Password must contain at least one number & 5 characters long.")
            return redirect("signup")
        user.set_password(password)
        user.save()

        # Cleanup OTP
        UserOTP.objects.filter(user=user).delete()
        messages.success(request, "Password updated successfully. You can now log in.")
        return redirect("login")

    return render(request, "auth/new_password.html")
