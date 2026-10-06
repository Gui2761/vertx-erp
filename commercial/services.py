import secrets
import uuid
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import InteresseComercial, PlanoComercial

SALT='vertyx.public.interest'


def form_token(request):
    if 'commercial_nonce' not in request.session:
        request.session['commercial_nonce']=secrets.token_urlsafe(24)
    return signing.dumps({'id':str(uuid.uuid4()),'nonce':request.session['commercial_nonce']},salt=SALT)


@transaction.atomic
def register_interest(request,form):
    try:
        data=signing.loads(form.cleaned_data['token'],salt=SALT,max_age=7200)
        if not request.session.get('commercial_nonce') or data['nonce']!=request.session['commercial_nonce']:
            raise ValueError
        token=uuid.UUID(data['id'])
    except (signing.BadSignature,ValueError,KeyError,TypeError):
        raise ValidationError('O formulário expirou. Recarregue a página e tente novamente.')
    existing=InteresseComercial.objects.filter(request_id=token).first()
    if existing:
        fields=['nome','empresa','email','telefone','objetivo','mensagem','periodicidade']
        if any(getattr(existing,key)!=form.cleaned_data[key] for key in fields) or existing.plano_id != getattr(form.cleaned_data.get('plano'),'pk',None):
            raise ValidationError('Solicitação já registrada. Recarregue para iniciar uma nova solicitação.')
        return existing
    # Minimal email-based abuse control. No raw IP, tracking or external captcha.
    if InteresseComercial.objects.filter(email=form.cleaned_data['email'],criado_em__gte=timezone.now()-timezone.timedelta(hours=1)).count() >= 5:
        raise ValidationError('Já recebemos solicitações para este e-mail. Tente novamente mais tarde.')
    lead=form.save(commit=False)
    if lead.plano_id:
        plan=PlanoComercial.objects.select_for_update().get(pk=lead.plano_id,ativo=True)
        if plan.periodicidade=='ANUAL' and lead.periodicidade!='ANUAL':
            raise ValidationError('As condições do plano foram atualizadas. Recarregue o formulário.')
        amount=plan.valor_anual if lead.periodicidade=='ANUAL' else plan.preco
        lead.oferta={'slug':plan.slug,'nome':plan.nome,'preco':str(amount) if amount is not None else None,'periodicidade':lead.periodicidade,'usuarios':plan.limite_usuarios,'tecnicos':plan.limite_tecnicos,'recursos':plan.recursos}
    lead.request_id=token
    lead.save()
    return lead
