from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import primary_care_services as svc
from .primary_care_forms import PrimaryFamilyForm, PrimaryFamilyMemberForm, PrimaryUnitFilterForm
from .public_services import has_municipal_permission
from .public_views import _context


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def primary_care_home(request):
    svc.primary_capability(request.user)
    can_manage = has_municipal_permission(request.user, 'saude.primary.manage', module='saude_sus')
    can_link = can_manage and has_municipal_permission(request.user, 'saude.patients.view', module='saude_sus')
    action = request.POST.get('action') if request.method == 'POST' else None
    if request.method == 'POST' and (not can_manage or action not in {'family', 'member'} or (action == 'member' and not can_link)):
        raise PermissionDenied('Operação de Atenção Básica não autorizada.')
    filter_form = PrimaryUnitFilterForm(request.GET, actor=request.user)
    unit = filter_form.cleaned_data['unidade'] if filter_form.is_valid() else None
    family_form = PrimaryFamilyForm(request.POST if action == 'family' else None, actor=request.user,
                                    prefix='family', initial={'unidade_saude': unit.pk if unit else None}) if can_manage else None
    member_form = PrimaryFamilyMemberForm(request.POST if action == 'member' else None, actor=request.user, prefix='member') if can_link else None
    selected_form = family_form if action == 'family' else member_form if action == 'member' else None
    if request.method == 'POST' and selected_form.is_valid():
        try:
            data = selected_form.cleaned_data
            if action == 'family':
                svc.create_family(request.user, data=data)
            else:
                svc.link_family_member(request.user, family_id=data['familia'].pk,
                                       citizen_document=data['cidadao'], relationship=data['parentesco'],
                                       reference=data['referencia'])
        except ValidationError as exc:
            selected_form.add_error(None, '; '.join(exc.messages))
        else:
            messages.success(request, 'Operação da UBS registrada e auditada.')
            return redirect('rh_municipal_public:saude_primary')
    rows = []
    if filter_form.is_valid():
        rows = svc.primary_overview(request.user, unit_id=unit.pk if unit else None)
    context = _context(request, title='Atenção Básica / UBS', can_health_primary=True,
                       primary_rows=rows, filter_form=filter_form, family_form=family_form,
                       member_form=member_form, can_manage_primary=can_manage)
    return render(request, 'rh_municipal/primary_care_home.html', context)
