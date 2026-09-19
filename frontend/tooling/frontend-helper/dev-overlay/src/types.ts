export type TraceEventKind =
  | "recording.started"
  | "recording.stopped"
  | "user.click"
  | "user.input"
  | "user.scroll"
  | "runtime.error"
  | "annotation";

export interface ElementReference {
  sessionNodeId: number;
  rrwebNodeId?: number;
  tagName: string;
  role?: string;
  accessibleName?: string;
  text?: string;
  testId?: string;
  selector: string;
  domPath: number[];
  rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  attributes: Record<string, string>;
  htmlSnippet: string;
  computedStyle: {
    display: string;
    position: string;
    color: string;
    backgroundColor: string;
    zIndex: string;
  };
}

export interface TraceEvent {
  id: string;
  at: number;
  kind: TraceEventKind;
  summary: string;
  target?: ElementReference;
  data?: Record<string, unknown>;
}

export interface Annotation {
  id: string;
  at: number;
  comment: string;
  target: ElementReference;
}

export interface FrontendHelperTrace {
  format: "frontend-helper-trace";
  version: 1;
  session: {
    id: string;
    startedAt: string;
    endedAt: string;
    durationMs: number;
    page: {
      url: string;
      title: string;
      viewport: { width: number; height: number; devicePixelRatio: number };
    };
    userAgent: string;
  };
  timeline: TraceEvent[];
  annotations: Annotation[];
  rrwebEvents: unknown[];
}

export interface ServiceVersion {
  name?: string;
  version?: string;
  commit?: string;
  branch?: string;
  dirty?: boolean;
}

export interface StoredTraceSummary {
  id: string;
  name: string | null;
  savedAt: string;
  service: ServiceVersion | null;
  page: { url?: string; title?: string } | null;
  durationMs: number | null;
  eventCount: number;
  annotationCount: number;
  rrwebEventCount: number;
}

export interface StoredFrontendHelperTrace extends FrontendHelperTrace {
  storage: {
    id: string;
    savedAt: string;
    name?: string;
  };
  service?: ServiceVersion;
}

export interface MountOptions {
  hotkey?: string;
  initiallyOpen?: boolean;
  traceEndpoint?: string;
}

export interface FrontendHelperController {
  open(): void;
  close(): void;
  start(): void;
  stop(): void;
  destroy(): void;
}
