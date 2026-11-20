# Padrão Arquitetural do Design System VERTYX (Dark & Light)

> **Ecossistema Superior Skill · BMad Method · Spec-Kit · Antigravity Kit**  
> **Status:** Ativo e Obrigatório em 100% das Telas do VERTYX ERP  
> **Última Atualização:** 2026-11-20

---

## 1. Regra Fundamental Universal

> [!IMPORTANT]
> **É estritamente proibido o uso de cores hexadecimais fixas (`#ffffff`, `#000000`, `#1e293b`, `background: white`, etc.) diretamente em elementos de templates HTML.**
> Toda e qualquer cor de fundo, texto, borda, badge ou botão **DEVE** obrigatoriamente derivar das variáveis CSS semânticas (`var(--vx-...)`) ou das classes canônicas do sistema.

Quando cores são inseridas de forma estática (por exemplo, `text-white` ou `background: #1e293b`), a tela quebra instantaneamente ao alternar entre **Modo Escuro** e **Modo Claro**, gerando textos invisíveis (branco sobre branco) ou manchas escuras em páginas claras.

---

## 2. Matriz de Tokens Semânticos

| Token Semântico | Modo Escuro (`data-theme="dark"`) | Modo Claro (`data-theme="light"`) | Aplicação Obrigatória |
| :--- | :--- | :--- | :--- |
| `--vx-bg` | `#0b111d` | `#f8fafc` | Fundo principal da página (`body`, `html`) |
| `--vx-bg-darker` | `#070b13` | `#ffffff` | Barra lateral (`.vx-nav`) e headers profundos |
| `--vx-surface` | `#121a29` | `#ffffff` | Fundo de cartões (`.card`), modais e dropdowns |
| `--vx-surface-card` | `#141e30` | `#ffffff` | Fundo de cartões aninhados e seções |
| `--vx-surface-subtle` | `#162032` | `#f8fafc` | Fundo sutil para cabeçalhos de tabela e filtros |
| `--vx-surface-hover` | `#182337` | `#f1f5f9` | Estado `:hover` de linhas, itens e botões |
| `--vx-border` | `rgba(255, 255, 255, 0.08)` | `#e2e8f0` | Bordas de separadores, cards e tabelas |
| `--vx-border-strong` | `rgba(255, 255, 255, 0.16)` | `#cbd5e1` | Bordas de inputs, botões outline e divisores |
| `--vx-ink` | `#ffffff` | `#0f172a` | Texto primário, títulos (`h1`-`h6`), links de tabela |
| `--vx-ink-secondary`| `#cbd5e1` | `#334155` | Texto secundário, descrições e metadados |
| `--vx-muted` | `#94a3b8` | `#64748b` | Legendas, datas, códigos secundários e dicas |
| `--vx-brand` | `#2563eb` | `#2563eb` | Botões primários, seleções ativas e destaques |
| `--vx-success` | `#10b981` | `#059669` | Sucesso, status concluído, valores positivos |
| `--vx-warning` | `#f59e0b` | `#d97706` | Alertas, avisos de reposição, pendências |
| `--vx-danger` | `#f43f5e` | `#e11d48` | Erros, itens zerados, cancelamentos |
| `--vx-info` | `#06b6d4` | `#0284c7` | Ações neutras, códigos SKU, informativos |

---

## 3. Padrão de Construção de Componentes

### 3.1. Cabeçalho de Página (`.vx-page-header`)
```html
<header class="d-flex justify-content-between align-items-center flex-wrap gap-3 mb-4 pb-2 border-bottom border-secondary border-opacity-10">
  <div>
    <p class="small mb-1 fw-semibold" style="color: var(--vx-muted) !important;">Módulo › Submódulo</p>
    <h1 class="h2 mb-1 fw-bold" style="color: var(--vx-ink) !important;">Título da Tela</h1>
    <p class="small mb-0" style="color: var(--vx-ink-secondary) !important;">Descrição objetiva do objetivo desta tela.</p>
  </div>
  <div class="d-flex align-items-center gap-2">
    <a class="btn btn-primary btn-sm d-flex align-items-center gap-2 px-3 py-2 fw-bold shadow-sm" href="...">
      <i class="bi bi-plus-lg"></i>
      <span>Ação Principal</span>
    </a>
  </div>
</header>
```

### 3.2. Grids de Indicadores KPI (`.stock-kpi-card`)
```html
<section class="stock-kpi-grid mb-4">
  <article class="stock-kpi-card">
    <div class="kpi-header">
      <span class="kpi-label">Indicador Chave</span>
      <div class="kpi-icon kpi-icon-primary"><i class="bi bi-activity"></i></div>
    </div>
    <strong class="kpi-value">124</strong>
    <span class="kpi-sub">Total registrado no período</span>
  </article>
</section>
```
*No CSS, `.stock-kpi-card` consome automaticamente `var(--vx-surface)`, `var(--vx-border)` e `var(--vx-ink)`.*

### 3.3. Tabela Canônica com Links e Badges (`.table`)
```html
<div class="card p-3 table-responsive mb-4">
  <table class="table table-hover align-middle mb-0">
    <thead>
      <tr class="small text-uppercase">
        <th>Identificador</th>
        <th class="text-center">Quantidade</th>
        <th>Status</th>
        <th class="text-end">Ações</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>
          <a class="vx-table-link d-block text-truncate" href="...">Nome do Item</a>
          <small class="d-block font-monospace fw-semibold" style="color: var(--vx-muted);"><i class="bi bi-upc me-1 text-info"></i>SKU-12345</small>
        </td>
        <td class="text-center font-monospace fw-bold" style="color: var(--vx-ink-secondary);">10,000</td>
        <td>
          <span class="badge bg-success-subtle text-success">Ativo</span>
        </td>
        <td class="text-end">
          <a class="btn btn-sm btn-outline-secondary" href="...">Detalhes</a>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

### 3.4. Barra de Filtros e Pílulas de Navegação (`.vx-filter-pill`)
```html
<div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
  <a href="?" class="vx-filter-pill {% if not request.GET.status %}active{% endif %}">
    <span>Todos</span>
    <span class="vx-filter-badge">505</span>
  </a>
  <a href="?status=pendente" class="vx-filter-pill {% if request.GET.status == 'pendente' %}active{% endif %}">
    <span>Pendentes</span>
    <span class="vx-filter-badge">22</span>
  </a>
</div>
```

### 3.5. Banners Executivos de Alerta (`.vx-stock-alert-banner`)
```html
<a class="d-flex align-items-center justify-content-between p-3 mb-4 text-decoration-none shadow-sm vx-stock-alert-banner" href="...">
  <div class="d-flex align-items-center gap-3">
    <div class="vx-alert-icon-box">
      <i class="bi bi-exclamation-triangle-fill fs-5"></i>
    </div>
    <div>
      <span class="d-block fw-bold text-uppercase vx-alert-title">ATENÇÃO — TÍTULO DO ALERTA</span>
      <span class="small vx-alert-sub">Explicação sucinta do motivo e impacto da ocorrência.</span>
    </div>
  </div>
  <div class="btn btn-sm fw-bold px-3 py-1.5 d-flex align-items-center gap-2 vx-alert-btn">
    <span>Resolver Agora</span>
    <i class="bi bi-arrow-right"></i>
  </div>
</a>
```

---

## 4. Antipadrões Terminantemente Proibidos

1. ❌ **`class="text-white"` dentro de `.card` ou `.table`**:
   No tema claro, o card é branco e o texto fica 100% invisível.
   ✅ **Solução:** Usar `class="vx-table-link"` ou `style="color: var(--vx-ink);"` ou `class="fw-bold"`.

2. ❌ **`style="background: #1e293b;"` ou `background: white;` inline**:
   Impede a troca dinâmica de tema e causa incongruência visual ("telas bizarras").
   ✅ **Solução:** Usar classes `.card`, `.stock-kpi-card` ou `var(--vx-surface)`.

3. ❌ **`btn-outline-primary` escuro sobre fundos escuros**:
   Possui contraste de apenas ~1.8:1, tornando o botão ilegível.
   ✅ **Solução:** Usar botão primário sólido `btn-primary` com fundo `#2563eb` e texto `#ffffff`.

4. ❌ **Injeção de Dados Mocados ou Sintéticos**:
   O sistema é multi-tenant real e será usado por várias empresas. Sempre consuma do backend oficial.

5. ❌ **Ativação Múltipla de Links do Menu Lateral (Bug de dois selecionados)**:
   Nunca utilize checagem cega de prefixo (`startswith`) sem desempate de especificidade. Sub-rotas como `/estoque/` e `/estoque/painel/` ou `/compras/` e `/compras/?cotacoes=1` causavam ativação simultânea de dois itens no menu lateral.
   ✅ **Solução:** Aplicar a arquitetura *Single Best Match* (tanto no context processor Python quanto no Javascript de bootstrap do cliente), atribuindo pontuação de especificidade e garantindo que exatamente **um** item receba a classe `.active`.

---

## 5. Checklist de Verificação Pré-Deploy

- [ ] Testou a tela com `data-theme="dark"` no elemento `<html>`?
- [ ] Testou a tela com `data-theme="light"` no elemento `<html>`?
- [ ] O menu lateral possui estritamente **1** item ativo selecionado (zero duplo destaque)?
- [ ] Todos os textos primários possuem contraste superior a 4.5:1 nos dois modos?
- [ ] Nenhum texto ficou com cor branca sobre fundo branco no modo claro?
- [ ] Nenhum elemento permaneceu como caixa preta no meio da tela no modo claro?
- [ ] Todos os botões e links respondem a estados `:hover` e `:focus-visible`?
