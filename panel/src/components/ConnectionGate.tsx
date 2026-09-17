"use client";

import { Spin } from "antd";
import type { ReactNode } from "react";
import AppShell from "./AppShell";
import ConnectForm from "./ConnectForm";
import { useConnection } from "@/lib/connection";
import { EventProvider } from "@/lib/events";

export default function ConnectionGate({ children }: { children: ReactNode }) {
  const { connected, autoTried } = useConnection();

  if (!connected) {
    // 自动连接尚未尝试完时显示加载骨架，避免登录页闪烁
    if (!autoTried) {
      return (
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Spin size="large" />
        </div>
      );
    }
    return <ConnectForm />;
  }

  // EventProvider 仅在连接成功后挂载：登录后才建立 WebSocket，登出即断开
  return (
    <EventProvider>
      <AppShell>{children}</AppShell>
    </EventProvider>
  );
}
