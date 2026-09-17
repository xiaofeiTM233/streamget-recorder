"use client";

import {
  DashboardOutlined,
  FolderOpenOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Tag, Tooltip } from "antd";
import { DisconnectOutlined } from "@ant-design/icons";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useConnection } from "@/lib/connection";
import { useEvents } from "@/lib/events";

const MENU_ITEMS = [
  { key: "/", icon: <DashboardOutlined />, label: "仪表盘" },
  { key: "/rooms", icon: <TeamOutlined />, label: "房间管理" },
  { key: "/recordings", icon: <FolderOpenOutlined />, label: "录制文件" },
  { key: "/settings", icon: <SettingOutlined />, label: "设置" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { config, disconnect } = useConnection();
  const { connected } = useEvents();
  const [collapsed, setCollapsed] = useState(false);

  const current = pathname.replace(/\/+$/, "") || "/";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark">
        <div
          style={{
            height: 48,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--ant-color-primary)",
            fontWeight: 700,
            fontSize: collapsed ? 20 : 16,
            whiteSpace: "nowrap",
            overflow: "hidden",
          }}
        >
          {collapsed ? "⏺" : "⏺ StreamGet 录播台"}
        </div>
        <Menu
          mode="inline"
          theme="dark"
          items={MENU_ITEMS}
          selectedKeys={[current]}
          onClick={({ key }) => router.push(key)}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 20px",
          }}
        >
          <span style={{ fontSize: 15, fontWeight: 600 }}>
            {MENU_ITEMS.find((item) => item.key === current)?.label ?? "仪表盘"}
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
            <Tag color={connected ? "green" : "red"} bordered={false}>
              {connected ? "● 实时连接" : "● 未连接"}
            </Tag>
            <Tag color="blue" bordered={false} style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis" }}>
              {config.baseUrl || "当前页面来源"}
            </Tag>
            <Tooltip title="断开连接">
              <Button
                type="text"
                icon={<DisconnectOutlined />}
                onClick={disconnect}
              />
            </Tooltip>
          </span>
        </Layout.Header>
        <Layout.Content style={{ margin: 16 }}>{children}</Layout.Content>
      </Layout>
    </Layout>
  );
}
