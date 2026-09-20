import { spawn, execFile } from 'node:child_process';
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { networkInterfaces } from 'node:os';
import { WebSocketServer, WebSocket } from 'ws';
import { readFile } from 'node:fs/promises';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = path.join(root, '.venv/bin/python');
const runFile = promisify(execFile);

export function allowedRequest(req, port, requireOrigin = false) {
  const hosts = new Set([`localhost:${port}`, `127.0.0.1:${port}`, `0.0.0.0:${port}`]);
  for (const addresses of Object.values(networkInterfaces())) {
    for (const { address, family } of addresses || []) {
      hosts.add(`${family === 'IPv6' ? `[${address}]` : address}:${port}`);
    }
  }
  const { host, origin } = req.headers;
  return hosts.has(host) && (origin
    ? origin === `http://${host}` || origin === `https://${host}`
    : !requireOrigin);
}

export function validateOptions(value) {
  if (!value || !['en', 'zh-CN'].includes(value.language) ||
      !['speaker', 'headphones'].includes(value.echoMode) ||
      !['wake', 'qa', 'realtime'].includes(value.responseMode) ||
      !Number.isInteger(value.seconds) ||
      !((value.seconds >= 10 && value.seconds <= 300) ||
        (value.seconds === 0 && value.transport === 'browser' && value.responseMode === 'realtime'))) {
    throw new Error('请选择问答模式、语言、播放方式和 10–300 秒的时长。');
  }
  if (value.transport !== undefined && !['browser', 'local'].includes(value.transport)) throw new Error('Invalid transport');
  if (value.transport === 'browser' && value.responseMode !== 'realtime') throw new Error('Invalid transport');
  for (const key of ['inputDevice', 'outputDevice']) {
    if (value[key] !== '' && (!Number.isInteger(value[key]) || value[key] < 0 || value[key] > 1024)) {
      throw new Error('设备编号无效，请刷新设备列表。');
    }
  }
  return value;
}

// One local hardware session; a browser heartbeat leases the microphone.
export class SessionController {
  constructor(spawnChild = spawn, clock = Date.now) {
    this.spawnChild = spawnChild;
    this.clock = clock;
    this.child = null;
    this.state = { id: null, status: 'idle', events: [], level: 0, gated: false, timingReliable: true };
  }
  snapshot() {
    this.lastSeen = this.clock();
    return this.state;
  }
  start(options) {
    validateOptions(options);
    if (this.child) throw new Error('测试正在运行，请先停止当前测试。');
    const args = ['-m', ...(options.responseMode === 'realtime' ? ['sparkie.realtime_session'] : ['sparkie.primitive', 'local']), '--language', options.language,
      '--seconds', String(options.seconds), '--echo-mode', options.echoMode,
      ];
    if (options.transport === 'browser') args.push('--transport', 'browser');
    if (options.responseMode !== 'realtime') args.push('--response-mode', options.responseMode);
    for (const [key, flag] of [['inputDevice', '--input-device'], ['outputDevice', '--output-device']]) {
      if (options[key] !== '') args.push(flag, String(options[key]));
    }
    this.state = { id: randomUUID(), status: 'starting', startedAt: this.clock(), options,
      events: [], level: 0, gated: false, timingReliable: true };
    this.outputDirectory = null;
    this.eventSequence = 0;
    this.lastSeen = this.clock();
    this.lastAudioAt = null;
    this.captureActive = false;
    this.recentCancellations = [];
    const child = this.spawnChild(python, args, { cwd: root, stdio: [options.responseMode === 'realtime' ? 'pipe' : 'ignore', 'pipe', 'pipe'] });
    this.child = child;
    child.stdin?.on('error', () => { this.state.warning = '控制连接已结束。'; });
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => {
      try {
        const event = JSON.parse(line);
        if (typeof event.type !== 'string') return;
        if (event.type === 'audio_output' || event.type === 'audio_clear') {
          if (this.audioSocket?.readyState === WebSocket.OPEN) {
            if (this.audioSocket.bufferedAmount > 512000) this.stop('audio-output-backpressure');
            else this.audioSocket.send(JSON.stringify(event));
          }
          return;
        }
        if (event.type === 'audio_level') {
          this.lastAudioAt = this.clock();
          if (this.state.warning === '麦克风输入已停滞，正在检查音频连接。') {
            this.state.warning = event.timing_reliable ? undefined : '音频已恢复，但本轮延迟计时无效。';
          }
          this.state.level = event.peak;
          this.state.gated = event.gated;
          this.state.timingReliable &&= event.timing_reliable;
          return;
        }
        if (event.type === 'transcript_partial') {
          // Provisional text is replaceable UI state, never final history or task context.
          this.state.partialTranscript = event.text || '';
          return;
        }
        if (event.type === 'transcript' || event.type === 'transcript_degraded') this.state.partialTranscript = '';
        if (event.type === 'user_speech_started') {
          this.state.speechActive = true;
          this.state.speechStartedAt = this.clock();
        }
        if (event.type === 'user_speech_stopped') this.state.speechActive = false;
        if (event.type === 'realtime_response_done' && event.status === 'cancelled') {
          this.recentCancellations = this.recentCancellations.filter(t => this.clock() - t < 15000);
          this.recentCancellations.push(this.clock());
          if (this.recentCancellations.length >= 2) {
            this.state.voiceHint = '回复连续被新的声音打断；说完后稍停一下，或试用耳机。';
            this.voiceHintUntil = this.clock() + 15000;
          }
        }
        if (event.type === 'assistant_transcript') {
          this.state.voiceHint = undefined;
          this.recentCancellations = [];
        }
        if (event.type === 'configuration_error') this.state.error = `缺少配置：${event.missing.join(', ')}`;
        if (event.type === 'session_failed') this.state.error = `实时会话失败（${event.error_type}），请检查连接与配置。`;
        if (event.type === 'session_created') this.outputDirectory = event.output;
        event.sequence = ++this.eventSequence;
        this.state.events.push(event);
        if (this.state.events.length > 2000) this.state.events.shift();
        if (event.type === 'listening_ready' && this.state.status === 'starting') {
          this.state.status = 'listening';
          if (this.audioSocket?.readyState === WebSocket.OPEN) this.audioSocket.send(JSON.stringify({ type: 'audio_ready' }));
          this.captureActive = true;
          this.lastAudioAt = this.clock();
        }
        if (event.type === 'audio_input_ended') this.captureActive = false;
        if (event.type === 'audio_warning') this.state.warning = '麦克风音频出现丢帧，本轮延迟计时无效；若转录不再更新，请停止后重新开始。';
        if (event.type === 'audio_failed' || event.type === 'audio_cleanup_failed') {
          this.state.error = '音频采集已中断，当前会话无法继续聆听。请重新开始；如果反复发生，请切换音频设备。';
          this.stop('audio-failed');
        }
        if (event.type === 'audio_warning' || event.type === 'playback_timing_unavailable') this.state.timingReliable = false;
      } catch { /* Plain CLI notices aren't part of the browser event contract. */ }
    });
    // Don't forward stderr/provider messages or environment values to the client.
    child.stderr.resume();
    child.on('error', () => { this.state.error = '音频服务启动失败。请先运行 uv sync --frozen。'; });
    child.on('close', (code, signal) => {
      clearTimeout(this.killTimer);
      clearTimeout(this.deadlineTimer);
      lines.close();
      this.child = null;
      this.audioSocket?.close(1000); this.audioSocket = null;
      this.state.level = 0;
      this.state.gated = false;
      this.captureActive = false;
      this.state.partialTranscript = '';
      this.state.speechActive = false;
      this.state.voiceHint = undefined;
      if (signal === 'SIGKILL') this.state.error ||= '音频进程卡住，已强制停止。请重新开始测试；本轮未正常结束。';
      this.state.status = code === 0 && !this.state.error ? 'ended' : 'failed';
      if (this.state.status === 'failed') this.state.error ||= '测试失败：请检查 Deepgram 配置、网络、音频设备和麦克风权限；问答模式还需有效的 Codex 登录及模型配置。详细错误类型见事件记录。';
      this.state.exitCode = code;
      this.state.exitSignal = signal || null;
    });
    if (options.seconds > 0) {
      this.deadlineTimer = setTimeout(() => this.stop('timeout'), (options.seconds + 45) * 1000);
      this.deadlineTimer.unref?.();
    }
    return this.state;
  }
  audioCommand(command) {
    if (!this.child || this.state.options?.transport !== 'browser') throw new Error('No browser audio session');
    if (!['audio_input', 'audio_progress', 'audio_settings'].includes(command.action)) throw new Error('Invalid audio command');
    // Live audio also renews the page lease when background-tab timers are throttled.
    this.lastSeen = this.clock();
    if (command.action === 'audio_input') {
      this.lastAudioAt = this.clock();
      if (this.state.audioStalled) {
        this.state.audioStalled = false;
        this.state.warning = undefined;
      }
    }
    if (this.child.stdin.writableLength > 256000) { this.stop('audio-input-backpressure'); return; }
    this.child.stdin.write(JSON.stringify(command) + '\n');
  }
  control(command) {
    if (!this.child || this.state.options?.responseMode !== 'realtime' ||
        !['interrupt', 'cancel_task', 'report_task'].includes(command.action) ||
        (command.action !== 'interrupt' && !/^[a-f0-9]{12}$/.test(command.task_id || ''))) throw new Error('Invalid control');
    this.child.stdin.write(JSON.stringify(command) + '\n');
    return { ok: true };
  }
  stop(reason = 'user') {
    if (this.child && this.state.status !== 'stopping') {
      this.state.status = 'stopping';
      this.state.stopReason = reason;
      this.child.kill('SIGTERM');
      const child = this.child;
      // Provider sockets can each spend a few seconds flushing/closing.
      this.killTimer = setTimeout(() => child.kill('SIGKILL'), 10000);
      this.killTimer.unref?.();
    }
    return this.state;
  }
  expire() {
    if (this.clock() >= this.voiceHintUntil) this.state.voiceHint = undefined;
    if (this.child && this.clock() - this.lastSeen > 15000) this.stop('page-disconnected');
    if (this.child && this.state.status === 'listening' && this.captureActive && this.lastAudioAt !== null) {
      const gap = this.clock() - this.lastAudioAt;
      if (gap > 3000) {
        this.state.level = 0;
        this.state.audioStalled = true;
        this.state.warning = this.state.options.transport === 'browser'
          ? '麦克风输入暂时中断，后台任务仍在继续。请点“恢复麦克风”。'
          : '麦克风输入已停滞，正在检查音频连接。';
      }
      if (gap > 6000 && this.state.options.transport !== 'browser') {
        this.state.error = '连续 6 秒没有收到麦克风音频，已停止本轮。请重新开始或切换音频设备。';
        this.stop('audio-stalled');
      }
    }
  }
}

export function localApi(port = 5178) {
  const controller = new SessionController();
  return {
    name: 'sparkie-local-api', apply: 'serve',
    configureServer(server) {
      const audioServer = new WebSocketServer({ noServer: true, maxPayload: 16384 });
      server.httpServer?.on('upgrade', (req, socket, head) => {
        const url = new URL(req.url, 'http://localhost');
        if (url.pathname !== '/audio') return;
        if (!allowedRequest(req, port, true) ||
            !controller.child || controller.state.options?.transport !== 'browser' ||
            url.searchParams.get('session') !== controller.state.id || controller.audioSocket) {
          socket.end('HTTP/1.1 403 Forbidden\r\n\r\n'); return;
        }
        audioServer.handleUpgrade(req, socket, head, ws => {
          controller.audioSocket = ws;
          if (controller.state.status === 'listening') ws.send(JSON.stringify({ type: 'audio_ready' }));
          ws.on('message', raw => {
            try { controller.audioCommand(JSON.parse(raw.toString())); }
            catch { controller.stop('invalid-audio'); ws.close(); }
          });
          ws.on('error', () => controller.stop('audio-disconnected'));
          ws.on('close', () => {
            if (controller.audioSocket === ws) { controller.audioSocket = null; controller.stop('audio-disconnected'); }
          });
        });
      });

      const heartbeat = setInterval(() => controller.expire(), 1000);
      heartbeat.unref();
      server.httpServer?.once('close', () => { clearInterval(heartbeat); controller.stop('server-closed'); });
      const shutdown = () => controller.stop('server-closed');
      process.once('SIGTERM', shutdown);
      process.once('SIGINT', shutdown);
      server.middlewares.use('/api', async (req, res) => {
        const send = (code, data) => {
          res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
          res.end(JSON.stringify(data));
        };
        if (!allowedRequest(req, port)) {
          return send(403, { error: '仅允许通过本机地址同源访问。' });
        }
        try {
          if (req.method === 'GET' && req.url === '/status') return send(200, controller.snapshot());
          if (req.method === 'GET' && req.url === '/transcript') {
            if (!controller.outputDirectory) return send(200, { records: [] });
            const directory = path.resolve(root, controller.outputDirectory);
            if (!directory.startsWith(path.join(root, 'output') + path.sep)) return send(403, { error: 'Invalid session' });
            const data = await readFile(path.join(directory, 'transcript.jsonl'), 'utf8').catch(error => { if (error.code === 'ENOENT') return ''; throw error; });
            return send(200, { records: data.split('\n').filter(Boolean).map(line => JSON.parse(line)) });
          }
          if (req.method === 'GET' && req.url === '/config') {
            const { stdout } = await runFile(python, ['-c', 'from dotenv import load_dotenv; import os,json; load_dotenv(); print(json.dumps({k:bool(os.getenv(k)) for k in ["OPENAI_API_KEY","DEEPGRAM_API_KEY"]}))'], { cwd: root, timeout: 5000 });
            return send(200, JSON.parse(stdout));
          }
          if (req.method === 'GET' && req.url === '/devices') {
            const code = 'import sounddevice as s,json; print(json.dumps({"devices":[{"id":i,"name":d["name"],"input":d["max_input_channels"]>0,"output":d["max_output_channels"]>0} for i,d in enumerate(s.query_devices())],"defaults":list(s.default.device)}))';
            const { stdout } = await runFile(python, ['-c', code], { cwd: root, timeout: 10000 });
            return send(200, JSON.parse(stdout));
          }
          if (req.method === 'POST') {
            if (!req.headers['content-type']?.startsWith('application/json')) return send(415, { error: 'Expected JSON' });
            let body = '';
            for await (const chunk of req) {
              body += chunk;
              if (body.length > 4096) return send(413, { error: 'Request too large' });
            }
            const options = JSON.parse(body);
            if (req.url === '/start') return send(200, controller.start(options));
            if (req.url === '/control') return send(200, controller.control(options));
            if (req.url === '/stop') return send(200, controller.stop());
          }
          send(404, { error: 'Not found' });
        } catch (error) {
          send(400, { error: error.message?.startsWith('请选择') || error.message?.startsWith('设备编号') || error.message?.startsWith('测试正在')
            ? error.message : '无法完成操作，请检查本地 Python 环境和音频设备后重试。' });
        }
      });
    },
  };
}
