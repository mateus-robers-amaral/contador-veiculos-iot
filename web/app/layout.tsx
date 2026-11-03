import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./painel.css";

export const metadata: Metadata = {
  title: "Estacionamento · vagas livres",
  description: "Vagas livres do estacionamento em tempo real, contadas pela câmera e pelo ESP32.",
};

export const viewport: Viewport = {
  themeColor: "#F5F6F4",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
