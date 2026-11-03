"""
ESP32 simulado: imita a parte local do esp32_estacionamento.ino, para testar o visao.py sem a placa.

Responde como a placa:
    POST /movimento  {"sentido": "entrada"|"saida", "sessao": "...", "id": 1}
    GET  /estado

Mesmas regras do firmware: ocupadas fica entre 0 e VAGAS, e um movimento repetido
(mesma sessão e id já visto) é confirmado, mas não conta de novo.

Uso:
    python testes/esp32_simulado.py                    (porta 8081, 100 vagas)
    python testes/esp32_simulado.py --porta 8081 --ocupadas 95
Depois:
    python visao.py --fonte teste.mp4 --esp32 127.0.0.1:8081 --sem-janela
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser(description="ESP32 simulado para testar o visao.py")
    parser.add_argument("--porta", type=int, default=8081)
    parser.add_argument("--vagas", type=int, default=100)
    parser.add_argument("--ocupadas", type=int, default=0, help="ocupação inicial")
    args = parser.parse_args()

    trava = threading.Lock()
    estado = {"ocupadas": args.ocupadas, "entradas": 0, "saidas": 0, "repetidos": 0,
              "sessao": "", "ultimo_id": 0}

    def resumo():
        ocupadas = estado["ocupadas"]
        indicador = "lotado" if ocupadas >= args.vagas else "quase" if ocupadas >= 0.9 * args.vagas else "livre"
        return {"vagas": args.vagas, "ocupadas": ocupadas, "livres": args.vagas - ocupadas,
                "indicador": indicador, "entradas": estado["entradas"], "saidas": estado["saidas"],
                "repetidos": estado["repetidos"], "simulado": True}

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
                else:
                    estado["sessao"], estado["ultimo_id"] = sessao, ident
                    if sentido == "entrada":
                        estado["entradas"] += 1
                        estado["ocupadas"] = min(args.vagas, estado["ocupadas"] + 1)
                    else:
                        estado["saidas"] += 1
                        estado["ocupadas"] = max(0, estado["ocupadas"] - 1)
                r = resumo()
                print(f"{sentido:7} id {ident}{' (repetido, ignorado)' if repetido else ''} -> "
                      f"ocupadas {r['ocupadas']}, livres {r['livres']}")
                self._json(dict(r, ok=True, novo=not repetido))

    print(f"ESP32 simulado em http://127.0.0.1:{args.porta} ({args.vagas} vagas, {args.ocupadas} ocupadas)")
    ThreadingHTTPServer(("0.0.0.0", args.porta), Placa).serve_forever()


if __name__ == "__main__":
    main()
