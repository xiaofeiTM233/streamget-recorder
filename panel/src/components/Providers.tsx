"use client";

import { AntdRegistry } from "@ant-design/nextjs-registry";
import { App as AntApp, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ConnectionProvider } from "@/lib/connection";

export default function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );
  return (
    <AntdRegistry>
      <QueryClientProvider client={queryClient}>
        <ConfigProvider
          locale={zhCN}
          theme={{
            algorithm: theme.darkAlgorithm,
            components: {
              Layout: {
                siderBg: "#141414",
                headerBg: "#141414",
                bodyBg: "#0a0a0a",
                triggerBg: "#1f1f1f",
              },
              Menu: {
                darkItemBg: "transparent",
                darkPopupBg: "#141414",
              },
            },
          }}
        >
          <AntApp>
            <ConnectionProvider>{children}</ConnectionProvider>
          </AntApp>        </ConfigProvider>
      </QueryClientProvider>
    </AntdRegistry>
  );
}
