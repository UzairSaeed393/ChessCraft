from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import logout
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from analysis.models import SavedAnalysis
from .utils import fetch_and_save_games
from .models import Game


@login_required
def profile_view(request):
    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        if action == 'delete_all_games':
            with transaction.atomic():
                analyses_qs = SavedAnalysis.objects.filter(user=request.user)
                analyses_count = analyses_qs.count()
                analyses_qs.delete()

                games_qs = Game.objects.filter(user=request.user)
                games_count = games_qs.count()
                games_qs.delete()

            messages.success(request, f"Removed {games_count} game(s) and {analyses_count} analysis record(s).")
            return redirect('profile')

        if action == 'delete_games_for_username':
            chess_username = (request.POST.get('chess_username') or '').strip()
            if not chess_username:
                messages.error(request, 'Please select a Chess.com username.')
                return redirect('profile')

            games_qs = Game.objects.filter(
                user=request.user,
                chess_username_at_time__iexact=chess_username,
            )
            game_ids = list(games_qs.values_list('id', flat=True))

            with transaction.atomic():
                analyses_count = 0
                if game_ids:
                    analyses_qs = SavedAnalysis.objects.filter(user=request.user, game_id__in=game_ids)
                    analyses_count = analyses_qs.count()
                    analyses_qs.delete()

                games_count = games_qs.count()
                games_qs.delete()

            messages.success(
                request,
                f"Removed {games_count} game(s) and {analyses_count} analysis record(s) for {chess_username}.",
            )
            return redirect('profile')

        messages.error(request, 'Invalid action.')
        return redirect('profile')

    chess_usernames = (
        Game.objects.filter(user=request.user)
        .order_by('chess_username_at_time')
        .values_list('chess_username_at_time', flat=True)
        .distinct()
    )

    total_games = Game.objects.filter(user=request.user).count()

    return render(
        request,
        'user/profile.html',
        {
            'chess_usernames': list(chess_usernames),
            'total_games': total_games,
        },
    )

@login_required
def game_view(request):
    if request.method == "POST":
        # 1. Capture data from the form
        chess_username = (request.POST.get('chess_username') or '').strip()
        date_range = request.POST.get('range', 'month') # Default to month if none selected
        
        # 2. Update user profile if the username is provided/changed
        if chess_username and request.user.chess_username != chess_username:
            User = get_user_model()
            if User.objects.exclude(pk=request.user.pk).filter(chess_username__iexact=chess_username).exists():
                messages.error(request, "That Chess.com username is already linked to another account.")
                return redirect('game')

            request.user.chess_username = chess_username
            try:
                request.user.save()
            except IntegrityError:
                messages.error(request, "Could not save Chess.com username (it may already be in use).")
                return redirect('game')

        if not chess_username:
            messages.error(request, "Please enter a Chess.com username to fetch games.")
            return redirect('game')

        # 3. Trigger the logic (we pass request.user so games are linked to THEM)
        success = fetch_and_save_games(request.user, chess_username, date_range)
        
        if success:
            messages.success(request, f"Successfully fetched your {date_range}ly games!")
        else:
            messages.error(request, "Could not fetch games. Please verify the username and try again.")
        
        return redirect('game')

    # GET request: Paginate games belonging to this user, newest first
    username_filter = request.GET.get('username', '').strip()
    opening_filter = request.GET.get('opening', '').strip()
    
    games_qs = Game.objects.filter(user=request.user).order_by('-date_played')
    
    if username_filter:
        games_qs = games_qs.filter(chess_username_at_time__iexact=username_filter)
    if opening_filter:
        games_qs = games_qs.filter(opening__icontains=opening_filter)

    paginator = Paginator(games_qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'user/game.html',
        {
            'games': page_obj.object_list,
            'page_obj': page_obj,
            'paginator': paginator,
            'total_games': games_qs.count(),
            'opening_filter': opening_filter,
        },
    )


@login_required
@require_POST
def delete_account_view(request):
    password = (request.POST.get("password") or "").strip()
    if not password:
        messages.error(request, "Please enter your password to delete your account.")
        return redirect('profile')

    if not request.user.check_password(password):
        messages.error(request, "Incorrect password. Account not deleted.")
        return redirect('profile')

    user_to_delete = request.user
    username = user_to_delete.username

    logout(request)
    user_to_delete.delete()

    messages.success(request, f"Account '{username}' deleted successfully.")
    return redirect('home')