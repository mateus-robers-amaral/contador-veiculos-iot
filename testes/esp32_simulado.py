"""
ESP32 simulado: imita o esp32_estacionamento.ino, para testar o projeto sem a placa.

Parte local (igual à placa):
    POST /movimento  {"sentido": "entrada"|"saida", "sessao": "...", "id": 1}
    GET  /estado

Mesmas regras do firmware: ocupadas fica entre 0 e VAGAS, e um movimento repetido
(mesma sessão e id já visto) é confirmado, mas não conta de novo.

Parte da nuvem (opcional, com --api): publica o estado em URL/api/estado no mesmo formato
da placa (fila de movimentos, número de sequência, sinal de vida) e aplica a correção manual
que o painel devolver. O token vem de --token, da variável INGEST_TOKEN ou do
esp32_estacionamento/segredos.h, o mesmo arquivo da placa.

Uso:
    python testes/esp32_simulado.py                                   (porta 8081, 100 vagas)
    python testes/esp32_simulado.py --ocupadas 95
    python testes/esp32_simulado.py --api http://localhost:3000       (publica no painel local)
    python testes/esp32_simulado.py --api https://SEU-PROJETO.vercel.app --aleatorio 4
Depois:
    python visao.py --fonte teste.mp4 --esp32 127.0.0.1:8081 --sem-janela
"""

import argparse
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SEGREDOS = Path(__file__).resolve().parent.parent / "esp32_estacionamento" / "segredos.h"
MOVIMENTOS_POR_ENVIO = 10   # como no firmware
ESPERA_APOS_FALHA = 5       # segundos


def ler_token(token_arg):
    if token_arg:
        return token_arg
    if os.environ.get("INGEST_TOKEN"):
        return os.environ["INGEST_TOKEN"]
    if SEGREDOS.exists():
        achou = re.search(r'INGEST_TOKEN\s*=\s*"([^"]*)"', SEGREDOS.read_text(encoding="utf-8"))
        if achou and achou.group(1):
            return achou.group(1)
    raise SystemExit("Sem token: use --token, a variável INGEST_TOKEN ou preencha o segredos.h.")


def main():
    parser = argparse.ArgumentParser(description="ESP32 simulado para testar o projeto sem a placa")
    parser.add_argument("--porta", type=int, default=8081)
    parser.add_argument("--vagas", type=int, default=100)
    parser.add_argument("--ocupadas", type=int, default=0, help="ocupação inicial")
    parser.add_argument("--api", default="", help="URL do painel para publicar (ex.: http://localhost:3000)")
    parser.add_argument("--token", default="", help="INGEST_TOKEN (padrão: variável de ambiente ou segredos.h)")
    parser.add_argument("--sinal", type=float, default=10, help="segundos entre sinais de vida (a placa usa 30)")
    parser.add_argument("--aleatorio", type=float, default=0,
                        help="gera uma entrada ou saída aleatória a cada N segundos (demonstração)")
    args = parser.parse_args()

    trava = threading.Lock()
    tem_algo = threading.Event()
    inicio = time.time()
    estado = {"ocupadas": args.ocupadas, "entradas": 0, "saidas": 0, "repetidos": 0,
              "sessao": "", "ultimo_id": 0,
              # nuvem: como na placa, cada movimento tem um seq e espera na fila até a API confirmar
              "instancia": random.randint(1, 2 ** 31), "seq": 0, "fila": [], "ajuste_aplicado": 0,
              "nuvem": "desligada" if not args.api else "aguardando"}

    def indicador():
        ocupadas = estado["ocupadas"]
        return "lotado" if ocupadas >= args.vagas else "quase" if ocupadas >= 0.9 * args.vagas else "livre"

    def resumo():
        ocupadas = estado["ocupadas"]
        return {"vagas": args.vagas, "ocupadas": ocupadas, "livres": args.vagas - ocupadas,
                "indicador": indicador(), "entradas": estado["entradas"], "saidas": estado["saidas"],
                "repetidos": estado["repetidos"], "fila_nuvem": len(estado["fila"]),
                "nuvem": estado["nuvem"], "simulado": True}

    def enfileirar(tipo, limitado):
        # chamar com a trava
        estado["seq"] += 1
        estado["fila"].append({"seq": estado["seq"], "tipo": tipo, "ocupadas": estado["ocupadas"],
                               "limitado": limitado, "criado": time.time()})
        tem_algo.set()

    def registrar(sentido):
        # chamar com a trava; devolve False se a contagem não mudou (lotado ou vazio)
        antes = estado["ocupadas"]
        if sentido == "entrada":
            estado["entradas"] += 1
            estado["ocupadas"] = min(args.vagas, antes + 1)
        else:
            estado["saidas"] += 1
            estado["ocupadas"] = max(0, antes - 1)
        limitado = estado["ocupadas"] == antes
        if args.api:
            enfileirar(sentido, limitado)
        r = resumo()
        print(f"{sentido:7} -> ocupadas {r['ocupadas']}, livres {r['livres']}"
              f"{' (no limite, contagem mantida)' if limitado else ''}")
        return not limitado

    class Placa(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, dados, codigo=200):
            corpo = json.dumps(dados).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if self.path.split("?")[0] == "/estado":
                with trava:
                    self._json(resumo())
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path.split("?")[0] != "/movimento":
                self.send_error(404)
                return
            try:
                dados = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                sentido, sessao, ident = dados["sentido"], str(dados["sessao"]), int(dados["id"])
                if sentido not in ("entrada", "saida"):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                self._json({"ok": False, "erro": "esperado {sentido, sessao, id}"}, 400)
                return
            with trava:
                repetido = sessao == estado["sessao"] and ident <= estado["ultimo_id"]
                if repetido:
                    estado["repetidos"] += 1
                    print(f"{sentido:7} id {ident} (repetido, ignorado)")
                else:
                    estado["sessao"], estado["ultimo_id"] = sessao, ident
                    registrar(sentido)
                self._json(dict(resumo(), ok=True, novo=not repetido))

    def publicar_na_nuvem(token):
        """Mesmo ciclo do publicar() do firmware: lote da fila, sinal de vida e ajuste na resposta."""
        url = args.api.rstrip("/") + "/api/estado"
        ultimo_erro = ""
        while True:
            tem_algo.wait(args.sinal)
            tem_algo.clear()
            with trava:
                lote = estado["fila"][:MOVIMENTOS_POR_ENVIO]
                agora = time.time()
                corpo = {"instancia": estado["instancia"], "seq": estado["seq"], "vagas": args.vagas,
                         "ocupadas": estado["ocupadas"], "ajuste_aplicado": estado["ajuste_aplicado"],
                         "ip": "simulado", "rssi": -55, "uptime_s": int(agora - inicio),
                         "movimentos": [{"seq": m["seq"], "tipo": m["tipo"], "ocupadas": m["ocupadas"],
                                         "limitado": m["limitado"], "atraso_ms": int((agora - m["criado"]) * 1000)}
                                        for m in lote]}
            pedido = urllib.request.Request(url, data=json.dumps(corpo).encode("utf-8"), headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
            try:
                with urllib.request.urlopen(pedido, timeout=10) as r:
                    resposta = json.loads(r.read())
            except (OSError, ValueError) as erro:
                if isinstance(erro, urllib.error.HTTPError) and erro.code == 401:
                    erro = "HTTP 401: token diferente do INGEST_TOKEN do painel"
                with trava:
                    estado["nuvem"] = f"falha: {erro}"
                if str(erro) != ultimo_erro:
                    ultimo_erro = str(erro)
                    print(f"Nuvem: falha ao publicar ({erro}). Tento de novo em {ESPERA_APOS_FALHA} s.")
                time.sleep(ESPERA_APOS_FALHA)
                tem_algo.set()
                continue
            with trava:
                if ultimo_erro:
                    print("Nuvem: conexão restabelecida.")
                ultimo_erro = ""
                estado["nuvem"] = "ok"
                del estado["fila"][:len(lote)]
                if estado["fila"]:
                    tem_algo.set()
                if lote:
                    print(f"Nuvem: {len(lote)} movimento(s) publicado(s), {resposta.get('novos', 0)} novo(s).")
                ajuste = resposta.get("ajuste")
                if ajuste and ajuste.get("id") != estado["ajuste_aplicado"]:
                    estado["ocupadas"] = max(0, min(args.vagas, int(ajuste["ocupadas"])))
                    estado["ajuste_aplicado"] = ajuste["id"]
                    enfileirar("ajuste", False)
                    print(f"AJUSTE manual {ajuste['id']} vindo do painel -> ocupadas {estado['ocupadas']}")

    def movimentos_aleatorios():
        # entra mais do que sai enquanto há vagas sobrando, e o contrário quando está cheio
        while True:
            time.sleep(args.aleatorio)
            with trava:
                chance_entrada = 0.65 if estado["ocupadas"] < 0.8 * args.vagas else 0.35
                registrar("entrada" if random.random() < chance_entrada else "saida")

    if args.api:
        token = ler_token(args.token)
        threading.Thread(target=publicar_na_nuvem, args=(token,), daemon=True).start()
        tem_algo.set()   # primeiro sinal de vida logo ao ligar, como a placa
    if args.aleatorio > 0:
        threading.Thread(target=movimentos_aleatorios, daemon=True).start()

    print(f"ESP32 simulado em http://127.0.0.1:{args.porta} ({args.vagas} vagas, {args.ocupadas} ocupadas)")
    if args.api:
        print(f"Publicando em {args.api.rstrip('/')}/api/estado (sinal de vida a cada {args.sinal:g} s)")
    if args.aleatorio > 0:
        print(f"Gerando um movimento aleatório a cada {args.aleatorio:g} s")
    ThreadingHTTPServer(("0.0.0.0", args.porta), Placa).serve_forever()


if __name__ == "__main__":
    main()
