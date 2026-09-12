"use client";

import { SearchOutlined } from "@ant-design/icons";
import {
  App as AntApp,
  Button,
  Card,
  DatePicker,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import {
  formatDuration,
  formatSize,
  useRecordingMutations,
  useRecordings,
  useRooms,
  type RecordingFilter,
} from "@/lib/api";
import type { RecordingSession, SessionFile } from "@/lib/types";

function statusTag(status: string) {
  if (status === "recording") return <Tag color="processing">录制中</Tag>;
  if (status === "finished") return <Tag color="success">已完成</Tag>;
  return <Tag color="error">{status}</Tag>;
}

export default function RecordingsPage() {
  const { message } = AntApp.useApp();
  const { data: rooms } = useRooms();
  const { deleteFile } = useRecordingMutations();
  const [anchor, setAnchor] = useState("");
  const [roomId, setRoomId] = useState<number | undefined>();
  const [range, setRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const filter: RecordingFilter = {
    anchor: anchor || undefined,
    room_id: roomId,
    start_date: range?.[0] ? range[0].format("YYYY-MM-DD") : undefined,
    end_date: range?.[1] ? range[1].format("YYYY-MM-DD") : undefined,
    page,
    page_size: pageSize,
  };
  const { data, isLoading, isFetching } = useRecordings(filter);

  return (
    <Card title="录制文件">
      <Space wrap style={{ marginBottom: 16 }}>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="按主播搜索"
          style={{ width: 200 }}
          onPressEnter={() => setPage(1)}
          onChange={(e) => {
            setAnchor(e.target.value);
            setPage(1);
          }}
        />
        <Select
          allowClear
          placeholder="按房间筛选"
          style={{ width: 220 }}
          value={roomId}
          onChange={(v) => {
            setRoomId(v);
            setPage(1);
          }}
          options={(rooms ?? []).map((r) => ({
            value: r.id,
            label: `${r.anchor_name || r.room_url}（${r.platform_name}）`,
          }))}
        />
        <DatePicker.RangePicker
          value={range}
          onChange={(v) => {
            setRange(v);
            setPage(1);
          }}
        />
      </Space>

      <Table<RecordingSession>
        rowKey="id"
        size="middle"
        loading={isLoading || isFetching}
        dataSource={data?.items ?? []}
        expandable={{
          expandedRowRender: (session) => (
            <Table<SessionFile>
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={session.files}
              columns={[
                { title: "文件", dataIndex: "filename", ellipsis: true },
                {
                  title: "大小",
                  dataIndex: "size",
                  width: 100,
                  render: (v: number) => formatSize(v),
                },
                {
                  title: "时长",
                  dataIndex: "duration",
                  width: 90,
                  render: (v: number) => formatDuration(v),
                },
                { title: "状态", dataIndex: "status", width: 90, render: statusTag },
                {
                  title: "操作",
                  key: "op",
                  width: 130,
                  render: (_, file) => (
                    <Space size={4}>
                      <a href={`${file.download_url}${getTokenQs()}`} target="_blank" rel="noreferrer">
                        下载
                      </a>
                      <Popconfirm
                        title="删除该文件？"
                        description="将同时删除磁盘上的文件"
                        onConfirm={async () => {
                          await deleteFile.mutateAsync({ id: file.id, deleteDisk: true });
                          message.success("已删除");
                        }}
                      >
                        <a style={{ color: "#ff4d4f" }}>删除</a>
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />
          ),
        }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 段录制`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
        columns={[
          {
            title: "主播",
            dataIndex: "anchor_name",
            width: 150,
            render: (v: string) => v || "（未识别）",
          },
          { title: "平台", dataIndex: "platform_name", width: 110 },
          {
            title: "标题",
            dataIndex: "title",
            ellipsis: true,
            render: (v: string) => <Typography.Text ellipsis={{ tooltip: v }}>{v || "—"}</Typography.Text>,
          },
          { title: "清晰度", dataIndex: "quality", width: 80 },
          {
            title: "开始时间",
            dataIndex: "start_time",
            width: 165,
            render: (v: string | null) => (v ? new Date(v).toLocaleString() : "—"),
          },
          {
            title: "总时长",
            key: "duration",
            width: 90,
            render: (_, s) => formatDuration(s.total_duration),
          },
          {
            title: "总大小",
            key: "size",
            width: 100,
            render: (_, s) => formatSize(s.total_size),
          },
          {
            title: "文件数",
            key: "files",
            width: 80,
            render: (_, s) => s.files.length,
          },
          { title: "状态", dataIndex: "status", width: 95, render: statusTag },
        ]}
      />
    </Card>
  );
}

function getTokenQs(): string {
  if (typeof window === "undefined") return "";
  const token = window.localStorage.getItem("recorder_token");
  return token ? `?token=${encodeURIComponent(token)}` : "";
}
