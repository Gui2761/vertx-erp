"""Read-only impact inventory; never grants capabilities or changes cash."""
import json
from django.core.management.base import BaseCommand, CommandError
from platform_core.models import Organization, OrganizationMembership
from platform_core.context import tenant_context
from platform_core.modules import has_capability
from operacao.models import SessaoCaixa

class Command(BaseCommand):
    help='Lista vendedores com histórico de operação de caixa sem alterar dados.'
    def add_arguments(self,parser):parser.add_argument('--organization',required=True)
    def handle(self,*args,**options):
        try:org=Organization.objects.get(slug=options['organization'])
        except Organization.DoesNotExist:raise CommandError('Organização não encontrada.')
        rows=[]
        with tenant_context(org):
            for member in OrganizationMembership.objects.filter(organization=org,role='VENDEDOR').select_related('user'):
                sessions=SessaoCaixa.objects.filter(operador=member.user)
                if sessions.exists():rows.append({'usuario':member.user.username,'membership_status':member.status,'caixas_operados':list(sessions.values('public_id','conta__nome','aberto_em','fechado_em')),'operar_pdv':has_capability(member.user,'operar_pdv')})
        self.stdout.write(json.dumps({'organization':org.slug,'vendedores_afetados':rows,'somente_leitura':True,'concessoes_automaticas':False},default=str,ensure_ascii=False,indent=2))
