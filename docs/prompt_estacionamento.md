# Prompt: estacionamento IoT com 100 vagas

> Abra o Claude Code na pasta `C:\Users\rober\contador-veiculos-iot` e cole todo o texto abaixo da linha.

---

Você vai transformar este projeto, hoje um contador de veículos genérico, em um **monitor de vagas de estacionamento IoT**. Leia todo o repositório antes de começar: `contador_veiculos.py`, `no_sensores_esp32/`, `teste_esp32/`, `README.md` e `.gitignore`. Planeje a mudança e me mostre o plano antes de editar.

## Cenário

Um estacionamento tem **100 vagas** e uma única entrada/saída. A **câmera de um celular** filma essa passagem. O sistema identifica se cada veículo está **entrando** ou **saindo** e mantém atualizado o número de **vagas disponíveis**. Esse número aparece:
- em um **painel web bonito**, acessível pelo celular de qualquer lugar (hospedado na **Vercel**);
- em um **indicador físico na entrada**, controlado pelo ESP32.

O trabalho deve ficar **mais simples** do que o atual. Saem a medição de altura, a classificação leve/pesado e a comparação entre métodos. O **ESP32 é obrigatório**, porque o projeto é de IoT, e precisa ter um papel claro e necessário, não decorativo.

## Arquitetura

```
[Celular: IP Webcam] --vídeo (Wi-Fi local)--> [Notebook: visao.py, OpenCV]
                                                     | POST /movimento (HTTP local)
                                                     v
                                  [ESP32: controlador do estacionamento]
                                   - mantém a contagem (persistente)
                                   - acende o indicador: LIVRE / LOTADO
                                   - publica o estado na nuvem (HTTPS)
                                                     |
                                                     v
                         [Vercel: API + banco Redis (Upstash)]  <--  [Painel web no celular]
```

Os papéis de cada parte:
- **Celular:** apenas o sensor de imagem (app IP Webcam ou DroidCam). Já funciona.
- **Notebook (`visao.py`):** processamento de borda. Detecta a passagem e o sentido com as duas faixas virtuais A e B, reaproveitando a lógica atual de `Faixa` e `Contador`, que já foi testada.
  - A faixa A fica do lado da rua e a B do lado de dentro. **A → B = entrada** e **B → A = saída**, com opção `--inverter`.
  - O notebook **não guarda a contagem oficial**: cada movimento é enviado ao ESP32.
  - Mantém uma página local simples, só para **calibrar a câmera**: imagem ao vivo com as faixas, como hoje. A imagem da câmera **nunca vai para a nuvem**, por privacidade e para não gastar dados.
- **ESP32 (`esp32_estacionamento/`):** o controlador do estacionamento e a peça IoT central.
  - Recebe `POST /movimento` do notebook na rede local e atualiza `ocupadas`, limitado entre 0 e o número de vagas.
  - Grava o estado na flash com `Preferences`, para não perder a contagem se faltar energia.
  - Controla o indicador na entrada:
    - LED verde = há vagas, LED vermelho = lotado, e amarelo opcional para "quase lotado" (≥ 90%);
    - se não houver LEDs externos, usa o LED azul da placa (aceso = lotado).
  - Publica o estado na API da Vercel por HTTPS a cada mudança e a cada 30 s como sinal de vida. Usa uma fila com reenvio se a internet cair e um número de sequência para a API ignorar duplicatas.
  - Anuncia-se na rede por mDNS como `estacionamento.local`, para o notebook achá-lo sem precisar do IP. `visao.py` aceita `--esp32 <ip>` como alternativa.
  - Oferece uma página local mínima (`GET /`) com o número de vagas, útil quando não houver internet.
- **Vercel (`web/`):** a API e o painel público.
  - `POST /api/estado`: recebe o estado do ESP32. Exige o cabeçalho `Authorization: Bearer <INGEST_TOKEN>`.
  - `GET /api/estado`: estado atual e últimos movimentos, para o painel.
  - `POST /api/ajuste`: correção manual de `ocupadas` pelo painel, protegida por um PIN (`ADMIN_PIN`). O ESP32 busca ajustes pendentes no próximo envio, ou o ajuste volta na resposta do `POST /api/estado`. Escolha o mais simples e explique.
  - Armazenamento em **Upstash Redis** (integração do Marketplace da Vercel). Guarde o estado atual, os últimos 50 movimentos e o total de entradas/saídas por hora do dia, para o gráfico.
  - O painel atualiza a cada 2–3 s por polling.

## O que remover

- O nó de sensores antigo (`no_sensores_esp32/`): IR, ultrassom, altura, leve/pesado, comparação câmera × ESP32. Apague a pasta. Ela continua no histórico do Git.
- No Python: a classe `NoESP32`, os endpoints `/evento` e `/status`, as colunas `altura_cm`/`categoria` e o modo `--sem-camera`.
- `PROMPT_interface.md`: este prompt o substitui.
- `teste_esp32/` pode ficar, porque é útil para testar uma placa nova.
- Os `.docx` **não** devem ser alterados. Os relatórios serão refeitos à parte.

## Painel web (Vercel)

- **Stack:** Next.js (App Router) + TypeScript na pasta `web/`, sem biblioteca de UI pesada. CSS próprio com variáveis. Fontes Geist e Geist Mono pelo pacote `geist` ou `next/font`, servidas pela própria Vercel.
- **Visual:** siga o design do projeto **Caderno de Campo** (https://github.com/jonhvinnykkj/caderno-de-campo-mongodb). Leia `public/css/app.css`, `views/painel.ejs` e `docs/telas/painel.png` desse repositório. Resumo:
  - **Cores** como variáveis CSS: `--papel #F5F6F4`, `--folha #FFFFFF`, `--degrau #ECEEEB`, `--linha #E1E4E0`, `--tinta #16231F`, `--tinta2 #55615C`, `--tinta3 #8A948F`, `--petroleo #0F4C5C`, `--petroleo-esc #0A3742`, `--petroleo-t #DCE9EC`, `--carimbo #B3402F`, `--carimbo-t #F6DFDB`, `--cana #1F8A70` (entradas), `--amendoim #C27A2C` (saídas), `--milho #E2B51F` (quase lotado).
  - **Fundo:** "papel quadriculado", com grade de 28 px em petróleo a 5,5% de opacidade.
  - **Cartões:** "folhas" brancas, `border-radius: 22px`.
  - **Títulos:** grandes, peso 600 e `letter-spacing` negativo.
  - **Textos em mono:** rótulos, horários e o kicker.
  - **Status:** "carimbos" levemente girados (-2°).
- **Conteúdo (celular primeiro):**
  1. Kicker `FATEC Pompeia · Big Data no Agronegócio` e título "Estacionamento".
  2. **O número principal:** vagas disponíveis em destaque máximo ("**37** vagas livres de 100"), com um carimbo de status: LIVRE (petróleo), QUASE LOTADO (milho) ou LOTADO (carimbo).
  3. Barra de ocupação de 0 a 100, com o trecho ocupado preenchido.
  4. Uma frase-resumo no estilo `.frase` do original. Exemplo:

     > Hoje entraram **58 veículos** e saíram **21**. O pico foi às **8h**.
  5. Gráfico de barras simples, em CSS/SVG e sem biblioteca, com entradas × saídas por hora.
  6. Lista "Últimos movimentos" no estilo diário: hora em mono, ENTRADA/SAÍDA com ponto colorido e vagas livres depois do movimento.
  7. Status do ESP32: "conectado" ou "sem sinal há X min", conforme o último sinal de vida.
  8. Botão discreto "Corrigir contagem", que abre um campo para o número de veículos e o PIN.
- **Celular:** uma coluna, alvos de toque ≥ 44 px, número principal enorme e legível a 1 m de distância.
- **Notebook:** duas colunas.
- Respeitar `prefers-reduced-motion`. Contraste AA. Textos em português do Brasil.
- Estados de erro: API fora do ar, ESP32 sem sinal e banco vazio, cada um com mensagem clara e sem tela quebrada.

## Segurança e configuração

- **Nenhum segredo no Git.**
  - No ESP32: estenda o `segredos.h` (já ignorado) com `INGEST_TOKEN` e `URL_API`, e atualize o `segredos.exemplo.h`.
  - Na Vercel: `INGEST_TOKEN`, `ADMIN_PIN` e as variáveis do Redis ficam nas variáveis de ambiente do projeto.
  - Crie `web/.env.example` com os nomes das variáveis.
- No ESP32, use `WiFiClientSecure`. Pode usar `setInsecure()` desde que haja um comentário explicando que, por ser projeto acadêmico, o certificado não é validado, e como validar com o CA raiz se quiserem.
- **Não crie conta nem faça deploy por mim.** Deixe tudo pronto e me diga os comandos, porque eu mesmo faço login na Vercel e no Upstash.

## Hardware que temos

- **ESP32 DevKit:** ESP32-D0WD-V3, chip USB CP2102, na porta **COM13**. O driver e o suporte no Arduino (esp32 3.3.x) já estão instalados.
- O `arduino-cli` está em `C:\Users\rober\AppData\Local\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`. FQBN: `esp32:esp32:esp32`.
- Protoboards à vontade. Se forem usados LEDs externos, indique os GPIOs e os resistores (220–330 Ω) num diagrama em texto no README.
- **Rede:** o notebook e o ESP32 estão na rede **BDAG**, que tem internet. Uma rede com login por página web não serve para o ESP32.

## Verificação (obrigatória, antes de me entregar)

1. **Visão:** gere um vídeo sintético com veículos entrando e saindo, com o mesmo método do teste que já existe: retângulos coloridos atravessando as faixas. Rode `visao.py` contra um **ESP32 simulado**, um pequeno servidor Python de teste. Confirme que as entradas e saídas chegam certas.
2. **ESP32:**
   - compile com o `arduino-cli`;
   - grave na COM13 e leia a serial;
   - mande `POST /movimento` de verdade, do notebook para a placa;
   - confirme que a contagem muda, que fica limitada entre 0 e 100, que o LED reage ao lotar e que a contagem **sobrevive a um reset** da placa.
3. **Web:**
   - rode `npm run build` e `npm run dev` em `web/`;
   - simule o ESP32 com `curl` em `POST /api/estado`, com token certo e com token errado;
   - teste o ajuste com PIN certo e errado;
   - tire screenshots do painel em 375 × 812 e em 1440 × 900 e me mostre.

     Para o Redis local, se eu ainda não tiver criado o banco, use um armazenamento em memória como reserva quando as variáveis do Upstash não existirem. Deixe isso explícito no código.
4. **Segredos:** confirme com `git status` e uma busca no conteúdo versionado que nenhum token, PIN ou senha vai entrar no commit.

## README

Reescreva o `README.md` para o novo cenário:
- objetivo e diagrama da arquitetura;
- ligações elétricas;
- como configurar `segredos.h` e as variáveis da Vercel;
- como rodar cada parte;
- como calibrar as faixas;
- limitações (por exemplo: entrada e saída pela mesma passagem, veículos lado a lado, mudança de luz, contagem dependente de calibração e correção manual).

## Ao final, me entregue

1. Um resumo do que mudou, arquivo por arquivo.
2. **Como testar tudo em casa e no laboratório**, passo a passo e em ordem:
   1. celular;
   2. notebook;
   3. ESP32;
   4. painel local;
   5. deploy na Vercel (login, criar o projeto apontando para `web/`, adicionar o Upstash pelo Marketplace, configurar as variáveis, fazer o deploy);
   6. teste de ponta a ponta com um carrinho passando na frente da câmera.
3. **Como commitar e enviar ao GitHub**, com os comandos exatos:
   - conferir o `git status`;
   - conferir que `segredos.h` e `.env*` estão ignorados;
   - fazer `git add` e um commit com mensagem descritiva em português;
   - fazer `git push` para `origin main`.

   Lembre que o repositório é **privado** e que o colega João (`jonhvinnykkj`) já foi convidado como colaborador.

   **Não faça o commit nem o push sozinho.** Só me mostre os comandos e espere eu confirmar.
