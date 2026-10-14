import csv
import io
from functools import wraps
from pathlib import Path
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse,Http404,HttpResponse,JsonResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from operacao import models as m
from . import services as s
from .catalog import CATALOG,PLANNED

STEPS=['Escolher','Modelo e arquivo','Colunas','Conferir','Importar','Concluído']

def guard(func):
    @login_required
    @wraps(func)
    def call(request,*args,**kwargs):
        s.authorize(request.user)
        result=func(request,*args,**kwargs);result['Cache-Control']='private, no-store';return result
    return call

def get_batch(request,key):
    obj=get_object_or_404(m.LoteImportacao,public_id=key);s.authorize(request.user,obj.tipo);return obj

def page(request,template,step,**context):
    context.update(steps=[dict(label=label,number=i+1,active=i+1==step,done=i+1<step) for i,label in enumerate(STEPS)],step=step)
    if context.get('lote'):context['spec']=CATALOG[context['lote'].tipo]
    if context.get('rows'):
        labels={f['key']:f['label'] for f in context['spec']['fields']}
        for row in context['rows']:row.display_data=[(labels.get(k,k),v) for k,v in row.dados.items()]
    return render(request,'integracoes/'+template+'.html',context)

class UploadForm(forms.Form):
    arquivo=forms.FileField(label='Selecione seu arquivo',widget=forms.ClearableFileInput(attrs={'accept':'.xlsx,.csv','class':'form-control'}))

def strict(request,allowed):
    if set(request.POST)-{'csrfmiddlewaretoken',*allowed}:raise ValidationError('Há campos não permitidos nesta solicitação.')
    if any(len(request.POST.getlist(key))!=1 for key in request.POST):raise ValidationError('Há campos repetidos nesta solicitação.')

@guard
@require_http_methods(['GET'])
def home(request):
    history=list(m.LoteImportacao.objects.order_by('-criado_em')[:15])
    for obj in history:
        obj.status_label={'MAPEAR':'Confira as colunas','CONFERIR':'Aguardando conferência','IMPORTANDO':'Em importação','CONCLUIDO':'Concluída'}.get(obj.status,'Consultar')
    return page(request,'home',1,kinds=[dict(key=key,**spec) for key,spec in CATALOG.items()],planned=PLANNED,history=history)

@guard
@require_http_methods(['GET'])
def template_file(request,kind):
    if kind not in CATALOG:raise Http404()
    s.authorize(request.user,kind)
    path=Path(settings.BASE_DIR)/'integracoes'/'modelos'/f'{kind}.xlsx'
    return FileResponse(path.open('rb'),as_attachment=True,filename=f'VERTYX_Modelo_{kind}.xlsx',content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@guard
@require_http_methods(['GET','POST'])
def upload(request,kind):
    if kind not in CATALOG:raise Http404()
    s.authorize(request.user,kind);form=UploadForm(request.POST or None,request.FILES or None)
    if request.method=='POST':
        try:
            strict(request,[])
            if set(request.FILES)!={'arquivo'}:raise ValidationError('Envie somente o arquivo selecionado.')
            if form.is_valid():
                obj,new=s.upload(request.user,kind,form.cleaned_data['arquivo'])
                if not new:messages.info(request,'Este arquivo já foi enviado para esta empresa. Abrimos a importação existente para evitar duplicação.')
                route='migration_result' if obj.status=='CONCLUIDO' else 'migration_progress' if obj.status=='IMPORTANDO' else 'migration_preview' if obj.status=='CONFERIR' else 'migration_mapping'
                return redirect('operacao:'+route,key=obj.public_id)
        except ValidationError as exc:form.add_error(None,exc)
        except OSError:form.add_error(None,'Armazenamento indisponível. Nenhum cadastro foi importado; tente novamente mais tarde.')
    return page(request,'upload',2,kind=kind,spec=CATALOG[kind],form=form)

@guard
@require_http_methods(['GET','POST'])
def mapping(request,key):
    obj=get_batch(request,key)
    if obj.status not in {'MAPEAR','CONFERIR'}:return redirect('operacao:migration_result' if obj.status=='CONCLUIDO' else 'operacao:migration_progress',key=key)
    form=forms.Form(request.POST or None)
    choices=[('','Não importar esta coluna')]+[(f['key'],f['label']+(' *' if f['required'] else '')) for f in CATALOG[obj.tipo]['fields']]
    for i,header in enumerate(obj.colunas):form.fields['col_'+str(i)]=forms.ChoiceField(label=header,choices=choices,required=False,initial=obj.mapeamento.get(str(i),''),widget=forms.Select(attrs={'class':'form-select'}))
    if request.method=='POST':
        try:
            strict(request,form.fields)
            if form.is_valid():s.map_columns(request.user,key,{str(i):form.cleaned_data['col_'+str(i)] for i in range(len(obj.colunas))});return redirect('operacao:migration_preview',key=key)
        except ValidationError as exc:form.add_error(None,exc)
    return page(request,'mapping',3,lote=obj,form=form)

@guard
@require_http_methods(['GET'])
def preview(request,key):
    obj=get_batch(request,key)
    if obj.status!='CONFERIR':return redirect('operacao:migration_mapping' if obj.status=='MAPEAR' else 'operacao:migration_progress' if obj.status=='IMPORTANDO' else 'operacao:migration_result',key=key)
    rows=Paginator(obj.linhas.order_by('numero'),30).get_page(request.GET.get('page'))
    return page(request,'preview',4,lote=obj,rows=rows,totals=s.summary(obj),ignored_columns=[h for i,h in enumerate(obj.colunas) if not obj.mapeamento.get(str(i))])

@guard
@require_http_methods(['GET','POST'])
def edit(request,key,number):
    obj=get_batch(request,key);s.writable(obj);row=get_object_or_404(obj.linhas,numero=number)
    form=forms.Form(request.POST or None)
    for field in CATALOG[obj.tipo]['fields']:
        value=row.correcoes.get(field['key'],row.dados.get(field['key'],''))
        if isinstance(value,bool):value='Sim' if value else 'Não'
        form.fields[field['key']]=forms.CharField(label=field['label'],required=False,max_length=1000,initial=value,widget=forms.TextInput(attrs={'class':'form-control'}))
    choices=[('CRIAR','Importar como novo'),('IGNORAR','Ignorar esta linha')]
    if obj.tipo!='estoque':choices.insert(1,('ATUALIZAR','Atualizar cadastro correspondente'))
    form.fields['acao']=forms.ChoiceField(label='O que fazer com esta linha?',choices=choices,initial=row.acao,widget=forms.Select(attrs={'class':'form-select'}))
    if request.method=='POST':
        try:
            strict(request,form.fields)
            if form.is_valid():s.edit_row(request.user,key,number,{k:v for k,v in form.cleaned_data.items() if k!='acao'},form.cleaned_data['acao']);return redirect('operacao:migration_preview',key=key)
        except ValidationError as exc:form.add_error(None,exc)
    return page(request,'edit',4,lote=obj,row=row,form=form)

@guard
@require_http_methods(['POST'])
def start(request,key):
    obj=get_batch(request,key)
    try:
        strict(request,{'confirmar','parcial'})
        if request.POST.get('confirmar')!='sim':raise ValidationError('Confirme a conferência dos dados antes de importar.')
        s.start(request.user,key,request.POST.get('parcial')=='sim')
    except ValidationError as exc:
        for message in exc.messages:messages.error(request,message)
        return redirect('operacao:migration_preview',key=key)
    return redirect('operacao:migration_progress',key=key)

@guard
@require_http_methods(['GET'])
def progress(request,key):
    obj=get_batch(request,key)
    if obj.status!='IMPORTANDO':return redirect('operacao:migration_result' if obj.status=='CONCLUIDO' else 'operacao:migration_preview',key=key)
    return page(request,'progress',5,lote=obj,totals=s.summary(obj),may_run=obj.iniciado_por_id==request.user.pk)

@guard
@require_http_methods(['POST'])
def chunk(request,key):
    get_batch(request,key)
    try:strict(request,[]);obj=s.execute_chunk(request.user,key)
    except ValidationError as exc:return JsonResponse({'error':'; '.join(exc.messages)},status=400)
    return JsonResponse({'status':obj.status,**s.summary(obj),'result_url':reverse('operacao:migration_result',kwargs={'key':key})})

@guard
@require_http_methods(['GET'])
def result(request,key):
    obj=get_batch(request,key)
    if obj.status!='CONCLUIDO':return redirect('operacao:migration_mapping' if obj.status=='MAPEAR' else 'operacao:migration_preview' if obj.status=='CONFERIR' else 'operacao:migration_progress',key=key)
    return page(request,'result',6,lote=obj,totals=s.summary(obj),rows=Paginator(obj.linhas.order_by('numero'),30).get_page(request.GET.get('page')))

def excel_safe(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value

@guard
@require_http_methods(['GET'])
def report(request,key):
    obj=get_batch(request,key);stream=io.StringIO(newline='');writer=csv.writer(stream,delimiter=';')
    writer.writerow(['VERTYX — Relatório de importação']);writer.writerow(['Identificador',str(obj.public_id)]);writer.writerow(['Tipo',CATALOG[obj.tipo]['title']]);writer.writerow(['Arquivo',excel_safe(obj.nome_arquivo)])
    writer.writerow(['Enviado por',excel_safe(obj.usuario.get_username())]);writer.writerow(['Confirmado por',excel_safe(obj.iniciado_por.get_username()) if obj.iniciado_por else 'Ainda não confirmado']);writer.writerow(['Recebido em',timezone.localtime(obj.criado_em).isoformat()]);writer.writerow(['Concluído em',timezone.localtime(obj.concluido_em).isoformat() if obj.concluido_em else 'Pendente'])
    for label,value in s.summary(obj).items():writer.writerow([label,value])
    writer.writerow([]);writer.writerow(['Linha','Situação','Ação','Registro','Problemas','Avisos'])
    for row in obj.linhas.order_by('numero'):writer.writerow([row.numero,row.estado,row.acao,row.registro,excel_safe('; '.join(row.problemas)),excel_safe('; '.join(row.avisos))])
    response=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8');response['Content-Disposition']=f'attachment; filename="VERTYX_importacao_{obj.public_id}.csv"';return response
