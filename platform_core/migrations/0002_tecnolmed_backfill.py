from django.db import migrations
from django.db.models import F


def establish_first_tenant(apps, schema_editor):
    database = schema_editor.connection.alias
    Organization = apps.get_model('platform_core', 'Organization')
    Catalog = apps.get_model('platform_core', 'ERPCatalog')
    OrganizationERP = apps.get_model('platform_core', 'OrganizationERP')
    Membership = apps.get_model('platform_core', 'OrganizationMembership')
    MembershipERP = apps.get_model('platform_core', 'MembershipERP')
    organization, _ = Organization.objects.using(database).get_or_create(slug='tecnolmed', defaults={'razao_social': 'TECNOLMED', 'nome_fantasia': 'TECNOLMED', 'cnpj': '', 'status': 'ATIVA'})
    erp, _ = Catalog.objects.using(database).get_or_create(code='assistencia', defaults={'name': 'ERP Assistência', 'description': 'Gestão completa de assistência técnica.', 'active': True})
    OrganizationERP.objects.using(database).get_or_create(organization=organization, erp=erp, defaults={'enabled': True})
    for app, name in [('clientes', 'Cliente'), ('contas', 'Tecnico'), ('equipamentos', 'CategoriaEquipamento'), ('equipamentos', 'Equipamento'), ('ordens', 'OrdemServico')]:
        Model = apps.get_model(app, name)
        Model.objects.using(database).filter(organization__isnull=True).update(organization_id=organization.pk)
        if Model.objects.using(database).filter(organization__isnull=True).exists():
            raise RuntimeError(f'Registros sem organização em {app}.{name}')
    User = apps.get_model('contas', 'Usuario')
    for user in User.objects.using(database).filter(is_superuser=False).iterator(chunk_size=1000):
        membership, _ = Membership.objects.using(database).get_or_create(user_id=user.pk, organization_id=organization.pk, defaults={'role': user.perfil, 'status': 'ATIVO' if user.is_active else 'INATIVO', 'joined_at': user.date_joined})
        MembershipERP.objects.using(database).get_or_create(membership=membership, erp=erp, defaults={'enabled': True})
    # Não alterar o JSON/digest assinado. O emissor anterior é metadado separado.
    Conference = apps.get_model('ordens', 'Conferencia')
    issuer = {'id': str(organization.public_id), 'nome': organization.nome_fantasia or organization.razao_social, 'razao_social': organization.razao_social, 'cnpj': '', 'email': organization.email, 'telefone': organization.telefone, 'details': organization.document_details, 'logo_key': organization.logo_key}
    for conference in Conference.objects.using(database).filter(issuer={}).iterator(chunk_size=1000):
        if 'organization' not in conference.dados:
            Conference.objects.using(database).filter(pk=conference.pk).update(issuer=issuer)
    # Verificação antes dos campos obrigatórios.
    Equipment = apps.get_model('equipamentos', 'Equipamento')
    Order = apps.get_model('ordens', 'OrdemServico')
    if Equipment.objects.using(database).exclude(organization_id=F('cliente__organization_id')).exists() or Equipment.objects.using(database).exclude(organization_id=F('categoria__organization_id')).exists():
        raise RuntimeError('Equipamentos com vínculo entre organizações diferentes.')
    for relation in ['cliente', 'equipamento', 'tecnico']:
        if Order.objects.using(database).exclude(organization_id=F(f'{relation}__organization_id')).exists():
            raise RuntimeError(f'OS com vínculo inconsistente em {relation}.')


class Migration(migrations.Migration):
    dependencies = [
        ('platform_core', '0001_initial'),
        ('clientes', '0002_cliente_organization_alter_cliente_cpf_cnpj_and_more'),
        ('contas', '0002_tecnico_organization_alter_tecnico_usuario_and_more'),
        ('equipamentos', '0002_categoriaequipamento_organization_and_more'),
        ('ordens', '0004_conferencia_issuer'),
    ]
    operations = [migrations.RunPython(establish_first_tenant, migrations.RunPython.noop)]
