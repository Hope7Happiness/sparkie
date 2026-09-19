import { record } from "@rrweb/record";
import { overlayStyles } from "./styles";
import type {
  Annotation,
  ElementReference,
  FrontendHelperController,
  FrontendHelperTrace,
  MountOptions,
  ServiceVersion,
  StoredFrontendHelperTrace,
  StoredTraceSummary,
  TraceEvent,
  TraceEventKind,
} from "./types";

export type {
  Annotation,
  ElementReference,
  FrontendHelperController,
  FrontendHelperTrace,
  MountOptions,
  ServiceVersion,
  StoredFrontendHelperTrace,
  StoredTraceSummary,
  TraceEvent,
} from "./types";

const ROOT_ATTRIBUTE = "data-frontend-helper-root";
const DEFAULT_HOTKEY = "Alt+Shift+H";
const PANEL_POSITION_KEY = "frontend-helper:panel-position";
const SCROLL_IDLE_MS = 120;

let activeController: FrontendHelperController | undefined;

export function mount(options: MountOptions = {}): FrontendHelperController {
  if (activeController) return activeController;

  const overlay = new FrontendHelperOverlay(options);
  activeController = overlay.controller;
  return activeController;
}

class FrontendHelperOverlay {
  private readonly host: HTMLElement;
  private readonly shadow: ShadowRoot;
  private readonly hotkey: string;
  private readonly traceEndpoint: string;
  private readonly nodeIds = new WeakMap<Element, number>();
  private readonly controllerApi: FrontendHelperController;
  private stopRrweb?: () => void;
  private tickTimer?: number;
  private readonly scrollBursts = new Map<
    EventTarget,
    { start: { x: number; y: number }; latest: { x: number; y: number }; idleTimer: number }
  >();
  private readonly lastScrolls = new Map<EventTarget, { x: number; y: number }>();
  private startedAtWall = "";
  private startedAtMono = 0;
  private nextNodeId = 1;
  private nextEventId = 1;
  private recording = false;
  private saving = false;
  private picking = false;
  private openState = false;
  private selectedElement?: Element;
  private selectedReference?: ElementReference;
  private traceId?: string;
  private saveError?: string;
  private libraryLoading = false;
  private libraryError?: string;
  private traceSummaries: StoredTraceSummary[] = [];
  private selectedStoredTrace?: StoredFrontendHelperTrace;
  private dragging = false;
  private dragOffsetX = 0;
  private dragOffsetY = 0;
  private rrwebEvents: unknown[] = [];
  private timeline: TraceEvent[] = [];
  private annotations: Annotation[] = [];

  private readonly launcher: HTMLButtonElement;
  private readonly panel: HTMLElement;
  private readonly panelHeader: HTMLElement;
  private readonly recorderView: HTMLElement;
  private readonly libraryView: HTMLElement;
  private readonly libraryButton: HTMLButtonElement;
  private readonly libraryContent: HTMLElement;
  private readonly statusDot: HTMLElement;
  private readonly statusTitle: HTMLElement;
  private readonly statusMeta: HTMLElement;
  private readonly startButton: HTMLButtonElement;
  private readonly pickerButton: HTMLButtonElement;
  private readonly traceResult: HTMLElement;
  private readonly traceResultLabel: HTMLElement;
  private readonly traceIdElement: HTMLElement;
  private readonly copyButton: HTMLButtonElement;
  private readonly deleteButton: HTMLButtonElement;
  private readonly timelineElement: HTMLElement;
  private readonly recordingFrame: HTMLElement;
  private readonly pickerBox: HTMLElement;
  private readonly pickerLabel: HTMLElement;
  private readonly commentCard: HTMLElement;
  private readonly commentTarget: HTMLElement;
  private readonly commentInput: HTMLTextAreaElement;

  constructor(options: MountOptions) {
    this.hotkey = options.hotkey ?? DEFAULT_HOTKEY;
    this.traceEndpoint = options.traceEndpoint ?? "/__frontend-helper/traces";
    this.host = document.createElement("frontend-helper-overlay");
    this.host.setAttribute(ROOT_ATTRIBUTE, "");
    this.shadow = this.host.attachShadow({ mode: "open" });
    this.shadow.innerHTML = this.template();
    document.documentElement.append(this.host);

    this.launcher = this.requireElement("[data-fh-launcher]");
    this.panel = this.requireElement("[data-fh-panel]");
    this.panelHeader = this.requireElement("[data-fh-header]");
    this.recorderView = this.requireElement("[data-fh-recorder-view]");
    this.libraryView = this.requireElement("[data-fh-library-view]");
    this.libraryButton = this.requireElement("[data-fh-library-toggle]");
    this.libraryContent = this.requireElement("[data-fh-library-content]");
    this.statusDot = this.requireElement("[data-fh-status-dot]");
    this.statusTitle = this.requireElement("[data-fh-status-title]");
    this.statusMeta = this.requireElement("[data-fh-status-meta]");
    this.startButton = this.requireElement("[data-fh-start]");
    this.pickerButton = this.requireElement("[data-fh-picker]");
    this.traceResult = this.requireElement("[data-fh-trace-result]");
    this.traceResultLabel = this.requireElement("[data-fh-trace-label]");
    this.traceIdElement = this.requireElement("[data-fh-trace-id]");
    this.copyButton = this.requireElement("[data-fh-copy]");
    this.deleteButton = this.requireElement("[data-fh-delete]");
    this.timelineElement = this.requireElement("[data-fh-timeline]");
    this.recordingFrame = this.requireElement("[data-fh-frame]");
    this.pickerBox = this.requireElement("[data-fh-picker-box]");
    this.pickerLabel = this.requireElement("[data-fh-picker-label]");
    this.commentCard = this.requireElement("[data-fh-comment]");
    this.commentTarget = this.requireElement("[data-fh-comment-target]");
    this.commentInput = this.requireElement("[data-fh-comment-input]");

    this.bindUi();
    this.bindPageEvents();
    this.restorePanelPosition();
    this.setOpen(options.initiallyOpen ?? false);
    this.render();

    this.controllerApi = {
      open: () => this.setOpen(true),
      close: () => this.setOpen(false),
      start: () => this.start(),
      stop: () => this.stop(),
      destroy: () => this.destroy(),
    };
  }

  get controller(): FrontendHelperController {
    return this.controllerApi;
  }

  private template(): string {
    return `
      <style>${overlayStyles}</style>
      <button class="fh-launcher" type="button" data-fh-launcher aria-label="打开 Frontend Helper">
        <span class="fh-mark">⌁</span>
        <span class="fh-launcher-label">Frontend Helper</span>
      </button>

      <section class="fh-panel" data-fh-panel hidden aria-label="Frontend Helper 调试面板">
        <header class="fh-header" data-fh-header title="拖动以移动 Frontend Helper">
          <div class="fh-brand">
            <div class="fh-brand-icon">⌁</div>
            <div>
              <div class="fh-title">Frontend Helper</div>
              <div class="fh-subtitle">AI-readable interaction trace</div>
            </div>
          </div>
          <div class="fh-header-actions">
            <button class="fh-icon-button" type="button" data-fh-library-toggle aria-label="查看轨迹列表" title="轨迹列表">☷</button>
            <button class="fh-icon-button" type="button" data-fh-close aria-label="收起面板">×</button>
          </div>
        </header>

        <div class="fh-view" data-fh-recorder-view>
          <div class="fh-status">
            <span class="fh-status-dot" data-fh-status-dot></span>
            <div class="fh-status-copy">
              <div class="fh-status-title" data-fh-status-title>准备就绪</div>
              <div class="fh-status-meta" data-fh-status-meta>尚未开始录制</div>
            </div>
          </div>

          <div class="fh-actions">
            <button class="fh-button primary" type="button" data-fh-start>● 开始录制</button>
            <button class="fh-button" type="button" data-fh-picker disabled>⌖ 引用元素</button>
          </div>

          <div class="fh-trace-result" data-fh-trace-result hidden>
            <div class="fh-trace-copy">
              <div class="fh-trace-label" data-fh-trace-label>轨迹已保存</div>
              <div class="fh-trace-id" data-fh-trace-id></div>
            </div>
            <button class="fh-mini-button" type="button" data-fh-copy>复制 ID</button>
            <button class="fh-mini-button delete" type="button" data-fh-delete>删除</button>
          </div>

          <div class="fh-timeline" data-fh-timeline>
            <div class="fh-empty">开始录制后，点击、输入和元素批注会出现在这里。</div>
          </div>
        </div>

        <div class="fh-view fh-library" data-fh-library-view hidden>
          <div class="fh-library-toolbar">
            <div><strong>已保存的轨迹</strong><span>查看、命名或删除开发轨迹</span></div>
            <button class="fh-mini-button" type="button" data-fh-library-refresh>刷新</button>
          </div>
          <div class="fh-library-content" data-fh-library-content>
            <div class="fh-library-empty">正在读取轨迹…</div>
          </div>
        </div>

        <footer class="fh-footer">
          <span>仅在 dev mode 加载</span>
          <span><span class="fh-key">${escapeHtml(this.hotkey)}</span> 显示/隐藏</span>
        </footer>
      </section>

      <div class="fh-picker-box" data-fh-picker-box hidden>
        <div class="fh-picker-label" data-fh-picker-label></div>
      </div>

      <div class="fh-comment-card" data-fh-comment hidden>
        <div class="fh-comment-target" data-fh-comment-target></div>
        <textarea class="fh-comment-input" data-fh-comment-input placeholder="告诉 AI 这个元素哪里不对…"></textarea>
        <div class="fh-comment-actions">
          <button class="fh-button" type="button" data-fh-comment-cancel>取消</button>
          <button class="fh-button primary" type="button" data-fh-comment-save>保存批注</button>
        </div>
      </div>

      <div class="fh-recording-frame" data-fh-frame hidden>
        <div class="fh-recording-label">RECORDING</div>
      </div>
    `;
  }

  private bindUi(): void {
    this.launcher.addEventListener("click", () => this.setOpen(true));
    this.requireElement<HTMLButtonElement>("[data-fh-close]").addEventListener("click", () => this.setOpen(false));
    this.libraryButton.addEventListener("click", () => {
      if (this.libraryView.hidden) void this.showLibrary();
      else this.showRecorder();
    });
    this.requireElement<HTMLButtonElement>("[data-fh-library-refresh]").addEventListener("click", () => void this.loadTraceList());
    this.libraryContent.addEventListener("click", (event) => void this.onLibraryClick(event));
    this.startButton.addEventListener("click", () => (this.recording ? this.stop() : this.start()));
    this.pickerButton.addEventListener("click", () => this.beginPicking());
    this.copyButton.addEventListener("click", () => this.copyTraceId());
    this.deleteButton.addEventListener("click", () => void this.deleteTrace());
    this.requireElement<HTMLButtonElement>("[data-fh-comment-cancel]").addEventListener("click", () => this.cancelComment());
    this.requireElement<HTMLButtonElement>("[data-fh-comment-save]").addEventListener("click", () => this.saveComment());
    this.commentInput.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") this.saveComment();
    });
    this.panelHeader.addEventListener("pointerdown", this.onPanelDragStart);
  }

  private bindPageEvents(): void {
    document.addEventListener("keydown", this.onKeyDown, true);
    document.addEventListener("click", this.onDocumentClick, true);
    document.addEventListener("input", this.onDocumentInput, true);
    document.addEventListener("scroll", this.onDocumentScroll, true);
    window.addEventListener("scroll", this.onWindowScroll, true);
    document.addEventListener("pointermove", this.onPointerMove, true);
    document.addEventListener("pointermove", this.onPanelDragMove, true);
    document.addEventListener("pointerup", this.onPanelDragEnd, true);
    document.addEventListener("pointercancel", this.onPanelDragEnd, true);
    window.addEventListener("error", this.onWindowError);
    window.addEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  private unbindPageEvents(): void {
    document.removeEventListener("keydown", this.onKeyDown, true);
    document.removeEventListener("click", this.onDocumentClick, true);
    document.removeEventListener("input", this.onDocumentInput, true);
    document.removeEventListener("scroll", this.onDocumentScroll, true);
    window.removeEventListener("scroll", this.onWindowScroll, true);
    document.removeEventListener("pointermove", this.onPointerMove, true);
    document.removeEventListener("pointermove", this.onPanelDragMove, true);
    document.removeEventListener("pointerup", this.onPanelDragEnd, true);
    document.removeEventListener("pointercancel", this.onPanelDragEnd, true);
    window.removeEventListener("error", this.onWindowError);
    window.removeEventListener("unhandledrejection", this.onUnhandledRejection);
  }

  private readonly onKeyDown = (event: KeyboardEvent): void => {
    if (matchesHotkey(event, this.hotkey)) {
      event.preventDefault();
      event.stopPropagation();
      this.setOpen(!this.openState);
      return;
    }

    if (event.key === "Escape") {
      if (this.picking) this.endPicking();
      if (!this.commentCard.hidden) this.cancelComment();
    }
  };

  private readonly onDocumentClick = (event: MouseEvent): void => {
    if (this.isOverlayEvent(event)) return;

    if (this.picking) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const target = document.elementFromPoint(event.clientX, event.clientY);
      if (target && target !== this.host && !this.host.contains(target)) this.selectElement(target);
      return;
    }

    if (!this.recording) return;
    const target = firstElementInPath(event.composedPath());
    if (!target) return;
    const reference = this.describeElement(target);
    this.pushEvent("user.click", `点击 ${elementLabel(reference)}`, reference, {
      point: { x: Math.round(event.clientX), y: Math.round(event.clientY) },
      button: event.button,
    });
  };

  private readonly onDocumentInput = (event: Event): void => {
    if (!this.recording || this.isOverlayEvent(event)) return;
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) return;
    const reference = this.describeElement(target);
    const privateValue = target instanceof HTMLInputElement && target.type === "password";
    const data = {
      value: privateValue ? "••••••" : target.value.slice(0, 240),
      masked: privateValue,
    };
    const previous = this.timeline.at(-1);
    if (previous?.kind === "user.input" && previous.target?.sessionNodeId === reference.sessionNodeId) {
      previous.at = this.elapsed();
      previous.summary = `修改 ${elementLabel(reference)}`;
      previous.target = reference;
      previous.data = data;
      this.renderTimeline();
      this.renderStatus();
      return;
    }
    this.pushEvent("user.input", `修改 ${elementLabel(reference)}`, reference, data);
  };

  private readonly onDocumentScroll = (event: Event): void => {
    if (!this.recording || this.isOverlayEvent(event)) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    this.queueScroll(target, target.scrollLeft, target.scrollTop);
  };

  private readonly onWindowScroll = (): void => {
    if (!this.recording) return;
    this.queueScroll(window, window.scrollX, window.scrollY);
  };

  private queueScroll(target: EventTarget, x: number, y: number): void {
    const position = { x: Math.round(x), y: Math.round(y) };
    const previous = this.lastScrolls.get(target);
    if (previous && previous.x === position.x && previous.y === position.y) return;
    if (!previous && position.x === 0 && position.y === 0) return;

    const burst = this.scrollBursts.get(target);
    if (burst) {
      burst.latest = position;
      window.clearTimeout(burst.idleTimer);
      burst.idleTimer = window.setTimeout(() => this.finishScrollBurst(target), SCROLL_IDLE_MS);
      return;
    }

    for (const activeTarget of [...this.scrollBursts.keys()]) {
      if (activeTarget !== target) this.finishScrollBurst(activeTarget);
    }

    this.scrollBursts.set(target, {
      start: position,
      latest: position,
      idleTimer: window.setTimeout(() => this.finishScrollBurst(target), SCROLL_IDLE_MS),
    });
    this.pushScrollEvent(target, position);
  }

  private finishScrollBurst(target: EventTarget): void {
    const burst = this.scrollBursts.get(target);
    if (!burst) return;
    window.clearTimeout(burst.idleTimer);
    this.scrollBursts.delete(target);
    this.lastScrolls.set(target, burst.latest);
    if (burst.latest.x === burst.start.x && burst.latest.y === burst.start.y) return;
    this.pushScrollEvent(target, burst.latest);
  }

  private pushScrollEvent(target: EventTarget, position: { x: number; y: number }): void {
    const element = target instanceof Element ? target : undefined;
    const reference = element ? this.describeElement(element) : undefined;
    const label = reference ? `滚动 ${elementLabel(reference)}` : "滚动页面";
    this.pushEvent("user.scroll", `${label} 到 (${position.x}, ${position.y})`, reference, {
      x: position.x,
      y: position.y,
      target: element ? "element" : "window",
    });
  }

  private flushScrollBursts(): void {
    for (const target of [...this.scrollBursts.keys()]) {
      const burst = this.scrollBursts.get(target);
      if (!burst) continue;
      window.clearTimeout(burst.idleTimer);
      this.scrollBursts.delete(target);
      this.lastScrolls.set(target, burst.latest);
      if (burst.latest.x === burst.start.x && burst.latest.y === burst.start.y) continue;
      this.pushScrollEvent(target, burst.latest);
    }
  }

  private clearScrollBursts(): void {
    for (const burst of this.scrollBursts.values()) window.clearTimeout(burst.idleTimer);
    this.scrollBursts.clear();
  }

  private readonly onPointerMove = (event: PointerEvent): void => {
    if (!this.picking || this.isOverlayEvent(event)) return;
    const target = document.elementFromPoint(event.clientX, event.clientY);
    if (!target || target === this.host || this.host.contains(target)) return;
    this.highlightElement(target);
  };

  private readonly onPanelDragStart = (event: PointerEvent): void => {
    if (event.button !== 0 || (event.target instanceof Element && event.target.closest("button"))) return;
    const rect = this.panel.getBoundingClientRect();
    this.dragging = true;
    this.dragOffsetX = event.clientX - rect.left;
    this.dragOffsetY = event.clientY - rect.top;
    this.panel.classList.add("dragging");
    this.panel.style.right = "auto";
    this.panel.style.bottom = "auto";
    event.preventDefault();
  };

  private readonly onPanelDragMove = (event: PointerEvent): void => {
    if (!this.dragging) return;
    const rect = this.panel.getBoundingClientRect();
    const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    const left = clamp(event.clientX - this.dragOffsetX, 8, maxLeft);
    const top = clamp(event.clientY - this.dragOffsetY, 8, maxTop);
    this.panel.style.left = `${Math.round(left)}px`;
    this.panel.style.top = `${Math.round(top)}px`;
    event.preventDefault();
  };

  private readonly onPanelDragEnd = (): void => {
    if (!this.dragging) return;
    this.dragging = false;
    this.panel.classList.remove("dragging");
    this.savePanelPosition();
  };

  private restorePanelPosition(): void {
    try {
      const raw = localStorage.getItem(`${PANEL_POSITION_KEY}:${location.origin}`);
      if (!raw) return;
      const position = JSON.parse(raw) as { left?: number; top?: number };
      if (typeof position.left !== "number" || typeof position.top !== "number") return;
      const rect = this.panel.getBoundingClientRect();
      const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
      const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
      this.panel.style.right = "auto";
      this.panel.style.bottom = "auto";
      this.panel.style.left = `${Math.round(clamp(position.left, 8, maxLeft))}px`;
      this.panel.style.top = `${Math.round(clamp(position.top, 8, maxTop))}px`;
    } catch {
      // Storage may be unavailable in a restricted browsing context.
    }
  }

  private savePanelPosition(): void {
    const rect = this.panel.getBoundingClientRect();
    try {
      localStorage.setItem(`${PANEL_POSITION_KEY}:${location.origin}`, JSON.stringify({ left: rect.left, top: rect.top }));
    } catch {
      // Storage may be unavailable in a restricted browsing context.
    }
  }

  private readonly onWindowError = (event: ErrorEvent): void => {
    if (!this.recording) return;
    this.pushEvent("runtime.error", event.message || "未捕获的运行时错误", undefined, {
      filename: event.filename,
      line: event.lineno,
      column: event.colno,
      stack: event.error instanceof Error ? event.error.stack : undefined,
    });
  };

  private readonly onUnhandledRejection = (event: PromiseRejectionEvent): void => {
    if (!this.recording) return;
    const reason = event.reason instanceof Error ? event.reason.message : String(event.reason);
    this.pushEvent("runtime.error", `未处理的 Promise rejection：${reason}`, undefined, {
      stack: event.reason instanceof Error ? event.reason.stack : undefined,
    });
  };

  private start(): void {
    if (this.recording) return;
    this.recording = true;
    this.startedAtWall = new Date().toISOString();
    this.startedAtMono = performance.now();
    this.nextEventId = 1;
    this.nextNodeId = 1;
    this.rrwebEvents = [];
    this.timeline = [];
    this.annotations = [];
    this.traceId = undefined;
    this.saveError = undefined;
    this.saving = false;
    this.clearScrollBursts();
    this.lastScrolls.clear();
    this.lastScrolls.set(window, {
      x: Math.round(window.scrollX),
      y: Math.round(window.scrollY),
    });

    const stop = record({
      emit: (event) => {
        if (!hasUnrecordedTarget(event)) this.rrwebEvents.push(event);
      },
      blockSelector: `[${ROOT_ATTRIBUTE}]`,
      maskInputOptions: { password: true },
      // The initial full snapshot plus DOM mutations already describe the whole
      // session. Periodic snapshots repeat that state without making this
      // in-memory recorder more durable.
      sampling: {
        mousemove: false,
        input: "last",
      },
    });
    if (typeof stop === "function") this.stopRrweb = stop;

    this.pushEvent("recording.started", "开始录制");
    this.tickTimer = window.setInterval(() => this.renderStatus(), 250);
    this.setOpen(true);
    this.render();
  }

  private stop(): void {
    if (!this.recording) return;
    this.flushScrollBursts();
    this.pushEvent("recording.stopped", "停止录制");
    this.recording = false;
    this.stopRrweb?.();
    this.stopRrweb = undefined;
    if (this.tickTimer) window.clearInterval(this.tickTimer);
    this.tickTimer = undefined;
    this.endPicking();
    this.cancelComment();
    this.render();
    void this.saveTrace();
  }

  private beginPicking(): void {
    if (!this.recording) return;
    this.picking = true;
    this.pickerButton.textContent = "按 Esc 取消";
    this.pickerButton.classList.add("danger");
    document.documentElement.style.cursor = "crosshair";
  }

  private endPicking(): void {
    this.picking = false;
    this.pickerBox.hidden = true;
    this.pickerButton.textContent = "⌖ 引用元素";
    this.pickerButton.classList.remove("danger");
    document.documentElement.style.removeProperty("cursor");
  }

  private highlightElement(element: Element): void {
    const rect = element.getBoundingClientRect();
    Object.assign(this.pickerBox.style, {
      left: `${Math.round(rect.left)}px`,
      top: `${Math.round(rect.top)}px`,
      width: `${Math.round(rect.width)}px`,
      height: `${Math.round(rect.height)}px`,
    });
    this.pickerLabel.textContent = elementLabel(this.describeElement(element));
    this.pickerBox.hidden = false;
  }

  private selectElement(element: Element): void {
    this.selectedElement = element;
    this.selectedReference = this.describeElement(element);
    this.endPicking();

    const rect = element.getBoundingClientRect();
    const cardWidth = Math.min(330, window.innerWidth - 32);
    const left = clamp(rect.left, 16, window.innerWidth - cardWidth - 16);
    const top = rect.bottom + 12 + 180 < window.innerHeight ? rect.bottom + 12 : Math.max(16, rect.top - 180);
    this.commentCard.style.left = `${Math.round(left)}px`;
    this.commentCard.style.top = `${Math.round(top)}px`;
    this.commentTarget.textContent = `引用：${elementLabel(this.selectedReference)}`;
    this.commentInput.value = "";
    this.commentCard.hidden = false;
    window.setTimeout(() => this.commentInput.focus(), 0);
  }

  private cancelComment(): void {
    this.commentCard.hidden = true;
    this.selectedElement = undefined;
    this.selectedReference = undefined;
    this.commentInput.value = "";
  }

  private saveComment(): void {
    const comment = this.commentInput.value.trim();
    const target = this.selectedReference;
    if (!comment || !target || !this.recording) return;

    const annotation: Annotation = {
      id: `annotation-${this.annotations.length + 1}`,
      at: this.elapsed(),
      comment,
      target,
    };
    this.annotations.push(annotation);
    this.pushEvent("annotation", `批注 ${elementLabel(target)}：${comment}`, target, { annotationId: annotation.id });
    this.cancelComment();
  }

  private pushEvent(
    kind: TraceEventKind,
    summary: string,
    target?: ElementReference,
    data?: Record<string, unknown>,
  ): void {
    if (kind !== "user.scroll" && kind !== "recording.started" && kind !== "recording.stopped") {
      this.flushScrollBursts();
    }
    this.timeline.push({
      id: `event-${this.nextEventId++}`,
      at: this.elapsed(),
      kind,
      summary,
      target,
      data,
    });
    this.renderTimeline();
    this.renderStatus();
  }

  private describeElement(element: Element): ElementReference {
    let sessionNodeId = this.nodeIds.get(element);
    if (!sessionNodeId) {
      sessionNodeId = this.nextNodeId++;
      this.nodeIds.set(element, sessionNodeId);
    }

    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const attributes = pickAttributes(element);
    const rrwebNodeId = getRrwebNodeId(element);

    return {
      sessionNodeId,
      ...(rrwebNodeId >= 0 ? { rrwebNodeId } : {}),
      tagName: element.tagName.toLowerCase(),
      role: getRole(element),
      accessibleName: getAccessibleName(element),
      text: normalizeText(element.textContent, 180),
      testId: element.getAttribute("data-testid") ?? element.getAttribute("data-test-id") ?? undefined,
      selector: buildSelector(element),
      domPath: buildDomPath(element),
      rect: {
        x: round(rect.x),
        y: round(rect.y),
        width: round(rect.width),
        height: round(rect.height),
      },
      attributes,
      htmlSnippet: sanitizeHtmlSnippet(element),
      computedStyle: {
        display: style.display,
        position: style.position,
        color: style.color,
        backgroundColor: style.backgroundColor,
        zIndex: style.zIndex,
      },
    };
  }

  private buildTrace(): FrontendHelperTrace {
    const endedAt = new Date();
    return {
      format: "frontend-helper-trace",
      version: 1,
      session: {
        id: crypto.randomUUID(),
        startedAt: this.startedAtWall,
        endedAt: endedAt.toISOString(),
        durationMs: this.timeline.at(-1)?.at ?? 0,
        page: {
          url: location.href,
          title: document.title,
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
            devicePixelRatio: window.devicePixelRatio,
          },
        },
        userAgent: navigator.userAgent,
      },
      timeline: this.timeline,
      annotations: this.annotations,
      rrwebEvents: this.rrwebEvents,
    };
  }

  private async saveTrace(): Promise<void> {
    if (!this.startedAtWall || this.recording || this.saving) return;
    this.saving = true;
    this.saveError = undefined;
    this.render();

    try {
      const response = await fetch(this.traceEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.buildTrace()),
      });
      if (!response.ok) throw new Error(`保存失败 (${response.status})`);
      const result = (await response.json()) as { id?: string };
      if (!result.id) throw new Error("后端没有返回轨迹 ID");
      this.traceId = result.id;
      if (!this.libraryView.hidden) await this.loadTraceList();
    } catch (error) {
      this.saveError = error instanceof Error ? error.message : String(error);
    } finally {
      this.saving = false;
      this.render();
    }
  }

  private async copyTraceId(): Promise<void> {
    if (!this.traceId) return;
    await navigator.clipboard.writeText(this.traceId);
    const previous = this.copyButton.textContent;
    this.copyButton.textContent = "已复制";
    window.setTimeout(() => (this.copyButton.textContent = previous), 1200);
  }

  private async deleteTrace(): Promise<void> {
    if (!this.traceId) return;
    const id = this.traceId;
    if (!window.confirm(`确定删除轨迹 ${id}？此操作无法撤销。`)) return;
    this.deleteButton.disabled = true;
    try {
      const response = await fetch(`${this.traceEndpoint}/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!response.ok) throw new Error(`删除失败 (${response.status})`);
      this.traceId = undefined;
      this.saveError = undefined;
      this.statusTitle.textContent = "轨迹已删除";
      this.statusMeta.textContent = `${id} 已从开发服务器移除`;
    } catch (error) {
      this.saveError = error instanceof Error ? error.message : String(error);
    } finally {
      this.deleteButton.disabled = false;
      this.renderTraceResult();
    }
  }

  private async showLibrary(): Promise<void> {
    this.recorderView.hidden = true;
    this.libraryView.hidden = false;
    this.libraryButton.textContent = "↩";
    this.libraryButton.title = "返回录制";
    this.selectedStoredTrace = undefined;
    await this.loadTraceList();
  }

  private showRecorder(): void {
    this.libraryView.hidden = true;
    this.recorderView.hidden = false;
    this.libraryButton.textContent = "☷";
    this.libraryButton.title = "轨迹列表";
    this.selectedStoredTrace = undefined;
  }

  private async loadTraceList(): Promise<void> {
    this.libraryLoading = true;
    this.libraryError = undefined;
    this.selectedStoredTrace = undefined;
    this.renderLibrary();
    try {
      const response = await fetch(this.traceEndpoint, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`读取列表失败 (${response.status})`);
      const result = (await response.json()) as { traces?: StoredTraceSummary[] };
      this.traceSummaries = result.traces ?? [];
    } catch (error) {
      this.libraryError = error instanceof Error ? error.message : String(error);
    } finally {
      this.libraryLoading = false;
      this.renderLibrary();
    }
  }

  private async loadStoredTrace(id: string): Promise<void> {
    this.libraryLoading = true;
    this.libraryError = undefined;
    this.renderLibrary();
    try {
      const response = await fetch(`${this.traceEndpoint}/${encodeURIComponent(id)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`读取轨迹失败 (${response.status})`);
      this.selectedStoredTrace = (await response.json()) as StoredFrontendHelperTrace;
    } catch (error) {
      this.libraryError = error instanceof Error ? error.message : String(error);
    } finally {
      this.libraryLoading = false;
      this.renderLibrary();
    }
  }

  private async renameStoredTrace(id: string): Promise<void> {
    const input = this.libraryContent.querySelector<HTMLInputElement>("[data-fh-name-input]");
    const name = input?.value.trim() ?? "";
    if (name.length > 80) {
      this.libraryError = "轨迹名称不能超过 80 个字符";
      this.renderLibrary();
      return;
    }

    try {
      const response = await fetch(`${this.traceEndpoint}/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) throw new Error(`命名失败 (${response.status})`);
      if (this.selectedStoredTrace?.storage.id === id) this.selectedStoredTrace.storage.name = name || undefined;
      const summary = this.traceSummaries.find((item) => item.id === id);
      if (summary) summary.name = name || null;
      this.libraryError = undefined;
      this.renderLibrary();
    } catch (error) {
      this.libraryError = error instanceof Error ? error.message : String(error);
      this.renderLibrary();
    }
  }

  private async deleteStoredTrace(id: string): Promise<void> {
    if (!window.confirm(`确定删除轨迹 ${id}？此操作无法撤销。`)) return;
    try {
      const response = await fetch(`${this.traceEndpoint}/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!response.ok) throw new Error(`删除失败 (${response.status})`);
      if (this.traceId === id) this.traceId = undefined;
      this.selectedStoredTrace = undefined;
      await this.loadTraceList();
      this.renderTraceResult();
    } catch (error) {
      this.libraryError = error instanceof Error ? error.message : String(error);
      this.renderLibrary();
    }
  }

  private async onLibraryClick(event: Event): Promise<void> {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest<HTMLButtonElement>("button[data-fh-action]");
    if (!button) return;
    const action = button.dataset.fhAction;
    const id = button.dataset.fhId;
    if (action === "back") {
      this.selectedStoredTrace = undefined;
      this.renderLibrary();
    } else if (action === "open" && id) {
      await this.loadStoredTrace(id);
    } else if (action === "rename" && id) {
      await this.renameStoredTrace(id);
    } else if (action === "delete" && id) {
      await this.deleteStoredTrace(id);
    }
  }

  private renderLibrary(): void {
    if (this.libraryLoading) {
      this.libraryContent.innerHTML = '<div class="fh-library-empty">正在读取轨迹…</div>';
      return;
    }
    if (this.libraryError) {
      this.libraryContent.innerHTML = `<div class="fh-library-empty">${escapeHtml(this.libraryError)}</div>`;
      return;
    }
    if (this.selectedStoredTrace) {
      this.renderStoredTraceDetail(this.selectedStoredTrace);
      return;
    }
    if (this.traceSummaries.length === 0) {
      this.libraryContent.innerHTML = '<div class="fh-library-empty">还没有保存的轨迹。<br>完成一次录制后会自动出现在这里。</div>';
      return;
    }

    this.libraryContent.innerHTML = this.traceSummaries
      .map((trace) => {
        const name = trace.name || "未命名轨迹";
        const version = formatServiceVersion(trace.service);
        return `
          <div class="fh-trace-row">
            <div class="fh-trace-main">
              <button class="fh-trace-main-button" type="button" data-fh-action="open" data-fh-id="${trace.id}">
                <span class="fh-trace-name ${trace.name ? "" : "unnamed"}">${escapeHtml(name)}</span>
                <span class="fh-trace-row-id">${trace.id}</span>
              </button>
              <button class="fh-row-delete" type="button" data-fh-action="delete" data-fh-id="${trace.id}">删除</button>
            </div>
            <div class="fh-trace-meta">
              <span>${formatSavedAt(trace.savedAt)}</span>
              <span>${trace.eventCount} 事件</span>
              <span>${trace.annotationCount} 批注</span>
              ${version ? `<span class="fh-version-pill">${escapeHtml(version)}</span>` : ""}
            </div>
          </div>
        `;
      })
      .join("");
  }

  private renderStoredTraceDetail(trace: StoredFrontendHelperTrace): void {
    const version = renderServiceVersion(trace.service);
    const events = trace.timeline
      .slice(0, 80)
      .map(
        (event) => `
          <div class="fh-detail-event">
            <time>${formatTime(event.at)}</time>
            <span>${escapeHtml(event.summary)}</span>
          </div>
        `,
      )
      .join("");
    this.libraryContent.innerHTML = `
      <div class="fh-detail">
        <button class="fh-detail-back" type="button" data-fh-action="back">← 返回轨迹列表</button>
        <div class="fh-detail-id">${trace.storage.id}</div>
        <div class="fh-name-editor">
          <input class="fh-name-input" data-fh-name-input maxlength="80" value="${escapeHtml(trace.storage.name ?? "")}" placeholder="给这条轨迹起个名字" />
          <button class="fh-mini-button" type="button" data-fh-action="rename" data-fh-id="${trace.storage.id}">保存名称</button>
        </div>
        ${version}
        <div class="fh-detail-heading">语义时间线 · ${trace.timeline.length} 个事件</div>
        ${events || '<div class="fh-library-empty">没有语义事件</div>'}
      </div>
    `;
  }

  private render(): void {
    this.recordingFrame.hidden = !this.recording;
    this.startButton.textContent = this.recording ? "■ 停止录制" : "● 开始录制";
    this.startButton.classList.toggle("primary", !this.recording);
    this.startButton.classList.toggle("danger", this.recording);
    this.startButton.disabled = this.saving;
    this.pickerButton.disabled = !this.recording;
    this.renderStatus();
    this.renderTimeline();
    this.renderTraceResult();
  }

  private renderStatus(): void {
    this.statusDot.classList.toggle("recording", this.recording);
    if (this.recording) {
      this.statusTitle.textContent = "正在录制";
      this.statusMeta.textContent = `${formatTime(this.elapsed())} · ${this.timeline.length} 个事件 · ${this.annotations.length} 条批注`;
    } else if (this.saving) {
      this.statusTitle.textContent = "正在保存轨迹";
      this.statusMeta.textContent = "上传到本地开发服务器…";
    } else if (this.traceId) {
      this.statusTitle.textContent = "轨迹已保存";
      this.statusMeta.textContent = "把下面的 ID 告诉 AI 即可";
    } else if (this.saveError) {
      this.statusTitle.textContent = "轨迹保存失败";
      this.statusMeta.textContent = this.saveError;
    } else if (this.timeline.length > 0) {
      this.statusTitle.textContent = "录制完成";
      this.statusMeta.textContent = `${this.timeline.length} 个事件 · ${this.annotations.length} 条批注`;
    } else {
      this.statusTitle.textContent = "准备就绪";
      this.statusMeta.textContent = "尚未开始录制";
    }
  }

  private renderTraceResult(): void {
    const visible = this.saving || Boolean(this.traceId) || Boolean(this.saveError);
    this.traceResult.hidden = !visible;
    this.copyButton.hidden = !this.traceId;
    this.deleteButton.hidden = !this.traceId;

    if (this.saving) {
      this.traceResultLabel.textContent = "正在保存到开发服务器";
      this.traceIdElement.textContent = "请稍候…";
    } else if (this.traceId) {
      this.traceResultLabel.textContent = "轨迹已保存，把这个 ID 告诉 AI";
      this.traceIdElement.textContent = this.traceId;
    } else if (this.saveError) {
      this.traceResultLabel.textContent = "保存失败";
      this.traceIdElement.textContent = this.saveError;
    }
  }

  private renderTimeline(): void {
    if (this.timeline.length === 0) {
      this.timelineElement.innerHTML = '<div class="fh-empty">开始录制后，点击、输入和元素批注会出现在这里。</div>';
      return;
    }

    this.timelineElement.innerHTML = this.timeline
      .slice(-30)
      .map(
        (event) => `
          <div class="fh-event">
            <div class="fh-event-time">${formatTime(event.at)}</div>
            <div class="fh-event-copy ${event.kind === "annotation" ? "annotation" : ""}">${escapeHtml(event.summary)}</div>
          </div>
        `,
      )
      .join("");
    this.timelineElement.scrollTop = this.timelineElement.scrollHeight;
  }

  private setOpen(open: boolean): void {
    this.openState = open;
    this.panel.hidden = !open;
    this.launcher.hidden = open;
    if (open) window.requestAnimationFrame(() => this.restorePanelPosition());
  }

  private elapsed(): number {
    if (!this.startedAtMono) return 0;
    return Math.max(0, Math.round(performance.now() - this.startedAtMono));
  }

  private isOverlayEvent(event: Event): boolean {
    return event.composedPath().includes(this.host);
  }

  private requireElement<T extends Element = HTMLElement>(selector: string): T {
    const element = this.shadow.querySelector<T>(selector);
    if (!element) throw new Error(`Frontend Helper UI is missing ${selector}`);
    return element;
  }

  private destroy(): void {
    this.stop();
    this.unbindPageEvents();
    this.clearScrollBursts();
    this.host.remove();
    activeController = undefined;
  }
}

function getRrwebNodeId(element: Element): number {
  const recorder = record as typeof record & { mirror?: { getId(node: Node): number } };
  return recorder.mirror?.getId(element) ?? -1;
}

function hasUnrecordedTarget(event: unknown): boolean {
  if (!event || typeof event !== "object") return false;
  const candidate = event as { type?: unknown; data?: unknown };
  if (candidate.type !== 3 || !candidate.data || typeof candidate.data !== "object") return false;
  const id = (candidate.data as { id?: unknown }).id;
  return typeof id === "number" && id < 0;
}

function firstElementInPath(path: EventTarget[]): Element | undefined {
  return path.find((item): item is Element => item instanceof Element);
}

function pickAttributes(element: Element): Record<string, string> {
  const safeNames = new Set([
    "id",
    "class",
    "name",
    "type",
    "href",
    "title",
    "alt",
    "role",
    "aria-label",
    "aria-labelledby",
    "aria-describedby",
    "data-testid",
    "data-test-id",
  ]);
  return Object.fromEntries(
    [...element.attributes]
      .filter((attribute) => safeNames.has(attribute.name))
      .map((attribute) => [attribute.name, attribute.value.slice(0, 240)]),
  );
}

function getRole(element: Element): string | undefined {
  const explicit = element.getAttribute("role");
  if (explicit) return explicit;
  const tag = element.tagName.toLowerCase();
  if (tag === "button") return "button";
  if (tag === "a" && element.hasAttribute("href")) return "link";
  if (tag === "textarea") return "textbox";
  if (tag === "select") return "combobox";
  if (tag === "dialog") return "dialog";
  if (element instanceof HTMLInputElement) {
    if (["button", "submit", "reset"].includes(element.type)) return "button";
    if (element.type === "checkbox") return "checkbox";
    if (element.type === "radio") return "radio";
    return "textbox";
  }
  return undefined;
}

function getAccessibleName(element: Element): string | undefined {
  const ariaLabel = normalizeText(element.getAttribute("aria-label"), 160);
  if (ariaLabel) return ariaLabel;

  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const label = labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    const normalized = normalizeText(label, 160);
    if (normalized) return normalized;
  }

  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) {
    const label = element.labels?.[0]?.textContent;
    const normalized = normalizeText(label, 160);
    if (normalized) return normalized;
  }

  return (
    normalizeText(element.getAttribute("alt"), 160) ??
    normalizeText(element.getAttribute("title"), 160) ??
    normalizeText(element.textContent, 160)
  );
}

function buildSelector(element: Element): string {
  const testId = element.getAttribute("data-testid");
  if (testId) return `[data-testid="${escapeSelectorString(testId)}"]`;
  const alternateTestId = element.getAttribute("data-test-id");
  if (alternateTestId) return `[data-test-id="${escapeSelectorString(alternateTestId)}"]`;
  if (element.id) return `#${cssEscape(element.id)}`;

  const parts: string[] = [];
  let current: Element | null = element;
  while (current && current !== document.documentElement && parts.length < 5) {
    let part = current.tagName.toLowerCase();
    const stableClasses = [...current.classList].filter((name) => !/^(active|selected|open|hover|focus|css-|sc-)/i.test(name)).slice(0, 2);
    if (stableClasses.length) part += stableClasses.map((name) => `.${cssEscape(name)}`).join("");
    const parent: Element | null = current.parentElement;
    if (parent) {
      const siblings = [...parent.children].filter((child) => child.tagName === current?.tagName);
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
    }
    parts.unshift(part);
    current = parent;
  }
  return parts.join(" > ");
}

function buildDomPath(element: Element): number[] {
  const path: number[] = [];
  let current: Element | null = element;
  while (current?.parentElement) {
    path.unshift([...current.parentElement.children].indexOf(current));
    current = current.parentElement;
  }
  return path;
}

function sanitizeHtmlSnippet(element: Element): string {
  const clone = element.cloneNode(true) as Element;
  clone.querySelectorAll("input, textarea").forEach((field) => {
    field.removeAttribute("value");
    field.textContent = "";
  });
  clone.querySelectorAll("script").forEach((script) => script.remove());
  const html = clone.outerHTML.replace(/\s+/g, " ").trim();
  return html.length > 900 ? `${html.slice(0, 897)}…` : html;
}

function elementLabel(reference: ElementReference): string {
  const name = reference.accessibleName || reference.text;
  const kind = reference.role || reference.tagName;
  return name ? `${kind} “${name.slice(0, 72)}”` : kind;
}

function matchesHotkey(event: KeyboardEvent, hotkey: string): boolean {
  const parts = hotkey.toLowerCase().split("+");
  const key = parts.at(-1);
  return (
    event.altKey === parts.includes("alt") &&
    event.shiftKey === parts.includes("shift") &&
    event.ctrlKey === parts.includes("ctrl") &&
    event.metaKey === (parts.includes("meta") || parts.includes("cmd")) &&
    event.key.toLowerCase() === key
  );
}

function normalizeText(value: string | null | undefined, maxLength: number): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) return undefined;
  return normalized.slice(0, maxLength);
}

function formatSavedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatServiceVersion(service: ServiceVersion | null | undefined): string | undefined {
  if (!service) return undefined;
  const identity = [service.name, service.version].filter(Boolean).join("@");
  const commit = service.commit ? service.commit.slice(0, 8) : undefined;
  const parts = [identity || undefined, commit, service.dirty ? "dirty" : undefined].filter(Boolean);
  return parts.length ? parts.join(" · ") : undefined;
}

function renderServiceVersion(service: ServiceVersion | undefined): string {
  if (!service) return '<div class="fh-version-card">这条轨迹没有可用的服务版本信息。</div>';
  const identity = [service.name, service.version].filter(Boolean).join(" @ ") || "未声明版本";
  const commit = service.commit ? `<br>commit <code>${escapeHtml(service.commit)}</code>` : "";
  const branch = service.branch ? `<br>branch <code>${escapeHtml(service.branch)}</code>` : "";
  const dirty = service.dirty === undefined ? "" : `<br>workspace <code>${service.dirty ? "dirty" : "clean"}</code>`;
  return `<div class="fh-version-card">服务版本 <code>${escapeHtml(identity)}</code>${commit}${branch}${dirty}</div>`;
}

function formatTime(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1000);
  const remainder = milliseconds % 1000;
  return `${String(seconds).padStart(2, "0")}.${String(remainder).padStart(3, "0")}`;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function cssEscape(value: string): string {
  return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : value.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function escapeSelectorString(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return entities[character];
  });
}
