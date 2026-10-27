# Contador de veículos IoT

Projeto da FATEC Pompeia (Big Data no Agronegócio). Dois métodos contam os veículos ao mesmo tempo e mandam os dados pelo Wi-Fi para um notebook:

- **Câmera do celular:** o celular transmite o vídeo. O notebook conta os veículos que cruzam duas faixas virtuais, **A** e **B**, e descobre o sentido. A antes de B é **ida**, B antes de A é **volta**.
- **Nó ESP32:** duas barreiras infravermelhas reais (faixas A e B) detectam a passagem e o sentido. Um sensor ultrassônico acima da pista mede a altura do veículo para classificá-lo em **leve** ou **pesado**.

O notebook roda `contador_veiculos.py`, que junta tudo num painel web e num único CSV. O painel abre no navegador de qualquer celular da mesma rede, e assim dá para comparar a precisão dos dois métodos.

```
[Celular com IP Webcam] ──vídeo──►┐
                                  ├─► [Notebook: contador_veiculos.py] ──► painel web (celular ou PC)
[ESP32 + IR + ultrassom] ──HTTP──►┘                                    └─► contagens.csv
```

Este guia vai do zero ao sistema funcionando: compra das peças, montagem dos sensores, gravação da placa, configuração do celular e uso do painel. Siga as partes na ordem. Cada uma termina com um **teste** que confirma que a etapa deu certo antes de passar para a próxima.

## Sumário

0. [Lista de materiais](#0-lista-de-materiais)
1. [Preparar o notebook](#1-preparar-o-notebook)
2. [Preparar a Arduino IDE e testar a placa](#2-preparar-a-arduino-ide-e-testar-a-placa)
3. [Montar os sensores](#3-montar-os-sensores)
4. [Configurar e gravar o programa do ESP32](#4-configurar-e-gravar-o-programa-do-esp32)
5. [Montar a maquete](#5-montar-a-maquete)
6. [Transformar o celular em câmera](#6-transformar-o-celular-em-câmera)
7. [Preparar a rede](#7-preparar-a-rede)
8. [Rodar o contador](#8-rodar-o-contador)
9. [Abrir o painel no celular](#9-abrir-o-painel-no-celular)
10. [Testar a precisão e analisar os dados](#10-testar-a-precisão-e-analisar-os-dados)
11. [Referência técnica](#11-referência-técnica)
12. [Solução de problemas](#12-solução-de-problemas)
13. [Limitações](#13-limitações)

---

## 0. Lista de materiais

### Eletrônica (nó ESP32)

| Item | Qtd. | Observação |
|---|---|---|
| Placa **ESP32 DevKit** (ESP32-WROOM-32, 30 ou 38 pinos) | 1 | Tem Wi-Fi embutido. Qualquer DevKit com GPIO 5, 18, 32 e 33 serve. |
| **Módulo sensor infravermelho de 2 canais** (comparador LM393, saídas OUT1 e OUT2) | 1 | Também servem dois módulos de 1 canal (tipo FC-51), um para cada faixa. |
| **Sensor ultrassônico HC-SR04** | 1 | Mede a altura do veículo. |
| Resistor de **1 kΩ** | 1 | Divisor de tensão do ECHO. |
| Resistor de **2 kΩ** (ou dois de 1 kΩ em série) | 1 | Divisor de tensão do ECHO. |
| Protoboard | 1 | 400 ou 830 furos. |
| Jumpers macho-macho e macho-fêmea | ~15 | |
| Cabo **USB de dados** compatível com a placa (micro-USB ou USB-C) | 1 | Cabo só de carga não grava a placa. |

### Câmera, rede e notebook

| Item | Qtd. | Observação |
|---|---|---|
| Celular Android ou iPhone | 1 | Vira câmera IP pelo app **IP Webcam** ou **DroidCam**. |
| Notebook com Wi-Fi | 1 | Windows, Linux ou macOS, com Python 3.10 ou mais recente. |
| Rede Wi-Fi **sem login por página web** ou hotspot do celular | 1 | O ESP32 não consegue fazer login em portal. |
| Segundo celular (opcional) | 1 | Para ver o painel enquanto o primeiro filma. |

### Bancada e maquete

| Item | Observação |
|---|---|
| Suporte articulado ou mini tripé com garra | Mantém o celular fixo, olhando a pista de cima. |
| Suporte para o HC-SR04 (papelão, palito, impressão 3D) | Deixa o sensor acima da pista, apontado para baixo. |
| Carrinhos de brinquedo de tamanhos e cores variados | 3 a 4. Inclua pelo menos um mais alto, para testar "pesado". |
| Papelão, papel e fita | Para a pista. |
| Power bank ou extensão | A transmissão de vídeo gasta muita bateria do celular. |

### Programas (todos gratuitos)

- Python 3 com as bibliotecas OpenCV e NumPy (o `pip` instala).
- Arduino IDE 2 com o pacote de placas ESP32 da Espressif.
- Git (opcional, para baixar o projeto).
- No celular: IP Webcam (Android) ou DroidCam (Android/iOS).
- Excel, LibreOffice Calc ou Google Planilhas, para analisar o CSV.

---

## 1. Preparar o notebook

### 1.1 Instalar o Python

1. Baixe o Python 3.12 em <https://www.python.org/downloads/>. No Windows também dá para instalar pela Microsoft Store.
2. No instalador do site, **marque "Add python.exe to PATH"** antes de clicar em *Install Now*.
3. Abra um terminal novo (PowerShell no Windows) e confira:

   ```bash
   python --version
   ```

   Deve aparecer `Python 3.10` ou mais recente.

### 1.2 Baixar o projeto

O repositório é privado. Peça acesso ao dono do repositório no GitHub e depois rode:

```bash
git clone https://github.com/mateus-robers-amaral/contador-veiculos-iot.git
cd contador-veiculos-iot
```

Sem Git, use *Code → Download ZIP* na página do repositório e extraia a pasta.

### 1.3 Instalar as bibliotecas

Dentro da pasta do projeto:

```bash
pip install -r requirements.txt
```

Isso instala o OpenCV e o NumPy. O painel web usa só a biblioteca padrão do Python, sem Flask nem outras dependências.

> **Teste da parte 1:** rode `python -c "import cv2, numpy; print(cv2.__version__)"`. Se aparecer um número de versão, está tudo certo.

### O que tem na pasta

```
contador-veiculos-iot/
├── contador_veiculos.py        programa do notebook (visão computacional + servidor do painel)
├── requirements.txt            bibliotecas Python
├── painel/                     página do painel web
│   ├── index.html
│   ├── painel.css
│   ├── painel.js
│   └── fontes/                 fontes Geist servidas localmente (licença OFL)
├── no_sensores_esp32/          programa da placa ESP32 com os sensores
│   ├── no_sensores_esp32.ino
│   └── segredos.exemplo.h      modelo para o nome e a senha do Wi-Fi
└── teste_esp32/
    └── teste_esp32.ino         teste rápido da placa (LED + busca de redes)
```

---

## 2. Preparar a Arduino IDE e testar a placa

### 2.1 Instalar a IDE e o suporte ao ESP32

1. Baixe a **Arduino IDE 2** em <https://www.arduino.cc/en/software> e instale.
2. Abra *File → Preferences* (*Arquivo → Preferências*). Em **Additional boards manager URLs**, cole:

   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```

3. Abra *Tools → Board → Boards Manager*, procure **esp32** e instale **"esp32 by Espressif Systems"**. O download é grande e pode demorar alguns minutos.

### 2.2 Conectar a placa

1. Ligue o ESP32 ao notebook com o cabo USB de **dados**.
2. No Windows, abra o *Gerenciador de Dispositivos → Portas (COM e LPT)*. Deve aparecer algo como `Silicon Labs CP210x (COM13)` ou `USB-SERIAL CH340 (COM5)`.
3. Se não aparecer nenhuma porta:
   - troque o cabo, porque muitos cabos só carregam;
   - instale o driver do chip da sua placa: **CP210x** (Silicon Labs) ou **CH340** (WCH). O nome do chip vem impresso perto do conector USB.

### 2.3 Gravar o programa de teste

1. Na Arduino IDE, abra `teste_esp32/teste_esp32.ino`.
2. Em *Tools → Board*, escolha **ESP32 Dev Module**. Em *Tools → Port*, escolha a porta COM do passo anterior.
3. Clique em **Upload** (a seta).
4. Se a gravação parar em `Connecting.....` e falhar, segure o botão **BOOT** da placa quando aparecer `Connecting` e solte quando a porcentagem começar a subir.
5. Abra o **Serial Monitor** (lupa no canto superior direito) em **115200 baud**.

> **Teste da parte 2:** o LED azul da placa pisca a cada meio segundo. O Monitor Serial mostra o modelo do chip e a **lista das redes Wi-Fi** próximas. Confira se a rede que você vai usar aparece na lista, com sinal melhor que −80 dBm.

Pela linha de comando, a gravação equivalente é:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 --upload -p COM13 teste_esp32
```

---

## 3. Montar os sensores

> **Desconecte o cabo USB antes de mexer nas ligações.**

### 3.1 Esquema de ligação

| Sensor / pino | Ligação no ESP32 |
|---|---|
| IR – VCC | 3V3 |
| IR – GND | GND |
| IR – OUT1 (faixa A) | GPIO 32 |
| IR – OUT2 (faixa B) | GPIO 33 |
| HC-SR04 – VCC | VIN (5 V) |
| HC-SR04 – GND | GND |
| HC-SR04 – TRIG | GPIO 5 |
| HC-SR04 – ECHO | resistor de **1 kΩ** até o GPIO 18, e do GPIO 18 um resistor de **2 kΩ** até o GND |

```
                     ESP32 DevKit
                   ┌──────────────┐
  IR VCC ──────────┤ 3V3          │
  IR GND ──────────┤ GND          │
  IR OUT1 (A) ─────┤ GPIO 32      │
  IR OUT2 (B) ─────┤ GPIO 33      │
                   │              │
  HC-SR04 VCC ─────┤ VIN (5 V)    │
  HC-SR04 GND ─────┤ GND          │
  HC-SR04 TRIG ────┤ GPIO 5       │
                   │      GPIO 18 ├────┬───── 1 kΩ ───── HC-SR04 ECHO
                   │              │    │
                   │              │   2 kΩ
                   │          GND ├────┘
                   └──────────────┘
```

> **Atenção:** nunca ligue o ECHO direto na ESP32. Ele sai com 5 V, e a ESP32 só aguenta 3,3 V. O divisor de 1 kΩ + 2 kΩ reduz o sinal para cerca de 3,3 V (5 V × 2 / 3).

### 3.2 Passo a passo na protoboard

1. Encaixe o ESP32 **atravessando o canal do meio** da protoboard, com uma fileira de pinos de cada lado. Se a placa for larga demais, use duas protoboards lado a lado ou jumpers macho-fêmea direto nos pinos.
2. Ligue um pino **GND** do ESP32 ao barramento azul (−) da protoboard. Todos os GND vão para esse barramento.
3. **Módulo IR:**
   - VCC no **3V3** (não no 5 V: assim a saída fica em 3,3 V, segura para a ESP32);
   - GND no barramento GND;
   - OUT1 no **GPIO 32** e OUT2 no **GPIO 33**.
4. **HC-SR04:**
   - VCC no **VIN**, que tem 5 V quando a placa está no USB;
   - GND no barramento GND;
   - TRIG no **GPIO 5**;
   - ECHO numa fileira livre da protoboard. Dessa fileira sai o resistor de **1 kΩ** até a fileira do **GPIO 18**. Da fileira do GPIO 18 sai o resistor de **2 kΩ** até o barramento GND.
5. Confira cada fio com a tabela antes de religar o USB.

Os pinos ficam no topo do `no_sensores_esp32.ino` (`PINO_IR_A`, `PINO_IR_B`, `PINO_TRIG`, `PINO_ECHO`), caso precise trocar algum.

### 3.3 Ajustar os sensores infravermelhos

Cada canal do módulo IR tem um **trimpot azul** (parafusinho) que ajusta o alcance.

1. Ligue o USB. O LED de alimentação do módulo acende.
2. Coloque um carrinho a cerca de 3 a 5 cm do sensor. Gire o trimpot até o **LED do canal acender**.
3. Tire o carrinho. O LED precisa **apagar**. Se continuar aceso, gire o trimpot no sentido contrário, aos poucos.
4. Repita para o outro canal.

> **Teste da parte 3:** com o carrinho na frente, o LED do canal acende; com a pista vazia, apaga. Se o seu módulo funcionar ao contrário, troque `IR_ATIVO` para `HIGH` no `.ino` (veja a parte 4).

---

## 4. Configurar e gravar o programa do ESP32

### 4.1 Nome e senha do Wi-Fi

1. Na pasta `no_sensores_esp32/`, copie `segredos.exemplo.h` para **`segredos.h`**.
2. Preencha o nome e a senha da rede:

   ```cpp
   const char* WIFI_SSID  = "NOME_DA_REDE";
   const char* WIFI_SENHA = "SENHA_DA_REDE";
   ```

   Numa rede aberta, sem senha, deixe `WIFI_SENHA = ""`.

O `segredos.h` está no `.gitignore`, então a senha nunca vai para o GitHub.

### 4.2 Endereço do notebook

O ESP32 manda as passagens para o notebook, então precisa saber o endereço dele. Descubra o IP do notebook (veja a [parte 7](#7-preparar-a-rede)) e coloque no início do `.ino`:

```cpp
const char* URL_NOTEBOOK = "http://10.64.69.164:8000";
```

O `contador_veiculos.py` também mostra essa linha pronta ao iniciar. **Sempre que o notebook mudar de rede, o IP muda e a placa precisa ser gravada de novo.**

### 4.3 Ajustes

| Constante | Padrão | Para que serve |
|---|---|---|
| `ALTURA_PESADO_CM` | 6.0 | Altura a partir da qual o veículo é "pesado". Ajuste aos seus carrinhos. |
| `IR_ATIVO` | `LOW` | Troque para `HIGH` se o módulo IR indicar "ocupado" ao contrário. |
| `TEMPO_MAX_TRAVESSIA_MS` | 2000 | Tempo máximo entre a primeira e a segunda faixa. |
| `TEMPO_LIVRE_MS` | 150 | Tempo com as duas faixas livres para encerrar a passagem. |
| `CARENCIA_MS` | 300 | Tempo em que novas detecções são ignoradas logo após uma passagem. |

### 4.4 Gravar

Abra `no_sensores_esp32/no_sensores_esp32.ino`, confira placa e porta e clique em **Upload**. Pela linha de comando:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 --upload -p COM13 no_sensores_esp32
```

> **Ao ligar, a pista precisa estar vazia.** A placa mede a distância até o chão nesse momento, e essa medida é a referência para calcular a altura dos veículos.

> **Teste da parte 4:** no Monitor Serial (115200 baud) aparece:
>
> ```
> === Nó ESP32 - contador de veículos ===
> Ultrassom: chão a 25.0 cm
> Conectando ao Wi-Fi "BDAG"...
> Wi-Fi conectado. IP 10.64.69.162, sinal -66 dBm. Enviando para http://10.64.69.164:8000
> ```
>
> Passe um carrinho pelas duas faixas. Deve aparecer uma linha como `Passagem: ida (A->B) | altura 4.2 cm (leve) | na fila: 1`. Se aparecer `Ultrassom: sem leitura`, revise as ligações do HC-SR04 e o divisor de tensão.

---

## 5. Montar a maquete

```
            visto de cima                                 visto de lado

        faixa A     faixa B                                 HC-SR04
          │           │                                       ▼▼
  ════════╪═══════════╪════════  ◄── pista              ──────┬┬──────  suporte
   ida ──►│  [carro]  │                                       ││
          │           │◄── volta                              ││ ~25 cm
  ════════╪═══════════╪════════                         ══════╧╧══════  pista
         [IR1]       [IR2]     ◄── módulo IR na lateral
```

1. Faça uma pista reta de papelão com pelo menos 40 cm de comprimento.
2. **Módulo IR:** na lateral da pista, com os dois pares apontados para a via. O canal 1 é a faixa A e o canal 2 é a faixa B. Na ida, o carro passa primeiro pelo canal 1.
3. **Distância entre as faixas:** menor que o comprimento do menor carrinho. Assim o mesmo veículo cobre A e B ao mesmo tempo em algum momento, e a ordem fica clara.
4. **HC-SR04:** num suporte acima da pista, apontado para baixo, **entre as duas faixas**. Entre 15 e 30 cm de altura funciona bem.
5. **Celular:** preso num suporte acima da pista, olhando para baixo, com as duas faixas do ESP32 no meio da imagem. **Ele não pode se mexer**, porque o programa compara cada quadro com o fundo aprendido.
6. Evite sombras fixas sobre a pista e luz do sol batendo direto. Os sensores IR também sofrem com sol forte.

---

## 6. Transformar o celular em câmera

### Android: IP Webcam (recomendado)

1. Instale o **IP Webcam** (de Pavel Khlebovich) pela Play Store.
2. Ajustes recomendados, antes de iniciar:
   - **Preferências de vídeo → Resolução do vídeo:** 640×480. O programa reduz a imagem para 320 px de largura, então resolução maior só gasta Wi-Fi e bateria.
   - **Qualidade:** em torno de 50%.
   - **Orientação:** paisagem, se o celular estiver deitado.
   - Deixe a opção de **manter a tela ligada** ativada e o celular no carregador.
3. Role até o fim e toque em **Iniciar servidor**.
4. A tela mostra o endereço, por exemplo `http://192.168.0.10:8080`. **O vídeo fica em `http://192.168.0.10:8080/video`.**

### iPhone ou Android: DroidCam

Instale o **DroidCam** e abra o app. Ele mostra o IP do celular. O vídeo fica em `http://IP_DO_CELULAR:4747/video`.

> **Teste da parte 6:** com o notebook na mesma rede, abra o endereço do vídeo (com `/video`) no navegador do notebook. A imagem ao vivo deve aparecer.

> **Um celular só?** O mesmo aparelho pode filmar e abrir o painel, mas o Android pode pausar o IP Webcam quando você troca para o navegador. O mais seguro é ver o painel no notebook ou num segundo celular.

---

## 7. Preparar a rede

O celular, o notebook e o ESP32 precisam estar **na mesma rede Wi-Fi**. Não precisa de internet.

### Qual rede usar

- **Rede sem senha ou com senha comum (WPA2), sem página de login:** funciona. No laboratório, a rede **BDAG** atende.
- **Rede com login por página web** (comum em faculdades): **não funciona**. O ESP32 não consegue fazer o login.
- **Rede que isola os aparelhos:** o celular não enxerga o notebook. Use outra rede.
- **Plano B:** o roteador do celular (hotspot). Conecte o notebook e o ESP32 a ele. Se o mesmo celular for a câmera, o IP Webcam continua funcionando normalmente.

### Descobrir o IP do notebook

O `contador_veiculos.py` mostra o IP ao iniciar. Para conferir à mão, no Windows:

```powershell
ipconfig
```

Use o **Endereço IPv4** do adaptador **Wi-Fi**, não os de "vEthernet" ou "Ethernet" de máquinas virtuais.

### Liberar o Firewall do Windows

Na primeira vez que o programa rodar, o Windows pergunta se o Python pode usar a rede. **Permita.** Sem isso, nem o celular nem o ESP32 conseguem falar com o notebook.

Se o celular não abrir o painel, veja como a rede está classificada em *Configurações → Rede e Internet → Wi-Fi → (nome da rede)*:
- **Rede privada:** a permissão de redes privadas basta.
- **Rede pública:** o Python precisa estar permitido também em redes públicas. Em *Firewall do Windows Defender → Permitir um aplicativo*, marque a coluna **Pública** do Python.

---

## 8. Rodar o contador

### 8.1 Primeiro, só com o ESP32

```bash
python contador_veiculos.py --sem-camera
```

O terminal mostra:

```
Painel web: http://10.64.69.164:8000  (abra no celular ou no notebook)
No nó ESP32, configure URL_NOTEBOOK = "http://10.64.69.164:8000"
Modo sem câmera: aguardando o nó ESP32. Ctrl+C para sair.
```

Ligue o ESP32. A cada passagem, o terminal mostra uma linha como `[2026-10-27T14:40:36] esp32: sentido ida, leve 3.2 cm`.

### 8.2 Depois, com a câmera

Encerre com **Ctrl+C** e rode com o endereço do vídeo do celular:

```bash
python contador_veiculos.py --fonte http://192.168.0.10:8080/video
```

- Uma janela abre com a imagem e as faixas. A faixa fica **verde** quando está livre e **vermelha** quando está ocupada.
- As faixas são **verticais** por padrão, para veículos que andam da esquerda para a direita na imagem. Se andarem de cima para baixo, use `--horizontal` ou aperte **o** na janela.
- Clique com o botão **esquerdo** onde quer a faixa A e com o **direito** onde quer a faixa B. Alinhe com as faixas do ESP32 para comparar os dois métodos.
- Deixe a distância entre as faixas **menor que o comprimento do carrinho**.

Também é possível usar a webcam do notebook (`--fonte 0`) ou um vídeo gravado (`--fonte teste.mp4`). O vídeo gravado é útil para repetir o mesmo teste e medir a precisão.

### Teclas na janela

| Tecla | Ação |
|---|---|
| `q` | sair |
| `r` | zerar a contagem das duas fontes |
| `f` | reaprender o fundo (use depois de mudar a luz ou mexer a câmera) |
| `o` | alternar faixas verticais/horizontais |

### Opções

| Opção | Padrão | Quando mudar |
|---|---|---|
| `--fonte` | 0 | URL do vídeo do celular, índice da webcam ou arquivo de vídeo. |
| `--sem-camera` | – | Não usa câmera: só recebe o nó ESP32. Útil para testar os sensores. |
| `--sem-janela` | – | Roda só com o painel web, sem janela. |
| `--ocupacao` | 0.05 | Fração da faixa que precisa mudar para contar como ocupada. Aumente se houver contagens falsas e diminua se carros pequenos não forem detectados. |
| `--faixa-a` / `--faixa-b` | 0.40 / 0.60 | Posição inicial das faixas (0 = borda esquerda/topo, 1 = borda direita/base). |
| `--horizontal` | – | Faixas horizontais, para veículos que se movem para cima e para baixo na imagem. |
| `--porta` | 8000 | Porta do painel web. Se mudar, ajuste também o `URL_NOTEBOOK` do ESP32. |
| `--csv` | contagens.csv | Arquivo de registro. |

---

## 9. Abrir o painel no celular

1. Conecte o celular à **mesma rede** do notebook (não ao 4G).
2. No navegador, digite o endereço que o terminal mostrou, **com `http://` e `:8000`**. Por exemplo: `http://10.64.69.164:8000`.
3. Dica: no Chrome, use *menu → Adicionar à tela inicial* para abrir o painel como um app.

O painel atualiza duas vezes por segundo e mostra:

- **Frase-resumo:** total, sentidos e diferença entre câmera e ESP32. Fica em vermelho quando o ESP32 está desconectado.
- **Câmera do celular:** imagem ao vivo, estado das faixas A e B, total, ida, volta e a proporção ida × volta. Com `--sem-camera`, mostra como ligar a câmera.
- **Nó ESP32:** conexão e IP, sinal Wi-Fi, distância do ultrassom em relação ao chão, faixas, total, sentidos e leves × pesados. Mostra um aviso amarelo quando há passagens na fila esperando envio.
- **Comparação:** câmera × ESP32 por sentido e um gráfico de passagens por hora das últimas 12 horas (inclui o histórico do CSV).
- **Últimas passagens** das duas fontes, com a mais nova no topo e um destaque rápido na linha nova.
- Botão **Baixar CSV**.

Se aparecer o aviso vermelho **"Sem conexão com o notebook"**, o celular perdeu o notebook (Wi-Fi caiu ou o programa foi encerrado). O aviso some sozinho quando a conexão volta.

A página fica na pasta `painel/`, e as fontes são servidas pelo próprio notebook. Nada é carregado da internet, então o painel funciona numa rede sem acesso externo.

---

## 10. Testar a precisão e analisar os dados

### Roteiro de teste

1. Ligue tudo e confirme no painel: câmera com imagem, ESP32 **conectado** e faixas **livres**.
2. Aperte **r** na janela para zerar as contagens.
3. **Grave um vídeo** do teste com outro celular, para conferir depois quantas vezes precisar.
4. Passe **20 carrinhos**, misturando sentidos e tamanhos, e anote numa folha a contagem manual (sentido de cada um).
5. Compare a contagem manual com a câmera e com o ESP32 na folha **Comparação** do painel.
6. Calcule a precisão de cada método: `acertos ÷ total manual × 100`.
7. Repita mudando uma coisa por vez: velocidade, iluminação, distância entre faixas, `--ocupacao`, `ALTURA_PESADO_CM`.

### O arquivo CSV

Cada passagem vira uma linha em `contagens.csv`, com as colunas:

| Coluna | Exemplo | Significado |
|---|---|---|
| `data_hora` | `2026-10-27T14:40:36` | Data e hora no relógio do notebook. Nas passagens do ESP32, desconta o tempo que o evento esperou na fila. |
| `fonte` | `camera` ou `esp32` | Quem contou. |
| `sentido` | `ida` ou `volta` | A→B é ida; B→A é volta. |
| `altura_cm` | `3.2` | Só no ESP32: altura medida pelo ultrassom. |
| `categoria` | `leve` ou `pesado` | Só no ESP32: classificação pela altura. |

No Excel ou no Google Planilhas, use **Dados → Texto para colunas** (separador vírgula) se tudo cair numa coluna só. Com uma **tabela dinâmica** dá para montar contagem por hora, por sentido, por fonte e por categoria.

---

## 11. Referência técnica

### Como a câmera conta

1. Cada quadro é reduzido para 320 px de largura e suavizado para diminuir o ruído.
2. Cada faixa guarda uma imagem de referência (fundo), atualizada devagar enquanto está livre, para acompanhar mudanças de luz.
3. A faixa é comparada com o fundo **em cores**. Um pixel é considerado alterado se algum canal mudar mais de 25 (numa escala de 0 a 255). Em tons de cinza, um carro vermelho sobre asfalto cinza pode ter o mesmo brilho do fundo e passar despercebido.
4. Se mais de 5% dos pixels mudarem (`--ocupacao`) em dois quadros seguidos, a faixa é considerada ocupada.
5. A ocupada antes de B conta **ida**; B antes de A conta **volta**. Se só uma faixa for ocupada por mais de 3 s, o evento é descartado.
6. O sistema espera as duas faixas ficarem livres antes de aceitar a próxima passagem.

### Como o ESP32 conta

- O instante em que cada faixa é ocupada é marcado por interrupção. Assim a ordem A/B não se perde, mesmo enquanto a placa mede o ultrassom.
- Durante a passagem, o ultrassom guarda a menor distância medida. A altura do veículo é a distância até o chão menos essa menor distância.
- A passagem termina quando as duas faixas ficam livres. Se só uma faixa foi acionada, o evento é descartado.
- As passagens vão para uma fila e só saem dela quando o notebook confirma o recebimento. Se o Wi-Fi cair, nada se perde, e o notebook ignora reenvios duplicados (pelo par `boot` + `seq`).
- A cada 2 s a placa envia um sinal de vida com o estado dos sensores. É ele que aparece no painel. Sem sinal de vida por 10 s, o painel mostra "desconectado".

### Endereços do servidor

| Endereço | Uso |
|---|---|
| `GET /` | painel web |
| `GET /dados` | JSON com as contagens das duas fontes, as últimas passagens e `por_hora` |
| `GET /quadro.jpg` | imagem atual da câmera com as faixas desenhadas (503 sem câmera) |
| `GET /contagens.csv` | registro completo |
| `GET /painel/...` | estilo, script e fontes do painel |
| `POST /evento` | passagem enviada pelo ESP32 |
| `POST /status` | sinal de vida do ESP32 |

Exemplo de `GET /dados`:

```json
{
  "camera": {"total": 12, "ida": 7, "volta": 5, "faixa_a": false, "faixa_b": false},
  "esp32": {"online": true, "total": 11, "ida": 7, "volta": 4, "leves": 9, "pesados": 2,
            "status": {"ip": "10.64.69.162", "rssi": -66, "faixa_a": false, "faixa_b": false,
                       "distancia_cm": 24.8, "referencia_cm": 25.0, "pendentes": 0}},
  "ultimos": [{"data_hora": "2026-10-27T14:40:36", "fonte": "esp32", "sentido": "ida",
               "altura_cm": 3.2, "categoria": "leve", "id": 22}],
  "por_hora": [{"hora": "2026-10-27T14", "camera": 12, "esp32": 11}]
}
```

`camera` vale `null` com `--sem-camera`, e `esp32.status` vem vazio quando o ESP32 está desconectado.

### Testar o servidor sem a placa

Dá para simular uma passagem do ESP32 com `curl` (no Git Bash, Linux ou macOS):

```bash
curl -X POST http://localhost:8000/evento -H "Content-Type: application/json" \
     -d '{"boot":1,"seq":1,"sentido":"ida","altura_cm":3.2,"categoria":"leve"}'
```

A resposta é `{"ok": true, "novo": true}`. Repetindo o mesmo `seq`, a resposta passa a ser `"novo": false`, porque o reenvio é ignorado.

---

## 12. Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| A placa não aparece em nenhuma porta COM | Cabo só de carga ou falta de driver | Troque o cabo; instale o driver CP210x ou CH340. |
| Gravação para em `Connecting.....` | Placa não entrou em modo de gravação | Segure **BOOT** durante o `Connecting` e solte quando começar a gravar. |
| `Ultrassom: sem leitura` | Ligação do HC-SR04 ou do divisor | Confira VCC no VIN, TRIG no 5 e ECHO → 1 kΩ → 18 → 2 kΩ → GND. |
| Altura sempre perto de 0 | A placa ligou com algo na pista | Esvazie a pista e aperte **EN/RST** para recalibrar o chão. |
| Faixa IR sempre ocupada | Trimpot sensível demais ou lógica invertida | Ajuste o trimpot; se precisar, troque `IR_ATIVO`. |
| Passagens descartadas ("só uma faixa") | Faixas distantes ou carro rápido demais | Aproxime os sensores ou aumente `TEMPO_MAX_TRAVESSIA_MS`. |
| ESP32 não conecta no Wi-Fi | Senha errada, rede de 5 GHz ou portal de login | O ESP32 só usa **2,4 GHz**. Confira o `segredos.h`. Redes com login por página não funcionam. |
| ESP32 conecta, mas o painel mostra "desconectado" | `URL_NOTEBOOK` errado ou Firewall | Use o IP que o programa mostra; libere o Python no Firewall. |
| O celular não abre o painel | Rede diferente, `https` ou Firewall | Mesma rede, `http://` com `:8000`, Python liberado no perfil da rede (pública ou privada). |
| Abria antes e agora não abre | O IP do notebook mudou | Veja o novo IP no terminal; regrave o ESP32 com o novo `URL_NOTEBOOK`. |
| "Sem imagem da câmera" | IP Webcam fechado ou endereço errado | Abra o app; o endereço do `--fonte` termina em `/video`. |
| Câmera conta carros que não passaram | Sombra, luz mudando ou celular tremendo | Fixe melhor o celular, aperte **f** para reaprender o fundo, aumente `--ocupacao`. |
| Câmera não detecta carrinhos pequenos | Faixa larga demais para o objeto | Diminua `--ocupacao` (por exemplo 0.03). |
| Aviso amarelo "passagens na fila" | O ESP32 contou, mas ainda não conseguiu enviar | Aguarde; elas chegam quando a conexão normalizar. |

---

## 13. Limitações

- A câmera não distingue tipos de veículo. O ESP32 só separa leve e pesado pela altura.
- Veículos colados um no outro podem ser contados como um só.
- Mudanças bruscas de luz, sombras em movimento e câmera tremendo geram contagens falsas na câmera.
- Os sensores IR têm alcance de até cerca de 30 cm, então o nó ESP32 é para maquete.
- O sistema depende de Wi-Fi estável. A câmera reconecta sozinha, e o ESP32 guarda as passagens até conseguir enviar.
- Redes com login por página web (comum em faculdades) não funcionam com o ESP32. Use uma rede aberta, como a BDAG, ou o hotspot do celular.
