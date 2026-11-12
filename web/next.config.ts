import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // o painel é servido para o celular na rede local durante os testes (npm run dev -H 0.0.0.0)
  allowedDevOrigins: ["10.*.*.*", "192.168.*.*", "*.local"],
  // não gerar AGENTS.md automaticamente no "next dev"
  agentRules: false,
};

export default nextConfig;
