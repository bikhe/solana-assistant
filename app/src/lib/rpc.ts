// JSON-RPC 2.0 client for solana-core over WebSocket. Types come from protocol/ts/ipc.ts.
import type { EmptyParams, EventMap, RequestMap } from "@protocol/ipc";

export type Method = keyof RequestMap;
export type Params<M extends Method> = RequestMap[M]["params"];
export type Result<M extends Method> = RequestMap[M]["result"];
export type EventName = keyof EventMap;
export type EventParams<E extends EventName> = EventMap[E];
export type ConnectionStatus = "connecting" | "connected" | "disconnected";

/** Methods whose params are empty can be called without the params argument. */
type ParamsArg<M extends Method> =
  EmptyParams extends Params<M> ? [params?: Params<M>] : [params: Params<M>];

export class RpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly data?: unknown,
  ) {
    super(message);
    this.name = "RpcError";
  }
}

/** Minimal WebSocket surface we use, so tests can pass a fake. */
export interface SocketLike {
  readonly readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  send(data: string): void;
  close(): void;
}

export type SocketFactory = (url: string) => SocketLike;

export interface CoreClientOptions {
  socketFactory?: SocketFactory;
  /** First reconnect delay; doubles up to maxReconnectMs. 0 disables reconnect. */
  reconnectMs?: number;
  maxReconnectMs?: number;
  requestTimeoutMs?: number;
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

const OPEN = 1;

export class CoreClient {
  private socket: SocketLike | null = null;
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly listeners = new Map<string, Set<(params: unknown) => void>>();
  private readonly anyListeners = new Set<(event: EventName, params: unknown) => void>();
  private readonly statusListeners = new Set<(status: ConnectionStatus) => void>();
  private reconnectDelay: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;
  private _status: ConnectionStatus = "disconnected";
  private readonly opts: Required<CoreClientOptions>;

  constructor(
    readonly url: string,
    options: CoreClientOptions = {},
  ) {
    this.opts = {
      socketFactory: options.socketFactory ?? ((u) => new WebSocket(u) as unknown as SocketLike),
      reconnectMs: options.reconnectMs ?? 500,
      maxReconnectMs: options.maxReconnectMs ?? 5000,
      requestTimeoutMs: options.requestTimeoutMs ?? 30_000,
    };
    this.reconnectDelay = this.opts.reconnectMs;
  }

  get status(): ConnectionStatus {
    return this._status;
  }

  connect(): void {
    this.closed = false;
    this.open();
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
    this.setStatus("disconnected");
    this.failPending(new Error("connection closed"));
  }

  request<M extends Method>(method: M, ...args: ParamsArg<M>): Promise<Result<M>> {
    const socket = this.socket;
    if (!socket || socket.readyState !== OPEN) {
      return Promise.reject(new Error("core is not connected"));
    }
    const id = this.nextId++;
    const params = args[0] ?? {};
    return new Promise<Result<M>>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, this.opts.requestTimeoutMs);
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer });
      socket.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  on<E extends EventName>(event: E, callback: (params: EventParams<E>) => void): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    const cb = callback as (params: unknown) => void;
    set.add(cb);
    return () => set.delete(cb);
  }

  /** Called with every event, e.g. for a debug log. */
  onAny(callback: (event: EventName, params: unknown) => void): () => void {
    this.anyListeners.add(callback);
    return () => this.anyListeners.delete(callback);
  }

  onStatus(callback: (status: ConnectionStatus) => void): () => void {
    this.statusListeners.add(callback);
    return () => this.statusListeners.delete(callback);
  }

  private open(): void {
    this.setStatus("connecting");
    const socket = this.opts.socketFactory(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.reconnectDelay = this.opts.reconnectMs;
      this.setStatus("connected");
    };
    socket.onmessage = (ev) => this.handleMessage(ev.data);
    socket.onerror = () => {
      // onclose follows and handles reconnect.
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.failPending(new Error("connection lost"));
      this.setStatus("disconnected");
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.closed || this.opts.reconnectMs <= 0) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closed) this.open();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.opts.maxReconnectMs);
  }

  private handleMessage(data: unknown): void {
    let message: {
      id?: number;
      method?: string;
      params?: unknown;
      result?: unknown;
      error?: { code: number; message: string; data?: unknown };
    };
    try {
      message = JSON.parse(String(data));
    } catch {
      return;
    }
    if (typeof message.method === "string") {
      this.emit(message.method, message.params);
      return;
    }
    if (typeof message.id !== "number") return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.error) {
      pending.reject(new RpcError(message.error.code, message.error.message, message.error.data));
    } else {
      pending.resolve(message.result);
    }
  }

  private emit(event: string, params: unknown): void {
    for (const cb of this.listeners.get(event) ?? []) cb(params);
    for (const cb of this.anyListeners) cb(event as EventName, params);
  }

  private setStatus(status: ConnectionStatus): void {
    if (status === this._status) return;
    this._status = status;
    for (const cb of this.statusListeners) cb(status);
  }

  private failPending(error: Error): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }
}
