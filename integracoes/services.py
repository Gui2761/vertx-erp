"""Preview-first imports over existing tenant models and audited services."""
import copy
import hashlib
import json
import re
import uuid
from datetime import datetime
from decimal import Decimal,InvalidOperation
from pathlib import PurePath
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F,Value,Count
from django.db.models.functions import Replace
from django.utils import timezone
from platform_core.context import current_organization
from platform_core.models import Organization
from platform_core.modules import require_capability,module_enabled
from platform_core.validators import validate_cnpj
from gestao import models as g,services as gs
from clientes.models import Cliente
from equipamentos.models import Equipamento,CategoriaEquipamento
from operacao import models as m
from .catalog import CATALOG,suggest
from .readers import read,MAX_BYTES,MAX_CELL

MODELS={'produtos':g.Peca,'clientes':Cliente,'fornecedores':g.Fornecedor,'equipamentos':Equipamento,'funcionarios':m.Funcionario,'estoque':g.Movimentacao}
MODULES={'produtos':'estoque','clientes':'','fornecedores':'compras','estoque':'estoque','equipamentos':'assistencia','funcionarios':'rh'}
FINAL={'CRIADA','ATUALIZADA','REJEITADA','IGNORADA'}

def authorize(user,kind=None):
    member=require_capability(user,'migracao')
    # An override cannot grant operational PWA users bulk administration.
    if member.role not in {'ADMIN','GESTOR'}:raise PermissionDenied('Migração é exclusiva da administração da organização.')
    if kind is not None and (kind not in CATALOG or not module_enabled(MODULES[kind])):raise PermissionDenied('Esse tipo não está disponível nesta organização.')
    return member

def batch(user,key,lock=False):
    authorize(user)
    qs=m.LoteImportacao.objects.select_for_update() if lock else m.LoteImportacao.objects
    obj=qs.get(public_id=key);authorize(user,obj.tipo);return obj

def writable(obj):
    if obj.status not in {'MAPEAR','CONFERIR'}:raise ValidationError('Esta importação já foi confirmada. Consulte o histórico.')

def digest(obj):
    values={f.attname:str(getattr(obj,f.attname)) for f in obj._meta.concrete_fields}
    if isinstance(obj,g.Peca):values['codigos']=list(obj.codigos_alternativos.order_by('codigo').values_list('codigo',flat=True))
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

@transaction.atomic
def upload(user,kind,file):
    authorize(user,kind)
    data=file.read(MAX_BYTES+1);headers,rows=read(file.name,data)
    sha=hashlib.sha256(data).hexdigest()
    Organization.objects.select_for_update().get(pk=current_organization().pk)
    previous=m.LoteImportacao.objects.filter(tipo=kind,sha256=sha).first()
    if previous:return previous,False
    from platform_core.saas_services import verificar_limite
    verificar_limite(current_organization(), 'armazenamento_mb', incremento=len(data))
    filename=PurePath(file.name)
    safe_name=filename.stem[:180-len(filename.suffix)]+filename.suffix.lower()
    obj=m.LoteImportacao(tipo=kind,usuario=user,nome_arquivo=safe_name,sha256=sha,colunas=headers,mapeamento=suggest(kind,headers))
    obj.organization=current_organization()
    try:
        obj.arquivo.save(obj.nome_arquivo,ContentFile(data),save=False);gs.write(obj)
        for number,row in rows:gs.write(m.LinhaImportacao(lote=obj,numero=number,original=row))
        gs.audit(user,'IMPORTACAO_ARQUIVO_RECEBIDO',obj,{'tipo':kind,'linhas':len(rows),'sha256':sha})
    except Exception:
        if obj.arquivo.name:
            try:obj.arquivo.delete(save=False)
            except OSError:pass
        raise
    return obj,True

def document(value,required=True):
    text=re.sub(r'[^0-9]','',str(value))
    if not text and not required:return ''
    if len(text)==14:validate_cnpj(text)
    elif len(text)==11:
        if len(set(text))==1 or any(int(text[i]) != ((sum(int(text[j])*(i+1-j) for j in range(i))*10)%11)%10 for i in (9,10)):
            raise ValidationError('CPF inválido. Confira o documento.')
    else:raise ValidationError('Informe CPF com 11 dígitos ou CNPJ com 14 dígitos. Preserve os zeros iniciais.')
    return text

def by_document(model,field,value):
    expr=F(field)
    for char in ('.','/','-',' '):expr=Replace(expr,Value(char),Value(''))
    return model.objects.annotate(_document=expr).filter(_document=value)

def one(qs,label):
    rows=list(qs[:2])
    if len(rows)!=1:raise ValidationError(f'{label}: selecione um cadastro único já existente nesta empresa.')
    return rows[0]

def normalized(kind,values):
    result={}
    for field in CATALOG[kind]['fields']:
        raw=str(values.get(field['key'],'')).strip()
        if field['required'] and not raw:raise ValidationError(f"{field['label']}: preencha este campo.")
        if not raw:continue
        if len(raw)>MAX_CELL:raise ValidationError(f"{field['label']}: use até 1.000 caracteres.")
        value=raw
        if field['kind'] in {'money','quantity'}:
            try:
                number=Decimal(raw.replace('.','').replace(',','.')) if ',' in raw else Decimal(raw)
                step=Decimal('.01') if field['kind']=='money' else Decimal('.001')
                if not number.is_finite() or number<0 or number.quantize(step)!=number or number>=Decimal('100000000000'):
                    raise InvalidOperation
                value=str(number.quantize(step))
            except (InvalidOperation,ValueError):raise ValidationError(f"{field['label']}: informe valor positivo ou zero, com até {2 if field['kind']=='money' else 3} casas decimais.") from None
        elif field['kind']=='bool':
            if raw.lower() not in {'sim','não','nao','s','n','true','false','1','0'}:raise ValidationError(f"{field['label']}: use Sim ou Não.")
            value=raw.lower() in {'sim','s','true','1'}
        elif field['kind']=='date':
            parsed=None
            for fmt in ('%Y-%m-%d','%d/%m/%Y'):
                try:parsed=datetime.strptime(raw,fmt).date();break
                except ValueError:pass
            if not parsed:raise ValidationError(f"{field['label']}: use DD/MM/AAAA.")
            value=parsed.isoformat()
        result[field['key']]=value
    if kind=='clientes':result['cpf_cnpj']=document(result['cpf_cnpj'])
    if kind=='fornecedores' and result.get('documento'):result['documento']=document(result['documento'])
    if kind=='equipamentos':result['cliente']=document(result['cliente'])
    if kind=='estoque' and result.get('fornecedor'):result['fornecedor']=document(result['fornecedor'])
    if result.get('email'):result['email']=result['email'].lower()
    return result

def identities(kind,data):
    keys=[]
    groups={'produtos':('sku','gtin','codigo_externo'),'clientes':('cpf_cnpj','email'),'fornecedores':('documento',),'equipamentos':('codigo_interno','numero_serie'),'funcionarios':('usuario','matricula'),'estoque':('identificador',)}
    for key in groups[kind]:
        if data.get(key):keys.append((key,str(data[key]).casefold()))
    if kind=='fornecedores' and not keys:keys.append(('nome',data['nome'].casefold()))
    return keys

def stock_token(data):
    return uuid.uuid5(current_organization().public_id,'VERTYX:MIGRACAO:ENTRADA:'+data['identificador'])

def matches(kind,data,lock=False):
    model=MODELS[kind];ids=set()
    if kind=='produtos':
        for field,key in [('sku','sku'),('gtin','gtin'),('codigo_barras','gtin')]:
            if data.get(key):ids.update(model.objects.filter(**{field+'__iexact':data[key]}).values_list('pk',flat=True))
        if data.get('codigo_externo'):
            ids.update(g.CodigoProduto.objects.filter(codigo__iexact=data['codigo_externo']).values_list('peca_id',flat=True))
            ids.update(model.objects.filter(codigo_barras__iexact=data['codigo_externo']).values_list('pk',flat=True))
    elif kind in {'clientes','fornecedores'}:
        field='cpf_cnpj' if kind=='clientes' else 'documento'
        if data.get(field):ids.update(by_document(model,field,data[field]).values_list('pk',flat=True))
        if kind=='clientes' and data.get('email'):ids.update(model.objects.filter(email__iexact=data['email']).values_list('pk',flat=True))
        if kind=='fornecedores' and not data.get('documento'):ids.update(model.objects.filter(nome__iexact=data['nome']).values_list('pk',flat=True))
    elif kind=='equipamentos':
        for field in ('codigo_interno','numero_serie'):
            if data.get(field):ids.update(model.objects.filter(**{field+'__iexact':data[field]}).values_list('pk',flat=True))
    elif kind=='funcionarios':
        ids.update(model.objects.filter(matricula__iexact=data['matricula']).values_list('pk',flat=True))
        ids.update(model.objects.filter(usuario__username__iexact=data['usuario']).values_list('pk',flat=True))
    else:ids.update(model.objects.filter(request_id=stock_token(data)).values_list('pk',flat=True))
    qs=model.objects.filter(pk__in=ids).order_by('pk')
    return list(qs.select_for_update() if lock else qs)

def employee_form(actor,data,obj):
    from operacao.employee_forms import FuncionarioForm,TECH_FIELDS
    from contas.models import Usuario
    # The existing central HR service owns the employee and technical sheet.
    user=one(Usuario.objects.filter(username=data['usuario'],is_active=True,memberships__organization=current_organization(),memberships__status='ATIVO').distinct(),'Usuário')
    if obj.pk and obj.usuario_id!=user.pk:raise ValidationError('A conta vinculada ao funcionário não pode ser substituída.')
    fields=FuncionarioForm._meta.fields
    values={key:getattr(obj,key+'_id',getattr(obj,key,None)) for key in fields}
    values.update({key:value for key,value in data.items() if key!='usuario'})
    values.update(usuario=str(user.pk),conta_modo='EXISTENTE',jornada_modo='EXISTENTE')
    for key,value in list(values.items()):
        if value is None:values[key]=''
    form=FuncionarioForm(values,instance=obj,actor=actor)
    form.manage_access=False;form.manage_technical=False
    for key in ('username','password1','password2','perfil','acesso_assistencia','tecnico_existente',*("tecnico_"+key for key in TECH_FIELDS)):
        form.fields.pop(key,None)
    form.fields['conta_modo'].choices=[('EXISTENTE','Conta existente')]
    if not form.is_valid():raise ValidationError([f'{form.fields[key].label if key in form.fields else "Funcionário"}: {message}' for key,errors in form.errors.items() for message in errors])
    return form

def candidate(actor,kind,data,old=None):
    warnings=[]
    if kind=='estoque':
        part=one(g.Peca.objects.filter(sku__iexact=data['sku'],ativo=True),'Produto')
        depot=one(m.Deposito.objects.filter(nome__iexact=data['deposito'],ativo=True),'Depósito')
        if Decimal(data['quantidade'])<=0:raise ValidationError('Quantidade de entrada deve ser maior que zero.')
        if not part.fracionavel and Decimal(data['quantidade'])%1:raise ValidationError('Este produto exige quantidade inteira.')
        if part.controla_validade and not data.get('validade'):raise ValidationError('Este produto exige validade por lote.')
        if data.get('validade') and data['validade']<timezone.localdate().isoformat():warnings.append('Lote vencido: ficará indisponível para consumo automático.')
        if data.get('fabricacao') and data.get('validade') and data['fabricacao']>data['validade']:raise ValidationError('Fabricação posterior à validade.')
        supplier=one(by_document(g.Fornecedor,'documento',data['fornecedor']),'Fornecedor') if data.get('fornecedor') else None
        if len(data['lote'])>100 or len(data['identificador'])>100 or len(data.get('documento_entrada',''))>180:raise ValidationError('Identificador, lote ou documento muito longo.')
        return dict(part=part,depot=depot,supplier=supplier),warnings
    obj=copy.deepcopy(old) if old else MODELS[kind](organization=current_organization())
    if kind=='funcionarios':return employee_form(actor,data,obj),warnings
    for key,value in data.items():
        if key not in {'codigo_externo','cliente','categoria'}:setattr(obj,key,value)
    if kind=='clientes':obj.tipo_pessoa='PF' if len(data['cpf_cnpj'])==11 else 'PJ'
    if kind=='equipamentos':
        obj.cliente=one(by_document(Cliente,'cpf_cnpj',data['cliente']),'Cliente')
        if old and old.cliente_id!=obj.cliente_id:raise ValidationError('Transferência de equipamento entre clientes exige o fluxo administrativo existente.')
        obj.categoria=one(CategoriaEquipamento.objects.filter(nome__iexact=data['categoria']),'Categoria')
    obj.full_clean()
    if kind=='produtos':
        if not obj.ncm:warnings.append('NCM não informado. O cadastro não autoriza emissão fiscal.')
        if obj.estoque_maximo is not None and obj.estoque_maximo<obj.estoque_minimo:raise ValidationError('Estoque ideal deve ser maior ou igual ao mínimo.')
        if len(data.get('codigo_externo',''))>80:raise ValidationError('Código externo deve ter até 80 caracteres.')
    return obj,warnings

@transaction.atomic
def map_columns(user,key,mapping):
    obj=batch(user,key,True);writable(obj)
    allowed={f['key'] for f in CATALOG[obj.tipo]['fields']}
    if set(mapping)!={str(i) for i in range(len(obj.colunas))} or any(v and v not in allowed for v in mapping.values()):raise ValidationError('Confira a correspondência das colunas.')
    targets=[v for v in mapping.values() if v]
    if len(targets)!=len(set(targets)):raise ValidationError('Cada campo do VERTYX deve receber somente uma coluna.')
    missing=[f['label'] for f in CATALOG[obj.tipo]['fields'] if f['required'] and f['key'] not in targets]
    if missing:raise ValidationError('Associe as colunas obrigatórias: '+', '.join(missing))
    obj.mapeamento=mapping;obj.status='CONFERIR';gs.write(obj);analyze(user,obj)
    gs.audit(user,'IMPORTACAO_COLUNAS_CONFIRMADAS',obj,{'tipo':obj.tipo})
    return obj

def analyze(user,obj):
    writable(obj);seen={};rows=list(obj.linhas.order_by('numero'))
    for row in rows:
        row.problemas=[];row.avisos=[];row.alvo=None;row.alvo_hash=''
        if row.acao=='IGNORAR':row.estado='IGNORADA';gs.write(row);continue
        values={target:row.original[int(index)] for index,target in obj.mapeamento.items() if target};values.update(row.correcoes)
        row.dados=values
        try:
            data=normalized(obj.tipo,values);row.dados=data
            found=matches(obj.tipo,data)
            if len(found)>1:raise ValidationError('Os identificadores correspondem a cadastros diferentes. Corrija ou ignore a linha.')
            if found:
                row.alvo=found[0].pk;row.alvo_hash=digest(found[0])
                if obj.tipo=='estoque':row.acao='CRIAR';row.estado='DUPLICADA';row.problemas=['Esta entrada já foi registrada. Ignore a linha para não somar novamente.']
                elif row.acao!='ATUALIZAR':row.estado='DUPLICADA';row.problemas=['Cadastro existente encontrado. Escolha Atualizar ou Ignorar.']
                else:row.estado='PRONTA'
            else:
                if row.acao=='ATUALIZAR':row.acao='CRIAR'
                row.estado='PRONTA'
            prepared,row.avisos=candidate(user,obj.tipo,data,found[0] if found else None)
            for identity in identities(obj.tipo,data):
                if identity in seen:
                    other=seen[identity];other.estado='DUPLICADA';other.problemas=['Identificador repetido neste arquivo. Corrija ou ignore uma das linhas.'];gs.write(other)
                    row.estado='DUPLICADA';row.problemas=['Identificador repetido neste arquivo. Corrija ou ignore uma das linhas.']
                else:seen[identity]=row
        except ValidationError as exc:row.estado='CORRIGIR';row.problemas=exc.messages
        gs.write(row)

@transaction.atomic
def edit_row(user,key,number,corrections,action):
    obj=batch(user,key,True);writable(obj)
    if obj.status!='CONFERIR':raise ValidationError('Confirme antes a correspondência das colunas.')
    if action not in {'CRIAR','ATUALIZAR','IGNORAR'} or action=='ATUALIZAR' and obj.tipo=='estoque':raise ValidationError('Ação não permitida.')
    allowed={f['key'] for f in CATALOG[obj.tipo]['fields']}
    if set(corrections)-allowed or any(len(str(v))>MAX_CELL for v in corrections.values()):raise ValidationError('Há campos não permitidos na correção.')
    row=obj.linhas.get(numero=number);row.correcoes=corrections;row.acao=action;gs.write(row);analyze(user,obj)
    gs.audit(user,'IMPORTACAO_LINHA_REVISADA',row,{'linha':number,'acao':action})
    return obj

@transaction.atomic
def start(user,key,allow_partial=False):
    obj=batch(user,key,True);writable(obj)
    if obj.status!='CONFERIR':raise ValidationError('Confira as colunas e os dados antes de importar.')
    # Refresh before confirmation. Later changes will become row conflicts.
    previous={row.pk:row.alvo_hash for row in obj.linhas.filter(estado='PRONTA',acao='ATUALIZAR')}
    analyze(user,obj)
    if any(row.alvo_hash!=previous[row.pk] for row in obj.linhas.filter(pk__in=previous)):
        raise ValidationError('Um cadastro mudou desde a prévia. Volte a Colunas e confira novamente antes de confirmar.')
    bad=obj.linhas.filter(estado__in=['CORRIGIR','DUPLICADA'])
    if bad.exists() and not allow_partial:raise ValidationError('Corrija os problemas ou confirme que deseja importar somente as linhas prontas.')
    if not obj.linhas.filter(estado='PRONTA').exists():raise ValidationError('Não há linhas prontas para importar.')
    for row in bad:row.estado='IGNORADA';row.acao='IGNORAR';gs.write(row)
    obj.status='IMPORTANDO';obj.iniciado_por=user;gs.write(obj);gs.audit(user,'IMPORTACAO_CONFIRMADA',obj,{'parcial':bool(allow_partial)})
    return obj

def persist(actor,kind,data,old):
    prepared,warnings=candidate(actor,kind,data,old)
    if kind=='estoque':
        lot={key:datetime.strptime(data[key],'%Y-%m-%d').date() for key in ('fabricacao','validade') if data.get(key)}
        lot.update(numero=data['lote'],custo_unitario=Decimal(data['custo_unitario']),fornecedor=prepared['supplier'],localizacao=data.get('localizacao',''),documento_entrada=data.get('documento_entrada',''))
        return gs.movimentar(actor,prepared['part'].pk,'ENTRADA',Decimal(data['quantidade']),destino_id=prepared['depot'].pk,request_id=stock_token(data),lote_data=lot,observacao='Entrada confirmada pelo Assistente de Migração: '+data['identificador'])
    if kind=='funcionarios':
        from operacao.employee_services import save_employee
        return save_employee(actor,prepared)
    before=digest(old) if old else ''
    prepared.save()
    if kind=='produtos' and data.get('codigo_externo'):
        existing=g.CodigoProduto.objects.filter(codigo__iexact=data['codigo_externo']).first()
        if not existing:g.CodigoProduto.objects.create(peca=prepared,codigo=data['codigo_externo'])
        elif existing.peca_id!=prepared.pk:raise ValidationError('Código externo vinculado a outro produto.')
    gs.audit(actor,'IMPORTACAO_CADASTRO_ATUALIZADO' if old else 'IMPORTACAO_CADASTRO_CRIADO',prepared,{'tipo':kind,'antes_sha256':before,'depois_sha256':digest(prepared),'campos':list(data)})
    return prepared

@transaction.atomic
def execute_chunk(user,key,limit=25):
    obj=batch(user,key,True)
    if obj.status=='CONCLUIDO':return obj
    if obj.status!='IMPORTANDO' or obj.iniciado_por_id!=user.pk:raise PermissionDenied('Confirme a importação com sua conta antes de continuar.')
    Organization.objects.select_for_update().get(pk=current_organization().pk)
    for row in obj.linhas.filter(estado='PRONTA').order_by('numero')[:max(1,min(limit,25))]:
        try:
            with transaction.atomic():
                found=matches(obj.tipo,row.dados,True)
                if row.acao=='ATUALIZAR':
                    if len(found)!=1 or found[0].pk!=row.alvo or digest(found[0])!=row.alvo_hash:raise ValidationError('O cadastro mudou depois da conferência. Revise em uma nova importação.')
                    old=found[0]
                else:
                    if found:raise ValidationError('Um cadastro com esse identificador foi criado depois da conferência. Não foi duplicado.')
                    old=None
                saved=persist(user,obj.tipo,row.dados,old)
                row.estado='ATUALIZADA' if old else 'CRIADA';row.registro=f'{saved._meta.label}:{saved.pk}'
        except ValidationError as exc:row.estado='REJEITADA';row.problemas=exc.messages
        except Exception:row.estado='REJEITADA';row.problemas=['Não foi possível importar esta linha. Os dados anteriores foram preservados; revise o cadastro e tente em um novo arquivo.']
        gs.write(row)
    if not obj.linhas.filter(estado='PRONTA').exists():
        obj.status='CONCLUIDO';obj.concluido_em=timezone.now();gs.write(obj);gs.audit(user,'IMPORTACAO_CONCLUIDA',obj,summary(obj))
    return obj

def summary(obj):
    counts={row['estado']:row['total'] for row in obj.linhas.values('estado').annotate(total=Count('pk'))}
    return dict(encontrada=sum(counts.values()),pronta=counts.get('PRONTA',0),corrigir=counts.get('CORRIGIR',0),duplicada=counts.get('DUPLICADA',0),criada=counts.get('CRIADA',0),atualizada=counts.get('ATUALIZADA',0),ignorada=counts.get('IGNORADA',0),rejeitada=counts.get('REJEITADA',0))
