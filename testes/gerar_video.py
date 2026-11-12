"""
Gera um vídeo sintético de teste: retângulos coloridos (os "carros") atravessando as faixas.

A faixa A fica à esquerda (lado da rua, 40% da largura) e a B à direita (60%), que é o
padrão do visao.py. Quem anda da esquerda para a direita está ENTRANDO; quem anda da
direita para a esquerda está SAINDO.

Uso:
    python testes/gerar_video.py teste.mp4                 (sequência padrão)
    python testes/gerar_video.py teste.mp4 EESESEEES       (E = entrada, S = saída)

Também inclui um alarme falso: um objeto que entra só na faixa A e volta. Ele não deve ser contado.
"""

import sys

import cv2
import numpy as np

LARG, ALT, FPS = 640, 360, 30
CORES = [(40, 40, 200), (200, 120, 30), (30, 180, 220), (240, 240, 240), (60, 160, 60), (20, 20, 20),
         (180, 60, 180), (0, 140, 255)]


def gerar(saida, sequencia):
    video = cv2.VideoWriter(saida, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (LARG, ALT))
    rng = np.random.default_rng(1)
    fundo = np.full((ALT, LARG, 3), (90, 92, 95), np.uint8)
    fundo += rng.integers(0, 6, fundo.shape, dtype=np.uint8)
    cv2.line(fundo, (0, ALT // 2), (LARG, ALT // 2), (220, 220, 220), 2)

    def vazio(n):
        for _ in range(n):
            video.write(fundo)

    def carro(cx, y, cor):
        quadro = fundo.copy()
        cv2.rectangle(quadro, (cx - 60, y), (cx + 60, y + 55), cor, -1)
        video.write(quadro)

    vazio(60)   # o programa aprende o fundo
    for i, letra in enumerate(sequencia):
        cor = CORES[i % len(CORES)]
        y = ALT // 2 - 70 if letra == "E" else ALT // 2 + 20
        for x in range(-150, LARG + 150, 8):
            carro(x if letra == "E" else LARG - x, y, cor)
        vazio(30)
        if i == 1:
            # alarme falso: chega até a faixa A e volta (não pode contar)
            for x in list(range(-150, 230, 8)) + list(range(230, -150, -8)):
                carro(x, ALT // 2 - 70, (120, 200, 200))
            vazio(30)
    video.release()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sequencia = (sys.argv[2] if len(sys.argv) > 2 else "EESESEEES").upper()
    if set(sequencia) - {"E", "S"}:
        raise SystemExit("A sequência só pode ter as letras E (entrada) e S (saída).")
    gerar(sys.argv[1], sequencia)
    print(f"{sys.argv[1]}: {sequencia.count('E')} entradas e {sequencia.count('S')} saídas, "
          f"mais 1 alarme falso que não deve ser contado.")
