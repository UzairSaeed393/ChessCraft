import os

# 1. Fix analysis/views.py
analysis_views_path = r'd:\Web development\Web Projects\ChessCraft\ChessCraft\analysis\views.py'
with open(analysis_views_path, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace local decorator with import
old_decorator = """def api_error_handler(view_func):
    \"\"\"Decorator to catch all exceptions and return a standardized JSON error response.\"\"\"
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Exception as e:
            return JsonResponse({
                'error': 'Internal Error',
                'message': 'Analysis failed unexpectedly. Please report to chesscraftinfo@gmail.com.',
                'details': str(e)
            }, status=500)
    return _wrapped_view"""

import_lines = "from ChessCraft.utils import api_error_handler"

if old_decorator in text:
    text = text.replace(old_decorator, import_lines)
else:
    # Fallback: just put the import after the wraps import
    text = text.replace("from functools import wraps", "from functools import wraps\nfrom ChessCraft.utils import api_error_handler")

with open(analysis_views_path, 'w', encoding='utf-8') as f:
    f.write(text)

# 2. Fix main/views.py
main_views_path = r'd:\Web development\Web Projects\ChessCraft\ChessCraft\main\views.py'
with open(main_views_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
new_lines.append("import json\n")
new_lines.append("from django.shortcuts import render, redirect\n")
new_lines.append("from django.contrib import messages\n")
new_lines.append("from django.http import JsonResponse\n")
new_lines.append("from django.views.decorators.http import require_POST\n")
new_lines.append("from ChessCraft.utils import api_error_handler\n")
new_lines.append("\n")
new_lines.append("from .forms import ContactForm\n")
new_lines.append("from analysis.engine import StockfishManager\n")
new_lines.append("\n")
new_lines.append("def contact(request):\n")
new_lines.append("    if request.method == 'POST':\n")
new_lines.append("        form = ContactForm(request.POST)\n")
new_lines.append("        if form.is_valid():\n")
new_lines.append("            form.save()\n")
new_lines.append("            messages.success(request, \"Your message has been sent successfully!\")\n")
new_lines.append("            return redirect('contact')\n")
new_lines.append("    else:\n")
new_lines.append("        form = ContactForm()\n")
new_lines.append("    return render(request, 'main/contact.html', {'form': form})\n")
new_lines.append("\n")
new_lines.append("def home(request):\n")
new_lines.append("    return render(request, 'main/Home.html')\n")
new_lines.append("\n")
new_lines.append("def about(request):\n")
new_lines.append("    return render(request, 'main/about.html')\n")
new_lines.append("\n")
new_lines.append("@require_POST\n")
new_lines.append("@api_error_handler\n")
new_lines.append("def play_vs_ai(request):\n")
new_lines.append("    body = json.loads(request.body or \"{}\")\n")
new_lines.append("    fen = body.get(\"fen\")\n")
new_lines.append("    elo = int(body.get(\"elo\", 1500))\n")
new_lines.append("    if not fen:\n")
new_lines.append("        return JsonResponse({\"error\": \"FEN is required\"}, status=400)\n")
new_lines.append("    manager = StockfishManager()\n")
new_lines.append("    result = manager.get_analysis(fen, depth=10, multipv=1, elo_limit=elo)\n")
new_lines.append("    return JsonResponse({\"status\": \"success\", \"best_move\": result.get(\"best_move\"), \"evaluation\": result.get(\"evaluation\")})\n")
new_lines.append("\n")
new_lines.append("def error_404(request, exception):\n")
new_lines.append("    return render(request, '404.html', status=404)\n")
new_lines.append("\n")
new_lines.append("def error_500(request):\n")
new_lines.append("    return render(request, '500.html', status=500)\n")

with open(main_views_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Fixes applied successfully.")
