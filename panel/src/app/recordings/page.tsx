"use client";

import { ArrowUpOutlined, FileOutlined, FolderOutlined, SearchOutlined } from "@ant-design/icons";
import {
  App as AntApp,
  Breadcrumb,
  Button,
  Card,
  Input,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";
import { formatDuration, formatSize, useBrowse, useRecordingMutations } from "@/lib/api";
import type { BrowseFile, BrowseFolder } from "@/lib/types";

type Row =
  | ({ key: string; type: "folder" } & BrowseFolder)
  | ({ key: string; type: "file" } & BrowseFile);

function statusTag(status: string) {
  if (status === "recording") return <Tag color="processing">录制中</Tag>;
  if (status === "finished") return <Tag color="success">已完成</Tag>;
  return <Tag color="error">{status}</Tag>;
}

function getTokenQs(): string {
  if (typeof window === "undefined") return "";
  const token = window.localStorage.getItem("recorder_token");
  return token ? `?token=${encodeURIComponent(token)}` : "";
}

export default function RecordingsPage() {
  const { message } = AntApp.useApp();
  const { deleteFile } = useRecordingMutations();
  const [path, setPath] = useState("");
  const [search, setSearch] = useState("");
  const [kw, setKw] = useState("");
  const { data, isLoading, isFetching } = useBrowse(path, search);

  const segments = path ? path.split("/") : [];
  const searching = !!search;
  const rows: Row[] = [
    ...(data?.folders ?? []).map((f) => ({ ...f, key: `d:${f.name}`, type: "folder" as const })),
    ...(data?.files ?? []).map((f) => ({ ...f, key: `f:${f.id}`, type: "file" as const })),
  ];

  const enterFolder = (name: string) => {
    setSearch("");
    setKw("");
    setPath(path ? `${path}/${name}` : name);
  };

  const columns: ColumnsType<Row> = [
    {
      title: "名称",
      key: "name",
      render: (_, row) =>
        row.type === "folder" ? (
          <a onClick={() => enterFolder(row.name)}>
            <Space size={8}>
              <FolderOutlined style={{ color: "#faad14", fontSize: 16 }} />
              <span>{row.name}</span>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {row.file_count} 个文件
              </Typography.Text>
            </Space>
          </a>
        ) : (
          <Tooltip title={row.file_path}>
            <Space size={8}>
              <FileOutlined style={{ color: "#8c8c8c", fontSize: 15 }} />
              <Typography.Text style={{ maxWidth: 480 }} ellipsis={{ tooltip: row.filename }}>
                {row.filename}
              </Typography.Text>
            </Space>
          </Tooltip>
        ),
    },
    ...(searching
      ? ([
          {
            title: "主播",
            key: "anchor",
            width: 130,
            render: (_, row: Row) => row.type === "file" ? row.anchor_name || "—" : "—",
          },
        ] as ColumnsType<Row>)
      : []),
    {
      title: "大小",
      key: "size",
      width: 110,
      render: (_, row) => formatSize(row.size),
    },
    {
      title: "时长",
      key: "duration",
      width: 100,
      render: (_, row) => (row.type === "file" ? formatDuration(row.duration) : "—"),
    },
    {
      title: "开始时间",
      key: "start_time",
      width: 170,
      render: (_, row) =>
        row.type === "file" && row.start_time ? new Date(row.start_time).toLocaleString() : "—",
    },
    {
      title: "状态",
      key: "status",
      width: 95,
      render: (_, row) => (row.type === "file" ? statusTag(row.status) : "—"),
    },
    {
      title: "操作",
      key: "op",
      width: 130,
      render: (_, row) =>
        row.type === "folder" ? (
          <a onClick={() => enterFolder(row.name)}>打开</a>
        ) : (
          <Space size={12}>
            <a href={`${row.download_url}${getTokenQs()}`} target="_blank" rel="noreferrer">
              下载
            </a>
            <Popconfirm
              title="删除该文件？"
              description="将同时删除磁盘上的文件"
              onConfirm={async () => {
                await deleteFile.mutateAsync({ id: row.id, deleteDisk: true });
                message.success("已删除");
              }}
            >
              <a style={{ color: "#ff4d4f" }}>删除</a>
            </Popconfirm>
          </Space>
        ),
    },
  ];

  return (
    <Card
      title="录制文件"
      extra={
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索文件名 / 主播 / 标题"
          style={{ width: 280 }}
          value={kw}
          onChange={(e) => {
            setKw(e.target.value);
            if (!e.target.value) setSearch("");
          }}
          onPressEnter={() => {
            setSearch(kw.trim());
            setPath("");
          }}
        />
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        {searching ? (
          <>
            <Tag color="blue" closable onClose={() => setSearch("")}>
              搜索：{search}
            </Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              最多显示 500 条结果
            </Typography.Text>
          </>
        ) : (
          <>
            <Breadcrumb
              items={[
                {
                  title: (
                    <a onClick={() => setPath("")}>
                      <FolderOutlined style={{ marginRight: 4 }} />
                      全部文件
                    </a>
                  ),
                },
                ...segments.map((seg, i) => ({
                  title:
                    i === segments.length - 1 ? (
                      seg
                    ) : (
                      <a onClick={() => setPath(segments.slice(0, i + 1).join("/"))}>{seg}</a>
                    ),
                })),
              ]}
            />
            <Button
              size="small"
              icon={<ArrowUpOutlined />}
              disabled={!path}
              onClick={() => setPath(segments.slice(0, -1).join("/"))}
            >
              返回上级
            </Button>
          </>
        )}
      </Space>

      <Table<Row>
        rowKey="key"
        size="middle"
        loading={isLoading || isFetching}
        dataSource={rows}
        onRow={(row) =>
          row.type === "folder"
            ? { onDoubleClick: () => enterFolder(row.name), style: { cursor: "pointer" } }
            : {}
        }
        pagination={{
          pageSize: 50,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100],
          showTotal: (total) => `共 ${total} 项`,
        }}
        columns={columns}
        locale={{
          emptyText:
            searching ? "没有匹配的文件" : path ? "该文件夹为空" : "还没有录制文件，添加房间后开播自动录制",
        }}
      />
    </Card>
  );
}
