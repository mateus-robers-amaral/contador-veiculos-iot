// Controlador do estacionamento (ESP32): a peça central do sistema IoT.
//
//  - Recebe os movimentos do notebook (POST /movimento, rede local) e mantém a
//    contagem oficial de vagas ocupadas, entre 0 e VAGAS.
//  - Grava a contagem na flash (Preferences): faltou energia, nada se perde.
//  - Acende o indicador na entrada: verde = há vagas, amarelo = quase lotado,
//    vermelho = lotado. O LED azul da placa acende quando lota (funciona sem LEDs externos).
//  - Publica o estado na API do painel (HTTP no notebook; HTTPS se for publicado na Vercel)
//    a cada mudança e a cada 30 s, com fila e reenvio se o painel não responder. A resposta da API pode trazer um ajuste manual da contagem.
//  - Anuncia-se como estacionamento.local (mDNS) e mostra as vagas em http://estacionamento.local/
//
// Ligações (ver README): LED verde GPIO 25, amarelo GPIO 26, vermelho GPIO 27,
// cada um com resistor de 220-330 Ω até o GND.
// Monitor Serial: 115200 baud.

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "segredos.h"  // WIFI_SSID, WIFI_SENHA, URL_API e INGEST_TOKEN (copie de segredos.exemplo.h)

// ------------------------------------------------------------ configuração
const int VAGAS = 100;
const int QUASE_LOTADO_PCT = 90;   // a partir desta ocupação o indicador fica amarelo

const int PINO_VERDE    = 25;
const int PINO_AMARELO  = 26;
const int PINO_VERMELHO = 27;
const int PINO_LED_PLACA = 2;      // LED azul da maioria das placas DevKit

const char* NOME_MDNS = "estacionamento";            // vira estacionamento.local
const unsigned long INTERVALO_SINAL_MS = 30000;      // sinal de vida para a nuvem
const unsigned long ESPERA_APOS_FALHA_MS = 5000;     // sem internet: tenta de novo depois disto
const int MOVIMENTOS_POR_ENVIO = 10;                 // vários movimentos vão no mesmo POST

// ------------------------------------------------------------ estado (persistente)
Preferences prefs;
WebServer servidor(80);

int ocupadas = 0;
uint32_t seq = 0;             // número do último movimento; a API ignora o que já recebeu
uint32_t instancia = 0;       // sorteado na primeira vez: se a flash for apagada, a API recomeça a sequência
uint32_t ajusteAplicado = 0;  // último ajuste manual vindo da nuvem que já foi aplicado
String sessaoNotebook = "";   // evita contar duas vezes um movimento reenviado pelo notebook
uint32_t ultimoIdNotebook = 0;

void salvar() {
  prefs.putInt("ocupadas", ocupadas);
  prefs.putUInt("seq", seq);
  prefs.putUInt("ajuste", ajusteAplicado);
  prefs.putString("sessao", sessaoNotebook);
  prefs.putUInt("ultimoId", ultimoIdNotebook);
}

void carregar() {
  prefs.begin("estacionamento", false);
  instancia = prefs.getUInt("instancia", 0);
  if (instancia == 0) {
    instancia = esp_random() | 1;
    prefs.putUInt("instancia", instancia);
  }
  ocupadas = constrain(prefs.getInt("ocupadas", 0), 0, VAGAS);
  seq = prefs.getUInt("seq", 0);
  ajusteAplicado = prefs.getUInt("ajuste", 0);
  sessaoNotebook = prefs.getString("sessao", "");
  ultimoIdNotebook = prefs.getUInt("ultimoId", 0);
}

// ------------------------------------------------------------ indicador na entrada
const char* indicador() {
  if (ocupadas >= VAGAS) return "lotado";
  if (ocupadas * 100 >= VAGAS * QUASE_LOTADO_PCT) return "quase";
  return "livre";
}

void atualizarLeds() {
  String i = indicador();
  digitalWrite(PINO_VERDE, i == "livre");
  digitalWrite(PINO_AMARELO, i == "quase");
  digitalWrite(PINO_VERMELHO, i == "lotado");
  digitalWrite(PINO_LED_PLACA, i == "lotado");
}

// ------------------------------------------------------------ fila de publicação
// Cada movimento (ou ajuste) fica aqui até a API confirmar. Se a fila encher, a mais
// antiga sai: o histórico perde uma linha, mas a contagem enviada continua certa.
struct Movimento {
  uint32_t seq;
  char tipo;          // 'E' entrada, 'S' saída, 'A' ajuste manual
  int ocupadasDepois;
  bool limitado;      // entrada com o estacionamento lotado ou saída com ele vazio
  unsigned long criadoMs;
};

const int TAM_FILA = 40;
Movimento fila[TAM_FILA];
int inicioFila = 0, qtdFila = 0;
bool publicarJa = true;
unsigned long ultimoEnvioMs = 0, proximaTentativaMs = 0;
String ultimoErroApi = "";
unsigned long ultimoSucessoMs = 0;

void enfileirar(char tipo, bool limitado) {
  if (qtdFila == TAM_FILA) {
    inicioFila = (inicioFila + 1) % TAM_FILA;
    qtdFila--;
  }
  fila[(inicioFila + qtdFila) % TAM_FILA] = {seq, tipo, ocupadas, limitado, millis()};
  qtdFila++;
  publicarJa = true;
}

// registra um movimento vindo do notebook; devolve false se a contagem já estava no limite
bool registrar(bool entrada) {
  int antes = ocupadas;
  ocupadas = constrain(ocupadas + (entrada ? 1 : -1), 0, VAGAS);
  bool limitado = ocupadas == antes;
  seq++;
  salvar();
  atualizarLeds();
  enfileirar(entrada ? 'E' : 'S', limitado);
  Serial.printf("%s%s -> ocupadas %d, livres %d (%s)\n", entrada ? "ENTRADA" : "SAIDA",
                limitado ? " (no limite, contagem mantida)" : "", ocupadas, VAGAS - ocupadas, indicador());
  return !limitado;
}

String jsonEstado() {
  return String("{\"vagas\":") + VAGAS + ",\"ocupadas\":" + ocupadas + ",\"livres\":" + (VAGAS - ocupadas) +
         ",\"indicador\":\"" + indicador() + "\",\"seq\":" + seq +
         ",\"leds\":{\"verde\":" + (digitalRead(PINO_VERDE) ? "true" : "false") +
         ",\"amarelo\":" + (digitalRead(PINO_AMARELO) ? "true" : "false") +
         ",\"vermelho\":" + (digitalRead(PINO_VERMELHO) ? "true" : "false") + "}" +
         ",\"nuvem\":{\"pendentes\":" + qtdFila + ",\"ultimo_sucesso_s\":" +
         (ultimoSucessoMs ? String((millis() - ultimoSucessoMs) / 1000) : String("null")) +
         ",\"erro\":\"" + ultimoErroApi + "\"}" +
         ",\"ip\":\"" + WiFi.localIP().toString() + "\",\"rssi\":" + WiFi.RSSI() + "}";
}

// Lê um número inteiro depois de "chave": no JSON (as respostas são pequenas e
// de formato conhecido, então não vale a pena incluir uma biblioteca de JSON).
bool lerInteiro(const String& json, const String& chave, long& valor, int desde = 0) {
  int i = json.indexOf("\"" + chave + "\"", desde);
  if (i < 0) return false;
  i = json.indexOf(':', i);
  if (i < 0) return false;
  i++;
  while (i < (int)json.length() && json[i] == ' ') i++;
  int fim = i;
  if (fim < (int)json.length() && json[fim] == '-') fim++;
  while (fim < (int)json.length() && isDigit(json[fim])) fim++;
  if (fim == i) return false;
  valor = json.substring(i, fim).toInt();
  return true;
}

String lerTexto(const String& json, const String& chave) {
  int i = json.indexOf("\"" + chave + "\"");
  if (i < 0) return "";
  i = json.indexOf('"', json.indexOf(':', i) + 1);
  int fim = json.indexOf('"', i + 1);
  return (i < 0 || fim < 0) ? "" : json.substring(i + 1, fim);
}

// ------------------------------------------------------------ publicação no painel (notebook ou Vercel)
String corpoPublicacao(int quantos) {
  String s = String("{\"instancia\":") + instancia + ",\"seq\":" + seq + ",\"vagas\":" + VAGAS +
             ",\"ocupadas\":" + ocupadas + ",\"ajuste_aplicado\":" + ajusteAplicado +
             ",\"ip\":\"" + WiFi.localIP().toString() + "\",\"rssi\":" + WiFi.RSSI() +
             ",\"uptime_s\":" + (millis() / 1000) + ",\"movimentos\":[";
  for (int k = 0; k < quantos; k++) {
    Movimento& m = fila[(inicioFila + k) % TAM_FILA];
    const char* tipo = m.tipo == 'E' ? "entrada" : m.tipo == 'S' ? "saida" : "ajuste";
    if (k) s += ",";
    s += String("{\"seq\":") + m.seq + ",\"tipo\":\"" + tipo + "\",\"ocupadas\":" + m.ocupadasDepois +
         ",\"limitado\":" + (m.limitado ? "true" : "false") + ",\"atraso_ms\":" + (millis() - m.criadoMs) + "}";
  }
  return s + "]}";
}

void aplicarAjuste(const String& resposta) {
  int i = resposta.indexOf("\"ajuste\"");
  if (i < 0 || resposta.indexOf("null", i) == resposta.indexOf(':', i) + 1) return;
  long id, valor;
  if (!lerInteiro(resposta, "id", id, i) || !lerInteiro(resposta, "ocupadas", valor, i)) return;
  if ((uint32_t)id == ajusteAplicado) return;
  ocupadas = constrain((int)valor, 0, VAGAS);
  ajusteAplicado = id;
  seq++;
  salvar();
  atualizarLeds();
  enfileirar('A', false);
  Serial.printf("AJUSTE manual %ld vindo do painel -> ocupadas %d, livres %d\n", id, ocupadas, VAGAS - ocupadas);
}

void publicar() {
  if (WiFi.status() != WL_CONNECTED || strlen(URL_API) == 0) return;
  int quantos = min(qtdFila, MOVIMENTOS_POR_ENVIO);
  String url = String(URL_API) + "/api/estado";
  bool seguro = url.startsWith("https://");

  // Projeto acadêmico: o certificado da Vercel NÃO é validado (setInsecure). A conexão continua
  // cifrada, mas não há garantia de que o outro lado é mesmo a Vercel. Para validar, troque
  // setInsecure() por cliente.setCACert(CA_RAIZ), com o certificado raiz da cadeia da Vercel
  // em formato PEM (veja no navegador: cadeado > certificado > raiz > exportar).
  WiFiClientSecure clienteSeguro;
  clienteSeguro.setInsecure();
  WiFiClient clienteSimples;   // http:// serve para testar contra o "npm run dev" do notebook

  HTTPClient http;
  http.setTimeout(6000);
  bool iniciou = seguro ? http.begin(clienteSeguro, url) : http.begin(clienteSimples, url);
  if (!iniciou) return;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + INGEST_TOKEN);
  int codigo = http.POST(corpoPublicacao(quantos));
  String resposta = codigo > 0 ? http.getString() : "";
  http.end();
  ultimoEnvioMs = millis();

  if (codigo == 200) {
    inicioFila = (inicioFila + quantos) % TAM_FILA;
    qtdFila -= quantos;
    publicarJa = qtdFila > 0;
    ultimoSucessoMs = millis();
    if (ultimoErroApi.length()) Serial.println("Nuvem: conexão restabelecida.");
    ultimoErroApi = "";
    aplicarAjuste(resposta);
  } else {
    ultimoErroApi = codigo > 0 ? String("HTTP ") + codigo : http.errorToString(codigo);
    Serial.printf("Nuvem: falha ao publicar (%s). %d na fila, tento de novo em %lu s.\n",
                  ultimoErroApi.c_str(), qtdFila, ESPERA_APOS_FALHA_MS / 1000);
    proximaTentativaMs = millis() + ESPERA_APOS_FALHA_MS;
  }
}

// ------------------------------------------------------------ servidor local
void responderJson(int codigo, const String& corpo) {
  servidor.sendHeader("Cache-Control", "no-store");
  servidor.send(codigo, "application/json", corpo);
}

void aoMovimento() {
  String corpo = servidor.arg("plain");
  String sentido = lerTexto(corpo, "sentido");
  String sessao = lerTexto(corpo, "sessao");
  long id = 0;
  if ((sentido != "entrada" && sentido != "saida") || !lerInteiro(corpo, "id", id)) {
    responderJson(400, "{\"ok\":false,\"erro\":\"esperado {sentido, sessao, id}\"}");
    return;
  }
  // o notebook reenvia se não recebeu a resposta: o mesmo (sessao, id) não conta duas vezes
  if (sessao == sessaoNotebook && (uint32_t)id <= ultimoIdNotebook) {
    String e = jsonEstado();
    responderJson(200, "{\"ok\":true,\"novo\":false," + e.substring(1));
    return;
  }
  sessaoNotebook = sessao;
  ultimoIdNotebook = id;
  registrar(sentido == "entrada");   // já salva sessão e id na flash
  String e = jsonEstado();
  responderJson(200, "{\"ok\":true,\"novo\":true," + e.substring(1));
}

void aoPaginaInicial() {
  // página mínima para quando não houver internet: abre em http://estacionamento.local/
  String cor = String(indicador()) == "lotado" ? "#B3402F" : String(indicador()) == "quase" ? "#8a6d00" : "#0F4C5C";
  String texto = String(indicador()) == "lotado" ? "LOTADO" : String(indicador()) == "quase" ? "QUASE LOTADO" : "LIVRE";
  String html =
    "<!doctype html><html lang=pt-BR><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<meta http-equiv=refresh content=3><title>Vagas</title>"
    "<body style='margin:0;font-family:system-ui,sans-serif;background:#F5F6F4;color:#16231F;display:grid;place-items:center;min-height:100vh;text-align:center'>"
    "<main><p style='font:12px monospace;color:#55615C'>Estacionamento · ESP32 (rede local)</p>"
    "<div style='font-size:120px;font-weight:700;letter-spacing:-.06em;line-height:1'>" + String(VAGAS - ocupadas) + "</div>"
    "<p style='font-size:20px;margin:6px 0 18px'>vagas livres de " + VAGAS + "</p>"
    "<span style='font:600 14px monospace;color:" + cor + ";border:2px solid " + cor + ";padding:4px 12px;border-radius:6px;display:inline-block;transform:rotate(-2deg)'>" +
    texto + "</span></main></body></html>";
  servidor.send(200, "text/html; charset=utf-8", html);
}

// ------------------------------------------------------------ programa principal
bool wifiAvisado = false;

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== ESP32 - controlador do estacionamento ===");

  for (int pino : {PINO_VERDE, PINO_AMARELO, PINO_VERMELHO, PINO_LED_PLACA}) pinMode(pino, OUTPUT);
  carregar();
  atualizarLeds();
  Serial.printf("Contagem recuperada da flash: %d ocupadas, %d livres (%s)\n", ocupadas, VAGAS - ocupadas, indicador());

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  Serial.printf("Conectando ao Wi-Fi \"%s\"...\n", WIFI_SSID);

  servidor.on("/", HTTP_GET, aoPaginaInicial);
  servidor.on("/estado", HTTP_GET, []() { responderJson(200, jsonEstado()); });
  servidor.on("/movimento", HTTP_POST, aoMovimento);
  servidor.onNotFound([]() { responderJson(404, "{\"ok\":false,\"erro\":\"nao encontrado\"}"); });
  servidor.begin();
}

void loop() {
  servidor.handleClient();

  if (WiFi.status() == WL_CONNECTED && !wifiAvisado) {
    wifiAvisado = true;
    MDNS.end();
    if (MDNS.begin(NOME_MDNS)) MDNS.addService("http", "tcp", 80);
    Serial.printf("Wi-Fi conectado. IP %s, sinal %d dBm. Também responde em http://%s.local\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI(), NOME_MDNS);
    Serial.printf("Publicando em %s\n", strlen(URL_API) ? URL_API : "(URL_API vazio: só rede local)");
    publicarJa = true;
  } else if (WiFi.status() != WL_CONNECTED && wifiAvisado) {
    wifiAvisado = false;
    Serial.println("Wi-Fi caiu, tentando reconectar...");
  }

  unsigned long agora = millis();
  bool podeTentar = (long)(agora - proximaTentativaMs) >= 0;
  if (podeTentar && (publicarJa || agora - ultimoEnvioMs >= INTERVALO_SINAL_MS)) publicar();
}
