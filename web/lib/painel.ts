// Regras do estacionamento do lado do painel: o que fazer com cada publicação do ESP32
// e como montar os dados do painel.

import { timingSafeEqual } from "node:crypto";
import { armazenamento } from "./armazenamento";
import type { DadosPainel, EstadoEsp, HoraDoDia, Movimento, TipoMovimento } from "./tipos";

export const FUSO = "America/Sao_Paulo";
export const ONLINE_ATE_S = 75;   // o ESP32 manda sinal de vida a cada 30 s; 75 s tolera uma falha
const QUASE_LOTADO = 0.9;

/** Compara segredos em tempo constante (não revela quantos caracteres acertou). */
export function segredoConfere(recebido: string, esperado: string) {
  const a = Buffer.from(recebido);
  const b = Buffer.from(esperado);
  return a.length === b.length && timingSafeEqual(a, b);
}

/** Dia ("AAAA-MM-DD") e hora (0-23) no horário de Brasília. */
export function diaEHora(quando: Date) {
  const partes = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone: FUSO, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23" })
      .formatToParts(quando)
      .map((p) => [p.type, p.value]),
  );
  return { dia: `${partes.year}-${partes.month}-${partes.day}`, hora: Number(partes.hour) };
}

export function indicador(ocupadas: number, vagas: number): "livre" | "quase" | "lotado" {
  if (ocupadas >= vagas) return "lotado";
  return ocupadas >= vagas * QUASE_LOTADO ? "quase" : "livre";
}

// ---------------------------------------------------------------- publicação do ESP32

const inteiro = (v: unknown, min: number, max: number) =>
  typeof v === "number" && Number.isInteger(v) && v >= min && v <= max ? v : null;

export interface Publicacao {
  instancia: number;
  seq: number;
  vagas: number;
  ocupadas: number;
  ajuste_aplicado: number;
  ip: string;
  rssi: number;
  uptime_s: number;
  movimentos: { seq: number; tipo: TipoMovimento; ocupadas: number; limitado: boolean; atraso_ms: number }[];
}

/** Valida o corpo enviado pelo ESP32. Devolve a mensagem de erro ou os dados prontos. */
export function validarPublicacao(corpo: unknown): Publicacao | string {
  if (!corpo || typeof corpo !== "object") return "corpo JSON esperado";
  const c = corpo as Record<string, unknown>;
  const vagas = inteiro(c.vagas, 1, 100000);
  if (vagas === null) return "vagas inválido";
  const ocupadas = inteiro(c.ocupadas, 0, vagas);
  const instancia = inteiro(c.instancia, 0, 2 ** 32);
  const seq = inteiro(c.seq, 0, 2 ** 32);
  if (ocupadas === null || instancia === null || seq === null) return "ocupadas, instancia e seq devem ser inteiros válidos";
  const lista = Array.isArray(c.movimentos) ? c.movimentos : [];
  if (lista.length > 50) return "no máximo 50 movimentos por envio";
  const movimentos: Publicacao["movimentos"] = [];
  for (const m of lista) {
    const mov = (m ?? {}) as Record<string, unknown>;
    const tipo = mov.tipo;
    const mSeq = inteiro(mov.seq, 0, 2 ** 32);
    const mOcup = inteiro(mov.ocupadas, 0, vagas);
    if ((tipo !== "entrada" && tipo !== "saida" && tipo !== "ajuste") || mSeq === null || mOcup === null) {
      return "movimento inválido";
    }
    movimentos.push({ seq: mSeq, tipo, ocupadas: mOcup, limitado: mov.limitado === true,
      atraso_ms: inteiro(mov.atraso_ms, 0, 7 * 86400_000) ?? 0 });
  }
  return {
    instancia, seq, vagas, ocupadas, movimentos,
    ajuste_aplicado: inteiro(c.ajuste_aplicado, 0, 2 ** 32) ?? 0,
    ip: typeof c.ip === "string" ? c.ip.slice(0, 45) : "",
    rssi: inteiro(c.rssi, -127, 0) ?? 0,
    uptime_s: inteiro(c.uptime_s, 0, 2 ** 32) ?? 0,
  };
}

/** Registra a publicação e devolve quantos movimentos eram novos e o ajuste pendente (se houver). */
export async function registrarPublicacao(p: Publicacao) {
  const banco = armazenamento();
  const agora = Date.now();
  const anterior = await banco.lerEstado();
  // a mesma instância nunca repete seq; se a flash do ESP32 foi apagada, a instância muda e a sequência recomeça
  const ultimoSeq = anterior && anterior.instancia === p.instancia ? anterior.ultimo_mov_seq : -1;

  const novos = p.movimentos.filter((m) => m.seq > ultimoSeq).sort((a, b) => a.seq - b.seq);
  await banco.registrarMovimentos(novos.map((m) => {
    const quando = new Date(agora - m.atraso_ms);
    const movimento: Movimento = { seq: m.seq, tipo: m.tipo, ocupadas: m.ocupadas, vagas: p.vagas,
      limitado: m.limitado, quando: quando.toISOString() };
    return { movimento, ...diaEHora(quando) };
  }));

  const estado: EstadoEsp = {
    instancia: p.instancia, seq: p.seq, vagas: p.vagas, ocupadas: p.ocupadas,
    ajuste_aplicado: p.ajuste_aplicado, ip: p.ip, rssi: p.rssi, uptime_s: p.uptime_s,
    ultimo_sinal: agora,
    ultimo_mov_seq: Math.max(ultimoSeq, ...novos.map((m) => m.seq)),
  };
  await banco.salvarEstado(estado);

  // o ajuste manual viaja na resposta; quando o ESP32 avisa que aplicou, ele sai da fila
  let ajuste = await banco.lerAjuste();
  if (ajuste && p.ajuste_aplicado >= ajuste.id) {
    await banco.limparAjuste();
    ajuste = null;
  }
  return { novos: novos.length, ajuste };
}

// ---------------------------------------------------------------- dados do painel

export async function montarDados(): Promise<DadosPainel> {
  const banco = armazenamento();
  const agora = Date.now();
  const { dia } = diaEHora(new Date(agora));
  const [estado, movimentos, horasBrutas, ajuste] = await Promise.all([
    banco.lerEstado(), banco.lerMovimentos(), banco.lerHoras(dia), banco.lerAjuste(),
  ]);

  const horas: HoraDoDia[] = Array.from({ length: 24 }, (_, hora) => {
    const hh = String(hora).padStart(2, "0");
    return { hora, entradas: Number(horasBrutas[`${hh}:entrada`] ?? 0), saidas: Number(horasBrutas[`${hh}:saida`] ?? 0) };
  });
  const entradas = horas.reduce((s, h) => s + h.entradas, 0);
  const saidas = horas.reduce((s, h) => s + h.saidas, 0);
  const pico = entradas ? horas.reduce((a, b) => (b.entradas > a.entradas ? b : a)).hora : null;

  return {
    agora,
    armazenamento: banco.tipo,
    estado: estado && {
      seq: estado.seq, vagas: estado.vagas, ocupadas: estado.ocupadas,
      livres: estado.vagas - estado.ocupadas, indicador: indicador(estado.ocupadas, estado.vagas),
      ip: estado.ip, rssi: estado.rssi, uptime_s: estado.uptime_s, ultimo_sinal: estado.ultimo_sinal,
      online: agora - estado.ultimo_sinal < ONLINE_ATE_S * 1000,
    },
    movimentos,
    horas,
    hoje: { entradas, saidas, pico },
    ajuste_pendente: ajuste,
  };
}
