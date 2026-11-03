// POST /api/ajuste  {"ocupadas": 42, "pin": "1234"}
// Correção manual da contagem pelo painel, protegida pelo ADMIN_PIN.
// O ajuste fica pendente e vai para o ESP32 na resposta da próxima publicação (até 30 s):
// a contagem oficial continua sendo a da placa.

import { armazenamento } from "@/lib/armazenamento";
import { segredoConfere } from "@/lib/painel";

const MAX_ERROS = 5;
const JANELA_S = 10 * 60;

export async function POST(request: Request) {
  const pinCerto = process.env.ADMIN_PIN;
  if (!pinCerto) {
    return Response.json({ ok: false, erro: "ADMIN_PIN não configurado no servidor." }, { status: 503 });
  }

  let corpo: { ocupadas?: unknown; pin?: unknown };
  try {
    corpo = await request.json();
  } catch {
    return Response.json({ ok: false, erro: "Envie o número de veículos e o PIN." }, { status: 400 });
  }

  const banco = armazenamento();
  // limite de tentativas por endereço, para o PIN não ser descoberto na força bruta
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0].trim() || "local";
  if ((await banco.errosPin(ip)) >= MAX_ERROS) {
    return Response.json({ ok: false, erro: "Muitas tentativas erradas. Espere 10 minutos." }, { status: 429 });
  }
  if (typeof corpo.pin !== "string" || !segredoConfere(corpo.pin, pinCerto)) {
    const erros = await banco.registrarErroPin(ip, JANELA_S);
    const restam = Math.max(0, MAX_ERROS - erros);
    return Response.json({ ok: false, erro: `PIN incorreto. ${restam} ${restam === 1 ? "tentativa restante" : "tentativas restantes"}.` },
      { status: 401 });
  }

  const estado = await banco.lerEstado();
  const vagas = estado?.vagas ?? 100;
  const ocupadas = corpo.ocupadas;
  if (typeof ocupadas !== "number" || !Number.isInteger(ocupadas) || ocupadas < 0 || ocupadas > vagas) {
    return Response.json({ ok: false, erro: `Informe um número inteiro de 0 a ${vagas}.` }, { status: 400 });
  }

  const id = await banco.proximoIdAjuste(estado?.ajuste_aplicado ?? 0);
  const ajuste = { id, ocupadas, criado_em: new Date().toISOString() };
  await banco.salvarAjuste(ajuste);
  return Response.json({ ok: true, ajuste });
}
