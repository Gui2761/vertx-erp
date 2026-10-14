from django.core.management.base import BaseCommand, CommandError

from platform_core.context import tenant_context
from platform_core.models import MembershipERP, Organization, OrganizationERP, OrganizationMembership

from rh_municipal.models import AcessoRH, PRODUCT_CODE
from rh_municipal.services import audit


class Command(BaseCommand):
    help = 'Provisiona explicitamente o primeiro administrador municipal de um tenant já habilitado.'

    def add_arguments(self, parser):
        parser.add_argument('--organization', required=True, help='Slug da Prefeitura.')
        parser.add_argument('--username', required=True, help='Conta alvo, que já deve possuir acesso ao ERP Gestão Pública.')
        parser.add_argument('--actor', required=True, help='Conta ADMIN da mesma Prefeitura que autorizou o provisionamento.')
        parser.add_argument('--confirm', action='store_true', help='Confirma a atribuição inicial de ADMIN_MUNICIPAL.')

    def handle(self, *args, **options):
        org = Organization.objects.filter(slug=options['organization'], status='ATIVA').first()
        if not org:
            raise CommandError('Organização ativa não encontrada.')
        target = OrganizationMembership.objects.filter(
            organization=org, user__username=options['username'], status='ATIVO',
            erp_accesses__erp__code=PRODUCT_CODE, erp_accesses__erp__active=True, erp_accesses__enabled=True,
        ).select_related('user').first()
        actor = OrganizationMembership.objects.filter(
            organization=org, user__username=options['actor'], status='ATIVO', role='ADMIN',
            erp_accesses__erp__code=PRODUCT_CODE, erp_accesses__erp__active=True, erp_accesses__enabled=True,
        ).select_related('user').first()
        enabled = OrganizationERP.objects.filter(organization=org, erp__code=PRODUCT_CODE, erp__active=True, enabled=True).exists()
        if not enabled or not target or not actor:
            raise CommandError('É necessário habilitar o ERP e confirmar contas alvo e ADMIN autorizador nesta mesma organização.')
        if not options['confirm']:
            self.stdout.write(f'Prévia: atribuir ADMIN_MUNICIPAL a {target.user.username} em {org.slug}, autorizado por {actor.user.username}.')
            self.stdout.write('Nenhuma alteração foi realizada. Repita com --confirm após sua autorização interna.')
            return
        with tenant_context(org):
            access, created = AcessoRH.objects.get_or_create(
                membership=target, papel=AcessoRH.Papel.ADMIN_MUNICIPAL,
                defaults={'atribuido_por': actor.user},
            )
            if created:
                audit(actor.user, 'RH_MUNICIPAL_BOOTSTRAP_ADMIN', access, {
                    'target_membership': target.pk, 'actor_membership': actor.pk,
                    'provisionamento': 'management_command_explicit_confirm',
                })
        self.stdout.write(self.style.SUCCESS('Administrador municipal provisionado.' if created else 'O administrador municipal já estava provisionado.'))
