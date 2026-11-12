// GET  /api/estado  -> dados do painel (estado atual, últimos movimentos, entradas/saídas por hora)
// POST /api/estado  -> publicação do ESP32. Exige "Authorization: Bearer <INGEST_TOKEN>".
//                      A resposta traz o ajuste manual pendente, se houver (o ESP32 aplica e confirma).

import { montarDados, registrarPublicacao, segredoConfere, validarPublicacao } from "@/lib/painel";

export const dynamic = "force-dynamic";

const semCache = { "Cache-Control": "no-store" };

export async function GET() {
  try {
    return Response.json(await montarDados(), { headers: semCache });
  } catch (erro) {
    console.error("[estacionamento] falha ao ler o banco", erro);
    return Response.json({ erro: "Não foi possível ler o banco de dados." }, { status: 503, headers: semCache });
  }
}

export async function POST(request: Request) {
  const esperado = process.env.INGEST_TOKEN;
  if (!esperado) {
    return Response.json({ ok: false, erro: "INGEST_TOKEN não configurado no servidor" }, { status: 500 });
  }
  const recebido = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? "";
  if (!segredoConfere(recebido, esperado)) {
    return Response.json({ ok: false, erro: "token inválido" }, { status: 401 });
  }

  let corpo: unknown;
  try {
    corpo = await request.json();
  } catch {
    return Response.json({ ok: false, erro: "JSON inválido" }, { status: 400 });
  }
  const publicacao = validarPublicacao(corpo);
  if (typeof publicacao === "string") {
    return Response.json({ ok: false, erro: publicacao }, { status: 400 });
  }

  try {
    const { novos, ajuste } = await registrarPublicacao(publicacao);
    // "ajuste" fica por último: o ESP32 lê os números dele procurando a partir dessa chave
    return Response.json({ ok: true, novos, ajuste: ajuste && { id: ajuste.id, ocupadas: ajuste.ocupadas } });
  } catch (erro) {
    console.error("[estacionamento] falha ao gravar a publicação", erro);
    return Response.json({ ok: false, erro: "falha ao gravar no banco" }, { status: 503 });
  }
}
