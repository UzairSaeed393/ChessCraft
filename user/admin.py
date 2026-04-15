from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from main.models import ErrorLog
from .models import Game, User


class ErrorLogInline(admin.TabularInline):
	model = ErrorLog
	fields = ('created_at', 'kind', 'path', 'message')
	readonly_fields = ('created_at', 'kind', 'path', 'message')
	extra = 0
	can_delete = False
	show_change_link = True
	ordering = ('-created_at',)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
	list_display = ('username', 'email', 'chess_username', 'is_staff', 'is_active', 'date_joined', 'last_login')
	search_fields = ('username', 'email', 'chess_username', 'first_name', 'last_name')
	list_filter = ('is_staff', 'is_superuser', 'is_active', 'date_joined')
	ordering = ('-date_joined',)
	inlines = (ErrorLogInline,)

	fieldsets = DjangoUserAdmin.fieldsets + (
		('ChessCraft', {'fields': ('chess_username',)}),
	)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'game_id', 'date_played', 'result', 'accuracy', 'is_analyzed')
	list_filter = ('is_analyzed', 'result')
	search_fields = ('game_id', 'white_player', 'black_player', 'opening', 'user__username', 'user__chess_username')
	ordering = ('-date_played',)
