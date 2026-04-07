from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import ContactForm


from django.contrib.auth import get_user_model


def contact(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)

        if form.is_valid():
            form.save()  # Save message into ContactMessage table
            messages.success(request, "Your message has been sent successfully!")
            return redirect('contact')

    else:
        form = ContactForm()

    return render(request, 'main/contact.html', {'form': form})


def home(request):
    return render(request, 'main/Home.html')


def about(request):
    return render(request, 'main/about.html')
