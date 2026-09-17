"use client";

import {
  ArrowUpOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FileOutlined,
  FolderOutlined,
  HomeOutlined,
  SearchOutlined,
} from "@ant-design/icons";
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
import { formatSize, useBrowse, useRecordingMutations } from "@/lib/api";
import type { BrowseFile, BrowseFolder } from "@/lib/types";

type Row =
  | ({ key: string; type: "folder" } & BrowseFolder)
  | ({ key: string; type: "file" } & BrowseFile);

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
    ...(data?.files ?? []).map((f) => ({ ...f, key: `f:${f.file_path}`, type: "file" as const })),
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
              <Typography.Text style={{ maxWidth: 480 }} ellipsis>
                {row.filename}
              </Typography.Text>
            </Space>
          </Tooltip>
        ),
    },
    {
      title: "大小",
      key: "size",
      width: 110,
      render: (_, row) => formatSize(row.size),
    },
    {
      title: "修改时间",
      key: "modified_time",
      width: 170,
      render: (_, row) =>
        row.type === "file" && row.modified_time
          ? new Date(row.modified_time).toLocaleString()
          : "—",
    },
    {
      title: "操作",
      key: "op",
      width: 110,
      render: (_, row) =>
        row.type === "folder" ? (
          <Popconfirm
            title="删除该文件夹？"
            description="文件夹内全部内容将移动到回收站"
            onConfirm={async () => {
              await deleteFile.mutateAsync({ path: path ? `${path}/${row.name}` : row.name });
              message.success("已删除");
            }}
          >
            <Tooltip title="删除">
              <a style={{ color: "#ff4d4f", fontSize: 16 }}>
                <DeleteOutlined />
              </a>
            </Tooltip>
          </Popconfirm>
        ) : (
          <Space size={14}>
            <Tooltip title="下载">
              <a href={`${row.download_url}${getTokenQs()}`} target="_blank" rel="noreferrer">
                <DownloadOutlined style={{ fontSize: 16 }} />
              </a>
            </Tooltip>
            <Popconfirm
              title="删除该文件？"
              description="文件将移动到回收站"
              onConfirm={async () => {
                await deleteFile.mutateAsync({ path: row.file_path });
                message.success("已删除");
              }}
            >
              <Tooltip title="删除">
                <a style={{ color: "#ff4d4f", fontSize: 16 }}>
                  <DeleteOutlined />
                </a>
              </Tooltip>
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
          placeholder="搜索文件 / 文件夹"
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
                    <Tooltip title="全部文件">
                      <a onClick={() => setPath("")}>
                        <HomeOutlined style={{ fontSize: 15 }} />
                      </a>
                    </Tooltip>
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
            <Tooltip title="返回上级">
              <Button
                size="small"
                icon={<ArrowUpOutlined />}
                disabled={!path}
                onClick={() => setPath(segments.slice(0, -1).join("/"))}
              />
            </Tooltip>
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
