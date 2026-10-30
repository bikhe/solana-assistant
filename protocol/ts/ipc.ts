/* Generated from protocol/ipc.schema.json by app/scripts/gen-protocol.mjs. Do not edit. */

/**
 * Main loop: idle -> wake -> listening -> thinking -> speaking -> idle. muted and error can be entered from any state.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "AssistantState".
 */
export type AssistantState =
  "idle" | "wake" | "listening" | "thinking" | "speaking" | "muted" | "error";
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "Language".
 */
export type Language = "ru" | "en";
/**
 * safe runs at once, confirm waits for a voice yes or a click, dangerous needs a click.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "Risk".
 */
export type Risk = "safe" | "confirm" | "dangerous";
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolSource".
 */
export type ToolSource = "builtin" | "mcp" | "skill";
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpServerStatus".
 */
export type McpServerStatus = "connected" | "connecting" | "disconnected" | "error";
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ModelKind".
 */
export type ModelKind = "wake" | "vad" | "stt" | "tts" | "llm" | "embedding";

/**
 * Solana IPC: JSON-RPC 2.0 over WebSocket between solana-app and solana-core. RequestMap lists app -> core requests (params and result of each method). EventMap lists core -> app notifications (params of each event). Field names on the wire are snake_case. This file is the single source of truth: TS types and pydantic models are generated from it.
 */
export interface IpcProtocol {
  protocol_version: 1;
  requests: RequestMap;
  events: EventMap;
}
/**
 * Every request method the core accepts.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "RequestMap".
 */
export interface RequestMap {
  ping: PingRequest;
  "state.get": StateGetRequest;
  "settings.get": SettingsGetRequest;
  "settings.set": SettingsSetRequest;
  "chat.send": ChatSendRequest;
  "voice.mute": VoiceMuteRequest;
  "confirm.reply": ConfirmReplyRequest;
  "tools.list": ToolsListRequest;
  "tools.set_enabled": ToolsSetEnabledRequest;
  "mcp.list": McpListRequest;
  "mcp.add": McpAddRequest;
  "mcp.remove": McpRemoveRequest;
  "mcp.set_enabled": McpSetEnabledRequest;
  "skills.list": SkillsListRequest;
  "skills.install": SkillsInstallRequest;
  "skills.remove": SkillsRemoveRequest;
  "skills.set_enabled": SkillsSetEnabledRequest;
  "models.list": ModelsListRequest;
  "models.download": ModelsDownloadRequest;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "PingRequest".
 */
export interface PingRequest {
  params: EmptyParams;
  result: PingResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "EmptyParams".
 */
export interface EmptyParams {}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "PingResult".
 */
export interface PingResult {
  pong: true;
  /**
   * solana-core version
   */
  version: string;
  protocol_version: number;
  /**
   * true when core runs with --fake
   */
  fake: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "StateGetRequest".
 */
export interface StateGetRequest {
  params: EmptyParams;
  result: StateEvent;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "StateEvent".
 */
export interface StateEvent {
  state: AssistantState;
  previous?: AssistantState;
  /**
   * Short machine-readable cause, e.g. wake_word, hotkey, timeout.
   */
  reason?: string;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SettingsGetRequest".
 */
export interface SettingsGetRequest {
  params: EmptyParams;
  result: SettingsResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SettingsResult".
 */
export interface SettingsResult {
  settings: Settings;
}
/**
 * The full user settings document. Its shape is defined by the pydantic model in core/solana_core/config/.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "Settings".
 */
export interface Settings {
  [k: string]: unknown;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SettingsSetRequest".
 */
export interface SettingsSetRequest {
  params: SettingsSetParams;
  result: SettingsResult;
}
/**
 * Deep-merge patch applied to the current settings. Secrets (API keys) never go through settings; they are stored in the OS keyring.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SettingsSetParams".
 */
export interface SettingsSetParams {
  patch: Settings;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ChatSendRequest".
 */
export interface ChatSendRequest {
  params: ChatSendParams;
  result: ChatSendResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ChatSendParams".
 */
export interface ChatSendParams {
  text: string;
  language?: Language;
}
/**
 * The answer itself streams as assistant.delta / assistant.done events with this turn_id.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ChatSendResult".
 */
export interface ChatSendResult {
  turn_id: string;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "VoiceMuteRequest".
 */
export interface VoiceMuteRequest {
  params: VoiceMuteParams;
  result: VoiceMuteParams;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "VoiceMuteParams".
 */
export interface VoiceMuteParams {
  muted: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ConfirmReplyRequest".
 */
export interface ConfirmReplyRequest {
  params: ConfirmReplyParams;
  result: OkResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ConfirmReplyParams".
 */
export interface ConfirmReplyParams {
  request_id: string;
  approved: boolean;
  /**
   * Always allow this tool from now on. Ignored for dangerous tools.
   */
  always?: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "OkResult".
 */
export interface OkResult {
  ok: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolsListRequest".
 */
export interface ToolsListRequest {
  params: EmptyParams;
  result: ToolsListResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolsListResult".
 */
export interface ToolsListResult {
  tools: ToolInfo[];
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolInfo".
 */
export interface ToolInfo {
  name: string;
  description: string;
  risk: Risk;
  source: ToolSource;
  enabled: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolsSetEnabledRequest".
 */
export interface ToolsSetEnabledRequest {
  params: ToolsSetEnabledParams;
  result: ToolInfo;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolsSetEnabledParams".
 */
export interface ToolsSetEnabledParams {
  name: string;
  enabled: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpListRequest".
 */
export interface McpListRequest {
  params: EmptyParams;
  result: McpListResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpListResult".
 */
export interface McpListResult {
  servers: McpServerInfo[];
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpServerInfo".
 */
export interface McpServerInfo {
  name: string;
  config: McpServerConfig;
  enabled: boolean;
  status: McpServerStatus;
  error?: string;
  tools: ToolInfo[];
}
/**
 * Same shape as one entry of mcpServers in Claude Desktop config. stdio servers use command/args/env, HTTP servers use url/headers.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpServerConfig".
 */
export interface McpServerConfig {
  command?: string;
  args?: string[];
  env?: {
    [k: string]: string;
  };
  url?: string;
  headers?: {
    [k: string]: string;
  };
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpAddRequest".
 */
export interface McpAddRequest {
  params: McpAddParams;
  result: McpServerInfo;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpAddParams".
 */
export interface McpAddParams {
  name: string;
  config: McpServerConfig;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpRemoveRequest".
 */
export interface McpRemoveRequest {
  params: McpNameParams;
  result: OkResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpNameParams".
 */
export interface McpNameParams {
  name: string;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpSetEnabledRequest".
 */
export interface McpSetEnabledRequest {
  params: McpSetEnabledParams;
  result: McpServerInfo;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "McpSetEnabledParams".
 */
export interface McpSetEnabledParams {
  name: string;
  enabled: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillsListRequest".
 */
export interface SkillsListRequest {
  params: EmptyParams;
  result: SkillsListResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillsListResult".
 */
export interface SkillsListResult {
  skills: SkillInfo[];
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillInfo".
 */
export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  languages: Language[];
  builtin: boolean;
  enabled: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillsInstallRequest".
 */
export interface SkillsInstallRequest {
  params: SkillsInstallParams;
  result: SkillInfo;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillsInstallParams".
 */
export interface SkillsInstallParams {
  /**
   * Local folder, path to a .zip file, or a git URL.
   */
  source: string;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillsRemoveRequest".
 */
export interface SkillsRemoveRequest {
  params: SkillIdParams;
  result: OkResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillIdParams".
 */
export interface SkillIdParams {
  id: string;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillsSetEnabledRequest".
 */
export interface SkillsSetEnabledRequest {
  params: SkillsSetEnabledParams;
  result: SkillInfo;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "SkillsSetEnabledParams".
 */
export interface SkillsSetEnabledParams {
  id: string;
  enabled: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ModelsListRequest".
 */
export interface ModelsListRequest {
  params: EmptyParams;
  result: ModelsListResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ModelsListResult".
 */
export interface ModelsListResult {
  models: ModelInfo[];
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ModelInfo".
 */
export interface ModelInfo {
  id: string;
  kind: ModelKind;
  name: string;
  size_bytes: number;
  installed: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ModelsDownloadRequest".
 */
export interface ModelsDownloadRequest {
  params: ModelsDownloadParams;
  result: ModelsDownloadResult;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ModelsDownloadParams".
 */
export interface ModelsDownloadParams {
  model_id: string;
}
/**
 * Progress arrives as download.progress events with this download_id.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ModelsDownloadResult".
 */
export interface ModelsDownloadResult {
  download_id: string;
}
/**
 * Every notification the core sends to the app.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "EventMap".
 */
export interface EventMap {
  state: StateEvent;
  "transcript.partial": TranscriptEvent;
  "transcript.final": TranscriptEvent;
  "assistant.delta": AssistantDeltaEvent;
  "assistant.done": AssistantDoneEvent;
  "tool.started": ToolStartedEvent;
  "tool.finished": ToolFinishedEvent;
  "confirm.request": ConfirmRequestEvent;
  "download.progress": DownloadProgressEvent;
  error: ErrorEvent;
}
/**
 * Used by both transcript.partial and transcript.final.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "TranscriptEvent".
 */
export interface TranscriptEvent {
  utterance_id: string;
  text: string;
  language?: Language;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "AssistantDeltaEvent".
 */
export interface AssistantDeltaEvent {
  turn_id: string;
  /**
   * Next chunk of the answer.
   */
  text: string;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "AssistantDoneEvent".
 */
export interface AssistantDoneEvent {
  turn_id: string;
  /**
   * The full answer.
   */
  text: string;
  interrupted?: boolean;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolStartedEvent".
 */
export interface ToolStartedEvent {
  call_id: string;
  turn_id?: string;
  tool: string;
  arguments: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ToolFinishedEvent".
 */
export interface ToolFinishedEvent {
  call_id: string;
  tool: string;
  ok: boolean;
  summary?: string;
  error?: string;
}
/**
 * Ask the user to approve a tool call. The app answers with confirm.reply.
 *
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ConfirmRequestEvent".
 */
export interface ConfirmRequestEvent {
  request_id: string;
  tool: string;
  risk: Risk;
  /**
   * Human readable, in the user's language.
   */
  title: string;
  details?: string;
  arguments: {
    [k: string]: unknown;
  };
  /**
   * false for dangerous tools: only a click can approve.
   */
  voice_allowed: boolean;
  timeout_s?: number;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "DownloadProgressEvent".
 */
export interface DownloadProgressEvent {
  download_id: string;
  model_id: string;
  downloaded_bytes: number;
  total_bytes: number | null;
  done: boolean;
  error?: string;
}
/**
 * This interface was referenced by `IpcProtocol`'s JSON-Schema
 * via the `definition` "ErrorEvent".
 */
export interface ErrorEvent {
  /**
   * Stable machine-readable code, e.g. mic_unavailable, llm_unreachable.
   */
  code: string;
  /**
   * Human readable, in the user's language.
   */
  message: string;
  recoverable: boolean;
}
