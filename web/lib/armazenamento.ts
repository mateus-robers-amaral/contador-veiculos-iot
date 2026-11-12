// Onde o estado do estacionamento fica guardado.
//
// NO NOTEBOOK (modo usado no projeto): um arquivo JSON em web/.dados/estacionamento.json.
// Os dados ficam na memória do processo e são gravados no arquivo a cada mudança, então o
// histórico sobrevive quando o "npm run dev" é reiniciado. O arquivo fica fora do Git.
//
// NA NUVEM (opcional): Upstash Redis (integração do Marketplace da Vercel). A integração cria
// as variáveis KV_REST_API_URL e KV_REST_API_TOKEN; as do Upstash direto
// (UPSTASH_REDIS_REST_URL e UPSTASH_REDIS_REST_TOKEN) também servem. Se elas existirem, o
// Redis é usado mesmo no notebook.
//
// Na Vercel sem Redis não dá para gravar arquivo: os dados ficam só na memória, somem quando
// a função reinicia, e o painel mostra um aviso.

import fs from "node:fs";
import path from "node:path";
import { Redis } from "@upstash/redis";
import type { Ajuste, EstadoEsp, Movimento } from "./tipos";

const MAX_MOVIMENTOS = 50;
const DIAS_HISTORICO = 8;
const PREFIXO = "estacionamento:";
const ARQUIVO_LOCAL = path.join(process.cwd(), ".dados", "estacionamento.json");

export interface Armazenamento {
  tipo: "redis" | "arquivo" | "memoria";
  lerEstado(): Promise<EstadoEsp | null>;
  salvarEstado(estado: EstadoEsp): Promise<void>;
  /** Grava movimentos novos (mais antigos primeiro) e soma entradas/saídas no dia e hora indicados. */
  registrarMovimentos(itens: { movimento: Movimento; dia: string; hora: number }[]): Promise<void>;
  lerMovimentos(): Promise<Movimento[]>;
  /** Entradas e saídas por hora de um dia ("AAAA-MM-DD"); chaves "HH:entrada" e "HH:saida". */
  lerHoras(dia: string): Promise<Record<string, number>>;
  lerAjuste(): Promise<Ajuste | null>;
  salvarAjuste(ajuste: Ajuste): Promise<void>;
  limparAjuste(): Promise<void>;
  proximoIdAjuste(minimo: number): Promise<number>;
  /** Conta uma tentativa errada de PIN e devolve quantas houve na janela de tempo. */
  registrarErroPin(chave: string, janelaS: number): Promise<number>;
  errosPin(chave: string): Promise<number>;
}

function campoHora(hora: number, tipo: "entrada" | "saida") {
  return `${String(hora).padStart(2, "0")}:${tipo}`;
}

// ---------------------------------------------------------------- Upstash Redis

class ArmazenamentoRedis implements Armazenamento {
  tipo = "redis" as const;
  constructor(private redis: Redis) {}

  lerEstado() {
    return this.redis.get<EstadoEsp>(PREFIXO + "estado");
  }
  async salvarEstado(estado: EstadoEsp) {
    await this.redis.set(PREFIXO + "estado", estado);
  }
  async registrarMovimentos(itens: { movimento: Movimento; dia: string; hora: number }[]) {
    if (!itens.length) return;
    const p = this.redis.pipeline();
    for (const { movimento, dia, hora } of itens) {
      p.lpush(PREFIXO + "movimentos", movimento);
      if (movimento.tipo !== "ajuste") {
        p.hincrby(PREFIXO + "horas:" + dia, campoHora(hora, movimento.tipo), 1);
        p.expire(PREFIXO + "horas:" + dia, DIAS_HISTORICO * 86400);
      }
    }
    p.ltrim(PREFIXO + "movimentos", 0, MAX_MOVIMENTOS - 1);
    await p.exec();
  }
  async lerMovimentos() {
    return (await this.redis.lrange<Movimento>(PREFIXO + "movimentos", 0, MAX_MOVIMENTOS - 1)) ?? [];
  }
  async lerHoras(dia: string) {
    return (await this.redis.hgetall<Record<string, number>>(PREFIXO + "horas:" + dia)) ?? {};
  }
  lerAjuste() {
    return this.redis.get<Ajuste>(PREFIXO + "ajuste");
  }
  async salvarAjuste(ajuste: Ajuste) {
    await this.redis.set(PREFIXO + "ajuste", ajuste);
  }
  async limparAjuste() {
    await this.redis.del(PREFIXO + "ajuste");
  }
  async proximoIdAjuste(minimo: number) {
    const id = await this.redis.incr(PREFIXO + "ajuste:contador");
    if (id > minimo) return id;
    await this.redis.set(PREFIXO + "ajuste:contador", minimo + 1);
    return minimo + 1;
  }
  async registrarErroPin(chave: string, janelaS: number) {
    const k = PREFIXO + "pin:" + chave;
    const n = await this.redis.incr(k);
    if (n === 1) await this.redis.expire(k, janelaS);
    return n;
  }
  async errosPin(chave: string) {
    return (await this.redis.get<number>(PREFIXO + "pin:" + chave)) ?? 0;
  }
}

// ---------------------------------------------------------------- notebook (arquivo) ou só memória

/** O que vai para o arquivo. As tentativas de PIN ficam só na memória. */
interface DadosArquivo {
  estado: EstadoEsp | null;
  movimentos: Movimento[];
  horas: Record<string, Record<string, number>>;
  ajuste: Ajuste | null;
  contadorAjuste: number;
}

class ArmazenamentoLocal implements Armazenamento {
  tipo: "arquivo" | "memoria";
  private estado: EstadoEsp | null = null;
  private movimentos: Movimento[] = [];
  private horas = new Map<string, Record<string, number>>();
  private ajuste: Ajuste | null = null;
  private contadorAjuste = 0;
  private pins = new Map<string, { n: number; expira: number }>();

  /** Sem arquivo, os dados ficam só na memória. */
  constructor(private arquivo: string | null) {
    this.tipo = arquivo ? "arquivo" : "memoria";
    if (arquivo) this.carregar(arquivo);
  }

  private carregar(arquivo: string) {
    if (!fs.existsSync(arquivo)) return;
    try {
      const d = JSON.parse(fs.readFileSync(arquivo, "utf8")) as Partial<DadosArquivo>;
      this.estado = d.estado ?? null;
      this.movimentos = d.movimentos ?? [];
      this.horas = new Map(Object.entries(d.horas ?? {}));
      this.ajuste = d.ajuste ?? null;
      this.contadorAjuste = d.contadorAjuste ?? 0;
    } catch (erro) {
      console.warn(`[estacionamento] Não consegui ler ${arquivo}; começando do zero.`, erro);
    }
  }

  private gravar() {
    if (!this.arquivo) return;
    // guarda só os últimos dias do gráfico por hora, como o Redis faz com o prazo de expiração
    for (const dia of [...this.horas.keys()].sort().slice(0, -DIAS_HISTORICO)) this.horas.delete(dia);
    const dados: DadosArquivo = {
      estado: this.estado,
      movimentos: this.movimentos,
      horas: Object.fromEntries(this.horas),
      ajuste: this.ajuste,
      contadorAjuste: this.contadorAjuste,
    };
    try {
      fs.mkdirSync(path.dirname(this.arquivo), { recursive: true });
      fs.writeFileSync(this.arquivo, JSON.stringify(dados, null, 1));
    } catch (erro) {
      console.warn(`[estacionamento] Não consegui gravar ${this.arquivo}.`, erro);
    }
  }

  async lerEstado() {
    return this.estado;
  }
  async salvarEstado(estado: EstadoEsp) {
    this.estado = estado;
    this.gravar();
  }
  async registrarMovimentos(itens: { movimento: Movimento; dia: string; hora: number }[]) {
    for (const { movimento, dia, hora } of itens) {
      this.movimentos.unshift(movimento);
      if (movimento.tipo !== "ajuste") {
        const h = this.horas.get(dia) ?? {};
        const campo = campoHora(hora, movimento.tipo);
        h[campo] = (h[campo] ?? 0) + 1;
        this.horas.set(dia, h);
      }
    }
    this.movimentos.length = Math.min(this.movimentos.length, MAX_MOVIMENTOS);
    this.gravar();
  }
  async lerMovimentos() {
    return this.movimentos;
  }
  async lerHoras(dia: string) {
    return this.horas.get(dia) ?? {};
  }
  async lerAjuste() {
    return this.ajuste;
  }
  async salvarAjuste(ajuste: Ajuste) {
    this.ajuste = ajuste;
    this.gravar();
  }
  async limparAjuste() {
    this.ajuste = null;
    this.gravar();
  }
  async proximoIdAjuste(minimo: number) {
    this.contadorAjuste = Math.max(this.contadorAjuste, minimo) + 1;
    this.gravar();
    return this.contadorAjuste;
  }
  async registrarErroPin(chave: string, janelaS: number) {
    const agora = Date.now();
    const atual = this.pins.get(chave);
    const item = atual && atual.expira > agora ? atual : { n: 0, expira: agora + janelaS * 1000 };
    item.n++;
    this.pins.set(chave, item);
    return item.n;
  }
  async errosPin(chave: string) {
    const item = this.pins.get(chave);
    return item && item.expira > Date.now() ? item.n : 0;
  }
}

// ---------------------------------------------------------------- escolha

const globalParaHmr = globalThis as unknown as { __armazenamento?: Armazenamento };

export function armazenamento(): Armazenamento {
  if (globalParaHmr.__armazenamento) return globalParaHmr.__armazenamento;
  const url = process.env.KV_REST_API_URL ?? process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN ?? process.env.UPSTASH_REDIS_REST_TOKEN;
  if (url && token) {
    globalParaHmr.__armazenamento = new ArmazenamentoRedis(new Redis({ url, token }));
  } else if (process.env.VERCEL) {
    console.warn("[estacionamento] Upstash Redis não configurado: usando só a memória da função.");
    globalParaHmr.__armazenamento = new ArmazenamentoLocal(null);
  } else {
    globalParaHmr.__armazenamento = new ArmazenamentoLocal(ARQUIVO_LOCAL);
  }
  return globalParaHmr.__armazenamento;
}
