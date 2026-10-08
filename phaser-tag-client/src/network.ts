import type { ClientMessage, ServerMessage } from "./protocol";

export type NetworkHandlers = {
  onMessage: (message: ServerMessage) => void;
  onOpen?: () => void;
  /** The socket closed (or failed to connect); a reconnect is scheduled. */
  onClose?: (event: { code: number; retryInMs: number }) => void;
  onError?: (event: Event) => void;
};

/** Reconnect backoff: first retry after this long, doubling up to the max. */
const RETRY_MIN_MS = 500;
const RETRY_MAX_MS = 5000;

/**
 * WebSocket to the game server that reconnects by itself: when the socket
 * closes (server restart / deploy, network blip, laptop sleep) it retries
 * after 0.5s, 1s, 2s, 4s, then every 5s (plus a little jitter so a server
 * restart isn't hit by every tab at the same instant), until close() is
 * called. A "service restart" close (1012, sent by the server on SIGTERM)
 * retries right away at the minimum delay.
 */
export class GameSocket {
  private socket: WebSocket | null = null;
  private readonly url: string;
  private readonly handlers: NetworkHandlers;
  private retryMs = RETRY_MIN_MS;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(url: string, handlers: NetworkHandlers) {
    this.url = url;
    this.handlers = handlers;
  }

  connect() {
    this.stopped = false;
    this.clearRetry();
    let socket: WebSocket;
    try {
      socket = new WebSocket(this.url);
    } catch (error) {
      // Bad URL etc.: still retry, so a fixed config comes back on its own.
      console.error("WebSocket failed:", error);
      this.scheduleReconnect(0);
      return;
    }
    this.socket = socket;

    socket.addEventListener("open", () => {
      if (socket !== this.socket) return;
      this.retryMs = RETRY_MIN_MS;
      this.handlers.onOpen?.();
    });

    socket.addEventListener("message", event => {
      if (socket !== this.socket) return;
      try {
        const message = JSON.parse(event.data) as ServerMessage;
        this.handlers.onMessage(message);
      } catch (error) {
        console.error("Invalid server message:", error, event.data);
      }
    });

    socket.addEventListener("close", event => {
      // Ignore events from a socket we've already replaced or closed.
      if (socket !== this.socket) return;
      this.socket = null;
      if (this.stopped) return;
      this.scheduleReconnect(event.code);
    });
    socket.addEventListener("error", event => {
      if (socket !== this.socket) return;
      this.handlers.onError?.(event); // "close" follows and schedules the retry
    });
  }

  send(message: ClientMessage) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  /** Close for good (no reconnect). */
  close() {
    this.stopped = true;
    this.clearRetry();
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  get connected() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  private scheduleReconnect(code: number) {
    if (this.stopped || this.retryTimer) return;
    if (code === 1012) this.retryMs = RETRY_MIN_MS; // server said "restarting"
    const delay = Math.round(this.retryMs * (0.85 + Math.random() * 0.3));
    this.retryMs = Math.min(RETRY_MAX_MS, this.retryMs * 2);
    this.handlers.onClose?.({ code, retryInMs: delay });
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  private clearRetry() {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }
}
