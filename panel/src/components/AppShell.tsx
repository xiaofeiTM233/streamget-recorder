"use client";

import {
  DashboardOutlined,
  FolderOpenOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { Button, Input, Layout, Menu, Modal, Tag } from "antd";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { getToken, setToken } from "@/lib/api";
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
  const { connected } = useEvents();
  const [collapsed, setCollapsed] = useState(false);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [tokenDraft, setTokenDraft] = useState("");

  useEffect(() => {
    const handler = () => {
      setTokenDraft(getToken());
      setTokenOpen(true);
    };
    window.addEventListener("recorder:unauthorized", handler);
    return () => window.removeEventListener("recorder:unauthorized", handler);
  }, []);

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
          <Tag color={connected ? "green" : "red"} bordered={false}>
            {connected ? "● 实时连接" : "● 未连接"}
          </Tag>
        </Layout.Header>
        <Layout.Content style={{ margin: 16 }}>{children}</Layout.Content>
      </Layout>

      <Modal
        title="需要访问令牌"
        open={tokenOpen}
        onCancel={() => setTokenOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setTokenOpen(false)}>
            取消
          </Button>,
          <Button
            key="save"
            type="primary"
            onClick={() => {
              setToken(tokenDraft.trim());
              setTokenOpen(false);
              window.location.reload();
            }}
          >
            保存并刷新
          </Button>,
        ]}
      >
        <p>此服务启用了访问令牌（RECORDER_ACCESS_TOKEN），请输入后继续。</p>
        <Input.Password
          value={tokenDraft}
          onChange={(e) => setTokenDraft(e.target.value)}
          placeholder="访问令牌"
        />
      </Modal>
    </Layout>
  );
}
