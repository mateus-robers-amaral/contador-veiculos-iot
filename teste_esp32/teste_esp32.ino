// Teste rápido da placa ESP32: informações do chip, LED piscando e busca de redes Wi-Fi.
// Abra o Monitor Serial em 115200 baud para ver as mensagens.

#include <WiFi.h>

const int PINO_LED = 2;  // LED azul da maioria das placas ESP32 DevKit

void listarRedes() {
  Serial.println("Procurando redes Wi-Fi...");
  int n = WiFi.scanNetworks();
  if (n == 0) {
    Serial.println("Nenhuma rede encontrada.");
  }
  for (int i = 0; i < n; i++) {
    Serial.printf("  %2d) %-32s sinal %4d dBm  canal %2d\n",
                  i + 1, WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i));
  }
  WiFi.scanDelete();
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  pinMode(PINO_LED, OUTPUT);

  Serial.println();
  Serial.println("=== Teste ESP32 ===");
  Serial.printf("Modelo: %s (revisao %d), %d nucleos a %lu MHz\n",
                ESP.getChipModel(), ESP.getChipRevision(), ESP.getChipCores(),
                (unsigned long)ESP.getCpuFreqMHz());
  Serial.printf("Memoria flash: %lu MB | RAM livre: %lu KB\n",
                (unsigned long)(ESP.getFlashChipSize() / (1024 * 1024)),
                (unsigned long)(ESP.getFreeHeap() / 1024));

  WiFi.mode(WIFI_STA);
  listarRedes();
  // o MAC só é lido corretamente depois que o rádio Wi-Fi foi ligado
  Serial.printf("Endereco MAC: %s\n", WiFi.macAddress().c_str());
}

void loop() {
  static unsigned long ultimaBusca = 0;
  digitalWrite(PINO_LED, !digitalRead(PINO_LED));
  delay(500);

  if (millis() - ultimaBusca > 15000) {
    ultimaBusca = millis();
    Serial.printf("[%lu s] placa funcionando\n", millis() / 1000);
    listarRedes();
  }
}
