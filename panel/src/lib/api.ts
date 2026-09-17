"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  BrowseResult,
  PlatformInfo,
  RoomOut,
  RoomPayload,
  SettingsPayload,
  Summary,
} from "./types";

export function normalizeBaseUrl(raw: string): string {
  return (raw || "").trim().replace(/\/+$/, "");
}

/* ---------- 连接地址与令牌（模块级，SSR 安全） ---------- */

const CONNECTION_KEY = "recorder_panel.connection";
const LEGACY_TOKEN_KEY = "recorder_token";

function readStoredToken(): string {
  if (typeof window === "undefined") return "";
  try {
    const raw = window.localStorage.getItem(CONNECTION_KEY);
    if (raw) return (JSON.parse(raw) as { token?: string }).token ?? "";
  } catch {
    // ignore
  }
  // 迁移旧版令牌键
  const legacy = window.localStorage.getItem(LEGACY_TOKEN_KEY) ?? "";
  if (legacy) {
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
  }
  return legacy;
}

let apiBase = "";
let apiToken = "";

if (typeof window !== "undefined") {
  apiBase = normalizeBaseUrl(readStoredBase());
  apiToken = readStoredToken();
}

function readStoredBase(): string {
  if (typeof window === "undefined") return "";
  try {
    const raw = window.localStorage.getItem(CONNECTION_KEY);
    if (raw) return (JSON.parse(raw) as { baseUrl?: string }).baseUrl ?? "";
  } catch {
    // ignore
  }
  return "";
}

export function getApiBase(): string {
  return apiBase;
}

export function getApiToken(): string {
  return apiToken;
}

/** 连接成功 / 登出后同步模块级凭据（api 与 WebSocket 共用）。 */
export function setApiCredentials(baseUrl: string, token: string) {
  apiBase = normalizeBaseUrl(baseUrl);
  apiToken = token;
}

/** 连接校验：GET {base}/api/summary，用显式凭据，不影响模块级状态。 */
export async function validateConnection(baseUrl: string, token: string): Promise<Summary> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let resp: Response;
  try {
    resp = await fetch(`${normalizeBaseUrl(baseUrl)}/api/summary`, { headers });
  } catch (e) {
    throw new Error(`无法连接到服务端：${e instanceof Error ? e.message : String(e)}`);
  }
  if (resp.status === 401) throw new Error("访问令牌缺失或不正确");
  if (!resp.ok) throw new Error(`请求失败（${resp.status}）`);
  return resp.json() as Promise<Summary>;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (apiToken) headers.Authorization = `Bearer ${apiToken}`;
  const resp = await fetch(`${apiBase}${path}`, { ...init, headers });
  if (!resp.ok) {
    if (resp.status === 401) {
      window.dispatchEvent(new Event("recorder:unauthorized"));
    }
    const body = await resp.json().catch(() => ({}) as { detail?: string });
    throw new Error(body.detail ?? `请求失败（${resp.status}）`);
  }
  return resp.json() as Promise<T>;
}

/* ---------- 查询 ---------- */

export function useSummary() {
  return useQuery({
    queryKey: ["summary"],
    queryFn: () => api<Summary>("/api/summary"),
    refetchInterval: 15_000,
  });
}

export function useRooms() {
  return useQuery({ queryKey: ["rooms"], queryFn: () => api<RoomOut[]>("/api/rooms") });
}

export function usePlatforms() {
  return useQuery({
    queryKey: ["platforms"],
    queryFn: () => api<PlatformInfo[]>("/api/platforms"),
    staleTime: Infinity,
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => api<SettingsPayload>("/api/settings"),
  });
}

/* ---------- 变更 ---------- */

export function useRoomMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["rooms"] });
    qc.invalidateQueries({ queryKey: ["summary"] });
  };
  const create = useMutation({
    mutationFn: (payload: RoomPayload) =>
      api<RoomOut>("/api/rooms", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<RoomPayload> }) =>
      api<RoomOut>(`/api/rooms/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/rooms/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
  const batchToggle = useMutation({
    mutationFn: (payload: { ids: number[]; enabled: boolean }) =>
      api("/api/rooms/batch-toggle", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: invalidate,
  });
  const checkNow = useMutation({
    mutationFn: (id: number) =>
      api<{ is_live: boolean; started: boolean; anchor_name: string; title: string }>(
        `/api/rooms/${id}/check`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  });
  const stop = useMutation({
    mutationFn: (id: number) => api<{ stopped: boolean }>(`/api/rooms/${id}/stop`, { method: "POST" }),
    onSuccess: invalidate,
  });
  const checkAll = useMutation({
    mutationFn: () => api<{ triggered: number }>("/api/rooms/check-all", { method: "POST" }),
  });
  return { create, update, remove, batchToggle, checkNow, stop, checkAll };
}

export function useSettingsMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (updates: Record<string, string | number | boolean>) =>
      api<SettingsPayload>("/api/settings", { method: "PUT", body: JSON.stringify(updates) }),
    onSuccess: (data) => qc.setQueryData(["settings"], data),
  });
}

export function useRecordingMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["recordings"] });
    qc.invalidateQueries({ queryKey: ["browse"] });
    qc.invalidateQueries({ queryKey: ["summary"] });
  };
  const deleteFile = useMutation({
    mutationFn: ({ path }: { path: string }) => {
      const qs = new URLSearchParams();
      qs.set("path", path);
      return api(`/api/recordings/files?${qs.toString()}`, { method: "DELETE" });
    },
    onSuccess: invalidate,
  });
  return { deleteFile };
}

export function useBrowse(path: string, search: string) {
  return useQuery({
    queryKey: ["browse", path, search],
    queryFn: () => {
      const qs = new URLSearchParams();
      if (path) qs.set("path", path);
      if (search) qs.set("search", search);
      return api<BrowseResult>(`/api/recordings/browse${qs.size ? `?${qs.toString()}` : ""}`);
    },
  });
}

/* ---------- 工具 ---------- */

export function formatDuration(seconds: number): string {
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}
