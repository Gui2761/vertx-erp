"""Offline intents are confirmed atomically by the existing commerce services."""
import hashlib
import json
import uuid
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError, PermissionDenied, ObjectDoesNotExist
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from platform_core.modules import require_capability, has_capability
from platform_core.context import current_organization
from gestao import models as g, services as gs, products
from . import models as m, commerce as c, seller_services as s

SALT='vertyx.pdv.offline.v1'

def identity(request):
    return {'organization':str(request.organization.public_id),'user':request.user.pk}

@login_required
def page(request):
    require_capability(request.user,'operar_pdv')
    return render(request,'operacao/pdv_offline.html',{'sessions':m.SessaoCaixa.objects.filter(operador=request.user,fechado_em__isnull=True,conta__deposito_padrao__ativo=True,conta__deposito_padrao__organization_id=current_organization().pk).select_related('conta','conta__deposito_padrao')})

@login_required
@require_GET
def shell(request):
    require_capability(request.user,'operar_pdv')
    from pathlib import Path
    from django.http import HttpResponse
    return HttpResponse((Path(settings.BASE_DIR)/'static/pwa/pdv-offline.html').read_text(encoding='utf-8'))

@login_required
@require_GET
def context(request):
    require_capability(request.user,'operar_pdv')
    return JsonResponse({**identity(request),'csrf':get_token(request)})

@login_required
@require_GET
@transaction.atomic
def prepare(request):
    require_capability(request.user,'operar_pdv')
    try:
        session=c.own_session(request.user,request.GET.get('caixa'))
        if session.operador_id!=request.user.pk:
            raise PermissionDenied('Prepare o dispositivo com o operador do caixa.')
        account=m.ContaBancaria.objects.select_related('deposito_padrao').get(pk=session.conta_id,ativo=True,tipo='CAIXA')
        depot=account.deposito_padrao
        if not depot or not depot.ativo or depot.organization_id!=current_organization().pk:
            raise ValidationError('O caixa não possui depósito padrão ativo configurado.')
        supplied=request.GET.get('deposito')
        if supplied and str(depot.pk)!=str(supplied):
            raise ValidationError('O depósito offline é definido pelo caixa.')
    except (ObjectDoesNotExist,ValueError,ValidationError):
        return JsonResponse({'error':'Selecione um caixa aberto com depósito padrão ativo.'},status=400)
    claims={**identity(request),'session':str(session.public_id),'depot':depot.pk}
    catalog=[]
    for part in g.Peca.objects.filter(ativo=True).prefetch_related('codigos_alternativos'):
        catalog.append({'sku':part.sku,'name':part.descricao,'price':str((part.preco_venda*part.fator_venda).quantize(c.CENT)),'factor':str(part.fator_venda),'fractional':part.fracionavel,'available':str(s.availability(part,depot)), 'codes':[part.sku,part.gtin,part.codigo_barras,*part.codigos_alternativos.values_list('codigo',flat=True)]})
    config=m.ConfiguracaoPDV.objects.first() or m.ConfiguracaoPDV()
    forms=[{'id':row.pk,'name':row.nome,'kind':row.tipo_pdv} for row in g.FormaPagamento.objects.filter(ativo=True,tipo_pdv__in=['DINHEIRO','PIX','DEBITO','CREDITO'])]
    return JsonResponse({**claims,'grant':signing.dumps(claims,salt=SALT,compress=True),'catalog':catalog,'forms':forms,'cash_name':session.conta.nome,'depot_name':depot.nome,'discount_limit':str(config.limite_desconto_percentual),'supervisor':has_capability(request.user,'desconto_supervisor'),'max_age':getattr(settings,'PDV_OFFLINE_MAX_AGE',28800)})

def fingerprint(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

@transaction.atomic
def accept(user,data):
    require_capability(user,'operar_pdv')
    if not isinstance(data,dict): raise ValidationError('Operação inválida.')
    org=current_organization()
    if data.get('organization')!=str(org.public_id) or data.get('user')!=user.pk:
        raise PermissionDenied('Operação pertence a outra organização ou usuário.')
    request_id=c.token(data.get('request_id'));device=c.token(data.get('device'))
    # Serialize all submissions for this cash session, including duplicate retries.
    session=c.own_session(user,data.get('session'),True)
    if session.operador_id!=user.pk: raise PermissionDenied('Operação pertence a outro operador.')
    digest=fingerprint(data)
    old=m.SincronizacaoPDV.objects.filter(request_id=request_id).select_related('venda').first()
    if old:
        if old.operador_id!=user.pk or old.payload_hash!=digest:
            raise ValidationError('UUID já confirmado com outro conteúdo.')
        return old.venda
    if session.fechado_em: raise ValidationError('Caixa fechado. Solicite análise do responsável; nenhum caixa será reaberto automaticamente.')
    if m.Venda.objects.filter(criacao_id=request_id).exists():
        raise ValidationError('UUID já utilizado por outra operação de venda.')
    try: claims=signing.loads(data.get('grant',''),salt=SALT,max_age=getattr(settings,'PDV_OFFLINE_MAX_AGE',28800))
    except signing.BadSignature: raise ValidationError('Preparação offline inválida ou expirada. Reprepare e revise a pendência.')
    expected={'organization':str(org.public_id),'user':user.pk,'session':str(session.public_id),'depot':data.get('depot')}
    if claims!=expected: raise PermissionDenied('Preparação não corresponde ao caixa, usuário ou depósito.')
    lines=data.get('items')
    if not isinstance(lines,list) or not lines or len(lines)>200: raise ValidationError('Revise os itens da operação.')
    if not isinstance(data.get('payments'),list): raise ValidationError('Pagamentos inválidos.')
    sale=c.new_sale(user,session.public_id,int(data['depot']),request_id=request_id)
    for line in lines:
        if not isinstance(line,dict): raise ValidationError('Item inválido.')
        part=products.lookup(line.get('sku',''))
        current=(part.preco_venda*part.fator_venda).quantize(c.CENT)
        if c.money(line.get('unit_price'),True)!=current: raise ValidationError(f'Preço alterado para {part.sku}. Revise a pendência.')
        c.add_item(user,sale.public_id,part.sku,line.get('quantity'),'venda',line.get('discount','0'),line.get('reason',''))
    c.pricing(user,sale.public_id,data.get('discount','0'),0,data.get('reason',''))
    for payment in data['payments']:
        form=g.FormaPagamento.objects.get(pk=payment.get('forma'),ativo=True)
        if form.tipo_pdv not in {'DINHEIRO','PIX','DEBITO','CREDITO'}:
            raise ValidationError('Forma de pagamento não preparada para offline.')
    sale=c.finalize(user,sale.public_id,data['payments'],uuid.uuid5(request_id,'finalizar-offline'))
    receipt=gs.write(m.SincronizacaoPDV(request_id=request_id,dispositivo=device,operador=user,venda=sale,payload_hash=digest))
    gs.audit(user,'PDV_OFFLINE_SINCRONIZADO',receipt,{'venda':sale.pk,'dispositivo':str(device),'request_id':str(request_id),'origem':'PWA_PDV_OFFLINE'})
    return sale

@login_required
@require_POST
def synchronize(request):
    require_capability(request.user,'operar_pdv')
    if len(request.body)>250000: return JsonResponse({'error':'Operação excede o tamanho permitido.'},status=400)
    try:
        sale=accept(request.user,json.loads(request.body))
        return JsonResponse({'status':'CONFIRMADA','sale':str(sale.public_id),'receipt':f'/pdv/vendas/{sale.public_id}/comprovante/'})
    except PermissionDenied:
        return JsonResponse({'error':'Usuário, organização ou permissão não correspondem à operação.'},status=403)
    except (ValidationError,ObjectDoesNotExist,ValueError,TypeError,KeyError) as exc:
        message='; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Revise produtos, pagamentos e dados da pendência.'
        return JsonResponse({'status':'CONFLITO','error':message},status=409)
