"use client";

import { PlusOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import {
  App as AntApp,
  Button,
  Card,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
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
import type { RoomOut, RoomPayload } from "@/lib/types";

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
};

export default function RoomsPage() {
  const { message } = AntApp.useApp();
  const { data: rooms, isLoading, refetch, isFetching } = useRooms();
  const { data: platforms } = usePlatforms();
  const { progress } = useEvents();
  const { create, update, remove, batchToggle, checkNow, stop, checkAll } = useRoomMutations();

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

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
                size="small"
                onClick={async () => {
                  await batchToggle.mutateAsync({ ids: selectedIds, enabled: true });
                  setSelectedIds([]);
                  message.success("已启用");
                }}
              >
                批量启用（{selectedIds.length}）
              </Button>
              <Button
                size="small"
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
            size="small"
            icon={<SyncOutlined />}
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
            全部刷新
          </Button>
          <Button icon={<ReloadOutlined />} size="small" loading={isFetching} onClick={() => refetch()} />
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openCreate}>
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
            width: 230,
            render: (_, room) => (
              <Space size={4}>
                <Button size="small" loading={checkNow.isPending} onClick={() => runCheck(room)}>
                  检测
                </Button>
                {room.recording && (
                  <Button
                    size="small"
                    danger
                    loading={stop.isPending}
                    onClick={async () => {
                      await stop.mutateAsync(room.id);
                      message.success("已停止录制");
                    }}
                  >
                    停止
                  </Button>
                )}
                <Button size="small" onClick={() => openEdit(room)}>
                  编辑
                </Button>
                <Popconfirm
                  title="删除该房间？"
                  description="录制记录会一并删除（磁盘文件保留）"
                  onConfirm={async () => {
                    await remove.mutateAsync(room.id);
                    message.success("已删除");
                  }}
                >
                  <Button size="small" danger>
                    删除
                  </Button>
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
        width={560}
      >
        <Space direction="vertical" size={12} style={{ width: "100%", marginTop: 8 }}>
          <Input
            placeholder="直播间地址，如 https://live.bilibili.com/6"
            value={form.room_url}
            onChange={(e) => setForm({ ...form, room_url: e.target.value })}
            disabled={form.id != null}
          />
          <Space.Compact style={{ width: "100%" }}>
            <Select
              style={{ width: 220 }}
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
            <Select
              style={{ width: 120 }}
              placeholder="清晰度"
              value={form.quality}
              onChange={(v) => setForm({ ...form, quality: v })}
              allowClear
              options={Object.entries(QUALITY_LABELS).map(([value, label]) => ({ value, label }))}
            />
            <InputNumber
              style={{ width: 140 }}
              placeholder="轮询间隔(秒)"
              min={10}
              max={3600}
              value={form.check_interval}
              onChange={(v) => setForm({ ...form, check_interval: v ?? undefined })}
            />
          </Space.Compact>
          <Input.TextArea
            placeholder="Cookie（可选，YouTube/淘宝等平台必需；敏感信息仅保存在本机数据库）"
            value={form.cookie}
            onChange={(e) => setForm({ ...form, cookie: e.target.value, clearCookie: false })}
            rows={2}
          />
          {form.id != null && form.hasCookie && (
            <Button
              size="small"
              danger={form.clearCookie}
              onClick={() => setForm({ ...form, clearCookie: !form.clearCookie })}
            >
              {form.clearCookie ? "已勾选：保存时删除 Cookie" : "删除已保存的 Cookie"}
            </Button>
          )}
          <Input
            placeholder="备注（可选）"
            value={form.remark}
            onChange={(e) => setForm({ ...form, remark: e.target.value })}
          />
          <Space>
            <span>启用监控</span>
            <Switch
              checked={form.enabled}
              onChange={(v) => setForm({ ...form, enabled: v })}
            />
          </Space>
        </Space>
      </Modal>
    </Card>
  );
}
