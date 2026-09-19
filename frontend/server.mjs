import { spawn, execFile } from 'node:child_process';
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const python = path.join(root, '.venv/bin/python');
const runFile = promisify(execFile);

export function validateOptions(value) {
  if (!value || !['en', 'zh-CN'].includes(value.language) ||
      !['speaker', 'headphones'].includes(value.echoMode) ||
      !Number.isInteger(value.seconds) || value.seconds < 10 || value.seconds > 300) {
    throw new Error('请选择语言、播放方式和 10–300 秒的时长。');
  }
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
    const args = ['-m', 'sparkie.primitive', 'local', '--language', options.language,
      '--seconds', String(options.seconds), '--echo-mode', options.echoMode];
    for (const [key, flag] of [['inputDevice', '--input-device'], ['outputDevice', '--output-device']]) {
      if (options[key] !== '') args.push(flag, String(options[key]));
    }
    this.state = { id: randomUUID(), status: 'starting', startedAt: this.clock(), options,
      events: [], level: 0, gated: false, timingReliable: true };
    this.lastSeen = this.clock();
    const child = this.spawnChild(python, args, { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    this.child = child;
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => {
      try {
        const event = JSON.parse(line);
        if (typeof event.type !== 'string') return;
        if (event.type === 'audio_level') {
          this.state.level = event.peak;
          this.state.gated = event.gated;
          this.state.timingReliable &&= event.timing_reliable;
          return;
        }
        this.state.events.push(event);
        if (this.state.events.length > 2000) this.state.events.shift();
        if (event.type === 'listening_ready' && this.state.status === 'starting') this.state.status = 'listening';
        if (event.type === 'audio_warning' || event.type === 'playback_timing_unavailable') this.state.timingReliable = false;
      } catch { /* Plain CLI notices aren't part of the browser event contract. */ }
    });
    // Don't forward stderr/provider messages or environment values to the client.
    child.stderr.resume();
    child.on('error', () => { this.state.error = '音频服务启动失败。请先运行 uv sync --frozen。'; });
    child.on('close', code => {
      clearTimeout(this.killTimer);
      clearTimeout(this.deadlineTimer);
      lines.close();
      this.child = null;
      this.state.level = 0;
      this.state.gated = false;
      this.state.status = code === 0 || this.state.status === 'stopping' ? 'ended' : 'failed';
      if (this.state.status === 'failed') this.state.error ||= '测试失败：请检查 .env 中的 Deepgram 配置、网络、音频设备和系统麦克风权限。详细错误类型见事件记录。';
      this.state.exitCode = code;
    });
    this.deadlineTimer = setTimeout(() => this.stop('timeout'), (options.seconds + 45) * 1000);
    this.deadlineTimer.unref?.();
    return this.state;
  }
  stop(reason = 'user') {
    if (this.child && this.state.status !== 'stopping') {
      this.state.status = 'stopping';
      this.state.stopReason = reason;
      this.child.kill('SIGTERM');
      const child = this.child;
      this.killTimer = setTimeout(() => child.kill('SIGKILL'), 5000);
      this.killTimer.unref?.();
    }
    return this.state;
  }
  expire() {
    if (this.child && this.clock() - this.lastSeen > 15000) this.stop('page-disconnected');
  }
}

export function localApi() {
  const controller = new SessionController();
  return {
    name: 'sparkie-local-api', apply: 'serve',
    configureServer(server) {
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
        const origin = req.headers.origin;
        const allowed = new Set(['http://127.0.0.1:5178', 'http://localhost:5178']);
        if (!['127.0.0.1:5178', 'localhost:5178'].includes(req.headers.host) || (origin && !allowed.has(origin))) {
          return send(403, { error: '仅允许本机页面访问。' });
        }
        try {
          if (req.method === 'GET' && req.url === '/status') return send(200, controller.snapshot());
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
