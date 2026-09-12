"use client";

import { App as AntApp, Alert, Button, Card, Form, Input, InputNumber, Radio, Select, Space, Typography } from "antd";
import { useEffect } from "react";
import { setToken, getToken, useSettings, useSettingsMutation, useSummary } from "@/lib/api";

const QUALITIES = ["OD", "UHD", "HD", "SD", "LD"];

export default function SettingsPage() {
  const { message } = AntApp.useApp();
  const { data, isLoading } = useSettings();
  const { data: summary } = useSummary();
  const save = useSettingsMutation();
  const [form] = Form.useForm();
  const [tokenForm] = Form.useForm();

  useEffect(() => {
    if (data) {
      form.setFieldsValue(data.settings);
      tokenForm.setFieldsValue({ token: getToken() });
    }
  }, [data, form, tokenForm]);

  const saveSettings = async () => {
    const values = await form.validateFields();
    try {
      await save.mutateAsync(values);
      message.success("设置已保存");
    } catch (err) {
      message.error((err as Error).message);
    }
  };

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="录制与监控" loading={isLoading}>
        <Form
          form={form}
          layout="vertical"
          style={{ maxWidth: 640 }}
          initialValues={{ output_format: "mp4", quality: "OD", check_interval: 60 }}
        >
          <Form.Item
            name="check_interval"
            label="开播检测间隔（秒）"
            extra="每个房间独立轮询的默认间隔，实际会有 ±15% 随机抖动"
            rules={[{ required: true, message: "必填" }]}
          >
            <InputNumber min={10} max={3600} style={{ width: 200 }} />
          </Form.Item>
          <Form.Item name="quality" label="默认清晰度" extra="所选清晰度不可用时库会自动降级">
            <Select
              style={{ width: 200 }}
              options={QUALITIES.map((q) => ({ value: q, label: q }))}
            />
          </Form.Item>
          <Form.Item name="output_format" label="输出格式" extra="mp4 通用；flv 兼容性最好（极少数平台 mp4 拷贝异常时可切换）">
            <Radio.Group
              options={[
                { value: "mp4", label: "MP4" },
                { value: "flv", label: "FLV" },
              ]}
              optionType="button"
            />
          </Form.Item>
          <Form.Item
            name="file_template"
            label="保存路径模板"
            extra="最后一段是文件名主干，可用占位符：{platform} {anchor} {title} {datetime} {quality}"
          >
            <Input placeholder="{platform}/{anchor}/{datetime}_{title}" />
          </Form.Item>
          <Form.Item name="record_dir" label="录制保存目录" extra={`留空则使用默认目录；当前生效：${data?.record_dir ?? "…"}`}>
            <Input placeholder="默认（data/recordings）" />
          </Form.Item>
          <Form.Item name="ffmpeg_path" label="FFmpeg 路径" extra="默认在 PATH 中查找 ffmpeg">
            <Input placeholder="ffmpeg" />
          </Form.Item>
          <Form.Item
            name="proxy_addr"
            label="代理地址"
            extra="用于检测与解析（国际平台需要时设置，如 http://127.0.0.1:7890），留空不使用"
          >
            <Input placeholder="不使用代理" />
          </Form.Item>
          <Form.Item
            name="reconnect_backoff_max"
            label="重连最大退避（秒）"
            extra="断流/失败后的重试间隔会指数增长，此为上限"
          >
            <InputNumber min={30} max={3600} style={{ width: 200 }} />
          </Form.Item>
          <Button type="primary" loading={save.isPending} onClick={saveSettings}>
            保存设置
          </Button>
        </Form>
      </Card>

      <Card title="访问令牌" style={{ maxWidth: 856 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="仅在服务端设置了 RECORDER_ACCESS_TOKEN 时需要。令牌只保存在当前浏览器。"
        />
        <Form
          form={tokenForm}
          layout="vertical"
          style={{ maxWidth: 480 }}
          onFinish={(values) => {
            setToken(values.token?.trim() ?? "");
            message.success("令牌已保存到本地浏览器");
          }}
        >
          <Form.Item name="token" label="访问令牌">
            <Input.Password placeholder="留空表示不使用" visibilityToggle={false} />
          </Form.Item>
          <Button htmlType="submit">保存令牌</Button>
        </Form>
      </Card>

      <Card title="关于" style={{ maxWidth: 856 }}>
        <Typography.Text type="secondary">
          StreamGet 录播台 v{summary?.version ?? "…"} · 基于 streamget（流地址解析）+ FFmpeg（录制）
        </Typography.Text>
      </Card>
    </Space>
  );
}
