// Painel do contador de veículos: busca /dados a cada 500 ms e só mexe no que mudou.
// A estrutura da página já vem pronta no HTML; aqui só trocamos textos, classes e larguras.
'use strict';

const $ = (id) => document.getElementById(id);
const INTERVALO_MS = 500;
const FALHAS_PARA_AVISO = 2;   // uma resposta perdida no Wi-Fi não deve piscar o aviso

const formatoCm = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const formatoPct = new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 0 });

// ---------------------------------------------------------------- utilidades

function texto(el, valor) {
  const s = String(valor);
  if (el.textContent !== s) el.textContent = s;
}
function html(el, valor) {   // só para trechos montados aqui, nunca com dados do ESP32
  if (el.dataset.html !== valor) { el.innerHTML = valor; el.dataset.html = valor; }
}
function mostrar(el, visivel) {
  if (el.hidden === visivel) el.hidden = !visivel;
}
function classe(el, nome, ligada) {
  if (el.classList.contains(nome) !== ligada) el.classList.toggle(nome, ligada);
}
function largura(el, pct) {
  const v = Math.max(0, Math.min(100, pct)).toFixed(1) + '%';
  if (el.style.width !== v) el.style.width = v;
}
function plural(n, um, varios) {
  return n === 1 ? um : varios;
}
function comSinal(n) {
  return n > 0 ? '+' + n : n < 0 ? '−' + Math.abs(n) : '0';
}

function carimboFaixa(el, nome, ocupada) {
  texto(el, `${nome} · faixa ${ocupada ? 'ocupada' : 'livre'}`);
  classe(el, 'ocupada', ocupada);
}

// Barra segmentada de duas partes (ida × volta ou leve × pesado).
function barra(el, legenda, a, b, nomeA, nomeB, vazioTxt) {
  const total = a + b;
  classe(el, 'zerada', total === 0);
  const [segA, segB] = el.children;
  const ga = String(total ? a : 1), gb = String(total ? b : 1);
  if (segA.style.flexGrow !== ga) segA.style.flexGrow = ga;
  if (segB.style.flexGrow !== gb) segB.style.flexGrow = gb;
  texto(legenda, total
    ? `${formatoPct.format(a / total)} ${nomeA} · ${formatoPct.format(b / total)} ${nomeB}`
    : vazioTxt);
}

// ---------------------------------------------------------------- frase-resumo

function atualizarFrase(cam, esp) {
  const base = cam || esp;
  const onde = cam ? 'pela câmera' : 'pelo ESP32';
  let s;
  if (base.total === 0) {
    s = `Nenhum veículo passou ${onde} ainda.`;
  } else {
    s = `<b>${base.total} ${plural(base.total, 'veículo', 'veículos')}</b> ${plural(base.total, 'passou', 'passaram')} ${onde}, ` +
        `<b>${base.ida} de ida</b> e <b>${base.volta} de volta</b>.`;
  }
  if (!esp.online) {
    s += ' <span class="alerta">O ESP32 está desconectado</span>.';
  } else if (cam) {
    const dif = Math.abs(cam.total - esp.total);
    s += dif === 0 ? ' A câmera e o ESP32 concordam.' : ` A câmera e o ESP32 diferem em <b>${dif}</b>.`;
  } else {
    s += ' O ESP32 está conectado.';
  }
  html($('frase'), s);
}

// ---------------------------------------------------------------- câmera

let cameraAtiva = false;

function atualizarCamera(cam) {
  cameraAtiva = Boolean(cam);
  mostrar($('c-ativa'), cameraAtiva);
  mostrar($('c-desligada'), !cameraAtiva);
  if (!cam) return;
  carimboFaixa($('c-fa'), 'A', cam.faixa_a);
  carimboFaixa($('c-fb'), 'B', cam.faixa_b);
  texto($('c-total'), cam.total);
  texto($('c-ida'), cam.ida);
  texto($('c-volta'), cam.volta);
  barra($('c-barra'), $('c-prop'), cam.ida, cam.volta, 'ida', 'volta', 'sem passagens ainda');
}

// A imagem é baixada à parte e só entra na tela depois de decodificada:
// assim nunca aparece quebrada nem pisca. Duas falhas seguidas mostram o estado vazio.
let falhasQuadro = 0;
let urlAnterior = null;

async function buscarQuadro() {
  if (!cameraAtiva || document.hidden) return 1000;
  try {
    const resposta = await fetch('/quadro.jpg', { cache: 'no-store' });
    if (!resposta.ok) throw new Error(resposta.status);
    const url = URL.createObjectURL(await resposta.blob());
    const nova = new Image();
    nova.src = url;
    await nova.decode();
    const img = $('c-img');
    img.src = url;
    if (urlAnterior) URL.revokeObjectURL(urlAnterior);
    urlAnterior = url;
    falhasQuadro = 0;
    mostrar(img, true);
    mostrar($('c-ao-vivo'), true);
    mostrar($('c-sem-img'), false);
    return 200;
  } catch {
    falhasQuadro += 1;
    if (falhasQuadro >= 2) {
      mostrar($('c-img'), false);
      mostrar($('c-ao-vivo'), false);
      mostrar($('c-sem-img'), true);
    }
    return 1000;
  }
}

async function cicloQuadro() {
  const espera = await buscarQuadro();
  setTimeout(cicloQuadro, espera);
}

// ---------------------------------------------------------------- ESP32

function atualizarEsp(esp) {
  const s = esp.status || {};
  const on = esp.online;
  const conexao = $('e-conexao');
  texto(conexao, on ? 'conectado' : 'desconectado');
  classe(conexao, 'ok', on);
  classe(conexao, 'alerta', !on);
  mostrar($('e-sem-sinal'), !on);
  classe($('e-leituras'), 'desligado', !on);

  texto($('e-ip'), on && s.ip ? s.ip : '—');

  // sinal Wi-Fi: −90 dBm (péssimo) a −40 dBm (ótimo)
  const medRssi = $('e-rssi-med');
  if (on && typeof s.rssi === 'number') {
    const pct = (s.rssi + 90) / 50 * 100;
    const nivel = s.rssi >= -67 ? 'bom' : s.rssi >= -80 ? 'regular' : 'fraco';
    texto($('e-rssi'), `${String(s.rssi).replace('-', '−')} dBm · ${nivel}`);
    largura(medRssi.firstElementChild, pct);
    classe(medRssi, 'fraco', nivel === 'fraco');
    medRssi.setAttribute('aria-valuenow', s.rssi);
  } else {
    texto($('e-rssi'), '—');
    largura(medRssi.firstElementChild, 0);
    medRssi.removeAttribute('aria-valuenow');
  }

  // ultrassom: barra cheia = nada entre o sensor e o chão
  const medDist = $('e-dist-med');
  const temDist = on && typeof s.distancia_cm === 'number' && s.distancia_cm >= 0;
  const temRef = on && typeof s.referencia_cm === 'number' && s.referencia_cm > 0;
  texto($('e-dist'), temDist ? formatoCm.format(s.distancia_cm) + ' cm' : on ? 'sem leitura' : '—');
  texto($('e-ref'), temRef ? formatoCm.format(s.referencia_cm) + ' cm' : '—');
  if (temDist && temRef) {
    const pct = s.distancia_cm / s.referencia_cm * 100;
    const altura = s.referencia_cm - s.distancia_cm;
    largura(medDist.firstElementChild, pct);
    medDist.setAttribute('aria-valuenow', Math.round(Math.min(100, pct)));
    texto($('e-altura'), altura >= 1 ? `objeto de ${formatoCm.format(altura)} cm` : 'pista livre');
  } else {
    largura(medDist.firstElementChild, 0);
    medDist.removeAttribute('aria-valuenow');
    texto($('e-altura'), on ? 'chão ainda não medido' : 'sem leitura');
  }

  for (const [id, nome, ocupada] of [['e-fa', 'A', s.faixa_a], ['e-fb', 'B', s.faixa_b]]) {
    if (on) carimboFaixa($(id), nome, Boolean(ocupada));
    else { texto($(id), `${nome} · sem leitura`); classe($(id), 'ocupada', false); }
    classe($(id), 'tracejado', !on);
  }

  const fila = on ? Number(s.pendentes) || 0 : 0;
  mostrar($('e-fila'), fila > 0);
  if (fila > 0) {
    texto($('e-fila-texto'), `${fila} ${plural(fila, 'passagem está', 'passagens estão')} na fila do ESP32, aguardando envio.`);
  }

  texto($('e-total'), esp.total);
  texto($('e-ida'), esp.ida);
  texto($('e-volta'), esp.volta);
  texto($('e-leves'), esp.leves);
  texto($('e-pesados'), esp.pesados);
  barra($('e-barra'), $('e-prop'), esp.ida, esp.volta, 'ida', 'volta', 'sem passagens ainda');
  barra($('e-barra-cat'), $('e-prop-cat'), esp.leves, esp.pesados, 'leves', 'pesados',
    'classificados pela altura no ultrassom');
}

// ---------------------------------------------------------------- comparação

function celulaDif(el, a, b) {
  texto(el, a === null ? '—' : comSinal(a - b));
}

function atualizarComparacao(cam, esp) {
  texto($('m-camera'), cam ? cam.total : '—');
  texto($('m-esp'), esp.total);
  const dif = $('m-dif');
  if (cam) {
    const d = cam.total - esp.total;
    texto(dif, Math.abs(d));
    texto($('m-dif-txt'), d === 0 ? 'iguais' : d > 0 ? 'câmera contou mais' : 'ESP32 contou mais');
    classe(dif.parentElement, 'diverge', d !== 0);
  } else {
    texto(dif, '—');
    texto($('m-dif-txt'), 'câmera desativada');
    classe(dif.parentElement, 'diverge', false);
  }
  texto($('t-c-ida'), cam ? cam.ida : '—');
  texto($('t-c-volta'), cam ? cam.volta : '—');
  texto($('t-e-ida'), esp.ida);
  texto($('t-e-volta'), esp.volta);
  celulaDif($('t-d-ida'), cam ? cam.ida : null, esp.ida);
  celulaDif($('t-d-volta'), cam ? cam.volta : null, esp.volta);
}

// Gráfico de passagens por hora: as colunas são criadas uma vez; depois só mudam as alturas.
let graficoMontado = false;

function atualizarGrafico(porHora) {
  const grafico = $('grafico');
  if (!Array.isArray(porHora) || porHora.length === 0) return;
  if (!graficoMontado || grafico.querySelectorAll('.hora').length !== porHora.length) {
    grafico.innerHTML = '<span class="maximo"></span>' +
      porHora.map(() => '<div class="hora"><i class="camera"></i><i class="esp32"></i></div>').join('');
    const horas = document.createElement('div');
    horas.className = 'grafico-horas';
    horas.id = 'grafico-horas';
    horas.innerHTML = porHora.map(() => '<span></span>').join('');
    $('grafico-horas')?.remove();
    grafico.after(horas);
    graficoMontado = true;
  }
  const maximo = Math.max(1, ...porHora.map((h) => Math.max(h.camera, h.esp32)));
  texto(grafico.querySelector('.maximo'), `${maximo} ${plural(maximo, 'passagem', 'passagens')}`);
  const colunas = grafico.querySelectorAll('.hora');
  const rotulos = $('grafico-horas').children;
  let resumo = [];
  porHora.forEach((h, i) => {
    const [barCam, barEsp] = colunas[i].children;
    const hora = h.hora.slice(11, 13) + 'h';
    const atual = i === porHora.length - 1;
    const alt = (n) => (n / maximo * 100).toFixed(1) + '%';
    if (barCam.style.height !== alt(h.camera)) barCam.style.height = alt(h.camera);
    if (barEsp.style.height !== alt(h.esp32)) barEsp.style.height = alt(h.esp32);
    const titulo = `${hora}: câmera ${h.camera}, ESP32 ${h.esp32}`;
    if (colunas[i].title !== titulo) colunas[i].title = titulo;
    classe(colunas[i], 'atual', atual);
    texto(rotulos[i], hora);
    classe(rotulos[i], 'atual', atual);
    if (h.camera || h.esp32) resumo.push(titulo);
  });
  const rotulo = 'Passagens por hora nas últimas 12 horas. ' + (resumo.length ? resumo.join('; ') : 'Nenhuma passagem.');
  if (grafico.getAttribute('aria-label') !== rotulo) grafico.setAttribute('aria-label', rotulo);
}

// ---------------------------------------------------------------- últimas passagens

const MAX_ENTRADAS = 12;
let primeiraCarga = true;

function chaveDe(v, i) {
  return v.id !== undefined ? String(v.id) : `${v.data_hora}|${v.fonte}|${v.sentido}|${i}`;
}

function criarEntrada(v) {
  const el = document.createElement('div');
  el.className = 'entrada';
  const d = document.createElement('span');
  d.className = 'd';
  d.textContent = v.data_hora.slice(11, 19);
  d.title = v.data_hora.slice(8, 10) + '/' + v.data_hora.slice(5, 7) + '/' + v.data_hora.slice(0, 4);
  const t = document.createElement('span');
  t.className = 't';
  t.textContent = v.fonte === 'camera' ? 'CAM' : 'ESP';
  t.title = v.fonte === 'camera' ? 'câmera do celular' : 'nó ESP32';
  const o = document.createElement('div');
  o.className = 'o';
  const sentido = document.createElement('strong');
  sentido.className = 'etiqueta ' + (v.sentido === 'ida' ? 'ida' : 'volta');
  sentido.textContent = v.sentido;
  o.append(sentido);
  if (v.altura_cm !== '' || v.categoria) {
    const det = document.createElement('span');
    det.className = 'det';
    if (v.altura_cm !== '') {
      const alt = document.createElement('span');
      alt.className = 'mono';
      alt.textContent = formatoCm.format(Number(v.altura_cm)) + ' cm';
      det.append(alt);
    }
    if (v.categoria) {
      const cat = document.createElement('span');
      cat.className = 'etiqueta ' + (v.categoria === 'pesado' ? 'pesado' : 'leve');
      cat.textContent = v.categoria;
      det.append(cat);
    }
    o.append(det);
  }
  el.append(d, t, o);
  return el;
}

function atualizarDiario(ultimos) {
  const diario = $('diario');
  const existentes = new Map([...diario.children].map((el) => [el.dataset.chave, el]));
  const chaves = ultimos.map(chaveDe);
  let anterior = null;
  chaves.forEach((chave, i) => {
    let el = existentes.get(chave);
    if (!el) {
      el = criarEntrada(ultimos[i]);
      el.dataset.chave = chave;
      if (!primeiraCarga) {
        el.classList.add('nova');
        el.addEventListener('animationend', () => el.classList.remove('nova'), { once: true });
      }
    }
    const lugar = anterior ? anterior.nextSibling : diario.firstChild;
    if (lugar !== el) diario.insertBefore(el, lugar);
    anterior = el;
  });
  const manter = new Set(chaves.slice(0, MAX_ENTRADAS));
  for (const [chave, el] of existentes) if (!manter.has(chave)) el.remove();
  mostrar($('diario-vazio'), ultimos.length === 0);
  texto($('p-info'), ultimos.length ? `${ultimos.length} mais recentes` : 'mais recentes no topo');
  primeiraCarga = false;
}

// ---------------------------------------------------------------- ciclo principal

let falhas = 0;
let ocupado = false;

async function atualizar() {
  if (ocupado) return;   // não empilha pedidos se o Wi-Fi estiver lento
  ocupado = true;
  try {
    const resposta = await fetch('/dados', { cache: 'no-store', signal: AbortSignal.timeout(2500) });
    if (!resposta.ok) throw new Error(resposta.status);
    const d = await resposta.json();
    falhas = 0;
    mostrar($('sem-conexao'), false);
    atualizarFrase(d.camera, d.esp32);
    atualizarCamera(d.camera);
    atualizarEsp(d.esp32);
    atualizarComparacao(d.camera, d.esp32);
    atualizarGrafico(d.por_hora);
    atualizarDiario(d.ultimos);
    texto($('atualizado'), new Date().toLocaleTimeString('pt-BR'));
  } catch {
    falhas += 1;
    if (falhas >= FALHAS_PARA_AVISO) mostrar($('sem-conexao'), true);
  } finally {
    ocupado = false;
  }
}

// destaca na barra lateral a folha que está na tela
function marcarMenu() {
  const links = [...document.querySelectorAll('.menu a')];
  const observador = new IntersectionObserver((entradas) => {
    for (const e of entradas) {
      if (!e.isIntersecting) continue;
      for (const a of links) {
        const ativo = a.getAttribute('href') === '#' + e.target.id;
        classe(a, 'ativo', ativo);
        if (ativo) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
      }
    }
  }, { rootMargin: '-45% 0px -50% 0px' });
  for (const a of links) observador.observe(document.querySelector(a.getAttribute('href')));
}

atualizar();
setInterval(atualizar, INTERVALO_MS);
cicloQuadro();
marcarMenu();
