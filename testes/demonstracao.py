"""
Demonstração completa por simulação, no lugar do teste com o hardware.

Roda a cadeia inteira do projeto sem celular e sem placa:

    vídeo sintético -> visao.py (OpenCV) -> ESP32 simulado -> API do painel -> painel web

1. Gera um vídeo com carros entrando e saindo (testes/gerar_video.py).
2. Liga o ESP32 simulado (testes/esp32_simulado.py), que publica na API como a placa.
3. Roda o visao.py sobre o vídeo, mandando cada movimento ao ESP32 simulado.
4. Confere se as contagens batem com o que o vídeo tem e mostra o estado no painel.

Uso:
    python testes/demonstracao.py                                    (só a parte local)
    python testes/demonstracao.py --api http://127.0.0.1:3000        (com o painel do "npm run dev")
    python testes/demonstracao.py --api http://127.0.0.1:3000 --continuar 4
                                    (depois do vídeo, segue gerando um movimento a cada 4 s; Ctrl+C para sair)
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PORTA_ESP = 8081
BANCOS = {"arquivo": "arquivo no notebook (web/.dados)", "redis": "Upstash Redis",
          "memoria": "só na memória do servidor (some ao reiniciar)"}


def pedir_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def main():
    parser = argparse.ArgumentParser(description="Demonstração completa do estacionamento por simulação")
    parser.add_argument("--sequencia", default="EEESESEES", help="E = entrada, S = saída (padrão: 6 E e 3 S)")
    parser.add_argument("--api", default="", help="URL do painel (ex.: http://127.0.0.1:3000)")
    parser.add_argument("--ocupadas", type=int, default=0, help="ocupação inicial do ESP32 simulado")
    parser.add_argument("--continuar", type=float, default=0,
                        help="depois do vídeo, gera um movimento aleatório a cada N segundos")
    args = parser.parse_args()

    saida = RAIZ / "testes" / "saida"
    saida.mkdir(exist_ok=True)
    video = saida / "demonstracao.mp4"
    esperado_e, esperado_s = args.sequencia.upper().count("E"), args.sequencia.upper().count("S")

    print(f"1/4 Gerando o vídeo ({esperado_e} entradas, {esperado_s} saídas e 1 alarme falso)...")
    subprocess.run([sys.executable, str(RAIZ / "testes" / "gerar_video.py"), str(video), args.sequencia.upper()],
                   check=True, stdout=subprocess.DEVNULL)

    print("2/4 Ligando o ESP32 simulado...")
    cmd_esp = [sys.executable, "-u", str(RAIZ / "testes" / "esp32_simulado.py"),
               "--porta", str(PORTA_ESP), "--ocupadas", str(args.ocupadas), "--sinal", "5"]
    if args.api:
        cmd_esp += ["--api", args.api]
    esp = subprocess.Popen(cmd_esp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace")
    try:
        for _ in range(50):
            try:
                pedir_json(f"http://127.0.0.1:{PORTA_ESP}/estado")
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise SystemExit("O ESP32 simulado não respondeu.")

        print("3/4 Rodando a visão computacional sobre o vídeo...")
        subprocess.run([sys.executable, str(RAIZ / "visao.py"), "--fonte", str(video),
                        "--esp32", f"127.0.0.1:{PORTA_ESP}", "--sem-janela", "--porta", "8090"],
                       check=True, stdout=subprocess.DEVNULL)

        print("4/4 Conferindo o resultado...")
        if args.api:
            # espera a fila do ESP32 simulado chegar à nuvem
            for _ in range(60):
                if pedir_json(f"http://127.0.0.1:{PORTA_ESP}/estado")["fila_nuvem"] == 0:
                    break
                time.sleep(0.5)
        placa = pedir_json(f"http://127.0.0.1:{PORTA_ESP}/estado")
        ok = placa["entradas"] == esperado_e and placa["saidas"] == esperado_s
        print(f"   ESP32 simulado: {placa['entradas']} entradas, {placa['saidas']} saídas, "
              f"{placa['ocupadas']} ocupadas, {placa['livres']} vagas livres "
              f"({'confere com o vídeo' if ok else f'ESPERADO {esperado_e} entradas e {esperado_s} saídas'})")
        if args.api:
            painel = pedir_json(args.api.rstrip("/") + "/api/estado")
            e = painel.get("estado") or {}
            print(f"   Painel ({args.api}): {e.get('livres')} vagas livres, indicador {e.get('indicador')}, "
                  f"{len(painel.get('movimentos', []))} movimentos no histórico, "
                  f"dados em: {BANCOS.get(painel.get('armazenamento'), painel.get('armazenamento'))}")
            ok = ok and e.get("livres") == placa["livres"]

        if args.continuar > 0:
            esp.terminate()
            esp.wait()
            print(f"\nModo contínuo: um movimento aleatório a cada {args.continuar:g} s. Ctrl+C para sair.")
            cmd = cmd_esp + ["--aleatorio", str(args.continuar), "--ocupadas", str(placa["ocupadas"])]
            subprocess.run(cmd)
            return
        print("\nResultado: " + ("OK, a cadeia inteira funcionou." if ok else "DIVERGÊNCIA, veja acima."))
        sys.exit(0 if ok else 1)
    except KeyboardInterrupt:
        pass
    finally:
        if esp.poll() is None:
            esp.terminate()


if __name__ == "__main__":
    main()
