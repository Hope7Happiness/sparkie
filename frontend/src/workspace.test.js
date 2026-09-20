import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

/* A DOM shim small enough to read, large enough to run workspace.js: the module
   only ever builds nodes and reads them back, so this covers the whole surface. */
const VOID = new Set(['img', 'hr', 'br', 'input', 'embed']);

class TextNode { constructor(value) { this.nodeType = 3; this.text = String(value); } }

class Element {
  constructor(tag) {
    this.tag = tag; this.tagName = tag.toUpperCase(); this.nodeType = 1;
    this.childNodes = []; this.dataset = {}; this.attrs = {};
    this.className = ''; this.parentNode = null;
    const self = this;
    this.classList = {
      set() { return new Set(String(self.className).split(/\s+/).filter(Boolean)); },
      contains(name) { return this.set().has(name); },
      add(name) { const s = this.set(); s.add(name); self.className = [...s].join(' '); },
      remove(name) { const s = this.set(); s.delete(name); self.className = [...s].join(' '); },
      toggle(name, on) { on ? this.add(name) : this.remove(name); },
    };
  }
  get children() { return this.childNodes.filter(node => node.nodeType === 1); }
  get childElementCount() { return this.children.length; }
  get lastElementChild() { return this.children.at(-1) || null; }
  append(...nodes) {
    for (const node of nodes) {
      const child = node instanceof Element || node instanceof TextNode ? node : new TextNode(node);
      if (child instanceof Element) child.parentNode = this;
      this.childNodes.push(child);
    }
  }
  remove() { if (this.parentNode) this.parentNode.childNodes = this.parentNode.childNodes.filter(n => n !== this); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  set textContent(value) { this.childNodes = value === '' || value == null ? [] : [new TextNode(value)]; }
  get textContent() { return this.childNodes.map(n => (n.nodeType === 3 ? n.text : n.textContent)).join(''); }
  matches(selector) {
    const attr = selector.match(/^\[([\w-]+)="([^"]*)"\]$/);
    if (attr) {
      const key = attr[1].replace(/^data-/, '').replace(/-(\w)/g, (_, c) => c.toUpperCase());
      return attr[1].startsWith('data-') ? this.dataset[key] === attr[2] : this.attrs[attr[1]] === attr[2];
    }
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    return this.tag === selector;
  }
  *walk() { for (const child of this.children) { yield child; yield* child.walk(); } }
  querySelector(selector) { for (const el of this.walk()) if (el.matches(selector)) return el; return null; }
  querySelectorAll(selector) { return [...this.walk()].filter(el => el.matches(selector)); }
  get tags() { return [...this.walk()].map(el => el.tag); }
}

function harness() {
  const root = new Element('body');
  const byId = new Map();
  const document = {
    createElement: tag => new Element(tag),
    getElementById(id) {
      if (!byId.has(id)) { const el = new Element('div'); el.attrs.id = id; root.append(el); byId.set(id, el); }
      return byId.get(id);
    },
    querySelector: selector => root.querySelector(selector),
    querySelectorAll: selector => root.querySelectorAll(selector),
  };
  const source = readFileSync(new URL('./workspace.js', import.meta.url), 'utf8')
    .replace(/^import '\.\/[\w-]+\.css';$/gm, '')
    + '\nglobalThis.api={renderMarkdown,renderStage,upsertTask,upsertArtifact,safeUrl,artifactKind,openOverlay,closeOverlay};';
  const context = vm.createContext({
    document, WebSocket: { OPEN: 1 }, fetch: async () => { throw new Error('offline'); },
    URL, Blob, FormData, console,
  });
  vm.runInContext(source, context);
  return { api: context.api, document, root };
}

const stage = document => document.getElementById('stage');

test('markdown renders headings, emphasis, lists, code and links as real nodes', () => {
  const { api } = harness();
  const md = api.renderMarkdown([
    '# 研究纪要',
    '',
    'Sparkie **确认**了 *两个* 结论，见 `plan.md`。',
    '',
    '- 第一条',
    '  - 嵌套一条',
    '- 第二条',
    '',
    '1. 步骤一',
    '2. 步骤二',
    '',
    '> 引用一句话',
    '',
    '```python',
    'print("hi")',
    '```',
    '',
    '[文档](https://example.com/doc)',
  ].join('\n'));

  assert.equal(md.querySelector('h1').textContent, '研究纪要');
  assert.equal(md.querySelector('strong').textContent, '确认');
  assert.equal(md.querySelector('em').textContent, '两个');
  assert.equal(md.querySelector('code').textContent, 'plan.md');
  const ul = md.querySelector('ul');
  assert.equal(ul.children.length, 2, 'two top-level items');
  // CommonMark nests the sublist inside its parent <li>, never as a <ul> sibling.
  assert.equal(ul.children[0].querySelector('ul').querySelector('li').textContent, '嵌套一条');
  assert.equal(md.querySelector('ol').children.length, 2);
  assert.equal(md.querySelector('blockquote').textContent, '引用一句话');
  const pre = md.querySelector('pre');
  assert.equal(pre.dataset.lang, 'python');
  assert.equal(pre.querySelector('code').textContent, 'print("hi")');
  const anchor = md.querySelector('a');
  assert.equal(anchor.href, 'https://example.com/doc');
  assert.equal(anchor.rel, 'noopener noreferrer');
});

test('markdown never injects markup and drops unsafe link schemes', () => {
  const { api } = harness();
  const md = api.renderMarkdown('<script>alert(1)</script>\n\n[点我](javascript:alert(1))');
  assert.ok(!md.tags.includes('script'), 'raw html stays text');
  assert.ok(md.textContent.includes('<script>alert(1)</script>'));
  assert.equal(md.querySelector('a'), null, 'javascript: is not linkified');
  assert.equal(api.safeUrl('javascript:alert(1)'), null);
  assert.equal(api.safeUrl('data:image/png;base64,AAA', 'image/'), 'data:image/png;base64,AAA');
  assert.equal(api.safeUrl('data:text/html,<script>', 'image/'), null);
});

test('task cards carry a status for every lifecycle event', () => {
  const { api, document } = harness();
  const card = () => document.querySelector('[data-task="t1"]');

  api.upsertTask({ task_id: 't1', instruction: 'research related work', status: 'queued' });
  assert.equal(card().dataset.status, 'queued');
  assert.equal(card().querySelector('small').textContent, '排队中');

  api.upsertTask({ type: 'task.started', task_id: 't1' });
  assert.equal(card().dataset.status, 'running');
  assert.ok(card().className.includes('status-running'));

  api.upsertTask({ type: 'task.completed', task_id: 't1' });
  assert.equal(card().dataset.status, 'completed');
  assert.equal(card().querySelector('small').textContent, '已完成');

  api.upsertTask({ type: 'task.failed', task_id: 't1', error_type: 'TimeoutError' });
  assert.equal(card().dataset.status, 'failed');
  assert.equal(card().querySelector('small').textContent, '失败 · TimeoutError');
  assert.equal(document.getElementById('task-count').textContent, '1', 'one card, not four');
});

test('stage renders each artifact content shape', () => {
  const { api, document } = harness();
  const body = () => stage(document);

  api.renderStage({ artifact_id: 'a1', title: 'r', content: { markdown: '## 小标题' } });
  assert.equal(body().querySelector('h2').textContent, '小标题');
  assert.equal(body().querySelector('.type-badge').dataset.kind, 'markdown');
  assert.equal(body().querySelector('.stage-actions').children.length, 2, 'markdown → 全屏 + .md');

  api.renderStage({ artifact_id: 'a2', content: { answer: '纯文本回答' } });
  assert.ok(body().querySelector('.stage-md').textContent.includes('纯文本回答'));

  api.renderStage({ artifact_id: 'a3', content: { image: 'https://example.com/x.png', caption: '图' } });
  assert.equal(body().querySelector('img').src, 'https://example.com/x.png');
  assert.equal(body().querySelector('.type-badge').dataset.kind, 'image');
  assert.equal(body().querySelector('.stage-actions').children.length, 3, 'non-markdown → 全屏 + .md + .json');

  api.renderStage({ artifact_id: 'a4', content: { pdf: 'https://example.com/x.pdf' } });
  assert.equal(body().querySelector('iframe').src, 'https://example.com/x.pdf');
  assert.equal(body().querySelector('iframe').getAttribute('sandbox'), null,
    'Chrome refuses to show its PDF viewer inside a sandboxed frame');

  api.renderStage({ artifact_id: 'a5', content: { url: 'https://example.com' } });
  assert.equal(body().querySelector('iframe').src, 'https://example.com');
  assert.equal(body().querySelector('iframe').getAttribute('sandbox'), 'allow-scripts allow-popups allow-forms');
  assert.equal(body().querySelector('.stage-caption').querySelector('a').href, 'https://example.com');

  api.renderStage({ artifact_id: 'a8', content: { markdown_url: 'https://example.com/notes.md' } });
  assert.equal(body().querySelector('.stage-md').textContent, '加载 markdown…');
  assert.equal(body().querySelector('.type-badge').dataset.kind, 'markdown_url');
  assert.equal(body().querySelector('iframe'), null, 'markdown url never goes through an iframe');

  api.renderStage({ artifact_id: 'a6', type: 'demo', content: { rows: [1, 2] } });
  assert.ok(body().querySelector('.stage-json').textContent.includes('"rows"'));
  assert.equal(body().querySelector('.type-badge').dataset.kind, 'demo');

  api.renderStage({ artifact_id: 'a7', content: { image: 'javascript:alert(1)' } });
  assert.equal(body().querySelector('img'), null, 'unsafe image falls back to json');
  assert.ok(body().querySelector('.stage-note'));
});

test('fullscreen overlay shows the artifact and offers a way back', () => {
  const { api, document } = harness();
  const overlay = document.getElementById('artifact-overlay');
  assert.ok(overlay.hidden !== false, 'overlay starts hidden in the page markup');

  api.openOverlay({ artifact_id: 'a9', title: '季度报告', summary: 's',
                    content: { markdown: '## 概览\n\n- 要点一' } });
  assert.equal(overlay.hidden, false);
  const card = document.getElementById('overlay-card');
  assert.equal(card.querySelector('h2').textContent, '季度报告');
  assert.ok(card.textContent.includes('要点一'), 'markdown rendered inside the overlay');

  api.closeOverlay();
  assert.equal(overlay.hidden, true, 'return path hides the overlay');

  api.openOverlay(null);
  assert.equal(overlay.hidden, true, 'empty artifact never opens the overlay');
});

test('artifact list cards get a type badge matching their content', () => {
  const { api, document } = harness();
  api.upsertArtifact({ artifact_id: 'art_1', title: '报告', type: 'report' });
  const card = document.querySelector('[data-artifact="art_1"]');
  assert.equal(card.querySelector('.type-badge').dataset.kind, 'report');
  assert.equal(card.querySelector('small').textContent, 'art_1');

  api.upsertArtifact({ artifact_id: 'art_2', content: { pdf: 'https://example.com/a.pdf' } });
  assert.equal(document.querySelector('[data-artifact="art_2"]').querySelector('.type-badge').dataset.kind, 'pdf');
  assert.equal(api.artifactKind({ type: 'artifact.ready', content: { url: 'https://x.dev' } }), 'url');
});
