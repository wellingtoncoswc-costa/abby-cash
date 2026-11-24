# Logomarca Abby — guia para recriar em outro sistema

Documento autossuficiente: com ele (e sem acesso a este repositório) dá para recriar a logomarca
idêntica, gerar todos os arquivos de ícone e aplicá-la em web e app. As cores e o conceito
valem para qualquer sistema da família Abby.

Decisão de origem: ADR 0050 do repositório abby-map (`docs/adr/0050-identidade-visual-claro-padrao-e-logomarca.md`).

## 1. Conceito

Um **"a" minúsculo desenhado como uma fibra óptica de traço contínuo**. O traço faz o bojo do "a",
sobe pela haste e, no topo, **se divide como um splitter**: uma derivação segue para a direita e
termina num **ponto de luz** (a luz saindo da fibra). A parte de baixo da haste termina numa
perna curta, como a cauda de um "a" de uma só barriga.

- Mostra o que o produto faz (distribuir fibra), em vez de usar pino de mapa ou ondas de sinal.
- Um único traço, uma única espessura, pontas arredondadas: funciona de 16 px a 1024 px.
- Só **um** elemento chama atenção: o ponto de luz. Todo o resto é calmo.

## 2. Cores

| Nome | Hex | Papel |
|------|-----|-------|
| Vidro | `#0E6B5C` | Cor da marca: traço da logo, botões, links |
| Luz | `#34D399` | Ponto de luz e halo. Destaque; nunca como cor de texto |
| Névoa | `#F6F8F7` | Fundo claro; traço da logo sobre fundo Vidro |
| Tinta | `#0F1F1B` | Texto e fundo escuro |

Em oklch (usado no CSS do web): Vidro `oklch(0.47 0.075 175)`, Luz `oklch(0.8 0.15 165)`,
Névoa `oklch(0.975 0.004 170)`, Tinta `oklch(0.24 0.025 175)`.

## 3. SVG de referência (fonte da verdade)

Versão principal, para fundo claro. `viewBox` 64×64, sem fundo:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <g stroke="#0E6B5C" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="25" cy="39" r="12.5"/>
    <path d="M37.5 39V50.5c0 3.2 2.3 5 5.5 5h1.5"/>
    <path d="M37.5 39V27c0-8 5.5-12.5 13-12.5"/>
  </g>
  <circle cx="53" cy="14.5" r="5.5" fill="#34D399"/>
  <circle cx="53" cy="14.5" r="9" stroke="#34D399" stroke-opacity=".35" stroke-width="2"/>
</svg>
```

Geometria, para quem for redesenhar em outra ferramenta:

| Parte | Definição |
|-------|-----------|
| Bojo | círculo, centro (25, 39), raio 12,5, traço 6 |
| Haste + perna | vertical em x = 37,5 (tangente ao bojo) de y = 39 até 50,5, curva à direita até (44,5, 55,5) |
| Derivação | da haste em y = 39 sobe até y = 27, curva em arco até (50,5, 14,5) |
| Ponto de luz | círculo cheio, centro (53, 14,5), raio 5,5, cor Luz |
| Halo | anel, centro (53, 14,5), raio 9, traço 2, cor Luz com 35 % de opacidade |
| Traço | espessura 6, pontas e junções arredondadas (`round`) em todo o desenho |

Regras de ouro:
- O traço **sempre** tem a mesma espessura (6 em 64). Não afine nem engrosse partes.
- O ponto de luz **encosta** na ponta da derivação e a cobre parcialmente. Não deixe folga.
- Não gire, não incline, não espelhe, não aplique sombra nem gradiente.
- Área de respiro mínima: metade do diâmetro do bojo (~12 unidades) em volta da marca.
- Tamanho mínimo: 16 px (favicon). Abaixo disso o halo some e o ponto continua legível.

## 4. Wordmark

O nome é **abby**, em minúsculas, **Onest** peso 600, espaçamento levemente fechado
(`tracking-tight`). É texto composto na fonte da interface, não um desenho. Não use caixa alta,
não coloque o nome em itálico nem destaque uma letra.

Em tela clara, texto em Tinta. Em tela escura, texto em Névoa.

## 5. Variantes e como gerar cada arquivo

Todas saem do mesmo SVG, mudando só cores, escala e fundo. "Escala" é aplicada em torno do
centro (32, 32) da tela 64×64.

| Arquivo | Tamanho | Fundo | Traço | Ponto | Halo | Escala |
|---------|---------|-------|-------|-------|------|--------|
| `icon.png` (ícone do app) | 1024 | quadrado Vidro | Névoa | Luz | .4 | .82 |
| `android-icon-foreground.png` | 1024 | transparente | Névoa | Luz | .4 | .56 |
| `android-icon-background.png` | 1024 | quadrado Vidro | — | — | — | — |
| `android-icon-monochrome.png` | 1024 | transparente | preto | preto | 0 | .56 |
| `splash-icon.png` | 1024 | transparente | Vidro | Luz | .35 | .9 |
| `favicon.png` / `marca.png` | 256 | transparente | Vidro | Luz | .35 | 1 |
| `marca.svg` | vetor | transparente | Vidro | Luz | .35 | 1 |

A escala .56 do ícone adaptativo do Android é a "zona segura": o sistema recorta o ícone em
círculo/gota/quadrado e corta as bordas.

### Script para gerar os PNGs

Não precisa de ImageMagick nem de biblioteca de imagem: basta um Chromium (o do Playwright serve).
Ajuste `C` para o caminho do executável.

```bash
C=~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome   # qualquer Chromium/Chrome
C=$(ls $C | head -1)

# mk NOME TAMANHO FUNDO TRAÇO PONTO OPACIDADE_HALO ESCALA
mk() {
cat > $1.svg <<E
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="$2" height="$2" fill="none">
$3
<g transform="translate(32 32) scale($7) translate(-32 -32)">
  <g stroke="$4" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="25" cy="39" r="12.5"/><path d="M37.5 39V50.5c0 3.2 2.3 5 5.5 5h1.5"/><path d="M37.5 39V27c0-8 5.5-12.5 13-12.5"/>
  </g>
  <circle cx="53" cy="14.5" r="5.5" fill="$5"/>
  <circle cx="53" cy="14.5" r="9" stroke="$5" stroke-opacity="$6" stroke-width="2"/>
</g></svg>
E
echo "<body style='margin:0;background:transparent'><img src='$1.svg' style='display:block' width=$2 height=$2></body>" > $1.html
"$C" --headless=new --no-sandbox --disable-gpu --allow-file-access-from-files \
  --default-background-color=00000000 --hide-scrollbars \
  --screenshot=$1.png --window-size=$2,$2 file://$PWD/$1.html >/dev/null 2>&1
}

mk icon   1024 '<rect width="64" height="64" fill="#0E6B5C"/>' '#F6F8F7' '#34D399' .4  .82
mk fg     1024 ''                                              '#F6F8F7' '#34D399' .4  .56
mk bg     1024 '<rect width="64" height="64" fill="#0E6B5C"/>' '#000'    '#000'    0   0.01
mk mono   1024 ''                                              '#000'    '#000'    0   .56
mk splash 1024 ''                                              '#0E6B5C' '#34D399' .35 .9
mk fav    256  ''                                              '#0E6B5C' '#34D399' .35 1
```

Confira cada PNG abrindo a imagem: o fundo transparente tem de sair transparente, e o ponto de
luz não pode ser cortado nas bordas (por isso a escala menor nos ícones com recorte).

## 6. Como aplicar

**Web (React/Vite):**
- `public/marca.svg` e `public/favicon.png`; no `<head>`: `rel="icon"` e `apple-touch-icon`
  apontando para `/favicon.png`, e `mask-icon` com a cor `#0E6B5C`.
- No cabeçalho/menu: `<img src="/marca.svg" alt="" className="size-10 dark:brightness-125" />`
  seguido do texto "abby". O `dark:brightness-125` clareia o Vidro sobre fundo escuro.
- No login: a marca centralizada em 64 px, o nome "abby" abaixo (24 px, peso 600).

**App (Expo / React Native):**
- `app.json`: `icon` = `icon.png`; `android.adaptiveIcon` com `foregroundImage`,
  `backgroundImage`, `monochromeImage` e `backgroundColor` `#0E6B5C`; plugin `expo-splash-screen`
  com `image` = `splash-icon.png`, `backgroundColor` `#F6F8F7` e `imageWidth` 76.
- Dentro do app (login etc.): `<Image source={require('.../marca.png')} />` em 88 px.
  Não adicione `react-native-svg` só por isso.
- Ícone e splash só mudam com um novo build nativo (no EAS, um novo `eas build`).

**Fundo escuro:** o traço Vidro tem pouco contraste sobre Tinta. No web usamos
`brightness-125`. Num sistema novo, o melhor é gerar uma variante com traço Névoa (receita do
`icon.png` sem o quadrado Vidro).

## 7. O que não fazer

- Não substituir o ponto de luz por outra cor nem por um pino de mapa.
- Não usar a marca em tons de cinza com o ponto colorido: ou é a versão colorida, ou a
  monocromática (tudo em uma cor só).
- Não colocar a marca dentro de um quadrado arredondado de cor diferente de Vidro, exceto no
  ícone do app, que é o único lugar com fundo.
- Não escrever "Abby" com maiúscula no wordmark da marca; o nome da marca é **abby**.
