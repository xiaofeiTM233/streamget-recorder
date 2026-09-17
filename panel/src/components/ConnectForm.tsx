"use client";

import { LinkOutlined, KeyOutlined, LockOutlined, DisconnectOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Card, Checkbox, Form, Input, Space, Typography } from "antd";
import { useState } from "react";
import { useConnection } from "@/lib/connection";

const { Title, Paragraph, Text } = Typography;

interface FormValues {
  baseUrl: string;
  token: string;
  remember: boolean;
  autoConnect: boolean;
}

export default function ConnectForm() {
  const { config, connecting, connect, resetAll, lastError } = useConnection();
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);

  const defaultBase =
    config.baseUrl ||
    (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000");

  const onFinish = async (values: FormValues) => {
    setSubmitting(true);
    try {
      await connect({
        baseUrl: values.baseUrl,
        token: values.token ?? "",
        remember: values.remember ?? false,
        autoConnect: values.autoConnect ?? false,
      });
      message.success("连接成功");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "连接失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <Card
        style={{
          width: "100%",
          maxWidth: 440,
          boxShadow: "0 10px 40px rgba(0,0,0,0.35)",
          borderRadius: 12,
        }}
        styles={{ body: { padding: 32 } }}
      >
        <Space orientation="vertical" size={4} style={{ width: "100%", marginBottom: 24 }}>
          <Title level={3} style={{ margin: 0 }}>
            StreamGet 录播台
          </Title>
          <Text type="secondary">连接到录播服务端以管理房间与录制文件</Text>
        </Space>

        <Form<FormValues>
          form={form}
          layout="vertical"
          autoComplete="off"
          initialValues={{
            baseUrl: defaultBase,
            token: config.token,
            remember: config.remember,
            autoConnect: config.autoConnect,
          }}
          onFinish={onFinish}
          requiredMark={false}
        >
          <Form.Item
            name="baseUrl"
            label="连接地址"
            rules={[
              { required: true, message: "请填写连接地址" },
              {
                validator: (_, value: string) => {
                  if (!value) return Promise.resolve();
                  try {
                    // eslint-disable-next-line no-new
                    new URL(value);
                    return Promise.resolve();
                  } catch {
                    return Promise.reject(new Error("请填写有效的 URL，例如 http://127.0.0.1:8000"));
                  }
                },
              },
            ]}
          >
            <Input
              size="large"
              prefix={<LinkOutlined />}
              placeholder="http://127.0.0.1:8000"
              autoComplete="off"
            />
          </Form.Item>

          <Form.Item
            name="token"
            label="访问令牌"
            extra="服务端在设置页设置了访问令牌时必填，否则留空"
            rules={[{ required: false }]}
          >
            <Input.Password
              size="large"
              prefix={<KeyOutlined />}
              placeholder="留空表示不使用"
              autoComplete="new-password"
              visibilityToggle={false}
            />
          </Form.Item>

          <Form.Item name="remember" valuePropName="checked" noStyle>
            <Checkbox>记住令牌</Checkbox>
          </Form.Item>
          <Form.Item name="autoConnect" valuePropName="checked" noStyle>
            <Checkbox style={{ marginLeft: 16 }}>自动连接</Checkbox>
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginTop: 24 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              size="large"
              loading={submitting || connecting}
              icon={<LockOutlined />}
            >
              连接
            </Button>
          </Form.Item>
        </Form>

        {lastError ? (
          <Paragraph type="danger" style={{ marginTop: 16, marginBottom: 0, fontSize: 12 }}>
            {lastError}
          </Paragraph>
        ) : null}

        <div style={{ marginTop: 16, textAlign: "right", fontSize: 12 }}>
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            icon={<DisconnectOutlined />}
            onClick={() => {
              resetAll();
              form.setFieldsValue({ baseUrl: window.location.origin, token: "", remember: false, autoConnect: false });
            }}
          >
            清除已保存配置
          </Button>
        </div>
      </Card>
    </div>
  );
}
