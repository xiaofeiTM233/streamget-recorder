"use client";

import { ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Row, Statistic, Table, Tag, Tooltip } from "antd";
import Link from "next/link";
import { formatDuration, formatSize, useRooms, useSummary } from "@/lib/api";
import { useEvents } from "@/lib/events";
import type { RoomOut } from "@/lib/types";

const STATUS_META: Record<string, { color: string; text: string }> = {
  idle: { color: "default", text: "等待开播" },
  recording: { color: "processing", text: "录制中" },
  error: { color: "error", text: "异常" },
  disabled: { color: "warning", text: "已停用" },
};

export default function DashboardPage() {
  const { data: summary } = useSummary();
  const { data: rooms, isLoading, refetch, isFetching } = useRooms();
  const { progress } = useEvents();

  const rows = rooms ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Row gutter={16}>
        <Col span={5}>
          <Card size="small">
            <Statistic title="监控房间" value={summary?.rooms_enabled ?? 0} suffix={`/ ${summary?.rooms_total ?? 0}`} />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small">
            <Statistic
              title="录制中"
              value={summary?.recording ?? 0}
              valueStyle={{ color: "#eb2f96" }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small">
            <Statistic title="异常" value={summary?.rooms_error ?? 0} valueStyle={{ color: summary?.rooms_error ? "#ff4d4f" : undefined }} />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small">
            <Statistic title="录制文件" value={summary?.file_count ?? 0} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="磁盘占用" value={formatSize(summary?.storage_size ?? 0)} />
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        title="房间实时状态"
        extra={
          <Button icon={<ReloadOutlined />} size="small" loading={isFetching} onClick={() => refetch()}>
            刷新
          </Button>
        }
      >
        {summary && summary.rooms_total === 0 ? (
          <Alert
            type="info"
            showIcon
            message="还没有监控房间"
            description={
              <span>
                先到 <Link href="/rooms/">房间管理</Link> 添加要监控的直播间，开播后将自动录制。
              </span>
            }
          />
        ) : (
          <Table<RoomOut>
            rowKey="id"
            size="small"
            loading={isLoading}
            pagination={false}
            dataSource={rows}
            columns={[
              {
                title: "状态",
                key: "status",
                width: 220,
                render: (_, room) => {
                  const meta = STATUS_META[room.status] ?? STATUS_META.idle;
                  const p = progress[room.id];
                  return (
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <Tag color={meta.color} style={{ width: "fit-content" }}>
                        {meta.text}
                      </Tag>
                      {room.status === "recording" && p && (
                        <Tooltip title={`${p.file ?? ""}`}>
                          <span style={{ fontSize: 12, opacity: 0.75 }}>
                            已录 {formatDuration(p.duration ?? 0)} · {formatSize(p.size ?? 0)}
                            {p.bitrate ? ` · ${p.bitrate}` : ""}
                          </span>
                        </Tooltip>
                      )}
                      {room.status === "error" && room.status_msg && (
                        <Tooltip title={room.status_msg}>
                          <span style={{ fontSize: 12, color: "#ff4d4f" }}>
                            {room.status_msg.slice(0, 40)}
                          </span>
                        </Tooltip>
                      )}
                    </div>
                  );
                },
              },
              {
                title: "主播",
                dataIndex: "anchor_name",
                width: 160,
                render: (v) => v || "（未识别）",
              },
              { title: "平台", dataIndex: "platform_name", width: 110 },
              {
                title: "直播间",
                dataIndex: "room_url",
                render: (url: string) => (
                  <a href={url} target="_blank" rel="noreferrer">
                    {url.length > 48 ? `${url.slice(0, 48)}…` : url}
                  </a>
                ),
              },
              {
                title: "最近检测",
                dataIndex: "last_check_at",
                width: 170,
                render: (v: string | null) => (v ? new Date(v).toLocaleString() : "—"),
              },
            ]}
          />
        )}
      </Card>
    </div>
  );
}
