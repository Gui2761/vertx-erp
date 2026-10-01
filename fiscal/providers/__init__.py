from django.core.exceptions import ValidationError

ADAPTERS = {}

def resolve(name, organization, environment):
    """Registro explícito de adaptadores revisados, nunca import informado pelo usuário.

    A fábrica recebe organização/ambiente e deve buscar segredos de um cofre ou
    configuração externa específica da empresa. Nenhum token pertence ao banco ERP.
    """
    factory = ADAPTERS.get(name)
    if not factory:
        raise ValidationError('Integração fiscal não configurada. Defina provedor, credenciais externas, cadastro fiscal e ambiente com o contador antes de emitir.')
    return factory(organization=organization, environment=environment)
