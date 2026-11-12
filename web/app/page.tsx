import { montarDados } from "@/lib/painel";
import type { DadosPainel } from "@/lib/tipos";
import Painel from "./Painel";

// a página já sai do servidor com os dados atuais; depois o navegador atualiza sozinho
export const dynamic = "force-dynamic";

export default async function Pagina() {
  let iniciais: DadosPainel | null = null;
  try {
    iniciais = await montarDados();
  } catch (erro) {
    console.error("[estacionamento] falha ao ler o banco na primeira carga", erro);
  }
  return <Painel iniciais={iniciais} />;
}
