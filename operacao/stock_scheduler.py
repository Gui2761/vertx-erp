"""Runner persistente/idempotente, independente de requisições e do Gunicorn."""
from django.db import transaction
from django.utils import timezone
from platform_core.models import Organization, OrganizationMembership
from platform_core.context import tenant_context
from .models import Configuracao
from .stock import scan_stock, generate_report

@transaction.atomic
def tick(user, now=None):
    now = now or timezone.now()
    config, _ = Configuracao.objects.get_or_create()
    config = Configuracao.objects.select_for_update().get(pk=config.pk)
    result = {'alertas':False,'relatorio':False}
    if not config.ultima_verificacao_estoque or now >= config.ultima_verificacao_estoque + timezone.timedelta(minutes=config.intervalo_alertas_minutos):
        scan_stock(user, now)
        config.ultima_verificacao_estoque = now
        config.save()
        result['alertas'] = True
    local = timezone.localtime(now)
    week = local.date()-timezone.timedelta(days=local.weekday())
    date = week+timezone.timedelta(days=config.relatorio_dia_semana)
    scheduled = timezone.make_aware(timezone.datetime.combine(date,config.relatorio_horario))
    if config.relatorio_semanal_ativo and now >= scheduled:
        from .models import RelatorioEstoque
        existed = RelatorioEstoque.objects.filter(semana=week,automatico=True).exists()
        generate_report(user,week,automatic=True,now=now)
        result['relatorio'] = not existed
    return result

def organizations(slug=None):
    qs = Organization.objects.filter(status='ATIVA',erp_accesses__erp__code='assistencia',erp_accesses__enabled=True).distinct()
    return qs.filter(slug=slug) if slug else qs

def administrator(org):
    from django.db.models import Case, When, IntegerField
    return OrganizationMembership.objects.filter(organization=org,status='ATIVO',role__in=['ADMIN','GESTOR','ESTOQUE'],user__is_active=True,erp_accesses__erp__code='assistencia',erp_accesses__enabled=True).select_related('user').annotate(priority=Case(When(role='ADMIN',then=0),When(role='GESTOR',then=1),default=2,output_field=IntegerField())).order_by('priority','pk').first()

def run(slug=None, now=None):
    results = []
    for org in organizations(slug):
        member = administrator(org)
        if not member:
            results.append({'organizacao':org.slug,'ignorada':'OPERADOR_ESTOQUE_ERP_ATIVO_AUSENTE'})
            continue
        try:
            with tenant_context(org):
                results.append({'organizacao':org.slug,**tick(member.user,now)})
        except Exception as exc:
            # Sem strings de conexão, credenciais ou traceback em saída agendada.
            results.append({'organizacao':org.slug,'erro':type(exc).__name__})
    return results
