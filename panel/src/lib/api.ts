"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  BrowseResult,
  PlatformInfo,
  RecordingList,
  RoomOut,
  RoomPayload,
  SettingsPayload,
  Summary,
} from "./types";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem("recorder_token") ?? "";
}

export function setToken(token: string) {
  window.localStorage.setItem("recorder_token", token);
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { ...init, headers });
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

export interface RecordingFilter {
  room_id?: number;
  anchor?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
  page_size?: number;
}

export function useRecordings(filter: RecordingFilter) {
  const qs = new URLSearchParams();
  if (filter.room_id != null) qs.set("room_id", String(filter.room_id));
  if (filter.anchor) qs.set("anchor", filter.anchor);
  if (filter.start_date) qs.set("start_date", filter.start_date);
  if (filter.end_date) qs.set("end_date", filter.end_date);
  qs.set("page", String(filter.page ?? 1));
  qs.set("page_size", String(filter.page_size ?? 20));
  return useQuery({
    queryKey: ["recordings", filter],
    queryFn: () => api<RecordingList>(`/api/recordings?${qs.toString()}`),
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
    mutationFn: ({ id, deleteDisk }: { id: number; deleteDisk: boolean }) =>
      api(`/api/recordings/files/${id}?delete_disk=${deleteDisk}`, { method: "DELETE" }),
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
