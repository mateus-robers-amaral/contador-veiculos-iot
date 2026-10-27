# Prompt: nova interface do painel do contador de veículos

> Cole o texto abaixo no Claude Code, aberto na pasta do projeto (onde está `contador_veiculos.py`).

---

Redesenhe a interface web do painel do contador de veículos IoT. Ela está na string `PAGINA` dentro de `contador_veiculos.py`. O visual deve seguir o design do projeto **Caderno de Campo** (https://github.com/jonhvinnykkj/caderno-de-campo-mongodb). Antes de começar, leia `public/css/app.css`, `views/painel.ejs` e `docs/telas/painel.png` desse repositório para pegar o estilo. Vamos testar primeiro **no celular**, então a interface deve ser pensada para tela de celular primeiro e se adaptar ao notebook depois.

## Contexto do projeto

- O `contador_veiculos.py` (Python, OpenCV, `http.server` da biblioteca padrão) conta veículos de duas fontes:
  - a **câmera do celular**, por faixas virtuais A e B na imagem;
  - um **nó ESP32** com sensores infravermelhos e ultrassônico, que envia as passagens por HTTP.
- O painel é servido pelo próprio notebook na rede local e é aberto pelo navegador do celular. A rede pode **não ter internet**.
- Endereços existentes, que **não podem mudar de formato** porque o ESP32 e o README dependem deles:
  - `GET /dados` devolve JSON:
    ```json
    {
      "camera": {"total": 0, "ida": 0, "volta": 0, "faixa_a": false, "faixa_b": false} ,
      "esp32": {"online": true, "total": 0, "ida": 0, "volta": 0, "leves": 0, "pesados": 0,
                "status": {"ip": "...", "rssi": -62, "faixa_a": false, "faixa_b": false,
                           "distancia_cm": 24.8, "referencia_cm": 25.0, "pendentes": 0}},
      "ultimos": [{"data_hora": "2026-10-27T14:40:36", "fonte": "esp32", "sentido": "ida",
                   "altura_cm": 3.2, "categoria": "leve"}]
    }
    ```
    `camera` vale `null` quando o programa roda com `--sem-camera`. `esp32.status` vem vazio quando o ESP32 está desconectado. `altura_cm` e `categoria` vêm como `""` nas passagens da câmera.
  - `GET /quadro.jpg`: imagem atual da câmera com as faixas desenhadas (503 se não houver câmera).
  - `GET /contagens.csv`: download do registro.
  - `POST /evento` e `POST /status`: usados pelo ESP32. **Não mexa neles.**
- Você pode **acrescentar** campos ao JSON de `/dados` (por exemplo, passagens por hora calculadas a partir do CSV) e novos endereços `GET`, desde que os campos existentes continuem iguais.

## Restrições

- **Sem dependências novas no Python.** Nada de Flask ou template engine: continue com `http.server`.
- O HTML, o CSS e o JS podem continuar dentro do `.py` ou ir para uma pasta `painel/` servida pelo mesmo servidor. Escolha o que deixar o código mais limpo e explique a escolha.
- **Nada de CDN em tempo de execução:** a rede local pode não ter internet. Use fontes do sistema com fallback ou inclua os arquivos da fonte Geist no projeto e sirva-os localmente. O mesmo vale para ícones: se usar Phosphor, sirva localmente; senão, use SVG inline.
- A atualização continua por `fetch('/dados')` a cada 500 ms. Não pode piscar nem reconstruir o DOM inteiro a cada ciclo; atualize só os valores que mudaram.
- Textos em português do Brasil.

## Linguagem visual a seguir (do Caderno de Campo)

- **Tokens de cor** (copie como variáveis CSS em `:root`):
  `--papel #F5F6F4`, `--folha #FFFFFF`, `--degrau #ECEEEB`, `--linha #E1E4E0`, `--tinta #16231F`, `--tinta2 #55615C`, `--tinta3 #8A948F`, `--petroleo #0F4C5C`, `--petroleo-esc #0A3742`, `--petroleo-t #DCE9EC`, `--carimbo #B3402F`, `--carimbo-t #F6DFDB`.
- **Cores dos dados:** use as cores de cultura do projeto original para as categorias.
  - ida e volta: `--cana #1F8A70` e `--amendoim #C27A2C`;
  - leve e pesado: `--soja #6B8F2E` e `--cafe #6E4428`.

  Mantenha a mesma cor para o mesmo significado em toda a página.
- **Fundo:** "papel quadriculado", com grade de 28 px em petróleo a 5,5% de opacidade sobre `--papel`.
- **Tipografia:** Geist para texto e Geist Mono para rótulos, datas, números técnicos e o "kicker".
  - Título grande: peso 600, `letter-spacing: -0.045em`.
  - Números com `font-variant-numeric: tabular-nums`.
- **Cabeçalho:** kicker em mono (`FATEC Pompeia · Big Data no Agronegócio`), título "Contador de veículos" e, à direita, um botão em pílula petróleo "Baixar CSV".
- **Frase-resumo** no estilo `.frase` do original: uma frase grande que resume o estado, com os números sublinhados em petróleo. Exemplo:

  > **12 veículos** passaram, **7 de ida** e **5 de volta**. A câmera e o ESP32 diferem em **1**.

  Se o ESP32 estiver desconectado, esse trecho aparece em vermelho-carimbo, como os "insumos abaixo do mínimo" do original.
- **Folhas:** cartões brancos, `border-radius: 22px`, com cabeçalho `.folha-cab` (h2 à esquerda, informação em mono à direita).
- **Carimbos de status:** borda de 1,5 px, fonte mono, levemente girados (-2°), como `.carimbo` do original. Usar para:
  - "conectado" (petróleo) e "desconectado" (carimbo) do ESP32;
  - "faixa ocupada" e "faixa livre" nas faixas A e B;
  - "câmera desativada" (tracejado).
- **Barras:** use a barra segmentada `.faixa-area` para mostrar a proporção ida × volta, e a de leve × pesado no ESP32. Use o `.medidor` para a força do sinal Wi-Fi e para a distância do ultrassom em relação ao chão.
- **Lista de passagens** no estilo "diário" de "Últimas operações":
  - hora em mono;
  - código da fonte (`CAM` ou `ESP`) em mono petróleo;
  - sentido em negrito com o ponto colorido;
  - altura e categoria quando houver.

## Estrutura sugerida da página (celular primeiro)

1. Cabeçalho e frase-resumo.
2. **Folha "Câmera do celular"**:
   - imagem ao vivo em proporção fixa, com cantos arredondados;
   - abaixo dela, os carimbos das faixas A e B e os números total, ida e volta;
   - quando `camera` for `null`, mostrar um estado vazio bem desenhado, com a explicação de como iniciar com `--fonte`.
3. **Folha "Nó ESP32"**:
   - carimbo de conexão e IP em mono;
   - medidor de sinal Wi-Fi (de -90 a -40 dBm);
   - carimbos das faixas;
   - distância atual e distância até o chão;
   - total, ida e volta, e barra leve × pesado;
   - quando houver passagens na fila, um aviso `.faixa.atencao`.
4. **Folha "Comparação"**:
   - câmera × ESP32 lado a lado e a diferença entre eles;
   - se você acrescentar a agregação no backend, um gráfico de barras simples de passagens por hora (CSS/SVG, sem biblioteca).
5. **Folha "Últimas passagens"** no estilo diário, com as mais recentes no topo e destaque breve na linha nova (fundo `--petroleo-t` que some em cerca de 1,5 s).

Layout:
- **Celular** (largura até 820 px): uma coluna, folhas com padding de 18 px, título por volta de 40 px, sem barra lateral. Alvos de toque com pelo menos 44 px de altura.
- **Notebook:** a câmera e o ESP32 lado a lado; a barra lateral é opcional, como a do original, com a marca "Contador de veículos".

## Estados e detalhes

- Se `fetch('/dados')` falhar, mostrar no topo uma `.faixa.erro` "Sem conexão com o notebook". Ela some sozinha quando a conexão voltar.
- A imagem da câmera não pode ficar quebrada: se `/quadro.jpg` falhar, mostrar o estado vazio.
- Respeitar `prefers-reduced-motion`.
- Contraste mínimo AA.

## Como verificar

1. Rode `python contador_veiculos.py --sem-camera`. Simule o ESP32 com `POST /status` e `POST /evento`, usando `urllib` ou `curl`. Abra o painel em viewport de celular (375 × 812) e de notebook (1440 × 900) e tire screenshots dos dois.
2. Rode com vídeo, `python contador_veiculos.py --fonte <video> --sem-janela`, para ver a folha da câmera com imagem.
3. Confirme que o `contador_veiculos.py` continua contando 6 veículos no vídeo de teste e que `POST /evento` com reenvio duplicado continua sendo ignorado.
4. Mostre os screenshots finais e liste o que mudou no código.
