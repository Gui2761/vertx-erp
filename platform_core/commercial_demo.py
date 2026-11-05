"""Explicit, transactional DEMO setup; never invoked by startup or migrations."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .context import tenant_context
from .models import Organization, PermissaoMembership
from .modules import CAPABILITIES
from .saas_models import PlanoSaaS, AssinaturaSaaS
from .saas_services import criar_cliente, convidar_avaliador, registrar


@transaction.atomic
def preparar_demo(accounts):
    if not getattr(settings, 'COMMERCIAL_DEMO_ENABLED', False):
        raise ValidationError('A preparação DEMO exige as settings de homologação.')
    if len(accounts) != 3 or len({a['email'].strip().casefold() for a in accounts}) != 3:
        raise ValidationError('Informe três pessoas e e-mails distintos.')
    if Organization.objects.filter(slug='vertyx-demo').exists():
        raise ValidationError('A organização DEMO já existe; nada foi sobrescrito.')
    plan = PlanoSaaS.objects.create(slug='vertyx-commercial-demo', nome='VERTYX DEMO', preco=0,
        modulos=['assistencia', 'estoque', 'financeiro', 'contratos', 'pdv'],
        limites={'usuarios': 3, 'filiais': 1, 'armazenamento_mb': 100})
    owner = criar_cliente(actor=None, plan_id=plan.pk,
        company={'razao_social':'VERTYX DEMO — Empresa Fictícia', 'nome_fantasia':'VERTYX DEMO',
                 'cnpj':'', 'email':'empresa@example.test', 'telefone':'',
                 'endereco':'Endereço fictício DEMO', 'cidade':'Cidade DEMO', 'uf':'SP'},
        admin={'nome':accounts[0]['nome'], 'email':accounts[0]['email'], 'whatsapp':''})
    org = owner['organization']
    org.slug = 'vertyx-demo'; org.save(update_fields=['slug'])
    subscription = org.assinatura_saas
    subscription.status = AssinaturaSaaS.Status.ACTIVE
    subscription.save(update_fields=['status'])
    people = [owner]
    for account, role in zip(accounts[1:], ('TECNICO', 'FINANCEIRO')):
        people.append(convidar_avaliador(actor=owner['user'], organization=org,
                                        nome=account['nome'], email=account['email'], role=role))
    with tenant_context(org):
        for person in people:
            for capability, (module, _) in CAPABILITIES.items():
                if module == 'fiscal':
                    PermissaoMembership.objects.create(membership=person['membership'],
                                                      capacidade=capability, permitido=False)
    from clientes.models import Cliente, Unidade
    from equipamentos.models import CategoriaEquipamento, Equipamento
    from contas.models import Tecnico
    from gestao import models as g, services as gs, forms as gf
    from ordens.forms import OrdemForm
    from ordens import services as os_services
    with tenant_context(org):
        client = Cliente.objects.create(nome_razao_social='Cliente Fictício DEMO',
                                        cpf_cnpj='DEMO-DOC-001', email='cliente@example.test')
        unit = Unidade.objects.create(cliente=client, nome='Unidade DEMO')
        category = CategoriaEquipamento.objects.create(nome='Categoria DEMO')
        equipment = Equipamento.objects.create(cliente=client, unidade=unit, categoria=category,
                                               nome='Equipamento DEMO', numero_serie='DEMO-001')
        tech = Tecnico.objects.create(nome='Profissional DEMO', usuario=people[1]['user'])
        part = g.Peca.objects.create(sku='DEMO-001', descricao='Peça Fictícia DEMO',
                                     preco_venda=25, custo_aquisicao=10)
        gs.movimentar(owner['user'], part.pk, 'ENTRADA', 10, 'Saldo fictício DEMO')
        order_form = OrdemForm({'cliente':client.pk, 'unidade':unit.pk, 'equipamento':equipment.pk,
                                'tecnico':tech.pk, 'tipo_atendimento':'CORRETIVA',
                                'defeito':'Verificação fictícia DEMO'})
        if not order_form.is_valid():
            raise ValidationError('Não foi possível preparar a OS DEMO pelas regras atuais.')
        os_services.criar(owner['user'], order_form)
        today = timezone.localdate()
        contract = gf.ContratoForm({'numero':'DEMO-001', 'cliente':client.pk, 'unidades':[unit.pk],
            'equipamentos':[equipment.pk], 'data_inicial':today.isoformat(),
            'data_final':(today+timezone.timedelta(days=90)).isoformat(), 'valor':'100.00',
            'periodicidade_cobranca':'MENSAL', 'tipo':'Manutenção DEMO', 'quantidade_visitas':1,
            'periodicidade_preventiva_meses':1, 'status':'ATIVO'})
        if not contract.is_valid():
            raise ValidationError('Não foi possível preparar o contrato DEMO pelas regras atuais.')
        gs.salvar_contrato(owner['user'], contract)
        quote = gs.write(g.Orcamento(cliente=client, unidade=unit, equipamento=equipment,
            validade=today+timezone.timedelta(days=30), criado_por=owner['user'],
            diagnostico='Avaliação fictícia DEMO', servicos='Serviço fictício DEMO'))
        gs.write(g.ItemOrcamento(orcamento=quote, tipo='SERVICO', descricao='Serviço DEMO',
                                quantidade=1, valor_unitario=50))
        gs.audit(owner['user'], 'ORCAMENTO_DEMO', quote)
        import uuid
        from operacao import models as operations, commerce
        depot = operations.Deposito.objects.get(nome='Principal')
        cash = operations.ContaBancaria.objects.create(nome='Caixa Fictício DEMO', tipo='CAIXA',
                                                      deposito_padrao=depot)
        session = commerce.open_cash(owner['user'], cash.pk, 0, uuid.uuid4())
        sale = commerce.new_sale(owner['user'], session.public_id, depot.pk, customer_id=client.pk)
        commerce.add_item(owner['user'], sale.public_id, part.sku, 1)
        money = g.FormaPagamento.objects.get(tipo_pdv='DINHEIRO', ativo=True)
        commerce.finalize(owner['user'], sale.public_id,
                          [{'forma':money.pk, 'valor':'25.00'}], uuid.uuid4())
        gs.audit(owner['user'], 'DEMO_PREPARADA', client, {'dados':'fictícios'})
    registrar(owner['user'], 'DEMO_PREPARADA', f'organization:{org.pk}', organization=org)
    return org, people
