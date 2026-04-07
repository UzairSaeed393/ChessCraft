from django import forms

class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "auth-input",
            "placeholder": "Email",
            "id": "id_email",
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "auth-input",
            "placeholder": "Password",
            "id": "id_password",
        })
    )


class RegisterForm(forms.Form):
    user_name = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "auth-input",
            "placeholder": "Name",
            "id": "id_user_name",
        })
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "auth-input",
            "placeholder": "Email",
            "id": "id_email",
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "auth-input",
            "placeholder": "Password",
            "id": "id_password",
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "auth-input",
            "placeholder": "Confirm Password",
            "id": "id_confirm_password",
        })
    )
