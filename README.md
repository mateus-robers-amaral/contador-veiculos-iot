# Contador de veículos IoT

Dois nós contam os veículos ao mesmo tempo e enviam os dados pelo Wi-Fi para o notebook:

- **Câmera do celular:** o celular transmite o vídeo. O notebook conta os veículos que cruzam as faixas virtuais **A** e **B** e identifica o sentido: A antes de B é **ida**, B antes de A é **volta**.
- **Nó ESP32:** duas barreiras infravermelhas reais (faixas A e B) detectam a passagem e o sentido. Um sensor ultrassônico acima da pista mede a altura do veículo para classificá-lo em **leve** ou **pesado**.

O notebook roda `contador_veiculos.py`, que junta tudo num painel web e num único CSV. Assim dá para comparar a precisão dos dois métodos.

```
[Celular / câmera IP] ---vídeo---> [Notebook: Python + OpenCV] ---> [Painel web no celular/PC]
[ESP32 + IR + ultrassom] --HTTP--> [  servidor do painel     ] ---> contagens.csv
```

## 1. Preparar o notebook

Instale o Python 3.10 ou mais recente e, na pasta do projeto, rode:

```bash
pip install -r requirements.txt
```

## 2. Preparar o celular

**Android:** instale o app **IP Webcam** (Pavel Khlebovich) e toque em *Iniciar servidor*. O app mostra um endereço como `http://192.168.0.10:8080`, e o vídeo fica em `http://192.168.0.10:8080/video`.
- Em *Preferências de vídeo*, use resolução baixa (640×480 já basta).

**iPhone ou Android:** o app **DroidCam** também funciona. O vídeo fica em `http://IP_DO_CELULAR:4747/video`.

O celular e o notebook precisam estar **na mesma rede Wi-Fi**. Redes de faculdade às vezes bloqueiam a comunicação entre aparelhos. Nesse caso, use o roteador do celular (hotspot) e conecte o notebook a ele.

## 3. Rodar

```bash
python contador_veiculos.py --fonte http://192.168.0.10:8080/video
```

- Uma janela abre com a imagem e as faixas. A faixa fica **verde** quando está livre e **vermelha** quando está ocupada.
- O terminal mostra o endereço do painel, por exemplo `http://192.168.0.5:8000`. Abra esse endereço no navegador do celular ou de outro computador.
- Cada passagem é gravada em `contagens.csv`. O CSV também pode ser baixado pelo painel.

### Posicionar a câmera e as faixas

- Prenda o celular **acima da pista, olhando para baixo**. Ele não pode se mexer, porque o sistema compara cada quadro com o fundo aprendido.
- As faixas são **verticais** por padrão, para veículos que andam da esquerda para a direita na imagem. Se andarem de cima para baixo, use `--horizontal` ou aperte **o** na janela.
- Clique com o botão **esquerdo** onde quer a faixa A e com o **direito** onde quer a faixa B.
- Deixe a distância entre as faixas **menor que o comprimento do carrinho** e evite sombras fixas sobre elas.

### Teclas na janela

| Tecla | Ação |
|---|---|
| `q` | sair |
| `r` | zerar a contagem |
| `f` | reaprender o fundo (use depois de mudar a luz ou mexer a câmera) |
| `o` | alternar faixas verticais/horizontais |

### Ajustes

| Opção | Padrão | Quando mudar |
|---|---|---|
| `--ocupacao` | 0.05 | Fração da faixa que precisa mudar para contar como ocupada. Aumente se houver contagens falsas e diminua se carros pequenos não forem detectados. |
| `--faixa-a` / `--faixa-b` | 0.40 / 0.60 | Posição inicial das faixas (0 = borda esquerda/topo, 1 = borda direita/base). |
| `--porta` | 8000 | Porta do painel web. |
| `--csv` | contagens.csv | Arquivo de registro. |
| `--sem-janela` | – | Roda só com o painel web, sem janela. |
| `--sem-camera` | – | Não usa câmera: só recebe o nó ESP32. Útil para testar os sensores. |

Também é possível testar com a webcam do notebook (`--fonte 0`) ou com um vídeo gravado (`--fonte teste.mp4`). O vídeo gravado é útil para repetir o mesmo teste e medir a precisão.

## 4. Nó ESP32 (sensores)

O programa da placa está em `no_sensores_esp32/no_sensores_esp32.ino`.

### Ligações

| Sensor / pino | Ligação na ESP32 |
|---|---|
| IR duplo – VCC | 3V3 |
| IR duplo – GND | GND |
| IR duplo – OUT1 (faixa A) | GPIO 32 |
| IR duplo – OUT2 (faixa B) | GPIO 33 |
| HC-SR04 – VCC | VIN (5 V) |
| HC-SR04 – GND | GND |
| HC-SR04 – TRIG | GPIO 5 |
| HC-SR04 – ECHO | resistor de **1 kΩ** até o GPIO 18, e do GPIO 18 um resistor de **2 kΩ** até o GND |

> **Atenção:** nunca ligue o ECHO direto na ESP32. Ele sai com 5 V e a ESP32 só aguenta 3,3 V. O divisor de 1 kΩ + 2 kΩ reduz o sinal para cerca de 3,3 V.

### Montagem

- **Módulo IR:** fica na lateral da pista, com os dois pares apontados para a via. O canal 1 é a faixa A e o canal 2 é a faixa B.
- **HC-SR04:** fica num suporte acima da pista, apontado para baixo, entre as duas faixas. Ao ligar, a placa mede a distância até o chão vazio, por isso a pista precisa estar livre nesse momento.

### Configuração

1. Copie `no_sensores_esp32/segredos.exemplo.h` para `no_sensores_esp32/segredos.h` e preencha a rede:

   ```cpp
   const char* WIFI_SSID  = "NOME_DA_REDE";
   const char* WIFI_SENHA = "SENHA_DA_REDE";
   ```

   O `segredos.h` está no `.gitignore`, então a senha nunca vai para o GitHub.

2. No início do `.ino`, coloque o endereço que o `contador_veiculos.py` mostra ao iniciar:

   ```cpp
   const char* URL_NOTEBOOK = "http://10.64.69.164:8000";
   ```

Outros ajustes:

| Constante | Padrão | Para que serve |
|---|---|---|
| `ALTURA_PESADO_CM` | 6.0 | Altura a partir da qual o veículo é "pesado". Ajuste aos seus carrinhos. |
| `IR_ATIVO` | `LOW` | Troque para `HIGH` se o módulo IR indicar "ocupado" ao contrário. |
| `TEMPO_MAX_TRAVESSIA_MS` | 2000 | Tempo máximo entre a primeira e a segunda faixa. |

Depois grave pela Arduino IDE (placa **ESP32 Dev Module**, porta **COM13**) ou pela linha de comando:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 --upload -p COM13 no_sensores_esp32
```

### Teste

1. Rode o painel. Para testar só o ESP32:
   ```bash
   python contador_veiculos.py --sem-camera
   ```
2. Na primeira vez, o **Firewall do Windows** pergunta se o Python pode usar a rede. Marque **Redes privadas** e permita. Sem isso, o ESP32 não consegue enviar os dados.
3. No painel, a seção *Nó ESP32* deve mostrar **conectado**, o sinal Wi-Fi, o estado das faixas e a distância do ultrassom.
4. Abra o Monitor Serial (115200 baud). A cada passagem aparece uma linha como `Passagem: ida (A->B) | altura 4.2 cm (leve)`.
5. Ajuste o trimpot azul de cada canal do módulo IR. O LED do canal deve acender com o carrinho na frente e apagar com a pista vazia.

### Como o ESP32 conta

- O instante em que cada faixa é ocupada é marcado por interrupção. Assim a ordem A/B não se perde, mesmo enquanto a placa mede o ultrassom.
- Durante a passagem, o ultrassom guarda a menor distância medida. A altura do veículo é a distância até o chão menos essa menor distância.
- A passagem termina quando as duas faixas ficam livres. Se só uma faixa foi acionada, o evento é descartado.
- As passagens vão para uma fila e só saem dela quando o notebook confirma o recebimento. Se o Wi-Fi cair, nada se perde, e o notebook ignora reenvios duplicados.
- A cada 2 s a placa envia um sinal de vida com o estado dos sensores. É ele que aparece no painel.

## Painel web

O painel atualiza duas vezes por segundo e mostra:
- **Câmera:** total, contagem por sentido, estado das faixas e imagem ao vivo.
- **Nó ESP32:** total, sentidos, leves e pesados, se está conectado, sinal Wi-Fi e leituras dos sensores.
- A diferença entre as duas contagens.
- As últimas passagens das duas fontes.
- Um link para baixar o CSV.

O CSV tem as colunas `data_hora, fonte, sentido, altura_cm, categoria`. A coluna `fonte` vale `camera` ou `esp32`.

Endereços do servidor:

| Endereço | Uso |
|---|---|
| `GET /dados` | JSON com as contagens das duas fontes |
| `GET /quadro.jpg` | imagem atual da câmera |
| `GET /contagens.csv` | registro completo |
| `POST /evento` | passagem enviada pelo ESP32 |
| `POST /status` | sinal de vida do ESP32 |

A tecla `r` na janela zera a contagem das duas fontes.

## Limitações

- A câmera não distingue tipos de veículo. O ESP32 só separa leve e pesado pela altura.
- Veículos colados um no outro podem ser contados como um só.
- Mudanças bruscas de luz, sombras em movimento e câmera tremendo geram contagens falsas na câmera.
- Os sensores IR têm alcance de até cerca de 30 cm, então o nó ESP32 é para maquete.
- O sistema depende de Wi-Fi estável. A câmera reconecta sozinha e o ESP32 guarda as passagens até conseguir enviar.
- Redes com login por página web (comum em faculdades) não funcionam com o ESP32. Use o hotspot do celular.
