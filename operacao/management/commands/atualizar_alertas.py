from django.core.management.base import BaseCommand, CommandError
from platform_core.models import Organization, OrganizationMembership
from platform_core.context import tenant_context
from operacao.notifications import scan

class Command(BaseCommand):
    help = 'Atualiza somente alertas internos da organização indicada; não envia e-mail/WhatsApp.'
    def add_arguments(self, parser):
        parser.add_argument('--organization', required=True)
    def handle(self, *args, **options):
        try:
            org=Organization.objects.get(slug=options['organization'], status='ATIVA')
        except Organization.DoesNotExist:
            raise CommandError('Organização ativa não encontrada.')
        member=OrganizationMembership.objects.filter(organization=org,status='ATIVO',role='ADMIN',user__is_active=True,erp_accesses__erp__code='assistencia',erp_accesses__enabled=True).select_related('user').first()
        if not member or not org.erp_accesses.filter(erp__code='assistencia',enabled=True).exists():
            raise CommandError('Organização exige ERP e administrador ativos.')
        with tenant_context(org):
            scan(member.user)
        self.stdout.write('Alertas internos atualizados somente na organização indicada.')
