"""
Visão do estacionamento: detecta veículos entrando e saindo pela câmera do celular.

O celular transmite o vídeo pelo Wi-Fi (app IP Webcam ou DroidCam). Este programa,
no notebook, observa duas faixas virtuais na imagem:
    faixa A = lado da rua      faixa B = lado de dentro
    A antes de B = ENTRADA     B antes de A = SAÍDA      (--inverter troca)

Cada movimento é enviado ao ESP32 (POST /movimento), que guarda a contagem oficial,
acende o indicador na entrada e publica as vagas no painel web. O notebook não guarda
contagem nenhuma: se o ESP32 estiver fora do ar, os movimentos esperam numa fila.

A página local (http://IP_DO_NOTEBOOK:8000) serve só para calibrar a câmera.
A imagem nunca sai da rede local.

Uso:
    python visao.py --fonte http://192.168.0.10:8080/video
    python visao.py --fonte 0                       (webcam do notebook)
    python visao.py --fonte teste.mp4 --esp32 127.0.0.1:8081

Teclas na janela: q = sair | f = refazer fundo | o = girar faixas (vertical/horizontal)
Mouse na janela:  botão esquerdo = posiciona faixa A | direito = faixa B
"""

import argparse
import json
import os
import secrets
import socket
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime
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
ESP32_PADRAO = "estacionamento.local"   # nome que o ESP32 anuncia na rede (mDNS)


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
    """Máquina de estados: A antes de B = entrada; B antes de A = saída (ou o contrário, com --inverter)."""

    def __init__(self, ao_passar, inverter=False):
        self.ao_passar = ao_passar   # chamado com "entrada" ou "saida"
        self.inverter = inverter
        self.zerar()

    def zerar(self):
        self.entradas = 0   # só desta sessão, para conferência; a contagem oficial fica no ESP32
        self.saidas = 0
        self.estado = "livre"
        self.primeira = None
        self.t_inicio = 0.0

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
                de_fora = (self.primeira == "A") != self.inverter
                self._registrar("entrada" if de_fora else "saida")
                self.estado = "aguardando"
            elif agora - self.t_inicio > TEMPO_MAX_TRAVESSIA:
                # só uma faixa foi acionada (mão, sombra, veículo que desistiu)
                self.estado = "aguardando"
        if self.estado == "aguardando" and not a and not b:
            self.estado, self.primeira = "livre", None

    def _registrar(self, sentido):
        if sentido == "entrada":
            self.entradas += 1
        else:
            self.saidas += 1
        self.ao_passar(sentido)


class EnvioESP32:
    """Fila de movimentos para o ESP32. Se a placa não responder, tenta de novo sem perder nada.

    Cada movimento leva (sessao, id): se a resposta se perder e o movimento for reenviado,
    o ESP32 reconhece a repetição e não conta duas vezes."""

    def __init__(self, endereco):
        self.endereco = endereco          # "estacionamento.local", "192.168.0.50" ou "ip:porta"
        self.sessao = secrets.token_hex(4)
        self.proximo_id = 1
        self.fila = deque()
        self.trava = threading.Lock()
        self.tem_algo = threading.Event()
        self.estado_esp = None            # última resposta do ESP32 (vagas, ocupadas...)
        self.ultimo_contato = 0.0
        self.ultimo_erro = ""
        self._ip = None
        threading.Thread(target=self._trabalhar, daemon=True).start()

    def enviar(self, sentido):
        with self.trava:
            item = {"sentido": sentido, "sessao": self.sessao, "id": self.proximo_id}
            self.proximo_id += 1
            self.fila.append(item)
        self.tem_algo.set()
        hora = datetime.now().strftime("%H:%M:%S")
        print(f"[{hora}] {sentido.upper():7} (movimento {item['id']}, na fila: {len(self.fila)})")

    def pendentes(self):
        with self.trava:
            return len(self.fila)

    def online(self):
        return time.time() - self.ultimo_contato < 15

    def _url(self, caminho):
        host = self.endereco
        if host.endswith(".local"):
            # resolve o mDNS uma vez e guarda o IP (resolver .local a cada pedido é lento no Windows)
            if self._ip is None:
                self._ip = socket.getaddrinfo(host, 80, socket.AF_INET)[0][4][0]
            host = self._ip
        return f"http://{host}{caminho}"

    def _pedir(self, caminho, dados=None):
        corpo = None if dados is None else json.dumps(dados).encode("utf-8")
        pedido = urllib.request.Request(self._url(caminho), data=corpo,
                                        headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(pedido, timeout=4) as resposta:
            return json.loads(resposta.read())

    def _trabalhar(self):
        ultima_consulta = 0.0
        while True:
            with self.trava:
                item = self.fila[0] if self.fila else None
            try:
                if item:
                    resposta = self._pedir("/movimento", item)
                    with self.trava:
                        self.fila.popleft()
                    self._contato(resposta)
                    livres = resposta.get("livres")
                    print(f"         ESP32 confirmou o movimento {item['id']}: {livres} vagas livres")
                    continue
                if time.time() - ultima_consulta > 5:
                    # sem movimentos: só consulta o estado, para a página de calibração
                    ultima_consulta = time.time()
                    self._contato(self._pedir("/estado"))
            except (OSError, ValueError) as erro:
                self._ip = None   # o IP do ESP32 pode ter mudado
                if str(erro) != self.ultimo_erro:
                    self.ultimo_erro = str(erro)
                    print(f"ESP32 sem resposta ({erro}). Os movimentos esperam na fila.")
                time.sleep(1)
                continue
            self.tem_algo.wait(1)
            self.tem_algo.clear()

    def _contato(self, resposta):
        self.estado_esp = resposta
        self.ultimo_contato = time.time()
        self.ultimo_erro = ""


# ---------------------------------------------------------------- página de calibração

PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Calibrar câmera</title><style>
:root{--papel:#F5F6F4;--folha:#fff;--degrau:#ECEEEB;--tinta:#16231F;--tinta2:#55615C;--petroleo:#0F4C5C;--carimbo:#B3402F;
--mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;padding:20px 16px 40px;background:var(--papel);color:var(--tinta);font:15px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;
background-image:linear-gradient(rgba(15,76,92,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(15,76,92,.055) 1px,transparent 1px);background-size:28px 28px}
main{max-width:720px;margin:0 auto}.k{font:12px var(--mono);color:var(--tinta2)}h1{font-size:34px;letter-spacing:-.045em;margin:4px 0 16px;line-height:1}
.folha{background:var(--folha);border-radius:18px;padding:16px;margin-bottom:14px}
.quadro{position:relative;aspect-ratio:4/3;background:var(--tinta);border-radius:12px;overflow:hidden;cursor:crosshair;touch-action:manipulation}
.quadro img{width:100%;height:100%;object-fit:contain;display:block}.quadro p{position:absolute;inset:0;margin:0;display:grid;place-items:center;color:#E9EFEC;font-size:14px;padding:20px;text-align:center}
.linha{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:12px}
button{min-height:44px;padding:0 18px;border-radius:999px;border:0;background:var(--degrau);color:var(--tinta2);font-family:inherit;font-weight:600;font-size:14px;cursor:pointer}
button.ativo{background:var(--petroleo);color:#fff}
.carimbo{display:inline-block;font:500 11px var(--mono);padding:2px 8px;border:1.5px solid currentColor;border-radius:5px;transform:rotate(-2deg);color:var(--tinta2)}
.carimbo.ok{color:var(--petroleo)}.carimbo.alerta{color:var(--carimbo)}
dl{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:0}dt{font:500 11px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--tinta2)}
dd{margin:4px 0 0;font-size:26px;font-weight:600;letter-spacing:-.04em}.dica{color:var(--tinta2);font-size:13.5px;margin-top:10px}
</style></head><body><main>
<div class="k">Estacionamento · calibração da câmera (rede local)</div><h1>Calibrar câmera</h1>
<div class="folha"><div class="quadro" id="quadro"><img id="img" alt="Imagem da câmera com as faixas A e B" hidden><p id="sem">Aguardando imagem da câmera…</p></div>
<div class="linha"><span>Tocar na imagem posiciona:</span><button id="bA" class="ativo">faixa A (rua)</button><button id="bB">faixa B (dentro)</button></div>
<div class="linha"><button id="girar">Girar faixas</button><button id="fundo">Reaprender fundo</button></div>
<p class="dica">A faixa A fica do lado da rua e a B do lado de dentro. Deixe a distância entre elas menor que o comprimento do carrinho.</p></div>
<div class="folha"><dl>
<div><dt>faixa A</dt><dd><span class="carimbo" id="fa">livre</span></dd></div><div><dt>faixa B</dt><dd><span class="carimbo" id="fb">livre</span></dd></div>
<div><dt>entradas</dt><dd id="ent">0</dd></div><div><dt>saídas</dt><dd id="sai">0</dd></div>
<div><dt>ESP32</dt><dd><span class="carimbo" id="esp">procurando</span></dd></div><div><dt>vagas livres</dt><dd id="livres">—</dd></div>
</dl><p class="dica" id="fila"></p></div>
</main><script>
const $=id=>document.getElementById(id);let alvo='A';
const post=(c,d)=>fetch(c,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d||{})});
$('bA').onclick=()=>{alvo='A';$('bA').className='ativo';$('bB').className=''};
$('bB').onclick=()=>{alvo='B';$('bB').className='ativo';$('bA').className=''};
$('girar').onclick=()=>post('/girar');$('fundo').onclick=()=>post('/fundo');
$('quadro').onclick=e=>{const img=$('img');if(img.hidden)return;const r=img.getBoundingClientRect();
 const esc=Math.min(r.width/img.naturalWidth,r.height/img.naturalHeight),w=img.naturalWidth*esc,h=img.naturalHeight*esc;
 const x=(e.clientX-r.left-(r.width-w)/2)/w,y=(e.clientY-r.top-(r.height-h)/2)/h;post('/faixa',{nome:alvo,x,y})};
function carimbo(el,txt,tipo){el.textContent=txt;el.className='carimbo '+(tipo||'')}
async function dados(){try{const d=await(await fetch('/estado.json')).json();
 carimbo($('fa'),d.faixa_a?'ocupada':'livre',d.faixa_a?'alerta':'');carimbo($('fb'),d.faixa_b?'ocupada':'livre',d.faixa_b?'alerta':'');
 $('ent').textContent=d.entradas;$('sai').textContent=d.saidas;
 carimbo($('esp'),d.esp32_online?'conectado':'sem resposta',d.esp32_online?'ok':'alerta');
 $('livres').textContent=d.livres??'—';$('fila').textContent=d.pendentes?d.pendentes+' movimento(s) esperando o ESP32 ('+d.esp32+')':'ESP32: '+d.esp32;
}catch(e){}}
async function quadro(){try{const r=await fetch('/quadro.jpg',{cache:'no-store'});if(!r.ok)throw 0;const u=URL.createObjectURL(await r.blob());
 const i=new Image();i.src=u;await i.decode();const img=$('img'),velho=img.src;img.src=u;img.hidden=false;$('sem').hidden=true;if(velho.startsWith('blob:'))URL.revokeObjectURL(velho);
 setTimeout(quadro,200)}catch(e){$('img').hidden=true;$('sem').hidden=false;setTimeout(quadro,1000)}}
setInterval(dados,500);dados();quadro();
</script></body></html>"""


def iniciar_pagina(estado, porta):
    class Pagina(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _enviar(self, corpo, tipo, codigo=200):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            caminho = self.path.split("?")[0]
            if caminho == "/":
                self._enviar(PAGINA.encode("utf-8"), "text/html; charset=utf-8")
            elif caminho == "/estado.json":
                envio = estado["envio"]
                esp = envio.estado_esp or {}
                with estado["trava"]:
                    dados = dict(estado["camera"])
                dados.update({
                    "esp32": envio.endereco, "esp32_online": envio.online(),
                    "pendentes": envio.pendentes(), "livres": esp.get("livres"),
                })
                self._enviar(json.dumps(dados).encode("utf-8"), "application/json")
            elif caminho == "/quadro.jpg":
                with estado["trava"]:
                    jpg = estado["jpg"]
                if jpg is None:
                    self.send_error(503)
                else:
                    self._enviar(jpg, "image/jpeg")
            else:
                self.send_error(404)

        def do_POST(self):
            # ajustes de calibração vindos da página (o loop de vídeo aplica no próximo quadro)
            caminho = self.path.split("?")[0]
            try:
                tamanho = int(self.headers.get("Content-Length", 0))
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
            except ValueError:
                self.send_error(400)
                return
            if caminho in ("/faixa", "/girar", "/fundo"):
                with estado["trava"]:
                    estado["comandos"].append((caminho, dados))
                self._enviar(b'{"ok":true}', "application/json")
            else:
                self.send_error(404)

    servidor = ThreadingHTTPServer(("0.0.0.0", porta), Pagina)
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
    texto = f"Entradas {contador.entradas}  Saidas {contador.saidas}"
    cv2.rectangle(quadro, (0, h - 24), (w, h), (0, 0, 0), -1)
    cv2.putText(quadro, texto, (6, h - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def aplicar_comandos(estado, faixas, vertical):
    """Aplica o que a página de calibração pediu. Devolve a orientação (pode ter girado)."""
    with estado["trava"]:
        comandos, estado["comandos"] = estado["comandos"], []
    for caminho, dados in comandos:
        if caminho == "/faixa":
            faixa = faixas[0] if dados.get("nome") == "A" else faixas[1]
            valor = dados.get("x") if vertical else dados.get("y")
            if isinstance(valor, (int, float)) and 0 <= valor <= 1:
                faixa.posicao = float(valor)
                faixa.zerar_fundo()
        elif caminho == "/girar":
            vertical = not vertical
            for faixa in faixas:
                faixa.zerar_fundo()
        elif caminho == "/fundo":
            for faixa in faixas:
                faixa.zerar_fundo()
    return vertical


def main():
    parser = argparse.ArgumentParser(description="Visão do estacionamento: entradas e saídas pela câmera do celular.")
    parser.add_argument("--fonte", default="0",
                        help="URL do vídeo do celular, índice da webcam ou arquivo de vídeo")
    parser.add_argument("--esp32", default=ESP32_PADRAO,
                        help="endereço do ESP32 (padrão: estacionamento.local; aceita IP ou ip:porta)")
    parser.add_argument("--inverter", action="store_true",
                        help="troca o sentido: B antes de A passa a ser entrada")
    parser.add_argument("--porta", type=int, default=8000, help="porta da página de calibração")
    parser.add_argument("--horizontal", action="store_true",
                        help="faixas horizontais (veículos se movem para cima/baixo na imagem)")
    parser.add_argument("--faixa-a", type=float, default=0.40, help="posição da faixa A, lado da rua (0 a 1)")
    parser.add_argument("--faixa-b", type=float, default=0.60, help="posição da faixa B, lado de dentro (0 a 1)")
    parser.add_argument("--ocupacao", type=float, default=LIMIAR_OCUPACAO,
                        help="fração da faixa que precisa mudar para contar como ocupada")
    parser.add_argument("--sem-janela", action="store_true", help="não abre janela (só a página de calibração)")
    args = parser.parse_args()

    envio = EnvioESP32(args.esp32)
    estado = {"trava": threading.Lock(), "jpg": None, "comandos": [], "envio": envio,
              "camera": {"faixa_a": False, "faixa_b": False, "entradas": 0, "saidas": 0}}
    iniciar_pagina(estado, args.porta)
    print(f"Calibração da câmera: http://{ip_local()}:{args.porta}")
    print(f"Enviando os movimentos para o ESP32 em {args.esp32}")
    print("Entrada = faixa " + ("B antes da A" if args.inverter else "A antes da B (A do lado da rua)"))

    vertical = not args.horizontal
    faixas = [Faixa("A", args.faixa_a), Faixa("B", args.faixa_b)]
    for faixa in faixas:
        faixa.limiar = args.ocupacao
    contador = Contador(envio.enviar, inverter=args.inverter)

    janela = "Estacionamento - calibrar camera"
    ultimo_tamanho = (1, 1)
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
        vertical = aplicar_comandos(estado, faixas, vertical)
        suave = cv2.GaussianBlur(quadro, (5, 5), 0)

        for faixa in faixas:
            faixa.atualizar(suave, vertical)
        contador.passo(faixas[0].ocupada, faixas[1].ocupada, agora)

        desenhar(quadro, faixas, vertical, contador)
        jpg = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
        with estado["trava"]:
            estado["jpg"] = jpg
            estado["camera"] = {"faixa_a": faixas[0].ocupada, "faixa_b": faixas[1].ocupada,
                                "entradas": contador.entradas, "saidas": contador.saidas}

        if not args.sem_janela:
            cv2.imshow(janela, quadro)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla in (ord("f"), ord("o")):
                if tecla == ord("o"):
                    vertical = not vertical
                for faixa in faixas:
                    faixa.zerar_fundo()

    captura.release()
    cv2.destroyAllWindows()
    # vídeo gravado acaba rápido: espera a fila chegar ao ESP32 antes de sair
    limite = time.time() + 15
    while envio.pendentes() and time.time() < limite:
        time.sleep(0.2)
    print(f"Encerrado. Entradas {contador.entradas}, saídas {contador.saidas}. "
          f"Movimentos ainda na fila: {envio.pendentes()}.")


if __name__ == "__main__":
    main()
