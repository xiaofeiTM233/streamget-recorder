"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { setApiCredentials, validateConnection } from "./api";
import type { ConnectionConfig } from "./types";

const STORAGE_KEY = "recorder_panel.connection";
const LEGACY_TOKEN_KEY = "recorder_token";

const DEFAULT_CONFIG: ConnectionConfig = {
  baseUrl: "",
  token: "",
  remember: false,
  autoConnect: false,
};

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function loadConnection(): ConnectionConfig {
  if (!isBrowser()) return { ...DEFAULT_CONFIG };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ConnectionConfig>;
      return { ...DEFAULT_CONFIG, ...parsed };
    }
  } catch {
    // ignore
  }
  // 迁移旧版令牌键：视为已记住 + 自动连接
  const legacy = window.localStorage.getItem(LEGACY_TOKEN_KEY);
  if (legacy) {
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
    return { ...DEFAULT_CONFIG, token: legacy, remember: true, autoConnect: true };
  }
  return { ...DEFAULT_CONFIG };
}

function saveConnection(config: ConnectionConfig): void {
  if (!isBrowser()) return;
  const persist: ConnectionConfig = { ...config };
  if (!config.remember) persist.token = "";
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persist));
}

function clearConnection(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(STORAGE_KEY);
  window.localStorage.removeItem(LEGACY_TOKEN_KEY);
}

interface ConnectionContextValue {
  config: ConnectionConfig;
  connected: boolean;
  connecting: boolean;
  /** 自动连接是否已尝试过（避免重复尝试） */
  autoTried: boolean;
  /** 上次连接错误信息 */
  lastError: string;
  connect: (override?: Partial<ConnectionConfig>) => Promise<void>;
  disconnect: () => void;
  /** 凭据失效时登出：保留连接地址，清空令牌 */
  logout: (reason?: string) => void;
  resetAll: () => void;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

/** 设置页保存令牌后同步本地连接（由 Provider 注册，未连接时为空操作）。 */
let localTokenSync: ((token: string) => void) | null = null;

export function applyLocalToken(token: string): void {
  localTokenSync?.(token);
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<ConnectionConfig>(() => loadConnection());
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [autoTried, setAutoTried] = useState(false);
  const [lastError, setLastError] = useState("");

  const configRef = useRef(config);
  configRef.current = config;
  const connectedRef = useRef(connected);
  connectedRef.current = connected;

  const connect = useCallback(async (override?: Partial<ConnectionConfig>) => {
    const merged = { ...configRef.current, ...override };
    const baseUrl = (merged.baseUrl || "").trim().replace(/\/+$/, "");
    const token = (merged.token ?? "").trim();

    if (!baseUrl) {
      const msg = "请填写连接地址";
      setLastError(msg);
      throw new Error(msg);
    }

    setConnecting(true);
    setLastError("");
    try {
      await validateConnection(baseUrl, token);
      const next: ConnectionConfig = { ...merged, baseUrl, token };
      saveConnection(next);
      setConfig(next);
      setApiCredentials(baseUrl, token);
      setConnected(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "连接失败";
      setLastError(msg);
      setConnected(false);
      throw e;
    } finally {
      setConnecting(false);
    }
  }, []);

  const disconnect = useCallback(() => {
    setConnected(false);
    setLastError("");
  }, []);

  const logout = useCallback((reason?: string) => {
    const cfg = configRef.current;
    const next: ConnectionConfig = { ...cfg, token: "", remember: false, autoConnect: false };
    saveConnection(next);
    setConfig(next);
    setApiCredentials(cfg.baseUrl, "");
    setConnected(false);
    setLastError(reason ?? "登录已失效，请重新连接");
  }, []);

  // api.ts 收到 401 时派发该事件：已连接状态下视为令牌失效，强制登出
  useEffect(() => {
    const handler = () => {
      if (connectedRef.current) logout("访问令牌已失效，请重新连接");
    };
    window.addEventListener("recorder:unauthorized", handler);
    return () => window.removeEventListener("recorder:unauthorized", handler);
  }, [logout]);

  const resetAll = useCallback(() => {
    clearConnection();
    setConnected(false);
    setAutoTried(true);
    setLastError("");
    setConfig({ ...DEFAULT_CONFIG });
    setApiCredentials("", "");
  }, []);

  // 设置页令牌变更 → 同步本地凭据，避免保存后立即 401 被登出
  useEffect(() => {
    localTokenSync = (token: string) => {
      if (token === configRef.current.token) return;
      const next: ConnectionConfig = {
        ...configRef.current,
        token,
        remember: token ? configRef.current.remember : false,
        autoConnect: token ? configRef.current.autoConnect : false,
      };
      saveConnection(next);
      setConfig(next);
      setApiCredentials(configRef.current.baseUrl, token);
    };
    return () => {
      localTokenSync = null;
    };
  }, []);

  // 自动连接：仅记住令牌 + 开启自动连接时，挂载后静默尝试一次
  useEffect(() => {
    if (autoTried) return;
    setAutoTried(true);
    const cfg = configRef.current;
    if (cfg.autoConnect && cfg.remember && cfg.token && cfg.baseUrl) {
      void connect().catch(() => {
        /* 错误已写入 lastError */
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = useMemo<ConnectionContextValue>(
    () => ({ config, connected, connecting, autoTried, lastError, connect, disconnect, logout, resetAll }),
    [config, connected, connecting, autoTried, lastError, connect, disconnect, logout, resetAll],
  );

  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
}

export function useConnection(): ConnectionContextValue {
  const ctx = useContext(ConnectionContext);
  if (!ctx) throw new Error("useConnection 必须在 ConnectionProvider 内使用");
  return ctx;
}
