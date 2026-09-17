"use client";

import {
  CloudSyncOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  App as AntApp,
  Button,
  Card,
  Col,
  Collapse,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useState } from "react";
import {
  formatDuration,
  usePlatforms,
  useRoomMutations,
  useRooms,
} from "@/lib/api";
import { useEvents } from "@/lib/events";
import { QUALITY_LABELS, qualityLabel } from "@/lib/types";
import type { RoomOut, RoomOverrides, RoomPayload } from "@/lib/types";

interface FormState {
  id: number | null;
  room_url: string;
  platform: string | undefined;
  quality: string | undefined;
  check_interval: number | undefined;
  cookie: string;
  clearCookie: boolean;
  hasCookie: boolean;
  remark: string;
  enabled: boolean;
  overrides: RoomOverrides;
}

const EMPTY_FORM: FormState = {
  id: null,
  room_url: "",
  platform: undefined,
  quality: undefined,
  check_interval: undefined,
  cookie: "",
  clearCookie: false,
  hasCookie: false,
  remark: "",
  enabled: true,
  overrides: {},
};

// 三态布尔选择（跟随全局/开启/关闭）
const BOOL_OPTS = [
  { value: "1", label: "开启" },
  { value: "0", label: "关闭" },
];
const boolVal = (v: boolean | undefined) => (v === undefined ? undefined : v ? "1" : "0");

export default function RoomsPage() {
  const { message } = AntApp.useApp();
  const { data: rooms, isLoading, refetch, isFetching } = useRooms();
  const { data: platforms } = usePlatforms();
  const { progress } = useEvents();
  const { create, update, remove, batchToggle, checkNow, stop, checkAll } = useRoomMutations();

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const setOv = (key: keyof RoomOverrides, value: RoomOverrides[keyof RoomOverrides] | undefined) => {
    const next: RoomOverrides = { ...form.overrides };
    if (value === undefined || value === "") {
      delete next[key];
    } else {
      (next as Record<string, unknown>)[key] = value;
    }
    setForm({ ...form, overrides: next });
  };

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setModalOpen(true);
  };

  const openEdit = (room: RoomOut) => {
    setForm({
      id: room.id,
      room_url: room.room_url,
      platform: room.platform,
      quality: room.quality || undefined,
      check_interval: room.check_interval ?? undefined,
      cookie: "",
      clearCookie: false,
      hasCookie: room.has_cookie,
      remark: room.remark,
      enabled: room.enabled,
      overrides: room.overrides ?? {},
    });
    setModalOpen(true);
  };

  const submit = async () => {
    if (!form.room_url.trim()) {
      message.warning("请填写直播间地址");
      return;
    }
    const payload: RoomPayload = {
      room_url: form.room_url.trim(),
      platform: form.platform ?? null,
      quality: form.quality ?? null,
      check_interval: form.check_interval ?? null,
      remark: form.remark || null,
      enabled: form.enabled,
      overrides: form.overrides,
    };
    try {
      if (form.id == null) {
        await create.mutateAsync({ ...payload, cookie: form.cookie || undefined });
        message.success("房间已添加");
      } else {
        // Cookie 三态：输入新值 = 更新；勾选清除 = 删除；留空 = 保持不变
        const cookie = form.cookie ? form.cookie : form.clearCookie ? "" : undefined;
        await update.mutateAsync({ id: form.id, payload: { ...payload, cookie } });
        message.success("房间已更新");
      }
      setModalOpen(false);
    } catch (err) {
      message.error((err as Error).message);
    }
  };

  const runCheck = async (room: RoomOut) => {
    try {
      message.loading({ content: "检测中…", key: `check-${room.id}`, duration: 0 });
      const result = await checkNow.mutateAsync(room.id);
      message.destroy(`check-${room.id}`);
      if (result.is_live) {
        message.success(
          result.started
            ? `「${result.anchor_name || room.anchor_name || room.platform}」正在直播，已开始录制`
            : `「${result.anchor_name}」正在直播，已在录制中`,
        );
      } else {
        message.info(`「${result.anchor_name || "该房间"}」当前未开播`);
      }
    } catch (err) {
      message.destroy(`check-${room.id}`);
      message.error((err as Error).message);
    }
  };

  const toggleEnabled = async (room: RoomOut, enabled: boolean) => {
    try {
      await update.mutateAsync({ id: room.id, payload: { enabled } });
    } catch (err) {
      message.error((err as Error).message);
    }
  };

  return (
    <Card
      title="房间管理"
      extra={
        <Space>
          {selectedIds.length > 0 && (
            <>
              <Button
                onClick={async () => {
                  await batchToggle.mutateAsync({ ids: selectedIds, enabled: true });
                  setSelectedIds([]);
                  message.success("已启用");
                }}
              >
                批量启用（{selectedIds.length}）
              </Button>
              <Button
                onClick={async () => {
                  await batchToggle.mutateAsync({ ids: selectedIds, enabled: false });
                  setSelectedIds([]);
                  message.success("已停用");
                }}
              >
                批量停用
              </Button>
            </>
          )}
          <Button
            icon={<CloudSyncOutlined />}
            loading={checkAll.isPending}
            onClick={async () => {
              try {
                const r = await checkAll.mutateAsync();
                message.success(`已触发 ${r.triggered} 个房间的立即检测`);
                refetch();
              } catch (err) {
                message.error((err as Error).message);
              }
            }}
          >
            检测全部
          </Button>
          <Button icon={<ReloadOutlined />} loading={isFetching} onClick={() => refetch()}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            添加房间
          </Button>
        </Space>
      }
    >
      <Table<RoomOut>
        rowKey="id"
        size="middle"
        loading={isLoading}
        dataSource={rooms ?? []}
        pagination={false}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (keys) => setSelectedIds(keys as number[]),
        }}
        columns={[
          {
            title: "监控",
            dataIndex: "enabled",
            width: 80,
            render: (_, room) => (
              <Switch
                size="small"
                checked={room.enabled}
                onChange={(checked) => toggleEnabled(room, checked)}
              />
            ),
          },
          {
            title: "状态",
            key: "status",
            width: 190,
            render: (_, room) => {
              const p = progress[room.id];
              if (room.recording) {
                return (
                  <Space size={4} wrap>
                    <Tag color="processing">录制中</Tag>
                    {p && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {formatDuration(p.duration ?? 0)} ·{" "}
                        {((p.size ?? 0) / 1048576).toFixed(1)}MB
                      </Typography.Text>
                    )}
                  </Space>
                );
              }
              const color =
                room.status === "error" ? "error" : room.status === "disabled" ? "warning" : "default";
              const text =
                room.status === "error"
                  ? "异常"
                  : room.status === "disabled"
                    ? "已停用"
                    : "等待开播";
              return (
                <Tooltip title={room.status_msg || undefined}>
                  <Tag color={color}>{text}</Tag>
                </Tooltip>
              );
            },
          },
          {
            title: "主播",
            dataIndex: "anchor_name",
            width: 150,
            render: (v: string, room) => (
              <Space size={6}>
                <span>{v || "（未识别）"}</span>
                {room.has_cookie && <Tag bordered={false}>Cookie</Tag>}
                {Object.keys(room.overrides ?? {}).length > 0 && (
                  <Tooltip title={Object.keys(room.overrides).join(", ")}>
                    <Tag color="blue" bordered={false}>
                      覆盖{Object.keys(room.overrides).length}
                    </Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          { title: "平台", dataIndex: "platform_name", width: 110 },
          {
            title: "直播间",
            dataIndex: "room_url",
            render: (url: string) => (
              <a href={url} target="_blank" rel="noreferrer">
                {url.length > 44 ? `${url.slice(0, 44)}…` : url}
              </a>
            ),
          },
          {
            title: "清晰度",
            dataIndex: "quality",
            width: 80,
            render: (q: string) => qualityLabel(q),
          },
          {
            title: "间隔",
            dataIndex: "check_interval",
            width: 70,
            render: (v: number | null) => (v ? `${v}s` : "全局"),
          },
          {
            title: "操作",
            key: "actions",
            width: 160,
            render: (_, room) => (
              <Space size={10}>
                <Tooltip title="检测">
                  <Button
                    type="text"
                    size="small"
                    icon={<CloudSyncOutlined style={{ fontSize: 16 }} />}
                    loading={checkNow.isPending}
                    onClick={() => runCheck(room)}
                  />
                </Tooltip>
                {room.recording && (
                  <Popconfirm
                    title="停止该房间的录制？"
                    onConfirm={async () => {
                      await stop.mutateAsync(room.id);
                      message.success("已停止录制");
                    }}
                  >
                    <Tooltip title="停止录制">
                      <Button type="text" size="small" danger loading={stop.isPending}>
                        停止
                      </Button>
                    </Tooltip>
                  </Popconfirm>
                )}
                <Tooltip title="编辑">
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined style={{ fontSize: 16 }} />}
                    onClick={() => openEdit(room)}
                  />
                </Tooltip>
                <Popconfirm
                  title="删除该房间？"
                  description="录制记录会一并删除（磁盘文件保留）"
                  onConfirm={async () => {
                    await remove.mutateAsync(room.id);
                    message.success("已删除");
                  }}
                >
                  <Tooltip title="删除">
                    <Button type="text" size="small" danger icon={<DeleteOutlined style={{ fontSize: 16 }} />} />
                  </Tooltip>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={form.id == null ? "添加房间" : "编辑房间"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        confirmLoading={create.isPending || update.isPending}
        width={720}
      >
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          除“基础信息”外，各设置项留空/清除 = 跟随全局设置
        </Typography.Text>
        <Card size="small" title="基础信息" style={{ marginTop: 8 }}>
          <Row gutter={[12, 8]}>
            <Col span={24}>
              <Input
                placeholder="直播间地址，如 https://live.bilibili.com/6"
                value={form.room_url}
                onChange={(e) => setForm({ ...form, room_url: e.target.value })}
                disabled={form.id != null}
              />
            </Col>
            <Col span={12}>
              <Select
                style={{ width: "100%" }}
                placeholder="平台（默认自动识别）"
                value={form.platform}
                onChange={(v) => setForm({ ...form, platform: v })}
                allowClear
                showSearch
                optionFilterProp="label"
                options={(platforms ?? [])
                  .filter((p) => !p.deprecated)
                  .map((p) => ({
                    value: p.key,
                    label: p.needs_cookie ? `${p.name}（需 Cookie）` : p.name,
                  }))}
                disabled={form.id != null}
              />
            </Col>
            <Col span={12}>
              <Input
                placeholder="备注（可选）"
                value={form.remark}
                onChange={(e) => setForm({ ...form, remark: e.target.value })}
              />
            </Col>
            <Col span={24}>
              <Input.TextArea
                placeholder="Cookie（可选，YouTube/淘宝等平台必需；敏感信息仅保存在本机数据库）"
                value={form.cookie}
                onChange={(e) => setForm({ ...form, cookie: e.target.value, clearCookie: false })}
                rows={2}
              />
            </Col>
            {form.id != null && form.hasCookie && (
              <Col span={24}>
                <Button
                  size="small"
                  danger={form.clearCookie}
                  onClick={() => setForm({ ...form, clearCookie: !form.clearCookie })}
                >
                  {form.clearCookie ? "已勾选：保存时删除 Cookie" : "删除已保存的 Cookie"}
                </Button>
              </Col>
            )}
            <Col span={24}>
              <Space>
                <span>启用监控</span>
                <Switch checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} />
              </Space>
            </Col>
          </Row>
        </Card>
        <Collapse
          size="small"
          style={{ marginTop: 12 }}
          items={[
            {
              key: "record",
              label: "常规录制",
              children: (
                <Row gutter={[12, 8]}>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="清晰度"
                      allowClear
                      value={form.quality}
                      onChange={(v) => setForm({ ...form, quality: v })}
                      options={Object.entries(QUALITY_LABELS).map(([value, label]) => ({ value, label }))}
                    />
                  </Col>
                  <Col span={8}>
                    <InputNumber
                      style={{ width: "100%" }}
                      placeholder="检测时间(秒)"
                      min={10}
                      max={3600}
                      value={form.check_interval}
                      onChange={(v) => setForm({ ...form, check_interval: v ?? undefined })}
                    />
                  </Col>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="录制格式"
                      allowClear
                      value={form.overrides.output_format}
                      options={[
                        { value: "mp4", label: "MP4" },
                        { value: "flv", label: "FLV" },
                      ]}
                      onChange={(v) => setOv("output_format", v)}
                    />
                  </Col>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="音频格式"
                      allowClear
                      value={form.overrides.audio_format}
                      options={[
                        { value: "auto", label: "自动" },
                        { value: "aac", label: "AAC" },
                        { value: "m4a", label: "M4A" },
                        { value: "mp3", label: "MP3" },
                      ]}
                      onChange={(v) => setOv("audio_format", v)}
                    />
                  </Col>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="拉流协议"
                      allowClear
                      value={form.overrides.stream_type}
                      options={[
                        { value: "auto", label: "自动" },
                        { value: "flv", label: "FLV 优先" },
                        { value: "hls", label: "HLS 优先" },
                      ]}
                      onChange={(v) => setOv("stream_type", v)}
                    />
                  </Col>
                </Row>
              ),
            },
            {
              key: "network",
              label: "网络",
              children: (
                <Row gutter={[12, 8]}>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="强制 HTTPS"
                      allowClear
                      value={boolVal(form.overrides.force_https)}
                      options={BOOL_OPTS}
                      onChange={(v) => setOv("force_https", v === undefined ? undefined : v === "1")}
                    />
                  </Col>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="下载器直连"
                      allowClear
                      value={boolVal(form.overrides.flv_direct_download)}
                      options={BOOL_OPTS}
                      onChange={(v) =>
                        setOv("flv_direct_download", v === undefined ? undefined : v === "1")
                      }
                    />
                  </Col>
                </Row>
              ),
            },
            {
              key: "limits",
              label: "录制限制",
              children: (
                <Row gutter={[12, 8]}>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="分段录制"
                      allowClear
                      value={boolVal(form.overrides.segment_enabled)}
                      options={BOOL_OPTS}
                      onChange={(v) =>
                        setOv("segment_enabled", v === undefined ? undefined : v === "1")
                      }
                    />
                  </Col>
                  <Col span={8}>
                    <InputNumber
                      style={{ width: "100%" }}
                      placeholder="分段时间(秒)"
                      min={30}
                      max={86400}
                      value={form.overrides.segment_seconds}
                      onChange={(v) => setOv("segment_seconds", v ?? undefined)}
                    />
                  </Col>
                  <Col span={8}>
                    <InputNumber
                      style={{ width: "100%" }}
                      placeholder="单场时长(h)"
                      min={0}
                      max={720}
                      value={form.overrides.max_session_hours}
                      onChange={(v) => setOv("max_session_hours", v ?? undefined)}
                    />
                  </Col>
                </Row>
              ),
            },
            {
              key: "postprocess",
              label: "录制后处理",
              children: (
                <Row gutter={[12, 8]}>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="转 MP4"
                      allowClear
                      value={boolVal(form.overrides.auto_convert_mp4)}
                      options={BOOL_OPTS}
                      onChange={(v) =>
                        setOv("auto_convert_mp4", v === undefined ? undefined : v === "1")
                      }
                    />
                  </Col>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="转换后删原文件"
                      allowClear
                      value={boolVal(form.overrides.delete_original_after_convert)}
                      options={BOOL_OPTS}
                      onChange={(v) =>
                        setOv("delete_original_after_convert", v === undefined ? undefined : v === "1")
                      }
                    />
                  </Col>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="时间字幕"
                      allowClear
                      value={boolVal(form.overrides.write_time_subtitle)}
                      options={BOOL_OPTS}
                      onChange={(v) =>
                        setOv("write_time_subtitle", v === undefined ? undefined : v === "1")
                      }
                    />
                  </Col>
                  <Col span={8}>
                    <Select
                      style={{ width: "100%" }}
                      placeholder="录后脚本"
                      allowClear
                      value={boolVal(form.overrides.run_script_after)}
                      options={BOOL_OPTS}
                      onChange={(v) =>
                        setOv("run_script_after", v === undefined ? undefined : v === "1")
                      }
                    />
                  </Col>
                  <Col span={16}>
                    <Input
                      placeholder="脚本命令（覆盖全局）"
                      allowClear
                      value={form.overrides.script_after_cmd}
                      onChange={(e) => setOv("script_after_cmd", e.target.value || undefined)}
                    />
                  </Col>
                </Row>
              ),
            },
          ]}
        />
      </Modal>
    </Card>
  );
}
