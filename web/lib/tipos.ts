// Formatos guardados no banco e devolvidos ao painel.

export type TipoMovimento = "entrada" | "saida" | "ajuste";

/** Último estado publicado pelo ESP32. */
export interface EstadoEsp {
  instancia: number;        // muda se a flash do ESP32 for apagada (a sequência recomeça)
  seq: number;
  vagas: number;
  ocupadas: number;
  ajuste_aplicado: number;
  ip: string;
  rssi: number;
  uptime_s: number;
  ultimo_sinal: number;     // epoch ms, marcado pela API
  ultimo_mov_seq: number;   // maior seq de movimento já registrado (para ignorar reenvios)
}

export interface Movimento {
  seq: number;
  tipo: TipoMovimento;
  ocupadas: number;         // ocupadas depois do movimento
  vagas: number;
  limitado: boolean;        // entrada com lotado ou saída com vazio: a contagem não mudou
  quando: string;           // ISO: hora em que a API recebeu, menos o tempo que esperou na fila do ESP32
}

/** Correção manual pedida pelo painel, esperando o ESP32 aplicar. */
export interface Ajuste {
  id: number;
  ocupadas: number;
  criado_em: string;
}

export interface HoraDoDia {
  hora: number;             // 0 a 23, horário de Brasília
  entradas: number;
  saidas: number;
}

/** Resposta de GET /api/estado. */
export interface DadosPainel {
  agora: number;
  armazenamento: "redis" | "memoria";
  estado: (Omit<EstadoEsp, "instancia" | "ultimo_mov_seq" | "ajuste_aplicado"> & {
    livres: number;
    indicador: "livre" | "quase" | "lotado";
    online: boolean;
  }) | null;
  movimentos: Movimento[];
  horas: HoraDoDia[];
  hoje: { entradas: number; saidas: number; pico: number | null };
  ajuste_pendente: Ajuste | null;
}
