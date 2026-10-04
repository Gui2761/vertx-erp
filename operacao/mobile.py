from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from platform_core.modules import require_capability

@login_required
def qr_reader(request):
    require_capability(request.user,'planejamento')
    return render(request,'operacao/mobile_qr.html')
