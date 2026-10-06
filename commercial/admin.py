from django.contrib import admin
from platform_core.admin import PlatformAdmin
from .models import PlanoComercial, InteresseComercial


@admin.register(PlanoComercial)
class PlanoAdmin(PlatformAdmin):
    list_display=['nome','preco','periodicidade','destaque','ordem','ativo']
    list_filter=['ativo','destaque','periodicidade']
    search_fields=['nome','slug']
    readonly_fields=['atualizado_em']
    fieldsets=[('Oferta pública',{'fields':['slug','nome','descricao','preco','periodicidade','destaque','ordem','ativo']}),
               ('Condições comerciais',{'fields':['limite_usuarios','limite_tecnicos','recursos','preco_anual','desconto_anual'],
                                        'description':'Limites são condições comerciais, não cotas técnicas. Recursos futuros nunca são divulgados pela página pública.'}),
               ('Registro',{'fields':['atualizado_em']})]


@admin.register(InteresseComercial)
class InteresseAdmin(PlatformAdmin):
    list_display=['empresa','nome','plano','status','criado_em']
    list_filter=['status','plano','objetivo']
    search_fields=['empresa','nome','email']
    readonly_fields=['request_id','plano','periodicidade','oferta','nome','empresa','email','telefone','objetivo','mensagem','consentimento','versao_privacidade','criado_em']

    def has_add_permission(self,request):
        return False
