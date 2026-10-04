import type { ClientMessage, ServerMessage } from "./protocol";

export type NetworkHandlers = {
  onMessage: (message: ServerMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (event: Event) => void;
};

export class GameSocket {
  private socket: WebSocket | null = null;
  private readonly url: string;
  private readonly handlers: NetworkHandlers;

  constructor(url: string, handlers: NetworkHandlers) {
    this.url = url;
    this.handlers = handlers;
  }

  connect() {
    this.socket = new WebSocket(this.url);

    this.socket.addEventListener("open", () => this.handlers.onOpen?.());

    this.socket.addEventListener("message", event => {
      try {
        const message = JSON.parse(event.data) as ServerMessage;
        this.handlers.onMessage(message);
      } catch (error) {
        console.error("Invalid server message:", error, event.data);
      }
    });

    this.socket.addEventListener("close", () => this.handlers.onClose?.());
    this.socket.addEventListener("error", event => this.handlers.onError?.(event));
  }

  send(message: ClientMessage) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  close() {
    this.socket?.close();
  }

  get connected() {
    return this.socket?.readyState === WebSocket.OPEN;
  }
}