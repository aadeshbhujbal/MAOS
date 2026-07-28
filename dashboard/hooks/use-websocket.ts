"use client";

/**
 * React hook wrapping the WSConnectionManager with lifecycle management.
 *
 * Provides automatic connection on mount, disconnection on unmount,
 * and exposes connection status and subscription helpers to components.
 *
 * @module hooks/use-websocket
 */

import { useEffect, useRef, useCallback } from "react";
import { WSConnectionManager } from "@/lib/ws/connection";
import { useWSStore } from "@/lib/stores/ws-store";
import type { WSEvent, ConnectionStatus } from "@/types";

/** Configuration options for the useWebSocket hook. */
interface UseWebSocketOptions {
  /** WebSocket endpoint URL. Defaults to derived from NEXT_PUBLIC_MAOS_API_URL. */
  url?: string;
  /** JWT authentication token. */
  token: string;
  /** Callback invoked for each received event. */
  onEvent?: (event: WSEvent) => void;
  /** Initial topics to subscribe to on connect. */
  topics?: string[];
  /** Whether to automatically connect on mount. Defaults to true. */
  autoConnect?: boolean;
}

/** Return value of the useWebSocket hook. */
interface UseWebSocketReturn {
  /** Current connection status. */
  status: ConnectionStatus;
  /** Subscribe to a topic. */
  subscribe: (topic: string) => void;
  /** Unsubscribe from a topic. */
  unsubscribe: (topic: string) => void;
  /** Manually trigger a connection. */
  connect: () => void;
  /** Manually disconnect. */
  disconnect: () => void;
}

/**
 * Derive the WebSocket URL from the API base URL.
 *
 * Converts http(s):// to ws(s):// and appends the /ws/events path.
 */
function getDefaultWSUrl(): string {
  const apiUrl =
    process.env.NEXT_PUBLIC_MAOS_API_URL ?? "http://localhost:8000";
  const wsProtocol = apiUrl.startsWith("https") ? "wss" : "ws";
  const baseUrl = apiUrl.replace(/^https?/, wsProtocol);
  return `${baseUrl}/ws/events`;
}

/**
 * React hook for managing WebSocket connections to the MAOS backend.
 *
 * Wraps `WSConnectionManager` with React lifecycle management:
 * - Auto-connects on component mount (configurable)
 * - Auto-disconnects on component unmount
 * - Syncs connection status to the global Zustand ws-store
 * - Provides imperative subscribe/unsubscribe methods
 *
 * @param options - Configuration for the WebSocket connection.
 * @returns Object with connection status and control methods.
 *
 * @example
 * ```tsx
 * const { status, subscribe } = useWebSocket({
 *   token: session.token,
 *   onEvent: (event) => handleEvent(event),
 *   topics: ["tasks.*", "agents.*"],
 * });
 * ```
 */
export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const {
    url,
    token,
    onEvent,
    topics = [],
    autoConnect = true,
  } = options;

  const managerRef = useRef<WSConnectionManager | null>(null);
  const { status, setStatus, setLastTimestamp } = useWSStore();

  // Stable reference for the event handler
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  // Initialize the connection manager
  useEffect(() => {
    const wsUrl = url ?? getDefaultWSUrl();

    const handleEvent = (event: WSEvent) => {
      setLastTimestamp(event.timestamp);
      onEventRef.current?.(event);
    };

    const handleStatusChange = (newStatus: ConnectionStatus) => {
      setStatus(newStatus);
    };

    const manager = new WSConnectionManager(
      wsUrl,
      token,
      handleEvent,
      handleStatusChange
    );
    managerRef.current = manager;

    // Subscribe to initial topics
    for (const topic of topics) {
      manager.subscribe(topic);
    }

    // Auto-connect if enabled
    if (autoConnect) {
      manager.connect();
    }

    // Cleanup on unmount
    return () => {
      manager.disconnect();
      managerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, token]);

  const subscribe = useCallback((topic: string) => {
    managerRef.current?.subscribe(topic);
  }, []);

  const unsubscribe = useCallback((topic: string) => {
    managerRef.current?.unsubscribe(topic);
  }, []);

  const connect = useCallback(() => {
    managerRef.current?.connect();
  }, []);

  const disconnect = useCallback(() => {
    managerRef.current?.disconnect();
  }, []);

  return {
    status,
    subscribe,
    unsubscribe,
    connect,
    disconnect,
  };
}
