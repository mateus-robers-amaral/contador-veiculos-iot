"use client";

import { useEffect, useRef, useState } from "react";
import type { DadosPainel, HoraDoDia, Movimento } from "@/lib/tipos";

const INTERVALO_MS = 2500;
const FALHAS_PARA_AVISO = 2;   // uma resposta perdida não deve piscar o aviso
const FUSO = "America/Sao_Paulo";

const formatoHora = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit", second: "2-digit" });
const formatoHoraCurta = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit" });

function plural(n: number, um: string, varios: string) {
  return n === 1 ? um : varios;
}

function tempoDesde(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const min = Math.round(s / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return `${h} h ${String(min % 60).padStart(2, "0")} min`;
}

const ROTULO_STATUS = { livre: "LIVRE", quase: "QUASE LOTADO", lotado: "LOTADO" } as const;

// ---------------------------------------------------------------- ícones (Phosphor, preenchidos, MIT)

function Icone({ d }: { d: string }) {
  return <svg className="ph" viewBox="0 0 256 256" aria-hidden="true"><path d={d} /></svg>;
}
const ICONE_CHIP = "M104,104h48v48H104Zm136,48a8,8,0,0,1-8,8H216v40a16,16,0,0,1-16,16H160v16a8,8,0,0,1-16,0V216H112v16a8,8,0,0,1-16,0V216H56a16,16,0,0,1-16-16V160H24a8,8,0,0,1,0-16H40V112H24a8,8,0,0,1,0-16H40V56A16,16,0,0,1,56,40H96V24a8,8,0,0,1,16,0V40h32V24a8,8,0,0,1,16,0V40h40a16,16,0,0,1,16,16V96h16a8,8,0,0,1,0,16H216v32h16A8,8,0,0,1,240,152ZM168,96a8,8,0,0,0-8-8H96a8,8,0,0,0-8,8v64a8,8,0,0,0,8,8h64a8,8,0,0,0,8-8Z";
const ICONE_SEM_REDE = "M213.92,210.62a8,8,0,1,1-11.84,10.76l-33.67-37-28.1,33.88A15.93,15.93,0,0,1,128,224h0a15.93,15.93,0,0,1-12.31-5.77L11.65,92.8A15.65,15.65,0,0,1,8.11,80.91,15.93,15.93,0,0,1,14.28,70.1,188.26,188.26,0,0,1,46.6,50.35l-4.29-4.72a8.22,8.22,0,0,1,.13-11.38,8,8,0,0,1,11.48.37Zm34-129.71a15.93,15.93,0,0,0-6.17-10.81A186.67,186.67,0,0,0,128,32a191,191,0,0,0-42.49,4.75,4,4,0,0,0-2,6.59L186,156.07a4,4,0,0,0,6-.14L244.35,92.8A15.65,15.65,0,0,0,247.89,80.91Z";
const ICONE_LAPIS = "M227.31,73.37,182.63,28.68a16,16,0,0,0-22.63,0L36.69,152A15.86,15.86,0,0,0,32,163.31V208a16,16,0,0,0,16,16H92.69A15.86,15.86,0,0,0,104,219.31L227.31,96a16,16,0,0,0,0-22.63ZM192,108.68,147.31,64l24-24L216,84.68Z";
const ICONE_ALERTA = "M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm-8,56a8,8,0,0,1,16,0v56a8,8,0,0,1-16,0Zm8,104a12,12,0,1,1,12-12A12,12,0,0,1,128,184Z";
const ICONE_CARRO = "M240,112H211.31L168,68.69A15.86,15.86,0,0,0,156.69,64H44.28A16,16,0,0,0,31,71.12L1.34,115.56A8.07,8.07,0,0,0,0,120v48a16,16,0,0,0,16,16H33a32,32,0,0,0,62,0h66a32,32,0,0,0,62,0h17a16,16,0,0,0,16-16V128A16,16,0,0,0,240,112ZM44.28,80H156.69l32,32H23ZM64,192a16,16,0,1,1,16-16A16,16,0,0,1,64,192Zm128,0a16,16,0,1,1,16-16A16,16,0,0,1,192,192Z";

// ---------------------------------------------------------------- partes do painel

function Vagas({ dados, offline }: { dados: DadosPainel; offline: string | null }) {
  const e = dados.estado;
  if (!e) {
    return (
      <section className="hero lombada" aria-labelledby="t-vagas">
        <span className="rotulo" id="t-vagas">vagas livres</span>
        <div className="grande vazio-num">—</div>
        <div className="aguardando">
          <span className="icone-redondo"><Icone d={ICONE_CHIP} /></span>
          <div>
            <strong>Aguardando o primeiro sinal do ESP32</strong>
            <p>O banco ainda está vazio. Assim que a placa publicar o estado, as vagas aparecem aqui.
              Confira o <code>URL_API</code> e o <code>INGEST_TOKEN</code> no <code>segredos.h</code>.</p>
          </div>
        </div>
      </section>
    );
  }
  const pct = e.vagas ? (e.ocupadas / e.vagas) * 100 : 0;
  return (
    <section className={`hero lombada status-${e.indicador}`} aria-labelledby="t-vagas">
      <div className="hero-topo">
        <span className="rotulo" id="t-vagas">vagas livres agora</span>
        <span className={`carimbo grande-carimbo ${e.indicador}`}>{ROTULO_STATUS[e.indicador]}</span>
      </div>
      <div className="grande" aria-live="polite">
        {e.livres}<small>{plural(e.livres, "vaga livre", "vagas livres")} de {e.vagas}</small>
      </div>
      {offline && (
        <div className="faixa atencao dentro">
          <Icone d={ICONE_SEM_REDE} />
          <span>O ESP32 está sem sinal há {offline}. O número pode estar desatualizado.</span>
        </div>
      )}
      <div className="ocupacao">
        <div className="ocupacao-barra" role="meter" aria-label="Ocupação do estacionamento"
          aria-valuemin={0} aria-valuemax={e.vagas} aria-valuenow={e.ocupadas}>
          <i style={{ width: `${pct}%` }} />
          <span className="marca-90" aria-hidden="true" />
        </div>
        <div className="ocupacao-legenda mono">
          <span><b>{e.ocupadas}</b> {plural(e.ocupadas, "ocupada", "ocupadas")} · {Math.round(pct)}%</span>
          <span>quase lotado a partir de 90%</span>
        </div>
      </div>
    </section>
  );
}

function Frase({ dados, offline }: { dados: DadosPainel; offline: string | null }) {
  const { entradas, saidas, pico } = dados.hoje;
  return (
    <p className="frase" aria-live="polite">
      {entradas + saidas === 0 ? (
        <>Nenhum movimento registrado hoje.</>
      ) : (
        <>
          Hoje {plural(entradas, "entrou", "entraram")} <b>{entradas} {plural(entradas, "veículo", "veículos")}</b> e{" "}
          {plural(saidas, "saiu", "saíram")} <b>{saidas}</b>.
          {pico !== null && <> O pico foi às <b>{pico}h</b>.</>}
        </>
      )}
      {offline && <> <span className="alerta">O ESP32 está sem sinal há {offline}</span>.</>}
    </p>
  );
}

function Grafico({ horas, horaAtual }: { horas: HoraDoDia[]; horaAtual: number }) {
  const maximo = Math.max(1, ...horas.map((h) => Math.max(h.entradas, h.saidas)));
  const resumo = horas.filter((h) => h.entradas || h.saidas)
    .map((h) => `${h.hora}h: ${h.entradas} entradas e ${h.saidas} saídas`).join("; ");
  return (
    <section className="folha" aria-labelledby="t-grafico">
      <div className="rel-num">hoje, por hora</div>
      <div className="folha-cab"><h2 id="t-grafico">Entradas × saídas</h2></div>
      <div className="legenda"><span><i className="entrada" />entradas</span><span><i className="saida" />saídas</span></div>
      <div className="grafico" role="img" aria-label={`Entradas e saídas por hora hoje. ${resumo || "Nenhum movimento."}`}>
        <span className="maximo">{resumo ? `${maximo} ${plural(maximo, "veículo", "veículos")}` : "sem movimentos hoje"}</span>
        {horas.map((h) => (
          <div key={h.hora} className={`hora${h.hora === horaAtual ? " atual" : ""}`} title={`${h.hora}h: ${h.entradas} entradas, ${h.saidas} saídas`}>
            <i className="entrada" style={{ height: `${(h.entradas / maximo) * 100}%` }} />
            <i className="saida" style={{ height: `${(h.saidas / maximo) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="grafico-horas" aria-hidden="true">
        {horas.map((h) => (
          // um rótulo a cada 3 h, mais a hora atual; some o vizinho da hora atual para não sobrepor
          <span key={h.hora} className={h.hora === horaAtual ? "atual"
            : h.hora % 3 || Math.abs(h.hora - horaAtual) === 1 ? "oculta" : ""}>{h.hora}h</span>
        ))}
      </div>
    </section>
  );
}

function Movimentos({ movimentos, novos }: { movimentos: Movimento[]; novos: Set<string> }) {
  const [todos, setTodos] = useState(false);
  const lista = todos ? movimentos : movimentos.slice(0, 12);
  return (
    <section className="folha movimentos" aria-labelledby="t-mov">
      <div className="folha-cab">
        <h2 id="t-mov">Últimos movimentos</h2>
        <span className="mono">{movimentos.length ? `${movimentos.length} mais recentes` : "mais recentes no topo"}</span>
      </div>
      {movimentos.length === 0 ? (
        <div className="vazio">
          <span className="icone-redondo cinza"><Icone d={ICONE_CARRO} /></span>
          Nenhum movimento registrado ainda.
        </div>
      ) : (
        <div className="diario" aria-live="polite">
          {lista.map((m) => {
            const chave = `${m.seq}-${m.quando}`;
            return (
              <div key={chave} className={`entrada-diario${novos.has(chave) ? " nova" : ""}`}>
                <span className="d" title={new Date(m.quando).toLocaleDateString("pt-BR", { timeZone: FUSO })}>
                  {formatoHora.format(new Date(m.quando))}
                </span>
                <strong className={`etiqueta ${m.tipo}`}>
                  {m.tipo === "entrada" ? "ENTRADA" : m.tipo === "saida" ? "SAÍDA" : "AJUSTE"}
                </strong>
                <span className="det">
                  <b>{m.vagas - m.ocupadas}</b> {plural(m.vagas - m.ocupadas, "livre", "livres")}
                  {m.limitado && <span className="tag">{m.tipo === "entrada" ? "já estava lotado" : "já estava vazio"}</span>}
                </span>
              </div>
            );
          })}
        </div>
      )}
      {movimentos.length > 12 && (
        <button className="botao sec mini" onClick={() => setTodos(!todos)}>
          {todos ? "Mostrar menos" : `Mostrar todos (${movimentos.length})`}
        </button>
      )}
    </section>
  );
}

function StatusEsp({ dados, offline, agora, aoAjustar }:
  { dados: DadosPainel; offline: string | null; agora: number; aoAjustar: () => void }) {
  const e = dados.estado;
  const aj = dados.ajuste_pendente;
  return (
    <section className="folha status" aria-labelledby="t-esp">
      <div className="rel-num">controlador na entrada</div>
      <div className="folha-cab">
        <h2 id="t-esp">ESP32</h2>
        {!e ? <span className="carimbo tracejado">sem dados</span>
          : offline ? <span className="carimbo alerta">sem sinal há {offline}</span>
          : <span className="carimbo ok">conectado</span>}
      </div>
      <dl className="ficha">
        <div><dt>último sinal</dt><dd>{e ? `há ${tempoDesde(agora - e.ultimo_sinal)}` : "—"}</dd></div>
        <div><dt>às</dt><dd className="mono-g">{e ? formatoHoraCurta.format(new Date(e.ultimo_sinal)) : "—"}</dd></div>
        <div><dt>IP na rede</dt><dd className="mono-g">{e?.ip || "—"}</dd></div>
        <div><dt>Wi-Fi</dt><dd className="mono-g">{e ? `${String(e.rssi).replace("-", "−")} dBm` : "—"}</dd></div>
      </dl>
      {aj && (
        <div className="faixa ok dentro">
          <Icone d={ICONE_LAPIS} />
          <span>Ajuste para <b>{aj.ocupadas}</b> {plural(aj.ocupadas, "veículo", "veículos")} aguardando o ESP32 (aplica no próximo contato, em até 30 s).</span>
        </div>
      )}
      {dados.armazenamento === "memoria" && (
        <div className="faixa atencao dentro">
          <Icone d={ICONE_ALERTA} />
          <span>Banco Upstash não configurado: os dados estão só na memória do servidor e somem quando ele reinicia.</span>
        </div>
      )}
      <button className="botao sec" onClick={aoAjustar}><Icone d={ICONE_LAPIS} />Corrigir contagem</button>
    </section>
  );
}

function FormAjuste({ vagas, ocupadas, aoFechar, aoEnviar }:
  { vagas: number; ocupadas: number | null; aoFechar: () => void; aoEnviar: () => void }) {
  const [valor, setValor] = useState(ocupadas === null ? "" : String(ocupadas));
  const [pin, setPin] = useState("");
  const [msg, setMsg] = useState<{ tipo: "erro" | "ok"; texto: string } | null>(null);
  const [enviando, setEnviando] = useState(false);
  const campo = useRef<HTMLInputElement>(null);
  useEffect(() => campo.current?.focus(), []);

  async function enviar(ev: React.FormEvent) {
    ev.preventDefault();
    setEnviando(true);
    setMsg(null);
    try {
      const r = await fetch("/api/ajuste", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ocupadas: Number(valor), pin }),
      });
      const corpo = await r.json();
      if (!r.ok) throw new Error(corpo.erro ?? "Não foi possível enviar o ajuste.");
      setMsg({ tipo: "ok", texto: "Ajuste enviado. O ESP32 aplica no próximo contato, em até 30 s." });
      setPin("");
      aoEnviar();
    } catch (erro) {
      setMsg({ tipo: "erro", texto: erro instanceof Error ? erro.message : "Sem conexão com o servidor." });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form className="folha form-ajuste" onSubmit={enviar} aria-labelledby="t-ajuste">
      <div className="folha-cab"><h2 id="t-ajuste">Corrigir contagem</h2>
        <button type="button" className="botao sec mini" onClick={aoFechar}>Fechar</button></div>
      <p className="subtitulo">Use quando a câmera errar: conte os veículos que estão no estacionamento e informe o total.</p>
      <div className="campos">
        <div className="campo">
          <label htmlFor="f-ocupadas">Veículos no estacionamento</label>
          <input id="f-ocupadas" ref={campo} type="number" inputMode="numeric" min={0} max={vagas} required
            value={valor} onChange={(e) => setValor(e.target.value)} />
          <div className="dica">de 0 a {vagas}</div>
        </div>
        <div className="campo">
          <label htmlFor="f-pin">PIN</label>
          <input id="f-pin" type="password" inputMode="numeric" autoComplete="off" required
            value={pin} onChange={(e) => setPin(e.target.value)} />
        </div>
      </div>
      {msg && <div className={`faixa ${msg.tipo === "ok" ? "ok" : "erro"} dentro`} role="status">{msg.texto}</div>}
      <button className="botao" type="submit" disabled={enviando}>{enviando ? "Enviando…" : "Enviar ajuste"}</button>
    </form>
  );
}

// ---------------------------------------------------------------- painel

export default function Painel({ iniciais }: { iniciais: DadosPainel | null }) {
  const [dados, setDados] = useState<DadosPainel | null>(iniciais);
  const [falhas, setFalhas] = useState(iniciais ? 0 : FALHAS_PARA_AVISO);
  const [desvio, setDesvio] = useState(0);         // relógio do servidor − relógio do celular
  const [agora, setAgora] = useState(() => iniciais?.agora ?? Date.now());
  const [ajustando, setAjustando] = useState(false);
  const [novos, setNovos] = useState<Set<string>>(new Set());
  const vistos = useRef<Set<string> | null>(iniciais ? new Set(iniciais.movimentos.map((m) => `${m.seq}-${m.quando}`)) : null);

  async function atualizar() {
    try {
      const r = await fetch("/api/estado", { cache: "no-store", signal: AbortSignal.timeout(6000) });
      if (!r.ok) throw new Error(String(r.status));
      const d: DadosPainel = await r.json();
      const chaves = d.movimentos.map((m) => `${m.seq}-${m.quando}`);
      if (vistos.current) setNovos(new Set(chaves.filter((c) => !vistos.current!.has(c))));
      vistos.current = new Set(chaves);
      setDesvio(d.agora - Date.now());
      setDados(d);
      setFalhas(0);
    } catch {
      setFalhas((f) => f + 1);
    }
  }

  useEffect(() => {
    atualizar();
    const id = setInterval(atualizar, INTERVALO_MS);
    const relogio = setInterval(() => setAgora(Date.now() + desvio), 1000);
    return () => { clearInterval(id); clearInterval(relogio); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desvio]);

  const semApi = falhas >= FALHAS_PARA_AVISO;
  const e = dados?.estado ?? null;
  const offline = e && agora - e.ultimo_sinal >= 75_000 ? tempoDesde(agora - e.ultimo_sinal) : null;
  const horaAtual = Number(new Intl.DateTimeFormat("en-GB", { timeZone: FUSO, hour: "2-digit", hourCycle: "h23" }).format(agora));

  return (
    <main className="principal">
      {semApi && (
        <div className="faixa erro topo" role="alert">
          <Icone d={ICONE_SEM_REDE} />
          <span>{dados ? "Sem conexão com o servidor. Mostrando os últimos dados recebidos; tentando de novo…"
            : "Não foi possível carregar o painel. Tentando de novo…"}</span>
        </div>
      )}

      <header className="cabecalho">
        <div className="kicker">FATEC Pompeia · Big Data no Agronegócio</div>
        <h1>Estacionamento</h1>
      </header>

      {dados ? (
        <div className="colunas">
          <div className="coluna">
            <Vagas dados={dados} offline={offline} />
            <Frase dados={dados} offline={offline} />
            <Grafico horas={dados.horas} horaAtual={horaAtual} />
          </div>
          <div className="coluna lateral-dados">
            <Movimentos movimentos={dados.movimentos} novos={novos} />
            <StatusEsp dados={dados} offline={offline} agora={agora} aoAjustar={() => setAjustando(true)} />
            {ajustando && (
              <FormAjuste vagas={e?.vagas ?? 100} ocupadas={e?.ocupadas ?? null}
                aoFechar={() => setAjustando(false)} aoEnviar={atualizar} />
            )}
          </div>
        </div>
      ) : (
        <section className="folha vazio grande-vazio">
          <span className="icone-redondo cinza"><Icone d={ICONE_SEM_REDE} /></span>
          <strong>O painel não conseguiu falar com o servidor.</strong>
          <span>Verifique a internet. A página tenta de novo sozinha a cada poucos segundos.</span>
        </section>
      )}

      <footer className="rodape mono">
        Contagem oficial no ESP32 da entrada · atualiza a cada {INTERVALO_MS / 1000} s · Pompeia/SP
      </footer>
    </main>
  );
}
