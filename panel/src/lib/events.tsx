"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getApiBase, getApiToken } from "./api";
import type { RecordingProgress, WsEvent } from "./types";

interface EventState {
  connected: boolean;
  progress: Record<number, RecordingProgress>;
}

const EventContext = createContext<EventState>({ connected: false, progress: {} });

function wsUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  const base = getApiBase();
  if (base) {
    return `${base.replace(/^http/, "ws")}/ws`;
  }
  if (process.env.NODE_ENV === "development") {
    const backend = process.env.NEXT_PUBLIC_BACKEND_URL ?? "ws://127.0.0.1:8000";
    return `${backend}/ws`;
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws`;
}

export function EventProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [progress, setProgress] = useState<Record<number, RecordingProgress>>({});
  const queryClient = useQueryClient();
  const handlerRef = useRef<(event: WsEvent) => void>(() => {});

  const handleEvent = useCallback(
    (data: WsEvent) => {
      switch (data.type) {
        case "snapshot": {
          const snapshotProgress = (data as WsEvent & { progress?: Record<number, RecordingProgress> })
            .progress;
          if (snapshotProgress) setProgress(snapshotProgress);
          queryClient.invalidateQueries({ queryKey: ["rooms"] });
          queryClient.invalidateQueries({ queryKey: ["summary"] });
          break;
        }
        case "room_status":
        case "recording_started":
          queryClient.invalidateQueries({ queryKey: ["rooms"] });
          queryClient.invalidateQueries({ queryKey: ["summary"] });
          break;
        case "recording_ended":
          setProgress((prev) => {
            if (data.room_id == null) return prev;
            const next = { ...prev };
            delete next[data.room_id];
            return next;
          });
          queryClient.invalidateQueries({ queryKey: ["rooms"] });
          queryClient.invalidateQueries({ queryKey: ["summary"] });
          queryClient.invalidateQueries({ queryKey: ["recordings"] });
          break;
        case "recording_progress":
          if (data.room_id != null) {
            setProgress((prev) => ({ ...prev, [data.room_id as number]: { ...data } }));
          }
          break;
        default:
          break;
      }
    },
    [queryClient],
  );
  handlerRef.current = handleEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retries = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const token = getApiToken();
      const url = token ? `${wsUrl()}?token=${encodeURIComponent(token)}` : wsUrl();
      ws = new WebSocket(url);
      ws.onopen = () => {
        setConnected(true);
        retries = 0;
      };
      ws.onmessage = (ev) => {
        try {
          handlerRef.current(JSON.parse(ev.data as string) as WsEvent);
        } catch {
          // 忽略无法解析的消息
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          retries += 1;
          timer = setTimeout(connect, Math.min(10_000, 1000 * retries));
        }
      };
      ws.onerror = () => ws?.close();
    };
    connect();

    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return (
    <EventContext.Provider value={{ connected, progress }}>{children}</EventContext.Provider>
  );
}

export function useEvents(): EventState {
  return useContext(EventContext);
}
