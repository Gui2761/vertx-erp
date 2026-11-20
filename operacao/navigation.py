import urllib.parse
from platform_core.modules import has_capability, module_enabled

ICON_ALIASES = {'calendar3':'calendar','calendar-check':'calendar','clipboard2-pulse':'document','telephone':'health','file-earmark-text':'document','file-earmark-ruled':'document','bag':'cart','people':'users','box-seam':'stock','arrow-left-right':'arrows','hourglass-split':'calendar','buildings':'stock','list-check':'document','bookmark-check':'document','cart-check':'cart','chat-square-text':'document','truck':'cart','box-arrow-in-down':'stock','person-vcard':'users','cash-stack':'bank','arrow-down-circle':'arrows','arrow-up-circle':'arrows','graph-up':'chart','file-earmark-check':'document','heart-pulse':'health','person-gear':'users','folder':'document','person-lock':'users','bar-chart':'chart','gear':'settings','sliders':'settings','person-check':'users'}

def menu(request):
    result=_menu(request)
    if getattr(request,'resolver_match',None) and request.resolver_match.url_name=='seller_login':
        result['seller_experience']=True
    if getattr(request,'resolver_match',None) and request.resolver_match.url_name=='pdv_login':
        result['pdv_experience']=True
    match=getattr(request,'resolver_match',None)
    from platform_core.modules import has_capability, module_enabled
    result['pdv_experience']=result.get('pdv_experience',False) or bool(match and match.namespace=='operacao' and match.url_name in {'pdv_home','pdv_sale','pdv_cash','pdv_receipt','pdv_products'} and request.user.is_authenticated and has_capability(request.user,'pdv'))
    return result


def _menu(request):
    membership=getattr(request,'membership',None)
    org=getattr(request,'organization',None)
    current_path=getattr(request,'path','')
    current_full_path = request.get_full_path() if hasattr(request, 'get_full_path') else current_path
    from platform_core.context import get_org_cache_dict
    org_cache = get_org_cache_dict(org) if org and membership else None
    nav_key = ('nav_menu_full', getattr(request.user, 'pk', None), getattr(membership, 'role', None), current_full_path)
    if org_cache is not None and nav_key in org_cache:
        return dict(org_cache[nav_key])
    res = _menu_uncached(request)
    if org_cache is not None:
        org_cache[nav_key] = dict(res)
    return res


def _menu_uncached(request):
    membership=getattr(request,'membership',None)
    match=getattr(request,'resolver_match',None)
    from platform_core.modules import has_capability, module_enabled, module_for_path
    from .planning_services import can_tv
    panel_access=bool(membership and can_tv(request.user))
    if membership and (membership.role in {'VENDEDOR','PDV'} or request.path.startswith('/pdv/') or request.path.startswith('/vendedor/') and not request.path.startswith('/vendedor/gestao/')):
        if request.path.startswith('/pdv/') and has_capability(request.user,'operar_pdv'):
            if membership.role in {'ADMIN', 'GESTOR'}:
                links=[('Central do PDV','/pdv/','cart'),('Caixas','/pdv/?gestao=1','bank')]
                if membership.role == 'ADMIN' and has_capability(request.user,'config_empresa'):
                    links.append(('Operadores','/vertyx/empresa/permissoes/','users'))
                if has_capability(request.user,'caixa_supervisor'):
                    links.extend([('Movimentações','/pdv/movimentacoes/','arrows'),('Histórico de vendas','/pdv/historico/','document')])
                if has_capability(request.user,'config_empresa'):
                    links.append(('Configurações','/pdv/configuracao/','settings'))
            else:
                links=[('Caixa','/pdv/','cart'),('Histórico de vendas','/pdv/historico/','document'),('Offline / sincronização','/pdv/offline/','arrows')]
                if has_capability(request.user,'caixa_supervisor'):
                    links.append(('Gestão de caixas','/pdv/?gestao=1','bank'))
            return {'pdv_experience':True,'can_operational_panel':False,'pdv_navigation':[{'label':label,'url':url,'icon':icon} for label,url,icon in links]}
        if membership.role in {'VENDEDOR','PDV'} or request.path.startswith('/vendedor/'):
            links=[('Minha rotina','/vendedor/','grid','central_vendedor'),('Minhas vendas','/vendedor/vendas/','document','central_vendedor'),('Minha meta','/vendedor/meta/','chart','central_vendedor'),('Minha comissão','/vendedor/comissao/','chart','central_vendedor'),('Meu ponto','/vendedor/ponto/','users','ponto'),('Hora extra','/vendedor/ponto/horas-extras/','calendar','ponto'),('Notificações','/vendedor/alertas/','bell','central_vendedor')]
            return {'seller_experience':True,'can_operational_panel':False,'seller_navigation':[{'label':label,'url':url,'icon':icon} for label,url,icon,cap in links if has_capability(request.user,cap) and module_enabled(module_for_path(url))]}
    if membership and membership.role == 'TECNICO':
        from platform_core.access import has_erp_access
        from platform_core.modules import has_capability, module_enabled, module_for_path
        # Presentation uses the active membership and the existing capabilities.
        # Never fall back to the administrative menu, even with no allowed links.
        links = [
            ('Meu atendimento / Atender', '/tecnico/', 'health', 'planejamento'),
            ('Minha agenda', '/planejamento/', 'calendar', 'planejamento'),
            ('Minhas OS', '/ordens/', 'document', None),
            ('Meus chamados', '/chamados/', 'document', 'operacional'),
            ('Ler QR / código', '/tecnico/qr/', 'document', 'planejamento'),
            ('Meu ponto', '/ponto/', 'users', 'ponto'),
            ('Alertas / notificações', '/notificacoes/', 'bell', None),
            ('Conhecimento técnico', '/conhecimento/', 'document', 'operacional'),
        ]
        erp_access = has_erp_access(request.user, request.organization)
        allowed = [
            {'label': label, 'url': url, 'icon': icon}
            for label, url, icon, capability in links
            if erp_access
            and module_enabled(module_for_path(url))
            and (capability is None or has_capability(request.user, capability))
        ]
        return {'technician_experience': True, 'can_operational_panel': False,
                'technician_navigation': allowed}
    if membership and membership.role in ['PLANEJADOR','ATENDIMENTO'] and not (match and match.app_name=='platform_core'):
        links=[{'label':'Planejamento','url':'/planejamento/','icon':'calendar'}]
        if panel_access:
            links.append({'label':'Painel de TV (Operações)','url':'/painel-operacional/','icon':'grid'})
        return {'can_operational_panel':panel_access,'executive_navigation':[{'title':'ASSISTÊNCIA','links':links}]}
    if not membership or membership.role not in ['ADMIN','GESTOR']:
        return {'can_operational_panel':panel_access}
    groups=[
        ('INÍCIO',[('Painel','/assistencia/','grid')]),
        ('ASSISTÊNCIA',[('Planejamento','/planejamento/','calendar3'),('Ordens de Serviço','/ordens/','clipboard2-pulse'),('Chamados','/chamados/','telephone'),('Preventivas','/preventivas/','calendar-check'),('Contratos','/contratos/','file-earmark-text')]),
        ('COMERCIAL',[('Orçamentos','/orcamentos/','file-earmark-ruled'),('Vendas e loja','/vendas/','bag')]),
        ('ESTOQUE',[('Painel do estoque','/estoque/painel/','box-seam'),('Produtos e Peças','/estoque/','box-seam'),('Movimentações & Lotes','/estoque/movimentar/','arrow-left-right'),('Depósitos & Inventário','/depositos/','buildings')]),
        ('COMPRAS',[('Compras e Pedidos','/compras/','cart'),('Cotações','/compras/?cotacoes=1','chat-square-text'),('Fornecedores','/estoque/fornecedores/','person-vcard')]),
        ('FINANCEIRO',[('Dashboard','/financeiro/','cash-stack'),('Contas a receber','/financeiro/lancamentos/?tipo=RECEBER','arrow-down-circle'),('Contas a pagar','/financeiro/lancamentos/?tipo=PAGAR','arrow-up-circle'),('Bancos e Caixas','/bancos/','bank'),('Movimentações & Conciliação','/financeiro/movimentacoes/','arrows'),('Central Fiscal (CBS/IBS)','/fiscal/hub/','file-earmark-check')]),
        ('CADASTROS',[('Clientes e Unidades','/clientes/','people'),('Equipamentos','/equipamentos/','heart-pulse'),('Técnicos','/contas/tecnicos/','person-gear'),('Carga em massa (Excel)','/integracoes/migracao/','stock')]),
        ('RELATÓRIOS',[('Relatórios','/relatorios/','bar-chart')]),
        ('CONFIGURAÇÕES',[('Configurações','/configuracoes/','gear'),('Usuários','/contas/usuarios/','person-check'),('Minha Assinatura','/vertyx/empresa/plano/','bookmark-check'),('Notificações','/notificacoes/','bell')])]
    if panel_access:
        groups[1][1].insert(1,('Painel de TV (Operações)','/painel-operacional/','grid'))
    if module_enabled('relatorios_completos') and has_capability(request.user, 'executivo'):
        groups[0][1].append(('Gestão executiva','/gestao/executiva/','chart'))
    pdv_links=[('Terminal do PDV','/pdv/','cart'),('Gestão de Caixas','/pdv/?gestao=1','bank'),('Histórico de Vendas','/pdv/historico/','document')]
    groups.insert(-1,('RH / PONTO',[('Funcionários','/rh/funcionarios/','users'),('Jornadas e Escalas','/rh/jornadas/','calendar'),('Meu ponto','/ponto/','users')]))
    by_title=dict(groups)
    groups=[
        ('Operacional',by_title['INÍCIO']+by_title['ASSISTÊNCIA']),
        ('Vendas',by_title['COMERCIAL']),
        ('PDV',pdv_links),
        ('Estoque',by_title['ESTOQUE']),
        ('Compras',by_title['COMPRAS']),
        ('Financeiro',by_title['FINANCEIRO']),
        ('Cadastros',by_title['CADASTROS']),
        ('RH',by_title['RH / PONTO']),
        ('Relatórios',by_title['RELATÓRIOS']),
        ('Configurações',by_title['CONFIGURAÇÕES']),
    ]
    from platform_core.modules import module_for_path, module_enabled, product_module_enabled, required_modules_for_path
    from gestao.permissions import allowed

    org = getattr(request, 'organization', None)
    _plan_modules = None
    _overrides = {}
    _sub = None
    if org:
        from platform_core.modules import (
            MODULE_IMPLIED_BY, effective_legacy_plan_codes, platform_module_overrides, _cached_subscription,
        )
        from platform_core.saas_models import AjusteModuloSaaS
        _overrides = platform_module_overrides(org)
        _sub = _cached_subscription(org)
        if _sub and _sub.plano:
            _plan_modules = effective_legacy_plan_codes(org, _sub.plano)

    _nav_cache = {}

    def _is_nav_allowed(url):
        if url in _nav_cache:
            return _nav_cache[url]
        clean_path = url.split('?')[0]
        if clean_path.startswith(('/financeiro/', '/bancos/')) and not allowed(request.user, 'financeiro'):
            _nav_cache[url] = False
            return False
        required = required_modules_for_path(clean_path, None)
        if not required:
            mod = module_for_path(clean_path)
            if mod:
                required = (mod,)
        if org and _sub and _sub.plano:
            from platform_core.saas_models import AjusteModuloSaaS
            for code in required:
                if code and _overrides.get(code) == AjusteModuloSaaS.Modo.DENY:
                    _nav_cache[url] = False
                    return False
                if code and _plan_modules is not None and code not in _plan_modules:
                    if not (MODULE_IMPLIED_BY.get(code, set()) & _plan_modules):
                        _nav_cache[url] = False
                        return False
        if org and required:
            if any(not product_module_enabled(request.user, 'assistencia', code, org) for code in required):
                _nav_cache[url] = False
                return False
        res = module_enabled(module_for_path(clean_path))
        _nav_cache[url] = res
        return res

    current_path = getattr(request, 'path', '')
    current_full_path = request.get_full_path() if hasattr(request, 'get_full_path') else current_path

    filtered_groups = []
    for title, links in groups:
        allowed_links = [(label, url, icon) for label, url, icon in links if _is_nav_allowed(url)]
        if allowed_links:
            filtered_groups.append((title, allowed_links))

    # Single Best Match: encontra o único item do menu com maior especificidade/pontuação
    best_match_key = None
    best_score = -1

    for title, links in filtered_groups:
        for label, url, icon in links:
            url_parts = urllib.parse.urlparse(url)
            link_path = url_parts.path
            link_query = urllib.parse.parse_qs(url_parts.query)

            score = -1
            if link_query:
                # Link com query parameters explícitos (ex: ?cotacoes=1, ?tipo=RECEBER, ?gestao=1)
                curr_parts = urllib.parse.urlparse(current_full_path)
                curr_query = urllib.parse.parse_qs(curr_parts.query)
                if current_path == link_path or (link_path not in ('/', '') and current_path.startswith(link_path)):
                    if all(curr_query.get(k) == v for k, v in link_query.items()):
                        score = 1000 + len(link_path) + len(url_parts.query)
            else:
                # Link sem query parameters
                if current_path == link_path:
                    score = 500 + len(link_path)
                elif link_path not in ('/', '') and current_path.startswith(link_path):
                    score = 100 + len(link_path)

            if score > best_score:
                best_score = score
                best_match_key = (title, url)

    exec_nav = []
    has_active_group = False

    for title, links in filtered_groups:
        group_has_active_link = any((title, url) == best_match_key for _, url, _ in links)
        if group_has_active_link:
            has_active_group = True

        exec_nav.append({
            'title': title,
            'is_active': group_has_active_link,
            'links': [
                {
                    'label': label,
                    'url': url,
                    'icon': ICON_ALIASES.get(icon, icon),
                    'is_active': ((title, url) == best_match_key)
                }
                for label, url, icon in links
            ]
        })

    if not has_active_group and exec_nav:
        exec_nav[0]['is_active'] = True

    return {
        'administrative_navigation': True,
        'can_operational_panel': panel_access,
        'executive_navigation': exec_nav
    }
