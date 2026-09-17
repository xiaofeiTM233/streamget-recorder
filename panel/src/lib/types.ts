"use client";

/** 与后端 API 契约对应的类型定义。 */

/** 房间级设置覆盖：键为全局设置名，未出现的键跟随全局。 */
export type RoomOverrides = Partial<{
  output_format: "mp4" | "flv";
  audio_format: "auto" | "aac" | "m4a" | "mp3";
  stream_type: "auto" | "flv" | "hls";
  segment_enabled: boolean;
  segment_seconds: number;
  max_session_hours: number;
  force_https: boolean;
  flv_direct_download: boolean;
  auto_convert_mp4: boolean;
  delete_original_after_convert: boolean;
  write_time_subtitle: boolean;
  run_script_after: boolean;
  script_after_cmd: string;
}>;

export interface RoomOut {
  id: number;
  platform: string;
  platform_name: string;
  room_url: string;
  anchor_name: string;
  remark: string;
  quality: string;
  check_interval: number | null;
  overrides: RoomOverrides;
  has_cookie: boolean;
  enabled: boolean;
  status: "idle" | "recording" | "error" | "disabled";
  status_msg: string;
  last_check_at: string | null;
  recording: boolean;
}

export interface RecordingProgress {
  session_id?: number;
  file?: string;
  duration?: number;
  size?: number;
  bitrate?: string;
  error?: string;
}

export interface WsEvent extends RecordingProgress {
  type: string;
  ts: string;
  room_id?: number;
  status?: string;
  status_msg?: string;
  is_live?: boolean;
  anchor_name?: string;
  title?: string;
  line?: string;
}

export interface PlatformInfo {
  key: string;
  name: string;
  needs_cookie: boolean;
  deprecated: boolean;
}

export interface Summary {
  rooms_total: number;
  rooms_enabled: number;
  rooms_error: number;
  recording: number;
  storage_size: number;
  file_count: number;
  version: string;
}

export interface BrowseFile {
  file_path: string;
  filename: string;
  size: number;
  modified_time: string | null;
  download_url: string;
}

export interface BrowseFolder {
  name: string;
  file_count: number;
  size: number;
}

export interface BrowseResult {
  path: string;
  search: string;
  folders: BrowseFolder[];
  files: BrowseFile[];
}

export interface SettingsPayload {
  settings: Record<string, string | number | boolean>;
  record_dir: string;
}

export interface RoomPayload {
  room_url: string;
  platform?: string | null;
  quality?: string | null;
  check_interval?: number | null;
  cookie?: string | null;
  remark?: string | null;
  enabled?: boolean;
  overrides?: RoomOverrides | null;
}

/** 清晰度代码 → 中文显示名（存储值仍为英文代码）。audio = 仅录制音频。 */
export const QUALITY_LABELS: Record<string, string> = {
  OD: "原画",
  UHD: "蓝光(4K)",
  HD: "高清",
  SD: "标清",
  LD: "流畅",
  audio: "仅音频",
};

export function qualityLabel(q: string | null | undefined): string {
  if (!q) return "默认";
  return QUALITY_LABELS[q] ?? q;
}
