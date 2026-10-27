"""
Contador de veículos IoT: câmera do celular + nó ESP32 com sensores.

O celular transmite o vídeo pelo Wi-Fi (app IP Webcam ou DroidCam), este
programa roda no notebook, conta os veículos que cruzam duas faixas virtuais
(A e B), identifica o sentido pela ordem de ocupação e publica os resultados
em um painel web acessível por qualquer aparelho da mesma rede.

O mesmo painel recebe as passagens do nó ESP32 (sensores infravermelhos e
ultrassônico), que as envia por HTTP para /evento. Assim os dois métodos
contam ao mesmo tempo e podem ser comparados.

Uso:
    python contador_veiculos.py --fonte http://192.168.0.10:8080/video
    python contador_veiculos.py --fonte 0              (webcam do notebook)
    python contador_veiculos.py --fonte teste.mp4      (vídeo gravado)
    python contador_veiculos.py --sem-camera           (só o nó ESP32)

Teclas na janela: q = sair | r = zerar contagem | f = refazer fundo
                  o = girar faixas (vertical/horizontal)
Mouse na janela:  botão esquerdo = posiciona faixa A | direito = faixa B
"""

import argparse
import csv
import json
import os
import socket
import threading
import time
from collections import Counter
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

LARGURA = 320              # o quadro é reduzido para esta largura (processamento rápido)
ESPESSURA_FAIXA = 0.04     # espessura de cada faixa, em fração da imagem
LIMIAR_PIXEL = 25          # diferença de cor (0-255) para considerar o pixel alterado
LIMIAR_OCUPACAO = 0.05     # fração de pixels alterados para a faixa estar ocupada (--ocupacao)
ALFA_FUNDO = 0.02          # velocidade de atualização do fundo (acompanha a luz)
QUADROS_CONFIRMA = 2       # quadros seguidos para confirmar ocupação/liberação
TEMPO_MAX_TRAVESSIA = 3.0  # segundos para o veículo ir de uma faixa à outra
ESP_OFFLINE_APOS = 10      # segundos sem notícia do ESP32 para considerá-lo desconectado

CAMPOS_CSV = ["data_hora", "fonte", "sentido", "altura_cm", "categoria"]


class Registro:
    """Grava as passagens de todas as fontes no mesmo CSV (com trava, pois há várias threads)."""

    def __init__(self, arquivo_csv):
        self.arquivo_csv = arquivo_csv
        self.trava = threading.Lock()
        self.eventos = []
        self.por_hora = Counter()   # (hora "AAAA-MM-DDTHH", fonte) -> passagens, inclui o CSV antigo
        self._carregar_historico()

    def _carregar_historico(self):
        if not os.path.exists(self.arquivo_csv):
            return
        with open(self.arquivo_csv, newline="", encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                if linha.get("data_hora") and linha.get("fonte"):
                    self.por_hora[(linha["data_hora"][:13], linha["fonte"])] += 1

    def gravar(self, evento):
        linha = {campo: evento.get(campo, "") for campo in CAMPOS_CSV}
        with self.trava:
            self.eventos.append(linha)
            self.por_hora[(linha["data_hora"][:13], linha["fonte"])] += 1
            novo = not os.path.exists(self.arquivo_csv)
            with open(self.arquivo_csv, "a", newline="", encoding="utf-8") as f:
                escritor = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
                if novo:
                    escritor.writeheader()
                escritor.writerow(linha)
        extra = f", {linha['categoria']}" if linha["categoria"] else ""
        if linha["altura_cm"] != "":
            extra += f" {linha['altura_cm']} cm"
        print(f"[{linha['data_hora']}] {linha['fonte']}: sentido {linha['sentido']}{extra}")

    def ultimos(self, n=12):
        # "id" é a posição na sessão: o painel usa para saber quais linhas são novas
        with self.trava:
            inicio = max(0, len(self.eventos) - n)
            return [dict(e, id=i) for i, e in enumerate(self.eventos[inicio:], inicio)][::-1]

    def passagens_por_hora(self, horas=12):
        agora = datetime.now().replace(minute=0, second=0, microsecond=0)
        resultado = []
        with self.trava:
            for atras in range(horas - 1, -1, -1):
                hora = (agora - timedelta(hours=atras)).strftime("%Y-%m-%dT%H")
                resultado.append({"hora": hora, "camera": self.por_hora[(hora, "camera")],
                                  "esp32": self.por_hora[(hora, "esp32")]})
        return resultado


class Faixa:
    """Sensor virtual: compara um recorte da imagem com o fundo aprendido."""

    def __init__(self, nome, posicao):
        self.nome = nome
        self.posicao = posicao      # centro da faixa, em fração (0 a 1)
        self.limiar = LIMIAR_OCUPACAO
        self.fundo = None
        self.ocupada = False
        self.fracao = 0.0
        self._seguidos = 0

    def recorte(self, imagem, vertical):
        h, w = imagem.shape[:2]
        tam = w if vertical else h
        meio = int(self.posicao * tam)
        meia = max(2, int(ESPESSURA_FAIXA * tam / 2))
        ini, fim = max(0, meio - meia), min(tam, meio + meia)
        return (slice(None), slice(ini, fim)) if vertical else (slice(ini, fim), slice(None))

    def atualizar(self, imagem, vertical):
        regiao = imagem[self.recorte(imagem, vertical)].astype(np.float32)
        if self.fundo is None or self.fundo.shape != regiao.shape:
            self.fundo = regiao.copy()
            self.ocupada, self.fracao, self._seguidos = False, 0.0, 0
            return
        # compara em cores: um carro vermelho sobre asfalto cinza pode ter o mesmo
        # brilho do fundo, mas difere bastante no canal vermelho
        diferenca = np.abs(regiao - self.fundo).max(axis=2)
        self.fracao = float(np.mean(diferenca > LIMIAR_PIXEL))
        bruto = self.fracao > self.limiar
        # só troca de estado depois de alguns quadros iguais (evita ruído)
        self._seguidos = self._seguidos + 1 if bruto != self.ocupada else 0
        if self._seguidos >= QUADROS_CONFIRMA:
            self.ocupada, self._seguidos = bruto, 0
        # o fundo só aprende quando a faixa está livre
        if not self.ocupada and not bruto:
            cv2.accumulateWeighted(regiao, self.fundo, ALFA_FUNDO)

    def zerar_fundo(self):
        self.fundo = None


class Contador:
    """Máquina de estados: A antes de B = sentido 1; B antes de A = sentido 2."""

    def __init__(self, registro):
        self.registro = registro
        self.zerar()

    def zerar(self):
        self.ida = 0      # A -> B
        self.volta = 0    # B -> A
        self.estado = "livre"
        self.primeira = None
        self.t_inicio = 0.0

    @property
    def total(self):
        return self.ida + self.volta

    def passo(self, a, b, agora):
        if self.estado == "livre":
            if a and not b:
                self.estado, self.primeira, self.t_inicio = "atravessando", "A", agora
            elif b and not a:
                self.estado, self.primeira, self.t_inicio = "atravessando", "B", agora
            elif a and b:
                self.estado = "aguardando"   # ambíguo: não conta
        elif self.estado == "atravessando":
            segunda = b if self.primeira == "A" else a
            if segunda:
                self._registrar("ida" if self.primeira == "A" else "volta")
                self.estado = "aguardando"
            elif agora - self.t_inicio > TEMPO_MAX_TRAVESSIA:
                # só uma faixa foi acionada (mão, sombra, veículo que voltou)
                self.estado = "aguardando"
        if self.estado == "aguardando" and not a and not b:
            self.estado, self.primeira = "livre", None

    def _registrar(self, sentido):
        if sentido == "ida":
            self.ida += 1
        else:
            self.volta += 1
        self.registro.gravar({
            "data_hora": datetime.now().isoformat(timespec="seconds"),
            "fonte": "camera",
            "sentido": sentido,
        })


class NoESP32:
    """Estado do nó ESP32 (sensores IR + ultrassônico), atualizado pelas mensagens HTTP."""

    def __init__(self, registro):
        self.registro = registro
        self.trava = threading.Lock()
        self.zerar()
        self.status = {}
        self.ultimo_contato = 0.0
        self._vistos = set()   # (boot, seq) já registrados: o ESP32 reenvia se não receber resposta

    def zerar(self):
        self.ida = self.volta = self.leves = self.pesados = 0

    def receber_status(self, dados):
        with self.trava:
            self.status = dados
            self.ultimo_contato = time.time()

    def receber_evento(self, dados):
        chave = (dados.get("boot"), dados.get("seq"))
        sentido = dados.get("sentido")
        if sentido not in ("ida", "volta"):
            raise ValueError("sentido deve ser 'ida' ou 'volta'")
        with self.trava:
            self.ultimo_contato = time.time()
            if chave in self._vistos:
                return False
            self._vistos.add(chave)
            if sentido == "ida":
                self.ida += 1
            else:
                self.volta += 1
            categoria = dados.get("categoria", "")
            if categoria == "leve":
                self.leves += 1
            elif categoria == "pesado":
                self.pesados += 1
        # o ESP32 não tem relógio: a hora é a do notebook menos o tempo que o evento esperou na fila
        quando = datetime.now() - timedelta(milliseconds=max(0, int(dados.get("atraso_ms", 0))))
        altura = dados.get("altura_cm")
        self.registro.gravar({
            "data_hora": quando.isoformat(timespec="seconds"),
            "fonte": "esp32",
            "sentido": sentido,
            "altura_cm": "" if altura is None or altura < 0 else round(float(altura), 1),
            "categoria": categoria,
        })
        return True

    def resumo(self):
        with self.trava:
            online = time.time() - self.ultimo_contato < ESP_OFFLINE_APOS
            return {
                "online": online, "ida": self.ida, "volta": self.volta,
                "total": self.ida + self.volta, "leves": self.leves, "pesados": self.pesados,
                "status": self.status if online else {},
            }


# ---------------------------------------------------------------- painel web

PASTA_PAINEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "painel")
TIPOS_PAINEL = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def arquivo_do_painel(nome):
    """Caminho de um arquivo da pasta painel/, ou None se não existir ou sair da pasta."""
    completo = os.path.normpath(os.path.join(PASTA_PAINEL, nome))
    extensao = os.path.splitext(completo)[1].lower()
    if (os.path.commonpath([completo, PASTA_PAINEL]) != PASTA_PAINEL
            or extensao not in TIPOS_PAINEL or not os.path.isfile(completo)):
        return None
    return completo


def iniciar_painel(estado, porta):
    class Painel(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _enviar(self, corpo, tipo, extra=None, codigo=200, cache="no-store"):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", cache)
            for chave, valor in (extra or {}).items():
                self.send_header(chave, valor)
            self.end_headers()
            self.wfile.write(corpo)

        def _json(self, dados, codigo=200):
            self._enviar(json.dumps(dados).encode("utf-8"), "application/json", codigo=codigo)

        def do_GET(self):
            caminho = self.path.split("?")[0]
            if caminho == "/" or caminho.startswith("/painel/"):
                # página, estilo, script e fontes ficam em painel/ (nada vem da internet)
                arquivo = arquivo_do_painel("index.html" if caminho == "/" else caminho[len("/painel/"):])
                if arquivo is None:
                    self.send_error(404)
                    return
                with open(arquivo, "rb") as f:
                    corpo = f.read()
                tipo = TIPOS_PAINEL[os.path.splitext(arquivo)[1].lower()]
                self._enviar(corpo, tipo, cache="max-age=86400" if tipo == "font/woff2" else "no-store")
            elif caminho == "/dados":
                with estado["trava"]:
                    camera = dict(estado["camera"]) if estado["camera"] is not None else None
                self._json({
                    "camera": camera,
                    "esp32": estado["esp32"].resumo(),
                    "ultimos": estado["registro"].ultimos(),
                    "por_hora": estado["registro"].passagens_por_hora(),
                })
            elif caminho == "/quadro.jpg":
                with estado["trava"]:
                    jpg = estado["jpg"]
                if jpg is None:
                    self.send_error(503)
                else:
                    self._enviar(jpg, "image/jpeg")
            elif caminho == "/contagens.csv":
                arquivo = estado["registro"].arquivo_csv
                corpo = (open(arquivo, "rb").read() if os.path.exists(arquivo)
                         else (",".join(CAMPOS_CSV) + "\n").encode("utf-8"))
                self._enviar(corpo, "text/csv; charset=utf-8",
                             {"Content-Disposition": "attachment; filename=contagens.csv"})
            else:
                self.send_error(404)

        def do_POST(self):
            # mensagens do nó ESP32: /evento (uma passagem) e /status (sinal de vida a cada 2 s)
            caminho = self.path.split("?")[0]
            try:
                tamanho = int(self.headers.get("Content-Length", 0))
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
                if caminho == "/evento":
                    novo = estado["esp32"].receber_evento(dados)
                    self._json({"ok": True, "novo": novo})
                elif caminho == "/status":
                    estado["esp32"].receber_status(dados)
                    self._json({"ok": True})
                else:
                    self.send_error(404)
            except (ValueError, TypeError) as erro:
                self._json({"ok": False, "erro": str(erro)}, codigo=400)

    servidor = ThreadingHTTPServer(("0.0.0.0", porta), Painel)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


def ip_local():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "localhost"


# ---------------------------------------------------------------- vídeo

def abrir_fonte(fonte):
    captura = cv2.VideoCapture(int(fonte) if fonte.isdigit() else fonte)
    if not captura.isOpened():
        raise SystemExit(f"Não foi possível abrir a fonte de vídeo: {fonte}")
    return captura


def desenhar(quadro, faixas, vertical, contador):
    h, w = quadro.shape[:2]
    for faixa in faixas:
        cor = (0, 0, 255) if faixa.ocupada else (0, 200, 0)
        pos = int(faixa.posicao * (w if vertical else h))
        meia = max(2, int(ESPESSURA_FAIXA * (w if vertical else h) / 2))
        if vertical:
            cv2.rectangle(quadro, (pos - meia, 0), (pos + meia, h - 1), cor, 2)
            cv2.putText(quadro, faixa.nome, (pos - 6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2)
        else:
            cv2.rectangle(quadro, (0, pos - meia), (w - 1, pos + meia), cor, 2)
            cv2.putText(quadro, faixa.nome, (6, pos - meia - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2)
    texto = f"Total {contador.total}  Ida {contador.ida}  Volta {contador.volta}"
    cv2.rectangle(quadro, (0, h - 24), (w, h), (0, 0, 0), -1)
    cv2.putText(quadro, texto, (6, h - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def main():
    parser = argparse.ArgumentParser(description="Contador de veículos IoT: câmera do celular + nó ESP32.")
    parser.add_argument("--fonte", default="0",
                        help="URL do vídeo do celular, índice da webcam ou arquivo de vídeo")
    parser.add_argument("--sem-camera", action="store_true",
                        help="não usa câmera: só recebe as passagens do nó ESP32")
    parser.add_argument("--porta", type=int, default=8000, help="porta do painel web")
    parser.add_argument("--csv", default="contagens.csv", help="arquivo de registro das passagens")
    parser.add_argument("--horizontal", action="store_true",
                        help="faixas horizontais (veículos se movem para cima/baixo na imagem)")
    parser.add_argument("--faixa-a", type=float, default=0.40, help="posição da faixa A (0 a 1)")
    parser.add_argument("--faixa-b", type=float, default=0.60, help="posição da faixa B (0 a 1)")
    parser.add_argument("--ocupacao", type=float, default=LIMIAR_OCUPACAO,
                        help="fração da faixa que precisa mudar para contar como ocupada")
    parser.add_argument("--sem-janela", action="store_true", help="não abre janela (só painel web)")
    args = parser.parse_args()

    registro = Registro(args.csv)
    estado = {"trava": threading.Lock(), "jpg": None, "camera": None,
              "registro": registro, "esp32": NoESP32(registro)}
    iniciar_painel(estado, args.porta)
    endereco = f"http://{ip_local()}:{args.porta}"
    print(f"Painel web: {endereco}  (abra no celular ou no notebook)")
    print(f"No nó ESP32, configure URL_NOTEBOOK = \"{endereco}\"")

    if args.sem_camera:
        print("Modo sem câmera: aguardando o nó ESP32. Ctrl+C para sair.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        resumo = estado["esp32"].resumo()
        print(f"Encerrado. ESP32: total {resumo['total']} (ida {resumo['ida']}, volta {resumo['volta']}).")
        return

    vertical = not args.horizontal
    faixas = [Faixa("A", args.faixa_a), Faixa("B", args.faixa_b)]
    for faixa in faixas:
        faixa.limiar = args.ocupacao
    contador = Contador(registro)

    janela = "Contador de veiculos"
    if not args.sem_janela:
        cv2.namedWindow(janela)

        def clique(evento, x, y, _flags, _param):
            if evento in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_RBUTTONDOWN):
                faixa = faixas[0] if evento == cv2.EVENT_LBUTTONDOWN else faixas[1]
                h, w = ultimo_tamanho
                faixa.posicao = x / w if vertical else y / h
                faixa.zerar_fundo()
        cv2.setMouseCallback(janela, clique)

    captura = abrir_fonte(args.fonte)
    eh_arquivo = os.path.isfile(args.fonte)
    fps = captura.get(cv2.CAP_PROP_FPS) or 30
    n_quadro = 0
    ultimo_tamanho = (1, 1)
    falhas = 0

    while True:
        ok, quadro = captura.read()
        if not ok:
            if eh_arquivo:
                break
            # câmera IP: a conexão Wi-Fi pode cair; tenta reconectar
            falhas += 1
            if falhas > 30:
                print("Sem imagem da câmera, tentando reconectar...")
                captura.release()
                time.sleep(1)
                captura = abrir_fonte(args.fonte)
                falhas = 0
            continue
        falhas = 0
        n_quadro += 1
        # em vídeo gravado o tempo vem do quadro, não do relógio
        agora = n_quadro / fps if eh_arquivo else time.time()

        escala = LARGURA / quadro.shape[1]
        quadro = cv2.resize(quadro, (LARGURA, int(quadro.shape[0] * escala)))
        ultimo_tamanho = quadro.shape[:2]
        suave = cv2.GaussianBlur(quadro, (5, 5), 0)

        for faixa in faixas:
            faixa.atualizar(suave, vertical)
        contador.passo(faixas[0].ocupada, faixas[1].ocupada, agora)

        desenhar(quadro, faixas, vertical, contador)
        jpg = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
        with estado["trava"]:
            estado["jpg"] = jpg
            estado["camera"] = {
                "total": contador.total, "ida": contador.ida, "volta": contador.volta,
                "faixa_a": faixas[0].ocupada, "faixa_b": faixas[1].ocupada,
            }

        if not args.sem_janela:
            cv2.imshow(janela, quadro)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == ord("r"):
                contador.zerar()
                estado["esp32"].zerar()
            if tecla in (ord("f"), ord("o")):
                if tecla == ord("o"):
                    vertical = not vertical
                for faixa in faixas:
                    faixa.zerar_fundo()

    captura.release()
    cv2.destroyAllWindows()
    resumo = estado["esp32"].resumo()
    print(f"Encerrado. Câmera: total {contador.total} (ida {contador.ida}, volta {contador.volta}) | "
          f"ESP32: total {resumo['total']}.")


if __name__ == "__main__":
    main()
