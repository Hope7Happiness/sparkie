export const overlayStyles = `
  :host {
    all: initial;
    color-scheme: dark;
    --fh-panel: rgba(17, 24, 39, 0.96);
    --fh-panel-soft: rgba(31, 41, 55, 0.92);
    --fh-border: rgba(255, 255, 255, 0.12);
    --fh-muted: #9ca3af;
    --fh-text: #f9fafb;
    --fh-accent: #a78bfa;
    --fh-recording: #fb7185;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }

  *, *::before, *::after { box-sizing: border-box; }
  button, textarea { font: inherit; }

  .fh-launcher {
    position: fixed;
    right: 22px;
    bottom: 22px;
    z-index: 2147483645;
    display: flex;
    align-items: center;
    gap: 8px;
    height: 42px;
    padding: 0 14px;
    border: 1px solid var(--fh-border);
    border-radius: 999px;
    color: var(--fh-text);
    background: var(--fh-panel);
    box-shadow: 0 18px 45px rgba(0, 0, 0, 0.28);
    cursor: pointer;
    transition: transform 140ms ease, border-color 140ms ease;
  }

  .fh-launcher:hover { transform: translateY(-2px); border-color: rgba(167, 139, 250, 0.55); }
  .fh-launcher[hidden] { display: none; }
  .fh-mark { color: var(--fh-accent); font-size: 16px; }
  .fh-launcher-label { font-size: 12px; font-weight: 700; letter-spacing: 0.02em; }

  .fh-panel {
    position: fixed;
    right: 22px;
    bottom: 22px;
    z-index: 2147483645;
    width: min(360px, calc(100vw - 32px));
    overflow: hidden;
    border: 1px solid var(--fh-border);
    border-radius: 20px;
    color: var(--fh-text);
    background: var(--fh-panel);
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.34);
    backdrop-filter: blur(18px);
  }

  .fh-panel.dragging { user-select: none; }

  .fh-panel[hidden] { display: none; }
  .fh-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 16px 12px; cursor: grab; touch-action: none; }
  .fh-header:active, .fh-panel.dragging .fh-header { cursor: grabbing; }
  .fh-brand { display: flex; align-items: center; gap: 10px; }
  .fh-brand-icon { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 10px; color: #111827; background: var(--fh-accent); font-weight: 900; }
  .fh-title { font-size: 13px; font-weight: 800; }
  .fh-subtitle { margin-top: 2px; color: var(--fh-muted); font-size: 10px; }

  .fh-icon-button {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border: 0;
    border-radius: 9px;
    color: var(--fh-muted);
    background: transparent;
    cursor: pointer;
  }

  .fh-icon-button:hover { color: var(--fh-text); background: rgba(255,255,255,0.08); }
  .fh-header-actions { display: flex; align-items: center; gap: 3px; }
  .fh-status { display: flex; align-items: center; gap: 8px; margin: 0 16px 12px; padding: 10px 12px; border: 1px solid var(--fh-border); border-radius: 12px; background: rgba(255,255,255,0.04); }
  .fh-status-dot { width: 8px; height: 8px; border-radius: 50%; background: #6b7280; }
  .fh-status-dot.recording { background: var(--fh-recording); box-shadow: 0 0 0 5px rgba(251,113,133,0.12); animation: fh-pulse 1.5s infinite; }
  .fh-status-copy { flex: 1; }
  .fh-status-title { font-size: 11px; font-weight: 750; }
  .fh-status-meta { margin-top: 2px; color: var(--fh-muted); font-size: 10px; }

  .fh-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 0 16px 14px; }
  .fh-button { min-height: 38px; padding: 0 12px; border: 1px solid var(--fh-border); border-radius: 11px; color: var(--fh-text); background: rgba(255,255,255,0.06); font-size: 11px; font-weight: 750; cursor: pointer; }
  .fh-button:hover:not(:disabled) { background: rgba(255,255,255,0.11); }
  .fh-button:disabled { opacity: 0.42; cursor: not-allowed; }
  .fh-button.primary { border-color: transparent; color: #17111f; background: var(--fh-accent); }
  .fh-button.danger { border-color: rgba(251,113,133,0.4); color: #fecdd3; background: rgba(251,113,133,0.12); }
  .fh-button.wide { grid-column: 1 / -1; }

  .fh-trace-result { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 7px; margin: 0 16px 14px; padding: 10px 10px 10px 12px; border: 1px solid rgba(167,139,250,0.28); border-radius: 12px; background: rgba(167,139,250,0.08); }
  .fh-trace-result[hidden] { display: none; }
  .fh-trace-copy { min-width: 0; }
  .fh-trace-label { color: var(--fh-muted); font-size: 9px; }
  .fh-trace-id { margin-top: 3px; color: #ddd6fe; font: 700 11px/1.3 ui-monospace, SFMono-Regular, Menlo, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fh-mini-button { height: 29px; padding: 0 9px; border: 1px solid var(--fh-border); border-radius: 8px; color: var(--fh-text); background: rgba(255,255,255,0.06); font-size: 9px; font-weight: 750; cursor: pointer; }
  .fh-mini-button:hover { background: rgba(255,255,255,0.12); }
  .fh-mini-button.delete { color: #fecdd3; }

  .fh-timeline { max-height: 190px; overflow: auto; border-top: 1px solid var(--fh-border); border-bottom: 1px solid var(--fh-border); background: rgba(0,0,0,0.12); }
  .fh-empty { padding: 24px 18px; color: var(--fh-muted); font-size: 11px; line-height: 1.55; text-align: center; }
  .fh-event { display: grid; grid-template-columns: 48px 1fr; gap: 10px; padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.06); }
  .fh-event:last-child { border-bottom: 0; }
  .fh-event-time { color: var(--fh-muted); font: 10px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }
  .fh-event-copy { min-width: 0; color: #e5e7eb; font-size: 10px; line-height: 1.45; overflow-wrap: anywhere; }
  .fh-event-copy.annotation { color: #ddd6fe; }

  .fh-footer { display: flex; justify-content: space-between; gap: 10px; padding: 11px 16px 13px; color: var(--fh-muted); font-size: 9px; }
  .fh-key { padding: 2px 6px; border: 1px solid var(--fh-border); border-radius: 5px; background: rgba(255,255,255,0.05); font-family: ui-monospace, monospace; }

  .fh-picker-box { position: fixed; z-index: 2147483644; pointer-events: none; border: 2px solid var(--fh-accent); border-radius: 6px; background: rgba(167,139,250,0.1); box-shadow: 0 0 0 1px rgba(17,24,39,0.9), 0 8px 24px rgba(0,0,0,0.18); }
  .fh-picker-label { position: absolute; left: -2px; bottom: calc(100% + 6px); max-width: 260px; padding: 5px 8px; border-radius: 6px; color: #17111f; background: var(--fh-accent); font: 700 10px/1.2 ui-monospace, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fh-picker-box[hidden] { display: none; }

  .fh-comment-card { position: fixed; z-index: 2147483646; width: min(330px, calc(100vw - 32px)); padding: 14px; border: 1px solid var(--fh-border); border-radius: 16px; color: var(--fh-text); background: var(--fh-panel); box-shadow: 0 20px 55px rgba(0,0,0,0.35); }
  .fh-comment-card[hidden] { display: none; }
  .fh-comment-target { margin-bottom: 9px; color: #ddd6fe; font-size: 10px; font-weight: 750; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fh-comment-input { display: block; width: 100%; min-height: 76px; resize: vertical; padding: 10px; border: 1px solid var(--fh-border); border-radius: 10px; outline: 0; color: var(--fh-text); background: rgba(255,255,255,0.06); font-size: 11px; line-height: 1.5; }
  .fh-comment-input:focus { border-color: rgba(167,139,250,0.72); }
  .fh-comment-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }

  .fh-recording-frame { position: fixed; inset: 4px; z-index: 2147483643; pointer-events: none; border: 2px solid var(--fh-recording); border-radius: 10px; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.4); }
  .fh-recording-frame[hidden] { display: none; }
  .fh-recording-label { position: absolute; top: 8px; left: 50%; transform: translateX(-50%); padding: 5px 9px; border-radius: 999px; color: white; background: var(--fh-recording); font-size: 9px; font-weight: 800; letter-spacing: 0.08em; }

  .fh-view[hidden] { display: none; }
  .fh-library { min-height: 330px; }
  .fh-library-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 16px 12px; }
  .fh-library-toolbar strong { font-size: 12px; }
  .fh-library-toolbar span { display: block; margin-top: 2px; color: var(--fh-muted); font-size: 9px; }
  .fh-library-content { max-height: 380px; overflow: auto; border-top: 1px solid var(--fh-border); background: rgba(0,0,0,0.12); }
  .fh-library-empty { display: grid; place-items: center; min-height: 250px; padding: 30px; color: var(--fh-muted); font-size: 10px; line-height: 1.55; text-align: center; }
  .fh-trace-row { padding: 13px 15px; border-bottom: 1px solid rgba(255,255,255,0.07); }
  .fh-trace-row:last-child { border-bottom: 0; }
  .fh-trace-main { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
  .fh-trace-main-button { min-width: 0; padding: 0; border: 0; color: var(--fh-text); background: none; text-align: left; cursor: pointer; }
  .fh-trace-name { display: block; max-width: 230px; overflow: hidden; font-size: 11px; font-weight: 760; text-overflow: ellipsis; white-space: nowrap; }
  .fh-trace-name.unnamed { color: #c4b5fd; }
  .fh-trace-row-id { display: block; margin-top: 3px; color: var(--fh-muted); font: 9px/1.3 ui-monospace, monospace; }
  .fh-trace-meta { display: flex; flex-wrap: wrap; gap: 5px 9px; margin-top: 9px; color: var(--fh-muted); font-size: 8px; }
  .fh-version-pill { padding: 2px 6px; border-radius: 999px; color: #d1fae5; background: rgba(52,211,153,0.1); }
  .fh-row-delete { padding: 2px 4px; border: 0; color: #fda4af; background: none; font-size: 9px; cursor: pointer; }

  .fh-detail { padding: 15px; }
  .fh-detail-back { padding: 0; border: 0; color: #c4b5fd; background: none; font-size: 9px; font-weight: 760; cursor: pointer; }
  .fh-detail-id { margin-top: 9px; color: var(--fh-muted); font: 9px/1.4 ui-monospace, monospace; }
  .fh-name-editor { display: grid; grid-template-columns: 1fr auto; gap: 7px; margin-top: 12px; }
  .fh-name-input { min-width: 0; height: 34px; padding: 0 10px; border: 1px solid var(--fh-border); border-radius: 9px; outline: 0; color: var(--fh-text); background: rgba(255,255,255,0.06); font-size: 10px; }
  .fh-name-input:focus { border-color: rgba(167,139,250,0.7); }
  .fh-version-card { margin-top: 12px; padding: 10px; border: 1px solid var(--fh-border); border-radius: 10px; color: #d1d5db; background: rgba(255,255,255,0.035); font-size: 9px; line-height: 1.55; }
  .fh-version-card code { color: #a7f3d0; font: 9px ui-monospace, monospace; }
  .fh-detail-heading { margin: 16px 0 7px; color: var(--fh-muted); font-size: 8px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
  .fh-detail-event { display: grid; grid-template-columns: 43px 1fr; gap: 8px; padding: 8px 0; border-top: 1px solid rgba(255,255,255,0.06); }
  .fh-detail-event time { color: var(--fh-muted); font: 8px ui-monospace, monospace; }
  .fh-detail-event span { color: #e5e7eb; font-size: 9px; line-height: 1.45; }

  @keyframes fh-pulse { 50% { opacity: 0.5; } }
`;
