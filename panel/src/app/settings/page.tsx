"use client";

import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import type { ColumnsType } from "antd/es/table";
import { setToken, getToken, usePlatforms, useSettings, useSettingsMutation, useSummary } from "@/lib/api";
import { QUALITY_LABELS } from "@/lib/types";

// 平台登录凭证行（存储为 JSON 数组字符串：platform_credentials）
interface CredRow {
  platform: string;
  cookie: string;
}

function parseCreds(raw: unknown): CredRow[] {
  try {
    const arr = JSON.parse(String(raw ?? "[]"));
    if (!Array.isArray(arr)) return [];
    return arr.map((r) => ({
      platform: String(r?.platform ?? ""),
      cookie: String(r?.cookie ?? ""),
    }));
  } catch {
    return [];
  }
}

// 文本/数字输入类字段：失去焦点时才保存，不逐字提交；开关/下拉等即时保存
const TEXT_FIELDS = new Set([
  "file_template",
  "record_dir",
  "ffmpeg_path",
  "ffmpeg_extra_args",
  "proxy_addr",
  "script_after_cmd",
  "webhook_url",
  "check_interval",
  "end_confirm_delay",
  "reconnect_backoff_max",
  "segment_seconds",
  "max_session_hours",
  "min_free_disk_gb",
  "max_consecutive_failures",
  "retention_days",
  "max_concurrent",
  "max_concurrent_per_platform",
]);

export default function SettingsPage() {
  const { message } = AntApp.useApp();
  const { data, isLoading } = useSettings();
  const { data: summary } = useSummary();
  const { data: platforms } = usePlatforms();
  const save = useSettingsMutation();
  const [form] = Form.useForm();
  const [tokenForm] = Form.useForm();
  const quality = Form.useWatch("quality", form);
  const pendingRef = useRef<Record<string, unknown>>({});
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [creds, setCreds] = useState<CredRow[]>([]);

  useEffect(() => {
    if (data) {
      const { proxy_record_platforms, output_format, ...rest } = data.settings;
      form.setFieldsValue({
        ...rest,
        // 兼容旧版本：录制格式曾可存 “audio”，迁移为清晰度“仅音频”
        quality: output_format === "audio" ? "audio" : data.settings.quality,
        output_format: output_format === "audio" ? "mp4" : output_format,
        proxy_record_platforms: String(proxy_record_platforms ?? "").split(",").filter(Boolean),
      });
      setCreds(parseCreds(data.settings.platform_credentials));
      tokenForm.setFieldsValue({ token: getToken() });
    }
  }, [data, form, tokenForm]);

  // 更新凭证表：同步进表单；选择/删除即时保存（immediate=true），文本输入在失焦时保存
  const updateCreds = (rows: CredRow[], immediate = true) => {
    setCreds(rows);
    form.setFieldsValue({ platform_credentials: JSON.stringify(rows) });
    if (immediate) {
      flushAutoSave(true);
    }
  };

  // force=true 时无条件保存（用于失焦/凭证表等未走 onValuesChange 的场景）
  const flushAutoSave = (force = false) => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (force) {
      pendingRef.current = {};
    } else {
      const pending = pendingRef.current;
      pendingRef.current = {};
      if (!Object.keys(pending).length) return;
    }
    const values = form.getFieldsValue();
    const payload: Record<string, string | number | boolean> = { ...values };
    if (Array.isArray(values.proxy_record_platforms)) {
      payload.proxy_record_platforms = values.proxy_record_platforms.join(",");
    }
    save.mutate(payload, {
      onSuccess: () => message.success("设置已自动保存"),
      onError: (err) => message.error((err as Error).message),
    });
  };

  // antd onValuesChange 第一参数才是本次变更字段（第二参数是全部表单值，不能用它判断）
  const handleValuesChange = (changedValues: Record<string, unknown>) => {
    Object.assign(pendingRef.current, changedValues);
    // 文本/数字输入不逐字保存，失去焦点时统一保存；开关/下拉等即时保存
    const immediate = Object.keys(changedValues).some((k) => !TEXT_FIELDS.has(k));
    if (immediate) flushAutoSave();
  };

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      {/* onBlur 在 React 中会冒泡：任一输入框失焦即触发一次保存检查（有改动才提交） */}
      <div onBlur={() => flushAutoSave()}>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ output_format: "mp4", quality: "OD", check_interval: 60 }}
        onValuesChange={handleValuesChange}
      >
        {/* 隐藏字段承载平台凭证 JSON，随表单一起保存 */}
        <Form.Item name="platform_credentials" hidden>
          <Input />
        </Form.Item>
        <Row gutter={[16, 16]} style={{ alignItems: "stretch" }}>
          <Col xs={24} xl={12} style={{ display: "flex" }}>
            <Card title="常规录制" loading={isLoading} style={{ width: "100%" }}>
              <Row gutter={[12, 8]}>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="check_interval"
                    label="检测时间（秒）"
                    tooltip="每个房间独立轮询的默认间隔，实际会有 ±15% 随机抖动"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={10} max={3600} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="end_confirm_delay"
                    label="下播确认延迟（秒）"
                    tooltip="检测到下播后等待再次确认，防止瞬时断流误判，0 = 立即结束"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={0} max={600} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="reconnect_backoff_max"
                    label="重连最大退避（秒）"
                    tooltip="断流/失败后的重试间隔指数增长，此为上限"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={30} max={3600} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="quality"
                    label="录制清晰度"
                    tooltip="所选清晰度不可用时库会自动降级；选“仅音频”只录声音，输出 .m4a/.mp3/.aac"
                  >
                    <Select
                      options={Object.entries(QUALITY_LABELS).map(([value, label]) => ({ value, label }))}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="output_format"
                    label="录制格式"
                    tooltip="mp4 通用；flv 兼容性最好；清晰度选“仅音频”时此项无效（输出由音频格式决定）"
                  >
                    <Radio.Group
                      disabled={quality === "audio"}
                      options={[
                        { value: "mp4", label: "MP4" },
                        { value: "flv", label: "FLV" },
                      ]}
                      optionType="button"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="audio_format"
                    label="音频格式"
                    tooltip="录视频时为音频轨处理（自动=跟随源拷贝，AAC/MP3 需实时转码）；清晰度选“仅音频”时为输出文件封装（自动=M4A，AAC 为裸流，MP3 需实时转码）"
                  >
                    <Select
                      options={[
                        { value: "auto", label: "自动" },
                        { value: "aac", label: "AAC" },
                        { value: "m4a", label: "M4A" },
                        { value: "mp3", label: "MP3" },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="stream_type"
                    label="拉流协议优先级"
                    tooltip="平台同时提供多种流地址时优先使用哪种"
                  >
                    <Select
                      options={[
                        { value: "auto", label: "自动（库默认）" },
                        { value: "flv", label: "FLV 优先" },
                        { value: "hls", label: "HLS (m3u8) 优先" },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="file_template"
                    label="保存路径模板"
                    tooltip="最后一段是文件名主干。占位符：{platform} 平台、{platform_name} 平台中文名、{anchor} 主播、{title} 标题、{remark} 备注、{room_id} 房间ID、{session_id} 会话ID、{datetime} 日期_时间、{date} {time} {year} {month} {day} {hour} {minute} {second} 时间分量、{quality} 清晰度"
                  >
                    <Input
                      placeholder="{platform}/{anchor}/{datetime}_{title}"
                      onBlur={() => flushAutoSave()}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="record_dir"
                    label="录制保存目录"
                    tooltip={`留空则使用默认目录；当前生效：${data?.record_dir ?? "data/recordings"}`}
                  >
                    <Input
                      placeholder="默认（data/recordings）"
                      onBlur={() => flushAutoSave()}
                    />
                  </Form.Item>
                </Col>
              </Row>
            </Card>
          </Col>

          <Col xs={24} xl={12} style={{ display: "flex" }}>
            <Card title="网络与通知" loading={isLoading} style={{ width: "100%" }}>
              <Row gutter={[12, 8]}>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="force_https"
                    label="强制 HTTPS 录制"
                    valuePropName="checked"
                    tooltip="把 http 流地址改写为 https，规避 CDN 劫持/拦截"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="flv_direct_download"
                    label="FLV 源下载器直连"
                    valuePropName="checked"
                    tooltip="FLV 流改用下载器直连录制（延迟更低，规避 FFmpeg 兼容问题）；不支持额外参数，分段到点直接切文件"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="proxy_addr"
                    label="代理地址"
                    tooltip="用于检测与解析；配合“代理录制平台”也用于拉流，留空不使用"
                  >
                    <Input
                      placeholder="http://127.0.0.1:7890"
                      onBlur={() => flushAutoSave()}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24}>
                  <Form.Item
                    name="proxy_record_platforms"
                    label="默认使用代理录制的平台"
                    tooltip="所选平台的 FFmpeg 拉流走上方代理地址（国际平台需要），其余平台直连"
                  >
                    <Select
                      mode="multiple"
                      allowClear
                      placeholder="不使用代理录制"
                      options={(platforms ?? []).map((p) => ({ value: p.key, label: p.name }))}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24}>
                  <Form.Item
                    name="webhook_url"
                    label="Webhook 通知"
                    tooltip="录制会话开始/结束时 POST JSON，可对接钉钉、企业微信、Bark 等；留空不启用"
                  >
                    <Input
                      placeholder="https://example.com/webhook"
                      onBlur={() => flushAutoSave()}
                    />
                  </Form.Item>
                </Col>
              </Row>
            </Card>
          </Col>

          <Col xs={24} xl={12} style={{ display: "flex" }}>
            <Card title="录制限制" loading={isLoading} style={{ width: "100%" }}>
              <Row gutter={[12, 8]}>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="segment_enabled"
                    label="分段录制"
                    valuePropName="checked"
                    tooltip="开启后按时长把整场直播切分为多个文件"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="segment_seconds"
                    label="分段时间（秒）"
                    tooltip="分段开启后生效，到点自动收尾并开新段"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={30} max={86400} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="max_session_hours"
                    label="单场最大时长（小时）"
                    tooltip="录满此时长后自动结束，0 = 不限制"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={0} max={720} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="min_free_disk_gb"
                    label="磁盘剩余阈值（GB）"
                    tooltip="空间不足则暂停等待释放后自动续录，0 = 不检查"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={0} max={1024} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="max_consecutive_failures"
                    label="连续失败上限（次）"
                    tooltip="达到后结束本次会话，交还轮询稍后自动重试"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={1} max={100} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="retention_days"
                    label="文件保留天数"
                    tooltip="超期文件（含记录）每小时自动清理，0 = 永久保留"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={0} max={3650} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="max_concurrent"
                    label="全局最大并发数"
                    tooltip="所有平台合计最多同时录制的路数，0 = 不限制"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={0} max={100} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="max_concurrent_per_platform"
                    label="平台最大并发数"
                    tooltip="同一平台最多同时录制的路数，0 = 不限制；已满时房间等待空位自动重试"
                    rules={[{ required: true, message: "必填" }]}
                  >
                    <InputNumber min={0} max={100} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
            </Card>
          </Col>

          <Col xs={24} xl={12} style={{ display: "flex" }}>
            <Card title="录制后处理" loading={isLoading} style={{ width: "100%" }}>
              <Row gutter={[12, 8]}>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="auto_convert_mp4"
                    label="转 MP4"
                    valuePropName="checked"
                    tooltip="输出格式为 FLV 时生效：录制结束后转封装（流拷贝，速度快）"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="delete_original_after_convert"
                    label="转换后删原文件"
                    valuePropName="checked"
                    tooltip="转换成功后删除原 FLV；关闭时原文件保留在磁盘"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="write_time_subtitle"
                    label="生成时间字幕"
                    valuePropName="checked"
                    tooltip="每个分段生成同名 .srt，每秒一条当时时间，便于对时间轴"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={8}>
                  <Form.Item
                    name="run_script_after"
                    label="录后自定义脚本"
                    valuePropName="checked"
                    tooltip="每个分段结束后在后台执行，不阻塞录制"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={16}>
                  <Form.Item
                    name="script_after_cmd"
                    label="脚本执行命令"
                    tooltip="占位符：{file} 完整路径、{filename}、{title}、{anchor}、{platform}、{session_id}"
                  >
                    <Input
                      placeholder='例如 python D:\scripts\notify.py "{file}"'
                      onBlur={() => flushAutoSave()}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item name="ffmpeg_path" label="FFmpeg 路径" tooltip="默认在 PATH 中查找 ffmpeg">
                    <Input placeholder="ffmpeg" onBlur={() => flushAutoSave()} />
                  </Form.Item>
                </Col>
                <Col xs={24} sm={12}>
                  <Form.Item
                    name="ffmpeg_extra_args"
                    label="FFmpeg 额外参数"
                    tooltip="追加到输出参数（如 -bsf:a aac_adtstoasc）；参数非法会导致录制失败"
                  >
                    <Input
                      placeholder="例如 -bsf:a aac_adtstoasc"
                      onBlur={() => flushAutoSave()}
                    />
                  </Form.Item>
                </Col>
              </Row>
            </Card>
          </Col>
        </Row>
      </Form>
      </div>

      <Row gutter={[16, 16]} style={{ alignItems: "stretch" }}>
        <Col xs={24} xl={12} style={{ display: "flex" }}>
          <Card title="平台登录" loading={isLoading} style={{ width: "100%" }}>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Alert
                type="info"
                showIcon
                message="此处 Cookie 为对应平台的兜底登录凭证（房间未单独配置 Cookie 时生效）。每个平台限一行。"
              />
              <Table<CredRow>
                size="small"
                rowKey={(_, index) => String(index)}
                dataSource={creds}
                pagination={false}
                columns={
                  [
                    {
                      title: "平台",
                      width: 160,
                      dataIndex: "platform",
                      render: (_, record, index) => (
                        <Select
                          showSearch
                          optionFilterProp="label"
                          style={{ width: "100%" }}
                          placeholder="选择平台"
                          value={record.platform || undefined}
                          options={(platforms ?? [])
                            .filter((p) => p.key === record.platform || !creds.some((r) => r.platform === p.key))
                            .map((p) => ({ value: p.key, label: p.name }))}
                          onChange={(v) =>
                            updateCreds(creds.map((r, i) => (i === index ? { ...r, platform: v } : r)))
                          }
                        />
                      ),
                    },
                    {
                      title: "Cookie",
                      dataIndex: "cookie",
                      render: (_, record, index) => (
                        <Input.TextArea
                          autoSize={{ minRows: 1, maxRows: 4 }}
                          placeholder="粘贴该平台的 Cookie（选填）"
                          value={record.cookie}
                          onChange={(e) =>
                            updateCreds(
                              creds.map((r, i) => (i === index ? { ...r, cookie: e.target.value } : r)),
                              false,
                            )
                          }
                          onBlur={() => flushAutoSave(true)}
                        />
                      ),
                    },
                    {
                      title: "操作",
                      width: 70,
                      render: (_, __, index) => (
                        <Button
                          type="link"
                          danger
                          size="small"
                          onClick={() => updateCreds(creds.filter((_, i) => i !== index))}
                        >
                          删除
                        </Button>
                      ),
                    },
                  ] as ColumnsType<CredRow>
                }
              />
              <Button onClick={() => updateCreds([...creds, { platform: "", cookie: "" }])}>添加平台行</Button>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={12} style={{ display: "flex" }}>
          <Card title="关于与令牌" style={{ width: "100%" }}>
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              <Alert
                type="info"
                showIcon
                message="仅在服务端设置了 RECORDER_ACCESS_TOKEN 时需要。令牌只保存在当前浏览器。"
              />
              <Form
                form={tokenForm}
                layout="vertical"
                onFinish={(values) => {
                  setToken(values.token?.trim() ?? "");
                  message.success("令牌已保存到本地浏览器");
                }}
              >
                <Form.Item name="token" label="访问令牌" style={{ maxWidth: 480, marginBottom: 12 }}>
                  <Input.Password placeholder="留空表示不使用" visibilityToggle={false} />
                </Form.Item>
                <Button htmlType="submit">保存令牌</Button>
              </Form>
              <Typography.Text type="secondary">
                StreamGet 录播台 v{summary?.version ?? "…"} · 基于 streamget（流地址解析）+ FFmpeg（录制）
              </Typography.Text>
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
