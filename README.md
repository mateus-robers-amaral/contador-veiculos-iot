# Estacionamento IoT: vagas livres em tempo real

Projeto da FATEC Pompeia (Big Data no Agronegócio). Um estacionamento de **100 vagas** tem uma única entrada e saída. A câmera de um celular filma essa passagem, o sistema identifica se cada veículo está **entrando** ou **saindo** e mantém o número de **vagas livres** sempre atualizado:

- num **indicador físico na entrada** (LEDs verde, amarelo e vermelho), controlado pelo ESP32;
- num **painel web** hospedado na Vercel, que abre no celular de qualquer lugar.

```
[Celular: IP Webcam] --vídeo (Wi-Fi local)--> [Notebook: visao.py, OpenCV]
                                                     | POST /movimento (HTTP local)
                                                     v
                                  [ESP32: controlador do estacionamento]
                                   - mantém a contagem (gravada na flash)
                                   - acende o indicador: LIVRE / QUASE LOTADO / LOTADO
                                   - publica o estado na nuvem (HTTPS)
                                                     |
                                                     v
                         [Vercel: API + Upstash Redis]  <--  [Painel web no celular]
```

| Parte | Papel |
|---|---|
| **Celular** | Só o sensor de imagem (app IP Webcam ou DroidCam). |
| **Notebook (`visao.py`)** | Processamento de borda: detecta a passagem e o sentido com duas faixas virtuais e manda cada movimento ao ESP32. Não guarda contagem. Tem uma página local só para calibrar a câmera. **A imagem nunca vai para a nuvem.** |
| **ESP32 (`esp32_estacionamento/`)** | A peça central. Guarda a **contagem oficial** (sobrevive a falta de energia), acende o indicador, publica as vagas na nuvem e aplica correções manuais. Funciona mesmo sem internet. |
| **Vercel (`web/`)** | API que recebe o estado do ESP32 e painel público com as vagas, o gráfico do dia e os últimos movimentos. |

## Sumário

1. [Materiais](#1-materiais)
2. [Ligações elétricas](#2-ligações-elétricas)
3. [Configurar e gravar o ESP32](#3-configurar-e-gravar-o-esp32)
4. [Preparar o notebook e rodar a visão](#4-preparar-o-notebook-e-rodar-a-visão)
5. [Calibrar as faixas](#5-calibrar-as-faixas)
6. [Painel web: rodar no notebook](#6-painel-web-rodar-no-notebook)
7. [Painel web: publicar na Vercel](#7-painel-web-publicar-na-vercel)
8. [Testes sem hardware](#8-testes-sem-hardware)
9. [Referência técnica](#9-referência-técnica)
10. [Solução de problemas](#10-solução-de-problemas)
11. [Limitações](#11-limitações)

```
contador-veiculos-iot/
├── visao.py                      visão computacional no notebook (câmera -> movimentos)
├── requirements.txt              bibliotecas Python (OpenCV e NumPy)
├── esp32_estacionamento/         programa do ESP32 (contagem, indicador, nuvem)
│   ├── esp32_estacionamento.ino
│   └── segredos.exemplo.h        modelo do segredos.h (Wi-Fi, URL da API, token)
├── web/                          painel e API (Next.js, para a Vercel)
│   ├── app/                      página, estilo e rotas /api/estado e /api/ajuste
│   ├── lib/                      regras do estacionamento e acesso ao banco
│   └── .env.example              nomes das variáveis de ambiente
├── testes/
│   ├── gerar_video.py            vídeo sintético com entradas e saídas
│   └── esp32_simulado.py         imita o ESP32 para testar a visão sem a placa
└── teste_esp32/                  teste rápido de uma placa nova (LED + busca de redes)
```

---

## 1. Materiais

| Item | Qtd. | Observação |
|---|---|---|
| ESP32 DevKit (ESP32-WROOM-32) | 1 | O do laboratório é ESP32-D0WD-V3 com USB CP2102. |
| LED verde, amarelo e vermelho (5 mm) | 1 de cada | Opcionais: sem eles, o LED azul da placa acende quando lota. |
| Resistor de 220 a 330 Ω | 3 | Um por LED. |
| Protoboard e jumpers | — | |
| Cabo USB de dados | 1 | Cabo só de carga não grava a placa. |
| Celular Android ou iPhone | 1 | App **IP Webcam** (Android) ou **DroidCam**. |
| Suporte ou mini tripé para o celular | 1 | A câmera não pode se mexer. |
| Notebook com Python 3.10+ e Node.js 20+ | 1 | |
| Rede Wi-Fi 2,4 GHz **sem login por página web** | 1 | No laboratório, a rede **BDAG**. |
| Carrinhos de brinquedo e uma pista de papelão | — | Para a maquete. |

---

## 2. Ligações elétricas

> Desligue o USB antes de mexer nas ligações.

| Componente | Ligação |
|---|---|
| LED verde (há vagas) | GPIO 25 → resistor 220–330 Ω → perna longa (+) do LED; perna curta (−) → GND |
| LED amarelo (quase lotado, ≥ 90%) | GPIO 26 → resistor → LED → GND |
| LED vermelho (lotado) | GPIO 27 → resistor → LED → GND |
| LED azul da placa | GPIO 2, já na placa: acende quando lota |

```
            ESP32 DevKit
          ┌──────────────┐
          │      GPIO 25 ├──[ 220 Ω ]──►|── verde ──┐
          │      GPIO 26 ├──[ 220 Ω ]──►|── amarelo ┤
          │      GPIO 27 ├──[ 220 Ω ]──►|── vermelho┤
          │          GND ├──────────────────────────┘
          └──────────────┘
                 ►|  = LED (lado do triângulo = perna longa, +)
```

Os pinos ficam no início do `.ino` (`PINO_VERDE`, `PINO_AMARELO`, `PINO_VERMELHO`), se precisar trocar.

---

## 3. Configurar e gravar o ESP32

### 3.1 Arduino IDE (uma vez só)

1. Instale a **Arduino IDE 2** (<https://www.arduino.cc/en/software>).
2. Em *File → Preferences → Additional boards manager URLs*, cole `https://espressif.github.io/arduino-esp32/package_esp32_index.json`.
3. Em *Tools → Board → Boards Manager*, instale **esp32 by Espressif Systems** (versão 3.x).
4. Ligue a placa. No Windows, ela aparece em *Gerenciador de Dispositivos → Portas* (no laboratório, **COM13**). Se não aparecer, instale o driver **CP210x** ou troque o cabo.

Para testar uma placa nova, grave antes o `teste_esp32/teste_esp32.ino`: o LED pisca e o Monitor Serial lista as redes Wi-Fi.

### 3.2 `segredos.h`

Copie `esp32_estacionamento/segredos.exemplo.h` para `esp32_estacionamento/segredos.h` e preencha:

```cpp
const char* WIFI_SSID    = "BDAG";
const char* WIFI_SENHA   = "...";                        // rede aberta: ""
const char* URL_API      = "https://seu-projeto.vercel.app";  // sem barra no final
const char* INGEST_TOKEN = "um-token-longo-e-aleatorio";  // igual ao da Vercel
```

- Para gerar o token: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Antes do deploy, dá para usar `URL_API = "http://IP_DO_NOTEBOOK:3000"` e testar com o painel rodando no notebook (parte 6).
- Com `URL_API = ""`, a placa funciona só na rede local: indicador e página `http://estacionamento.local/`.
- O `segredos.h` está no `.gitignore`: senha e token nunca vão para o GitHub.

### 3.3 Gravar

Na Arduino IDE, abra `esp32_estacionamento/esp32_estacionamento.ino`, escolha a placa **ESP32 Dev Module** e a porta, e clique em **Upload**. Se travar em `Connecting...`, segure o botão **BOOT** até a gravação começar.

Pela linha de comando:

```powershell
$cli = "$env:LOCALAPPDATA\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
& $cli compile --fqbn esp32:esp32:esp32 --upload -p COM13 esp32_estacionamento
```

### 3.4 Conferir

Abra o **Monitor Serial** em **115200 baud**:

```
=== ESP32 - controlador do estacionamento ===
Contagem recuperada da flash: 0 ocupadas, 100 livres (livre)
Conectando ao Wi-Fi "BDAG"...
Wi-Fi conectado. IP 10.64.69.162, sinal -62 dBm. Também responde em http://estacionamento.local
Publicando em https://seu-projeto.vercel.app
```

No navegador do notebook, `http://estacionamento.local/` mostra as vagas, e `http://estacionamento.local/estado` mostra o JSON com o estado e os LEDs.

---

## 4. Preparar o notebook e rodar a visão

### 4.1 Instalar

```bash
pip install -r requirements.txt
```

### 4.2 Celular como câmera

- **Android, IP Webcam:** em *Preferências de vídeo*, escolha resolução **640×480** e toque em **Iniciar servidor**. O vídeo fica em `http://IP_DO_CELULAR:8080/video`.
- **DroidCam:** o vídeo fica em `http://IP_DO_CELULAR:4747/video`.
- O celular, o notebook e o ESP32 precisam estar **na mesma rede**.

### 4.3 Rodar

```bash
python visao.py --fonte http://192.168.0.10:8080/video
```

O programa procura o ESP32 por `estacionamento.local`. Se o nome não resolver, use o IP que aparece no Monitor Serial:

```bash
python visao.py --fonte http://192.168.0.10:8080/video --esp32 10.64.69.162
```

| Opção | Padrão | Para que serve |
|---|---|---|
| `--fonte` | 0 | URL do vídeo do celular, índice da webcam ou arquivo de vídeo. |
| `--esp32` | estacionamento.local | Endereço do ESP32 (nome, IP ou ip:porta). |
| `--inverter` | – | Troca o sentido: B antes de A passa a ser entrada. |
| `--faixa-a` / `--faixa-b` | 0.40 / 0.60 | Posição inicial das faixas (0 = borda esquerda/topo, 1 = borda direita/base). |
| `--horizontal` | – | Faixas horizontais, para veículos que andam para cima e para baixo na imagem. |
| `--ocupacao` | 0.05 | Fração da faixa que precisa mudar para ela contar como ocupada. |
| `--porta` | 8000 | Porta da página de calibração. |
| `--sem-janela` | – | Não abre a janela do OpenCV (só a página de calibração). |

Cada movimento aparece no terminal e é confirmado pelo ESP32:

```
[14:40:36] ENTRADA (movimento 1, na fila: 1)
         ESP32 confirmou o movimento 1: 62 vagas livres
```

Se o ESP32 não responder, os movimentos esperam numa fila e são enviados quando ele voltar. O ESP32 ignora reenvios, então nada é contado duas vezes.

Na primeira vez, o **Firewall do Windows** pergunta se o Python pode usar a rede. Permita, inclusive em **redes públicas** se a rede estiver classificada assim.

---

## 5. Calibrar as faixas

A **faixa A** fica do lado da **rua** e a **faixa B** do lado de **dentro**. **A → B = entrada** e **B → A = saída**.

1. Prenda o celular acima da passagem, olhando para baixo. Ele **não pode se mexer**: o programa compara cada quadro com o fundo aprendido.
2. Abra a página de calibração que o `visao.py` mostra ao iniciar (`http://IP_DO_NOTEBOOK:8000`), no notebook ou no celular.
3. Toque em **faixa A (rua)** e depois na imagem, onde a faixa deve ficar. Repita com a **faixa B (dentro)**. Na janela do OpenCV, o botão esquerdo do mouse posiciona a A e o direito a B.
4. Se os veículos andam de cima para baixo na imagem, toque em **Girar faixas** (ou aperte **o** na janela).
5. Deixe a distância entre as faixas **menor que o comprimento do carrinho**: assim o mesmo veículo cobre A e B ao mesmo tempo em algum momento.
6. Depois de mexer na câmera ou se a luz mudar, toque em **Reaprender fundo** (ou aperte **f**).
7. Passe um carrinho entrando e confira na página: **entradas** sobe e **vagas livres** desce. Se o sentido sair trocado, rode com `--inverter`.

Teclas na janela: `q` sai, `f` reaprende o fundo, `o` gira as faixas.

---

## 6. Painel web: rodar no notebook

```bash
cd web
npm install
copy .env.example .env.local      (no Linux/macOS: cp .env.example .env.local)
```

Preencha o `web/.env.local`:

```
INGEST_TOKEN=o-mesmo-token-do-segredos.h
ADMIN_PIN=um-pin-para-corrigir-a-contagem
```

Sem as variáveis do Upstash, a API guarda tudo **na memória**: serve para testar, mas os dados somem quando o servidor reinicia. O painel avisa quando isso acontece.

```bash
npm run dev
```

O painel abre em `http://localhost:3000`, ou em `http://IP_DO_NOTEBOOK:3000` no celular. Para a placa publicar nele, use `URL_API = "http://IP_DO_NOTEBOOK:3000"` no `segredos.h`. O Windows pode pedir para liberar o Node.js no Firewall.

Para conferir o build de produção: `npm run build`.

---

## 7. Painel web: publicar na Vercel

1. **Conta e CLI:** crie a conta em <https://vercel.com> e instale a CLI: `npm i -g vercel`.
2. **Projeto:** dentro de `web/`, rode `vercel login` e depois `vercel link`. Crie um projeto novo. O diretório raiz é a própria pasta `web` (se criar pelo site, importando do GitHub, configure **Root Directory = `web`**).
3. **Banco:** no painel da Vercel, abra o projeto → **Storage** → **Create Database** → **Upstash for Redis** (Marketplace). Conecte o banco ao projeto. A integração cria as variáveis `KV_REST_API_URL` e `KV_REST_API_TOKEN` sozinha.
4. **Variáveis:** em **Settings → Environment Variables**, cadastre `INGEST_TOKEN` (o mesmo do `segredos.h`) e `ADMIN_PIN`. Pela CLI: `vercel env add INGEST_TOKEN production` e `vercel env add ADMIN_PIN production`.
5. **Deploy:** `vercel --prod`. A CLI mostra a URL, por exemplo `https://estacionamento-xyz.vercel.app`.
6. **ESP32:** coloque essa URL em `URL_API` no `segredos.h` e grave a placa de novo (parte 3.3). Em até 30 s o painel mostra **conectado**.

Teste a API publicada:

```bash
curl https://estacionamento-xyz.vercel.app/api/estado
```

Variáveis do projeto (nomes também em `web/.env.example`):

| Variável | Para que serve |
|---|---|
| `INGEST_TOKEN` | Senha do ESP32 para publicar (`Authorization: Bearer ...`). |
| `ADMIN_PIN` | PIN para corrigir a contagem pelo painel. |
| `KV_REST_API_URL`, `KV_REST_API_TOKEN` | Upstash Redis. A integração cria. `UPSTASH_REDIS_REST_URL/TOKEN` também servem. |

---

## 8. Testes sem hardware

**Visão sem câmera e sem placa:** gere um vídeo e use o ESP32 simulado.

```bash
python testes/gerar_video.py teste.mp4            # 6 entradas, 3 saídas e 1 alarme falso
python testes/esp32_simulado.py                   # em outro terminal (porta 8081)
python visao.py --fonte teste.mp4 --esp32 127.0.0.1:8081 --sem-janela
```

O simulador deve terminar com 6 entradas, 3 saídas e 3 ocupadas. A sequência do vídeo pode ser escolhida: `python testes/gerar_video.py teste.mp4 EESESEEES` (E = entrada, S = saída).

**API sem placa:** com o `npm run dev` rodando, simule uma publicação do ESP32 (no Git Bash):

```bash
curl -X POST http://localhost:3000/api/estado \
  -H "Authorization: Bearer SEU_TOKEN" -H "Content-Type: application/json" \
  -d '{"instancia":1,"seq":1,"vagas":100,"ocupadas":1,"ajuste_aplicado":0,"ip":"10.0.0.2","rssi":-60,"uptime_s":10,
       "movimentos":[{"seq":1,"tipo":"entrada","ocupadas":1,"limitado":false,"atraso_ms":0}]}'
```

Com o token errado a resposta é **401**. Repetindo o mesmo envio, `"novos"` vem 0, porque a duplicata é ignorada.

---

## 9. Referência técnica

### Como a câmera detecta o sentido

- Cada quadro é reduzido para 320 px de largura e suavizado.
- Cada faixa guarda uma imagem de fundo, que se atualiza devagar enquanto a faixa está livre.
- A faixa é comparada com o fundo **em cores**: um pixel conta como alterado se algum canal mudar mais de 25 (de 0 a 255). Se mais de 5% dos pixels mudarem (`--ocupacao`) em dois quadros seguidos, a faixa está ocupada.
- A ocupada antes de B = entrada; B antes de A = saída. Se só uma faixa for ocupada por mais de 3 s, o evento é descartado. As duas precisam ficar livres antes da próxima passagem.

### O que o ESP32 faz

- **`POST /movimento`** (do notebook), com `{"sentido": "entrada", "sessao": "a1b2", "id": 7}`. Soma ou subtrai uma vaga ocupada, sempre entre 0 e 100. Um `(sessao, id)` repetido não conta de novo.
- **`GET /estado`**: vagas, ocupadas, livres, indicador, LEDs, fila da nuvem, IP e sinal.
- **`GET /`**: página simples com o número de vagas, para quando não houver internet.
- **Flash:** ocupadas, sequência e último ajuste ficam gravados com `Preferences`. A contagem sobrevive a reset e a falta de energia.
- **Indicador:** verde abaixo de 90% de ocupação, amarelo de 90% a 99% e vermelho em 100%. O LED azul da placa acende quando lota.
- **Nuvem:**
  - publica em `URL_API/api/estado` a cada movimento e a cada 30 s (sinal de vida);
  - os movimentos ficam numa fila de até 40 e vão em lotes de até 10;
  - se a internet cair, tenta de novo a cada 5 s;
  - cada movimento tem um número de sequência, e a API ignora os que já recebeu.
- **HTTPS:** usa `WiFiClientSecure` com `setInsecure()`. A conexão é cifrada, mas o certificado da Vercel não é validado, o que é aceitável num projeto acadêmico. Para validar, troque por `setCACert()` com o certificado raiz (há um comentário no código explicando como).

### Correção manual da contagem

O painel tem o botão **Corrigir contagem**: informe quantos veículos estão no estacionamento e o PIN.

- **O ajuste viaja na resposta do sinal de vida.** A API guarda o ajuste como pendente e o devolve na resposta da próxima publicação do ESP32, em até 30 s. O ESP32 aplica, grava na flash, acende o LED certo e confirma no envio seguinte. Assim a placa continua sendo a dona da contagem, sem endpoint nem consulta extra.
- **O PIN aceita no máximo 5 erros a cada 10 minutos** por endereço.

### API (Vercel)

| Endereço | Uso |
|---|---|
| `GET /api/estado` | Estado atual, últimos 50 movimentos, entradas e saídas por hora de hoje, ajuste pendente. |
| `POST /api/estado` | Publicação do ESP32. Exige `Authorization: Bearer <INGEST_TOKEN>`. Responde `{"ok":true,"novos":2,"ajuste":null}`. |
| `POST /api/ajuste` | `{"ocupadas": 42, "pin": "..."}`. Corrige a contagem (protegido pelo `ADMIN_PIN`). |

No Redis ficam o estado atual, os últimos 50 movimentos e um contador de entradas e saídas por hora de cada dia (guardado por 8 dias). Os horários seguem o fuso de São Paulo.

---

## 10. Solução de problemas

| Sintoma | O que fazer |
|---|---|
| A placa não aparece em nenhuma porta COM | Troque o cabo (alguns só carregam) e instale o driver CP210x. |
| `estacionamento.local` não resolve | Use `--esp32 IP_DA_PLACA`, com o IP do Monitor Serial. |
| `visao.py` mostra "ESP32 sem resposta" | Confira se a placa está na mesma rede e ligada. Os movimentos esperam na fila. |
| Painel: "Aguardando o primeiro sinal do ESP32" | Confira `URL_API` e `INGEST_TOKEN` no `segredos.h` e veja o Monitor Serial. `HTTP 401` = token diferente do da Vercel. |
| Painel: "sem sinal há X min" | A placa está sem internet ou desligada. O indicador da entrada continua funcionando. |
| Painel avisa "dados só na memória" | Falta conectar o Upstash ao projeto na Vercel (parte 7, passo 3). |
| Contagem errada | Use **Corrigir contagem** no painel e revise a calibração (parte 5). |
| Sentido trocado | Rode o `visao.py` com `--inverter`. |
| Câmera conta carros que não passaram | Fixe melhor o celular, toque em **Reaprender fundo** e aumente `--ocupacao`. |
| Carrinhos pequenos não são detectados | Diminua `--ocupacao` (por exemplo 0.03). |
| ESP32 não conecta no Wi-Fi | Ele só usa redes de **2,4 GHz**. Redes com login por página web não funcionam. |

---

## 11. Limitações

- **Entrada e saída pela mesma passagem:** dois veículos se cruzando ao mesmo tempo, ou um colado no outro, podem ser contados como um só ou descartados.
- **Veículos lado a lado** ocupam as faixas juntos, e a ordem A/B fica ambígua (o evento é descartado).
- **Mudança de luz**, sombras em movimento e câmera tremendo geram contagens falsas.
- **A contagem depende da calibração.** Os erros se acumulam com o tempo, então a **correção manual** faz parte da operação (por exemplo, conferir no início do dia).
- **O notebook precisa ficar ligado** para a câmera contar. Sem ele, o ESP32 mantém o último número e o indicador continua aceso, mas não vê novos movimentos.
- **Sem internet**, o painel na Vercel fica desatualizado e avisa "sem sinal". O indicador da entrada e a página `http://estacionamento.local/` continuam funcionando na rede local.
- **Fila do ESP32 em RAM:** se a placa reiniciar sem internet, os movimentos ainda não publicados somem do histórico do painel, mas a contagem fica certa (está na flash).
