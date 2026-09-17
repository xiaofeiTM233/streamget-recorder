import type { Metadata } from "next";
import ConnectionGate from "@/components/ConnectionGate";
import Providers from "@/components/Providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "StreamGet 录播台",
  description: "多平台直播录播面板，基于 streamget + FFmpeg",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <ConnectionGate>{children}</ConnectionGate>
        </Providers>
      </body>
    </html>
  );
}
