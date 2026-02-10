from pathlib import Path
from django.conf import settings
from django.http import HttpResponse

def putevoy_page(request):
    p = Path(settings.BASE_DIR) / "putevoy.html"
    if not p.exists():
        return HttpResponse("putevoy.html not found in project root", status=404)
    return HttpResponse(
        p.read_text(encoding="utf-8"),
        content_type="text/html; charset=utf-8",
    )
