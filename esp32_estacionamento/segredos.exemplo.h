// Copie este arquivo para "segredos.h" e preencha. O segredos.h fica fora do Git.
#pragma once

// Rede Wi-Fi (2,4 GHz, sem login por página web). Rede aberta: deixe a senha "".
const char* WIFI_SSID  = "NOME_DA_REDE";
const char* WIFI_SENHA = "SENHA_DA_REDE";

// Endereço do painel, sem barra no final. Exemplos:
//   "https://seu-projeto.vercel.app"   (depois do deploy)
//   "http://192.168.0.5:3000"          (teste local com "npm run dev" no notebook)
//   ""                                 (sem nuvem: só o indicador e a página local)
const char* URL_API = "https://seu-projeto.vercel.app";

// Mesmo valor da variável INGEST_TOKEN na Vercel. Gere um aleatório, por exemplo:
//   python -c "import secrets; print(secrets.token_urlsafe(32))"
const char* INGEST_TOKEN = "TROQUE_POR_UM_TOKEN_ALEATORIO";
