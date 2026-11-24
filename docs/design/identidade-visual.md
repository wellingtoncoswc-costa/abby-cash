# Identidade visual do Abby Cash

O Abby Cash usa **a mesma logomarca e o mesmo visual da família Abby**. A referência é o **abby-map**, que tem o guia oficial da marca (ADR 0050). Este documento é autossuficiente: não é preciso ter o abby-map na máquina para aplicar a identidade.

- Logomarca, conceito, cores, wordmark e receita dos ícones: `docs/design/logomarca.md` (cópia fiel do guia do abby-map).
- Arquivos prontos: `docs/design/marca/marca.svg` (vetor), `docs/design/marca/favicon.png` (256 px) e `docs/design/marca/use-tema.ts.txt` (hook de tema do abby-map, para copiar como `.ts`).

> O abby-chat ainda usa o visual antigo (azul-marinho escuro, ícone de raio, "ISP Suite") e **não** é referência. Se ele for migrado, a referência continua sendo este guia.

## Regras

1. **A logomarca é a mesma da família:** o "a" de traço contínuo com o ponto de luz. Não crie uma variante "de finanças" (cifrão, moeda, gráfico). O que diferencia o produto é o **nome do produto ao lado do wordmark**, não o desenho.
2. **Wordmark:** `abby` em minúsculas, Onest 600, `tracking-tight`. O nome do produto aparece como rótulo secundário: `cash`, em minúsculas, peso 500 e cor `text-muted-foreground`, na mesma linha (`abby cash`). Esse padrão é a decisão do Abby Cash. O abby-map exibe só "abby".
3. **Tema claro por padrão**, escuro opcional pela classe `.dark` no `<html>`, guardado em `localStorage` na chave `abby-tema` (mesma chave da família), aplicado antes da primeira pintura.
4. **Só tokens.** Telas usam `bg-background`, `text-foreground`, `bg-primary` etc. Nunca hex fixo em componente.
5. **Fonte Onest** (400/500/600/700) e JetBrains Mono (400/500) para números tabulares, via Google Fonts. Valores monetários usam `font-variant-numeric: tabular-nums` (classe `tabular-nums`).
6. **Componentes:** shadcn/ui estilo `new-york`, ícones `lucide-react`, raio `0.625rem`.

## Paleta

| Nome | Hex | oklch | Papel |
|---|---|---|---|
| Vidro | `#0E6B5C` | `oklch(0.47 0.075 175)` | Cor da marca: logo, botões, links, `primary` |
| Luz | `#34D399` | `oklch(0.8 0.15 165)` | Destaque (`accent`). Nunca como cor de texto |
| Névoa | `#F6F8F7` | `oklch(0.975 0.004 170)` | Fundo claro |
| Tinta | `#0F1F1B` | `oklch(0.24 0.025 175)` | Texto e fundo escuro |

### Cores com significado financeiro (decisão do Abby Cash, derivadas da paleta)
- **Receita:** `success`. **Despesa:** `foreground` (neutro). Despesa não fica vermelha por padrão, porque gastar é normal.
- **Teto:** barra em `primary` até 80%, `warning` de 80% a 99% e `destructive` a partir de 100%, os mesmos limiares dos alertas.
- **Metas:** `accent` (Luz) para o progresso.
- **Gráficos por categoria:** `chart-1` a `chart-5`, depois repetir com opacidade de 60%.

## Tokens (copiar para `web/src/styles.css`)

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

@theme inline {
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --radius-2xl: calc(var(--radius) + 8px);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-ring-offset-background: var(--background);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
  --color-success: var(--success);
  --color-warning: var(--warning);
  --color-critical: var(--critical);
  --font-sans: "Onest", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}

:root {
  --radius: 0.625rem;
  --background: oklch(0.975 0.004 170); /* Névoa */
  --foreground: oklch(0.24 0.025 175); /* Tinta */
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.24 0.025 175);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.24 0.025 175);
  --primary: oklch(0.47 0.075 175); /* Vidro */
  --primary-foreground: oklch(0.98 0.005 170);
  --secondary: oklch(0.955 0.006 170);
  --secondary-foreground: oklch(0.24 0.025 175);
  --muted: oklch(0.955 0.006 170);
  --muted-foreground: oklch(0.5 0.02 175);
  --accent: oklch(0.8 0.15 165); /* Luz */
  --accent-foreground: oklch(0.24 0.025 175);
  --destructive: oklch(0.55 0.2 25);
  --destructive-foreground: oklch(0.98 0.01 260);
  --border: oklch(0.24 0.025 175 / 12%);
  --input: oklch(0.24 0.025 175 / 16%);
  --ring: oklch(0.47 0.075 175);
  --success: oklch(0.55 0.13 160);
  --warning: oklch(0.7 0.15 75);
  --critical: oklch(0.55 0.2 25);
  --chart-1: oklch(0.55 0.1 175);
  --chart-2: oklch(0.7 0.15 75);
  --chart-3: oklch(0.55 0.2 25);
  --chart-4: oklch(0.6 0.12 235);
  --chart-5: oklch(0.6 0.14 300);
  --sidebar: oklch(0.99 0.003 170);
  --sidebar-foreground: oklch(0.32 0.025 175);
  --sidebar-primary: oklch(0.47 0.075 175);
  --sidebar-primary-foreground: oklch(0.98 0.005 170);
  --sidebar-accent: oklch(0.945 0.014 170);
  --sidebar-accent-foreground: oklch(0.24 0.025 175);
  --sidebar-border: oklch(0.24 0.025 175 / 9%);
  --sidebar-ring: oklch(0.47 0.075 175);
}

.dark {
  --background: oklch(0.145 0.02 260);
  --foreground: oklch(0.92 0.01 250);
  --card: oklch(0.18 0.02 260);
  --card-foreground: oklch(0.92 0.01 250);
  --popover: oklch(0.19 0.02 260);
  --popover-foreground: oklch(0.92 0.01 250);
  --primary: oklch(0.72 0.16 165);
  --primary-foreground: oklch(0.145 0.02 260);
  --secondary: oklch(0.24 0.02 260);
  --secondary-foreground: oklch(0.92 0.01 250);
  --muted: oklch(0.22 0.02 260);
  --muted-foreground: oklch(0.62 0.02 255);
  --accent: oklch(0.72 0.16 165);
  --accent-foreground: oklch(0.145 0.02 260);
  --destructive: oklch(0.62 0.22 22);
  --destructive-foreground: oklch(0.98 0.01 260);
  --border: oklch(1 0 0 / 8%);
  --input: oklch(1 0 0 / 10%);
  --ring: oklch(0.72 0.16 165);
  --success: oklch(0.72 0.16 165);
  --warning: oklch(0.78 0.16 75);
  --critical: oklch(0.65 0.22 22);
  --sidebar: oklch(0.16 0.02 260);
  --sidebar-foreground: oklch(0.85 0.01 255);
  --sidebar-primary: oklch(0.72 0.16 165);
  --sidebar-primary-foreground: oklch(0.145 0.02 260);
  --sidebar-accent: oklch(0.22 0.02 260);
  --sidebar-accent-foreground: oklch(0.92 0.01 250);
  --sidebar-border: oklch(1 0 0 / 6%);
  --sidebar-ring: oklch(0.72 0.16 165);
}

@layer base {
  * { border-color: var(--color-border); }
  html, body, #root { height: 100%; }
  body {
    background-color: var(--color-background);
    color: var(--color-foreground);
    font-family: var(--font-sans);
    font-feature-settings: "cv11", "ss01";
  }
}
```

## Padrões de tela (iguais aos do abby-map)

**Menu lateral (desktop):** um trilho de 64 px que expande para 240 px no hover, com a marca no topo:
```tsx
<div className="flex h-10 w-full items-center gap-3 px-3 mb-4">
  <img src="/marca.svg" alt="" className="size-10 shrink-0 dark:brightness-125" />
  <span className="hidden whitespace-nowrap text-base font-semibold tracking-tight group-hover/rail:inline">
    abby <span className="font-medium text-muted-foreground">cash</span>
  </span>
</div>
```
**Celular:** barra inferior com 4 ou 5 destinos (Painel, Lançamentos, Contas, Metas, Mais) e marca de 32 px no topo.

**Login:** cartão centralizado `max-w-sm rounded-2xl border bg-card p-8 shadow-sm`, marca de 64 px, `abby` em 24 px peso 600, com `cash` em `text-muted-foreground` logo abaixo.

**Alternância de tema:** botão nas Configurações e no menu do usuário, usando `useTema()` (copiado de `docs/design/marca/use-tema.ts.txt`). O script `TEMA_BOOT` roda inline no `<head>` do `index.html`.

## Arquivos da marca no web

| Arquivo em `web/public/` | Origem |
|---|---|
| `marca.svg` | copiar de `docs/design/marca/marca.svg` |
| `favicon.png` (256) | copiar de `docs/design/marca/favicon.png` |
| `icon-192.png`, `icon-512.png` | receita `fav` de `logomarca.md` em 192 e 512 |
| `icon-maskable-512.png` | receita `icon` de `logomarca.md` (fundo Vidro), mas com escala `.56` (zona segura) |
| `apple-touch-icon.png` (180) | receita `icon` em 180 |

**Manifest do PWA:** `name: "abby cash"`, `short_name: "abby cash"`, `theme_color: "#0E6B5C"`, `background_color: "#F6F8F7"`, `display: "standalone"`, `lang: "pt-BR"`, com os ícones acima (o maskable com `purpose: "maskable"`).

**`<head>`:** Google Fonts (Onest e JetBrains Mono), `rel="icon"` → `/favicon.png`, `apple-touch-icon` → `/apple-touch-icon.png`, `mask-icon` com a cor `#0E6B5C`, `<meta name="theme-color" content="#0E6B5C">`, `<title>abby cash</title>`.

## Apps Android/iOS (fase futura)
Seguir a seção 6 de `logomarca.md` (app.json, ícone adaptativo e splash), igual ao app do abby-map.

## Mensagens no chat
O bot se apresenta como **abby cash** (em minúsculas), sem emoji de cifrão. Os emojis ficam restritos aos de status: ✅ confirmação, ⚠️ alerta, 🎙️ transcrição, 📅 lembrete, 🎯 meta.
