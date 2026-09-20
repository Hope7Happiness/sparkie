/* Local presentation state: a slide contains one or more deliberately paced beats. */
(() => {
  'use strict';
  const data = window.SPARKIE_DECK, story = window.SPARKIE_STORY;
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const params = new URLSearchParams(location.search);
  const presenter = params.has('presenter'), preview = params.has('preview');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (n, max) => Math.max(0, Math.min(max, n));
  const number = (n) => String(n + 1).padStart(2, '0');
  function normalize(slide, beat = 0) {
    const s = clamp(Number.isInteger(slide) ? slide : 0, data.slides.length - 1);
    return {slide: s, beat: clamp(Number.isInteger(beat) ? beat : 0, story.counts[s] - 1)};
  }
  function readHash() {
    const match = location.hash.match(/^#(\d{1,2})(?:[/.](\d+))?$/);
    return match ? normalize(Number(match[1]) - 1, Number(match[2] || 1) - 1) : normalize(0);
  }
  const hashFor = (state) => '#' + number(state.slide) + (state.beat ? '/' + (state.beat + 1) : '');
  let state = readHash(), speakerWindow, transition, demoPlayer;
  let running = false, accumulated = 0, started = 0;
  const elapsed = () => accumulated + (running ? performance.now() - started : 0);
  const formatTime = (ms) => String(Math.floor(ms / 60000)).padStart(2, '0') + ':' + String(Math.floor(ms / 1000 % 60)).padStart(2, '0');
  function renderTimer() {
    const timer = presenter ? $('#presenter-timer') : $('#talk-timer');
    if (timer) timer.textContent = formatTime(elapsed());
    if ($('#timer-toggle')) $('#timer-toggle').textContent = running ? 'Pause timer' : 'Start timer';
  }
  function toggleTimer() {
    if (running) accumulated = elapsed(); else started = performance.now();
    running = !running;
    if ($('#talk-timer')) $('#talk-timer').hidden = false;
    renderTimer();
  }
  setInterval(renderTimer, 250);
  function send(target, message) {
    if (target && !target.closed) target.postMessage({app: 'sparkie-deck', ...message}, '*');
  }
  function syncSpeaker() { send(speakerWindow, {type: 'state', ...state}); }
  function go(slide, beat = 0, options = {}) {
    const next = normalize(slide, beat), old = state;
    const changedSlide = next.slide !== old.slide, changedBeat = next.beat !== old.beat;
    state = next;
    if (options.history !== false && location.hash !== hashFor(state)) history.pushState(null, '', hashFor(state));
    if (presenter) {
      renderPresenter();
      if (!options.remote) send(window.opener, {type: 'navigate', ...state});
    } else {
      if (changedSlide && document.startViewTransition && !reduced.matches && !preview) {
        if (transition) transition.skipTransition();
        transition = document.startViewTransition(() => renderSlide(true));
        transition.ready.catch(() => {}); transition.finished.catch(() => {});
      } else {
        if (transition) transition.skipTransition();
        renderSlide(changedSlide);
        if (changedBeat && !changedSlide) animateBeat(old.beat);
      }
      syncSpeaker();
    }
  }
  function advance(direction) {
    if (direction > 0) {
      if (state.beat + 1 < story.counts[state.slide]) go(state.slide, state.beat + 1);
      else if (state.slide + 1 < data.slides.length) go(state.slide + 1);
    } else if (state.beat > 0) go(state.slide, state.beat - 1);
    else if (state.slide > 0) go(state.slide - 1, story.counts[state.slide - 1] - 1);
  }
  function historyChanged() {
    const next = readHash();
    if (next.slide !== state.slide || next.beat !== state.beat) go(next.slide, next.beat, {history: false});
  }
  addEventListener('hashchange', historyChanged); addEventListener('popstate', historyChanged);
  addEventListener('message', (event) => {
    const message = event.data;
    if (!message || message.app !== 'sparkie-deck') return;
    if (presenter && event.source === window.opener && message.type === 'state' && Number.isInteger(message.slide) && Number.isInteger(message.beat)) {
      history.replaceState(null, '', hashFor(normalize(message.slide, message.beat)));
      go(message.slide, message.beat, {history: false, remote: true});
    } else if (!presenter && event.source === speakerWindow) {
      if (message.type === 'ready') syncSpeaker();
      if (message.type === 'navigate' && Number.isInteger(message.slide) && Number.isInteger(message.beat)) go(message.slide, message.beat);
    }
  });
  function renderPresenter() {
    const slide = data.slides[state.slide];
    $('#speaker-title').textContent = slide.title;
    $('#speaker-notes').textContent = slide.notes; $('#speaker-cue').textContent = slide.cue;
    $('#speaker-time').textContent = 'SLIDE ' + number(state.slide) + ' · ' + slide.seconds + ' SECONDS';
    $('#speaker-count').textContent = number(state.slide) + ' / 10';
    $('#speaker-beat').textContent = 'Item ' + (state.beat + 1) + ' of ' + story.counts[state.slide];
    $('#speaker-next').textContent = state.beat + 1 < story.counts[state.slide] ? 'Next: reveal item ' + (state.beat + 2) + ' on this slide.' : state.slide < 9 ? 'Next slide: ' + data.slides[state.slide + 1].title : 'End of the presentation.';
    $('#speaker-previous').disabled = state.slide === 0 && state.beat === 0;
    $('#speaker-forward').disabled = state.slide === 9 && state.beat === story.counts[9] - 1;
    const frame = $('#speaker-frame'), url = new URL('index.html', location.href);
    url.search = '?preview=1'; url.hash = hashFor(state);
    if (frame.getAttribute('src') !== url.href) frame.src = url.href;
  }
  function setText(selector, text) { $(selector).textContent = text; }
  function setImage(selector, src, fallback) {
    const node = $(selector);
    if (node.getAttribute('src') === src) return;
    node.onerror = fallback ? () => { node.onerror = null; node.src = fallback; } : null;
    node.src = src;
  }
  function renderBeat() {
    const {slide, beat} = state;
    $$('.slide')[slide].dataset.beat = beat;
    $$('[data-slide][data-beat]').forEach((button) => {
      const selected = Number(button.dataset.slide) === slide && (slide === 3 ? Math.floor(Number(button.dataset.beat) / 3) === Math.floor(beat / 3) : Number(button.dataset.beat) === beat);
      button.setAttribute('aria-pressed', String(selected));
    });
    if (slide === 2) {
      const product = story.market[beat];
      $('#product-link').href = product.url;
      setImage('#product-image', product.image, product.fallback); setImage('#product-icon', product.icon);
      $('#product-image').alt = beat === 3 ? 'Editorial collaboration photograph, illustrating Sparkie’s focus.' : product.name + ' official website or official product image.';
      setText('#product-name', product.name);
      setText('#product-solves-label', product.solvesLabel || 'They deliver');
      setText('#product-gap-label', product.gapLabel || 'Still missing');
      setText('#product-focus-label', product.focusLabel || 'Sparkie closes the gap');
      setText('#product-strength', product.strength);
      setText('#product-tradeoff', product.tradeoff); setText('#product-focus', product.focus);
    } else if (slide === 3) {
      const scene = story.inspiration[Math.floor(beat / 3)], turn = beat % 3;
      setImage('#inspiration-image', scene.image); setText('#title-04', scene.title); setText('#inspiration-context', scene.scene);
      const list = $('#inspiration-dialogue');
      // Stable nodes make each newly revealed dialogue turn animate independently.
      if (list.dataset.scene !== String(Math.floor(beat / 3))) {
        list.replaceChildren(); list.dataset.scene = Math.floor(beat / 3);
        scene.lines.forEach((line, i) => {
          const row = document.createElement('div'); row.className = 'dialogue-line';
          const role = document.createElement('span'); role.textContent = scene.roles[i];
          const quote = document.createElement('p'); quote.textContent = line; row.append(role, quote); list.append(row);
        });
      }
      [...list.children].forEach((row, i) => { row.classList.toggle('is-revealed', i <= turn); row.setAttribute('aria-hidden', String(i > turn)); });
      setText('#inspiration-result', scene.result); $('#inspiration-result').classList.toggle('is-revealed', turn === 2);
      $('#inspiration-result').setAttribute('aria-hidden', String(turn !== 2));
    } else if (slide === 5) {
      const step = story.rhythm[beat]; setText('#rhythm-title', step.title); setText('#rhythm-detail', step.detail);
      setText('#flow-voice', step.voice); setText('#flow-worker', step.worker);
    } else if (slide === 6) {
      const step = story.conversation[beat]; setText('#conversation-role', step.role); setText('#conversation-line', step.line);
      setText('#conversation-response', step.response); setText('#conversation-detail', step.detail);
    } else if (slide === 7) {
      setText('#architecture-title', story.architecture[beat].title); setText('#architecture-detail', story.architecture[beat].detail);
    } else if (slide === 8) {
      const item = story.cases[beat]; setText('#case-status', item.status); setText('#case-context', item.context);
      setText('#case-request', item.request); setText('#case-review', item.review); setText('#case-filename', item.filename);
      setText('#case-artifact-label', item.artifactLabel); $('#case-evidence').href = item.evidence;
      $('#case-lines').replaceChildren(...item.lines.map((text) => { const p = document.createElement('p'); p.textContent = text; return p; }));
    }
  }
  function animateBeat(previousBeat) {
    if (reduced.matches || preview) return;
    const targets = {2:'.comparison-copy',3:'.dialogue-line.is-revealed:last-child',5:'#slide-06 .build-caption',6:'.conversation-panel blockquote',7:'#slide-08 .build-caption',8:'.case-brief, .case-artifact'};
    if (targets[state.slide]) $$(targets[state.slide]).forEach((node, i) => {
      node.getAnimations().forEach((animation) => animation.cancel());
      node.animate([{opacity:.15,transform:'translateY(20px) rotateX(6deg)'},{opacity:1,transform:'translateY(0) rotateX(0)'}],{duration:650,delay:i*65,easing:'cubic-bezier(.18,.8,.18,1)'});
    });
    if (state.slide === 2 || (state.slide === 3 && Math.floor(previousBeat / 3) !== Math.floor(state.beat / 3))) {
      const photo = state.slide === 2 ? $('#product-image') : $('#inspiration-image');
      photo.getAnimations().forEach((animation) => animation.cancel());
      photo.animate([{clipPath:'inset(0 100% 0 0)',transform:'scale(1.08)'},{clipPath:'inset(0)',transform:'scale(1)'}],{duration:850,easing:'cubic-bezier(.18,.8,.18,1)'});
    }
  }
  function renderSlide(changedSlide) {
    const slides = $$('.slide'), active = slides[state.slide];
    if (document.activeElement.closest('.slide') && !active.contains(document.activeElement)) document.activeElement.blur();
    slides.forEach((slide, i) => {
      slide.classList.toggle('is-active', i === state.slide); slide.classList.remove('is-exiting');
      slide.inert = i !== state.slide; slide.setAttribute('aria-hidden', String(i !== state.slide));
      slide.querySelectorAll('[data-morph]').forEach((node) => { node.style.viewTransitionName = i === state.slide ? node.dataset.morph : 'none'; });
    });
    if (changedSlide) active.scrollTop = 0;
    renderBeat(); document.body.dataset.theme = active.dataset.theme;
    $('#previous').disabled = state.slide === 0 && state.beat === 0;
    $('#next').disabled = state.slide === 9 && state.beat === story.counts[9] - 1;
    setText('#current-slide', number(state.slide)); setText('#chapter-label', data.slides[state.slide].chapter);
    const all = story.counts.reduce((a, b) => a + b, 0), completed = story.counts.slice(0, state.slide).reduce((a, b) => a + b, 0) + state.beat + 1;
    $('#progress-fill').style.width = (completed / all * 100) + '%';
    $('#beat-progress').replaceChildren(...Array.from({length:story.counts[state.slide]}, (_, i) => {
      const dot = document.createElement('i'); dot.classList.toggle('active', i === state.beat); dot.setAttribute('aria-hidden', 'true'); return dot;
    }));
    $('#beat-progress').setAttribute('aria-label', 'Item ' + (state.beat + 1) + ' of ' + story.counts[state.slide]);
    setText('#slide-announcement', 'Slide ' + (state.slide + 1) + ', item ' + (state.beat + 1) + ' of ' + story.counts[state.slide] + '. ' + data.slides[state.slide].title);
    $$('.overview-card').forEach((card, i) => card.setAttribute('aria-current', String(i === state.slide)));
    if (state.slide !== 4) demoPlayer?.pause();
  }
  if (presenter) {
    document.body.dataset.mode = 'presenter'; document.body.dataset.theme = 'light';
    document.body.innerHTML = '<main class="presenter-shell"><header class="presenter-header"><strong>Sparkie / Speaker view</strong><span id="presenter-timer">00:00</span><button id="timer-toggle">Start timer</button></header><section class="presenter-preview"><div class="preview-viewport"><iframe id="speaker-frame" title="Audience slide preview" tabindex="-1"></iframe></div><div class="presenter-nav"><button id="speaker-previous">← Previous item</button><span id="speaker-count"></span><button id="speaker-forward">Next item →</button></div><p class="presenter-next" id="speaker-next"></p></section><section class="presenter-notes"><span class="time-badge" id="speaker-time"></span><h1 id="speaker-title"></h1><p id="speaker-beat" class="presenter-beat"></p><p id="speaker-notes"></p><p class="cue" id="speaker-cue"></p></section></main>';
    $('#speaker-previous').onclick = () => advance(-1); $('#speaker-forward').onclick = () => advance(1);
    $('#timer-toggle').onclick = toggleTimer; renderPresenter();
    const resize = () => { $('#speaker-frame').style.transform = 'scale(' + ($('.preview-viewport').clientWidth / 1280) + ')'; };
    new ResizeObserver(resize).observe($('.preview-viewport')); resize(); send(window.opener, {type:'ready'});
  } else {
    if (preview) document.body.dataset.mode = 'preview';
    data.slides.forEach((slide, i) => {
      const button = document.createElement('button'); button.className = 'overview-card'; button.dataset.theme = $$('.slide')[i].dataset.theme;
      const n = document.createElement('span'); n.textContent = number(i);
      const title = document.createElement('strong'); title.textContent = slide.title;
      button.append(n, title); button.onclick = () => { $('#overview-dialog').close(); go(i); }; $('#overview-grid').append(button);
    });
    data.sources.forEach((source) => {
      const a = document.createElement('a'); a.className = 'source-item'; a.href = source.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      const h = document.createElement('h3'); h.textContent = source.name;
      const p = document.createElement('p'); p.textContent = source.summary;
      const arrow = document.createElement('span'); arrow.textContent = '↗'; a.append(h, p, arrow); $('#source-list').append(a);
    });
    $('#previous').onclick = () => advance(-1); $('#next').onclick = () => advance(1);
    $$('[data-slide][data-beat]').forEach((button) => { button.onclick = () => go(Number(button.dataset.slide), Number(button.dataset.beat)); });
    const open = (id) => { if (!$(id).open) $(id).showModal(); };
    $('#overview-button').onclick = () => open('#overview-dialog'); $('#sources-button').onclick = () => open('#sources-dialog'); $('#help-button').onclick = () => open('#help-dialog');
    $$('[data-close]').forEach((button) => { button.onclick = () => button.closest('dialog').close(); });
    $$('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => {
      if (event.target !== dialog) return;
      const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
    }));
    $('#presenter-button').onclick = () => {
      if (speakerWindow && !speakerWindow.closed) { speakerWindow.focus(); syncSpeaker(); return; }
      const url = new URL('index.html', location.href); url.search = '?presenter=1'; url.hash = hashFor(state);
      speakerWindow = window.open(url.href, 'sparkie-speaker', 'popup,width=1250,height=850');
      if (!speakerWindow) setText('#slide-announcement', 'Allow pop-ups to open speaker view.');
    };
    $('#fullscreen-button').onclick = async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
        else setText('#slide-announcement', 'Use your browser fullscreen command.');
      } catch { setText('#slide-announcement', 'Use your browser fullscreen command.'); }
    };
    const video = $('#demo-video'); let objectURL;
    demoPlayer = window.createSparkieDemoPlayer({video, placeholder:$('#video-placeholder'), error:$('#media-error')});
    const loadVideo = (src) => demoPlayer.load(src);
    $('#choose-video').onclick = $('#replace-video').onclick = () => $('#video-input').click();
    $('#video-input').onchange = (event) => {
      const file = event.target.files[0]; if (!file) return; if (objectURL) URL.revokeObjectURL(objectURL);
      objectURL = URL.createObjectURL(file); loadVideo(objectURL); event.target.value = '';
    };
    const media = window.SPARKIE_MEDIA || {}; if (media.demoVideo) loadVideo(media.demoVideo);
    [['meetingImage','#meeting-image','meeting-placeholder.svg'],['artifactImage','#artifact-image','artifact-placeholder.svg']].forEach(([key, selector, fallback]) => {
      if (!media[key]) return; const img = $(selector);
      img.onerror = () => { img.onerror = null; img.src = 'assets/' + fallback; img.alt = 'Media placeholder.'; if (key === 'artifactImage') setText('#artifact-label', 'File placeholder'); };
      if (key === 'artifactImage') setText('#artifact-label', 'The result.');
      img.src = media[key]; img.alt = key === 'meetingImage' ? 'Real Zoom meeting capture.' : 'Actual generated project artifact.';
    });
    addEventListener('beforeunload', () => { if (objectURL) URL.revokeObjectURL(objectURL); });
    let touch;
    $('#deck').addEventListener('touchstart', (event) => {
      if (event.target.closest('button,a,video,input') || event.touches.length !== 1) { touch = null; return; }
      touch = {x:event.touches[0].clientX,y:event.touches[0].clientY};
    }, {passive:true});
    $('#deck').addEventListener('touchend', (event) => {
      if (!touch) return; const dx = event.changedTouches[0].clientX - touch.x, dy = event.changedTouches[0].clientY - touch.y;
      if (Math.abs(dx) > 65 && Math.abs(dx) > Math.abs(dy) * 1.7) advance(dx < 0 ? 1 : -1); touch = null;
    }, {passive:true});
    renderSlide(false);
    // Local preloading keeps image changes from exposing an empty plane mid-transition.
    [...new Set(story.market.flatMap((p) => [p.image,p.fallback,p.icon]).concat(story.inspiration.map((p) => p.image)))].forEach((src) => { const image = new Image(); image.src = src; });
  }
  document.addEventListener('keydown', (event) => {
    if (preview || event.ctrlKey || event.metaKey || event.altKey || $('dialog[open]')) return;
    if (event.target.closest('input,textarea,select,video,[contenteditable="true"]')) return;
    if (event.target.closest('button,a') && [' ','Enter'].includes(event.key)) return;
    const actions = {
      arrowright:() => advance(1), arrowleft:() => advance(-1), ' ':() => advance(event.shiftKey ? -1 : 1),
      pagedown:() => go(state.slide + 1), pageup:() => go(state.slide - 1), home:() => go(0), end:() => go(9), t:toggleTimer
    };
    if (!presenter) Object.assign(actions,{o:() => $('#overview-button').click(),s:() => $('#sources-button').click(),p:() => $('#presenter-button').click(),f:() => $('#fullscreen-button').click(),'?':() => $('#help-button').click()});
    const action = actions[event.key.toLowerCase()]; if (action) { event.preventDefault(); action(); }
  });
})();
