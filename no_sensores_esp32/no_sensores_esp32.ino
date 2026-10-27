// Nó ESP32 do contador de veículos IoT.
//
// Duas barreiras infravermelhas (faixas A e B) detectam a passagem e o sentido;
// o sensor ultrassônico, acima da pista, mede a altura do veículo para
// classificá-lo como leve ou pesado. Cada passagem é enviada por Wi-Fi ao
// painel do notebook (contador_veiculos.py), via HTTP POST em /evento.
//
// Ligações (ver README):
//   IR duplo  VCC -> 3V3   GND -> GND   OUT1 -> GPIO 32 (faixa A)   OUT2 -> GPIO 33 (faixa B)
//   HC-SR04   VCC -> VIN (5 V)   GND -> GND   TRIG -> GPIO 5
//             ECHO -> resistor 1 kΩ -> GPIO 18, e GPIO 18 -> resistor 2 kΩ -> GND
//
// Monitor Serial: 115200 baud.

#include <WiFi.h>
#include <HTTPClient.h>
#include "segredos.h"  // WIFI_SSID e WIFI_SENHA (copie de segredos.exemplo.h)

// ------------------------------------------------------------ configuração
// endereço que o contador_veiculos.py mostra ao iniciar
const char* URL_NOTEBOOK = "http://10.64.69.164:8000";

const int PINO_IR_A = 32;
const int PINO_IR_B = 33;
const int PINO_TRIG = 5;
const int PINO_ECHO = 18;
const int PINO_LED  = 2;

// os módulos IR com LM393 vão para LOW quando detectam algo; se o seu for
// ao contrário (LED da placa aceso sem nada na frente), troque para HIGH
const int IR_ATIVO = LOW;

const float ALTURA_PESADO_CM   = 6.0;   // a partir desta altura o veículo é "pesado" (escala de maquete)
const unsigned long TEMPO_MAX_TRAVESSIA_MS = 2000;  // entre a primeira e a segunda faixa
const unsigned long TEMPO_LIVRE_MS = 150;  // faixas livres por este tempo = passagem terminou
const unsigned long CARENCIA_MS = 300;    // ignora novas detecções logo após uma passagem
const unsigned long INTERVALO_ULTRASSOM_MS = 40;
const unsigned long INTERVALO_STATUS_MS = 2000;

// ------------------------------------------------------------ detecção
// O momento em que cada faixa foi ocupada é marcado por interrupção, para não
// perder a ordem enquanto o programa está medindo o ultrassom ou usando o Wi-Fi.
volatile unsigned long tA = 0, tB = 0;

void IRAM_ATTR aoOcuparA() { if (tA == 0) tA = micros() | 1; }
void IRAM_ATTR aoOcuparB() { if (tB == 0) tB = micros() | 1; }

bool ocupada(int pino) { return digitalRead(pino) == IR_ATIVO; }

float medirDistanciaCm() {
  digitalWrite(PINO_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PINO_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PINO_TRIG, LOW);
  unsigned long us = pulseIn(PINO_ECHO, HIGH, 12000);  // até ~2 m
  return us == 0 ? -1 : us / 58.0;
}

// distância até o chão vazio: mediana de várias leituras
float referenciaCm = -1;

void calibrarChao() {
  float leituras[15];
  int n = 0;
  for (int i = 0; i < 15; i++) {
    float d = medirDistanciaCm();
    if (d > 0) leituras[n++] = d;
    delay(30);
  }
  if (n < 5) {
    referenciaCm = -1;
    Serial.println("Ultrassom: sem leitura (verifique as ligações). Altura não será medida.");
    return;
  }
  // ordena para pegar a mediana
  for (int i = 1; i < n; i++)
    for (int j = i; j > 0 && leituras[j] < leituras[j - 1]; j--) {
      float t = leituras[j]; leituras[j] = leituras[j - 1]; leituras[j - 1] = t;
    }
  referenciaCm = leituras[n / 2];
  Serial.printf("Ultrassom: chão a %.1f cm\n", referenciaCm);
}

// ------------------------------------------------------------ fila de envio
// As passagens ficam numa fila até o notebook confirmar o recebimento, assim
// nada se perde se o Wi-Fi cair por alguns segundos.
struct Passagem {
  uint32_t seq;
  bool ida;
  float alturaCm;
  unsigned long criadoMs;
};

const int TAM_FILA = 32;
Passagem fila[TAM_FILA];
int inicioFila = 0, qtdFila = 0;
uint32_t proximoSeq = 1;
uint32_t idBoot;  // distingue os envios de cada vez que a placa liga

void enfileirar(bool ida, float alturaCm) {
  if (qtdFila == TAM_FILA) {  // fila cheia: descarta a mais antiga
    inicioFila = (inicioFila + 1) % TAM_FILA;
    qtdFila--;
  }
  fila[(inicioFila + qtdFila) % TAM_FILA] = {proximoSeq++, ida, alturaCm, millis()};
  qtdFila++;
}

const char* categoria(float alturaCm) {
  if (alturaCm < 0) return "indefinido";
  return alturaCm >= ALTURA_PESADO_CM ? "pesado" : "leve";
}

bool postar(const char* caminho, const String& json) {
  HTTPClient http;
  http.setTimeout(1500);
  if (!http.begin(String(URL_NOTEBOOK) + caminho)) return false;
  http.addHeader("Content-Type", "application/json");
  int codigo = http.POST(json);
  http.end();
  return codigo == 200;
}

void enviarFila() {
  if (qtdFila == 0 || WiFi.status() != WL_CONNECTED) return;
  Passagem& p = fila[inicioFila];
  String json = String("{\"no\":\"esp32\",\"boot\":") + idBoot +
                ",\"seq\":" + p.seq +
                ",\"sentido\":\"" + (p.ida ? "ida" : "volta") + "\"" +
                ",\"altura_cm\":" + String(p.alturaCm, 1) +
                ",\"categoria\":\"" + categoria(p.alturaCm) + "\"" +
                ",\"atraso_ms\":" + (millis() - p.criadoMs) + "}";
  if (postar("/evento", json)) {
    inicioFila = (inicioFila + 1) % TAM_FILA;
    qtdFila--;
  }
}

void enviarStatus(float distanciaCm) {
  if (WiFi.status() != WL_CONNECTED) return;
  String json = String("{\"no\":\"esp32\",\"ip\":\"") + WiFi.localIP().toString() + "\"" +
                ",\"rssi\":" + WiFi.RSSI() +
                ",\"faixa_a\":" + (ocupada(PINO_IR_A) ? "true" : "false") +
                ",\"faixa_b\":" + (ocupada(PINO_IR_B) ? "true" : "false") +
                ",\"distancia_cm\":" + String(distanciaCm, 1) +
                ",\"referencia_cm\":" + String(referenciaCm, 1) +
                ",\"pendentes\":" + qtdFila + "}";
  postar("/status", json);
}

// ------------------------------------------------------------ programa principal
bool atravessando = false;
unsigned long inicioTravessiaMs = 0, livreDesdeMs = 0, fimTravessiaMs = 0, ultimoUltrassomMs = 0, ultimoStatusMs = 0;
float menorDistanciaCm = -1;
bool wifiAvisado = false;

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== Nó ESP32 - contador de veículos ===");

  pinMode(PINO_IR_A, INPUT_PULLUP);
  pinMode(PINO_IR_B, INPUT_PULLUP);
  pinMode(PINO_TRIG, OUTPUT);
  pinMode(PINO_ECHO, INPUT);
  pinMode(PINO_LED, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(PINO_IR_A), aoOcuparA, IR_ATIVO == LOW ? FALLING : RISING);
  attachInterrupt(digitalPinToInterrupt(PINO_IR_B), aoOcuparB, IR_ATIVO == LOW ? FALLING : RISING);

  idBoot = esp_random();
  calibrarChao();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  Serial.printf("Conectando ao Wi-Fi \"%s\"...\n", WIFI_SSID);
}

void finalizarTravessia() {
  noInterrupts();
  unsigned long a = tA, b = tB;
  tA = tB = 0;
  interrupts();

  if (a && b) {
    bool ida = (long)(b - a) > 0;  // A antes de B
    float altura = (referenciaCm > 0 && menorDistanciaCm > 0) ? referenciaCm - menorDistanciaCm : -1;
    if (altura >= 0 && altura < 0.5) altura = 0;  // ruído do sensor
    enfileirar(ida, altura);
    Serial.printf("Passagem: %s | altura %.1f cm (%s) | na fila: %d\n",
                  ida ? "ida (A->B)" : "volta (B->A)", altura, categoria(altura), qtdFila);
  } else {
    Serial.println("Descartado: só uma faixa foi acionada.");
  }
  atravessando = false;
  fimTravessiaMs = millis();
  menorDistanciaCm = -1;
  digitalWrite(PINO_LED, LOW);
}

void loop() {
  unsigned long agora = millis();
  bool a = ocupada(PINO_IR_A), b = ocupada(PINO_IR_B);

  // logo depois de uma passagem, ignora oscilações da saída do sensor na saída do veículo
  if (!atravessando && (tA || tB) && agora - fimTravessiaMs < CARENCIA_MS) {
    noInterrupts();
    tA = tB = 0;
    interrupts();
  }

  if (!atravessando && (tA || tB)) {
    atravessando = true;
    inicioTravessiaMs = agora;
    livreDesdeMs = 0;
    digitalWrite(PINO_LED, HIGH);
  }

  if (atravessando) {
    // durante a passagem, o ultrassom guarda a menor distância (= ponto mais alto do veículo)
    if (agora - ultimoUltrassomMs >= INTERVALO_ULTRASSOM_MS) {
      ultimoUltrassomMs = agora;
      float d = medirDistanciaCm();
      if (d > 0 && (menorDistanciaCm < 0 || d < menorDistanciaCm)) menorDistanciaCm = d;
    }
    bool soUmaFaixa = !(tA && tB);
    if (a || b) {
      livreDesdeMs = 0;
    } else if (livreDesdeMs == 0) {
      livreDesdeMs = agora;
    }
    bool terminou = livreDesdeMs && agora - livreDesdeMs >= TEMPO_LIVRE_MS &&
                    (!soUmaFaixa || agora - inicioTravessiaMs >= TEMPO_MAX_TRAVESSIA_MS);
    if (terminou) finalizarTravessia();
    return;  // durante a passagem não usa o Wi-Fi, para medir sem atraso
  }

  // fora de passagem: Wi-Fi, envio da fila e sinal de vida
  if (WiFi.status() == WL_CONNECTED && !wifiAvisado) {
    wifiAvisado = true;
    Serial.printf("Wi-Fi conectado. IP %s, sinal %d dBm. Enviando para %s\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI(), URL_NOTEBOOK);
  } else if (WiFi.status() != WL_CONNECTED && wifiAvisado) {
    wifiAvisado = false;
    Serial.println("Wi-Fi caiu, tentando reconectar...");
  }

  enviarFila();
  if (agora - ultimoStatusMs >= INTERVALO_STATUS_MS) {
    ultimoStatusMs = agora;
    float d = medirDistanciaCm();
    if (referenciaCm < 0 && d > 0) calibrarChao();  // sensor ligado depois da placa
    enviarStatus(d);
  }
}
