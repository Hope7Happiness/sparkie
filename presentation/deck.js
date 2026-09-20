/* Standalone presentation. All interactions are local; no backend calls. */
(() => {
  'use strict';
  const data = window.SPARKIE_DECK;
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const params = new URLSearchParams(location.search);
  const presenter = params.has('presenter'), preview = params.has('preview');
  const clamp = (n) => Math.max(0, Math.min(data.slides.length - 1, n));
  const fromHash = () => /^#\d{2}$/.test(location.hash) ? clamp(Number(location.hash.slice(1)) - 1) : 0;
  const number = (n) => String(n + 1).padStart(2, '0');
  const formatTime = (ms) => Math.floor(ms / 60000).toString().padStart(2, '0') + ':' + Math.floor(ms / 1000 % 60).toString().padStart(2, '0');
  let current = fromHash(), speakerWindow = null;
  let running = false, accumulated = 0, started = 0, transition;
  const elapsed = () => accumulated + (running ? performance.now() - started : 0);
  function toggleTimer() {
    if (running) accumulated = elapsed(); else started = performance.now();
    running = !running;
    if ($('#talk-timer')) $('#talk-timer').hidden = false;
    renderTimer();
  }
  function renderTimer() {
    const timer = presenter ? $('#presenter-timer') : $('#talk-timer');
    if (timer) timer.textContent = formatTime(elapsed());
    if ($('#timer-toggle')) $('#timer-toggle').textContent = running ? 'Pause timer' : 'Start timer';
  }
  setInterval(renderTimer, 250);
  function send(target, message) {
    if (target && !target.closed) target.postMessage({app: 'sparkie-deck', ...message}, '*');
  }
  function syncSpeaker() { send(speakerWindow, {type: 'state', index: current}); }
  function go(index, history = true) {
    if (!Number.isInteger(index)) return;
    const next = clamp(index);
    if (presenter && window.opener && !window.opener.closed) send(window.opener, {type: 'navigate', index: next});
    const changed = next !== current;
    current = next;
    if (history && location.hash !== '#' + number(current)) location.hash = number(current);
    if (presenter) renderPresenter();
    else if (changed && document.startViewTransition && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      if (transition) transition.skipTransition();
      transition = document.startViewTransition(() => renderSlide(false));
      transition.ready.catch(() => {});
      transition.finished.catch(() => {});
    } else renderSlide(changed);
    syncSpeaker();
  }
  window.addEventListener('hashchange', () => { if (fromHash() !== current) go(fromHash(), false); });
  window.addEventListener('message', (event) => {
    const message = event.data;
    if (!message || message.app !== 'sparkie-deck') return;
    if (presenter && event.source === window.opener && message.type === 'state' && Number.isInteger(message.index)) {
      current = clamp(message.index);
      window.history.replaceState(null, '', '#' + number(current)); renderPresenter();
    } else if (!presenter && event.source === speakerWindow) {
      if (message.type === 'ready') syncSpeaker();
      if (message.type === 'navigate') go(message.index);
    }
  });
  function renderPresenter() {
    const slide = data.slides[current];
    $('#speaker-title').textContent = slide.title;
    $('#speaker-notes').textContent = slide.notes; $('#speaker-cue').textContent = slide.cue;
    $('#speaker-time').textContent = 'SLIDE ' + number(current) + ' / ' + slide.seconds + ' SECONDS';
    $('#speaker-count').textContent = number(current) + ' / 10';
    $('#speaker-next').textContent = current < 9 ? 'Next: ' + data.slides[current + 1].title : 'End of the presentation.';
    $('#speaker-previous').disabled = current === 0; $('#speaker-forward').disabled = current === 9;
    const frame = $('#speaker-frame'), url = new URL('index.html', location.href);
    url.search = '?preview=1'; url.hash = number(current);
    if (frame.getAttribute('src') !== url.href) frame.src = url.href;
  }
  if (presenter) {
    document.body.dataset.mode = 'presenter'; document.body.dataset.theme = 'light';
    document.body.innerHTML = '<main class="presenter-shell"><header class="presenter-header"><strong>Sparkie / Speaker view</strong><span id="presenter-timer">00:00</span><button id="timer-toggle">Start timer</button></header><section class="presenter-preview"><div class="preview-viewport"><iframe id="speaker-frame" title="Audience slide preview"></iframe></div><div class="presenter-nav"><button id="speaker-previous">← Previous</button><span id="speaker-count"></span><button id="speaker-forward">Next →</button></div><p class="presenter-next" id="speaker-next"></p></section><section class="presenter-notes"><span class="time-badge" id="speaker-time"></span><h1 id="speaker-title"></h1><p id="speaker-notes"></p><p class="cue" id="speaker-cue"></p></section></main>';
    $('#speaker-previous').onclick = () => go(current - 1);
    $('#speaker-forward').onclick = () => go(current + 1);
    $('#timer-toggle').onclick = toggleTimer;
    renderPresenter();
    const resizePreview = () => { $('#speaker-frame').style.transform = 'scale(' + ($('.preview-viewport').clientWidth / 1280) + ')'; };
    new ResizeObserver(resizePreview).observe($('.preview-viewport')); resizePreview();
    send(window.opener, {type: 'ready'});
  } else {
    if (preview) document.body.dataset.mode = 'preview';
    const slides = $$('.slide');
    data.slides.forEach((slide, i) => {
      const button = document.createElement('button');
      button.className = 'overview-card'; button.dataset.theme = slides[i].dataset.theme;
      const count = document.createElement('span'); count.textContent = number(i);
      const title = document.createElement('strong'); title.textContent = slide.title;
      button.append(count, title);
      button.onclick = () => { $('#overview-dialog').close(); go(i); };
      $('#overview-grid').append(button);
    });
    data.sources.forEach((source) => {
      const link = document.createElement('a');
      link.className = 'source-item'; link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      const title = document.createElement('h3'); title.textContent = source.name;
      const detail = document.createElement('p'); detail.textContent = source.summary;
      const arrow = document.createElement('span'); arrow.textContent = '↗';
      link.append(title, detail, arrow); $('#source-list').append(link);
    });
    $('#previous').onclick = () => go(current - 1); $('#next').onclick = () => go(current + 1);
    $$('[data-go]').forEach((button) => { button.onclick = () => go(Number(button.dataset.go)); });
    const open = (id) => { if (!$(id).open) $(id).showModal(); };
    $('#overview-button').onclick = () => open('#overview-dialog');
    $('#sources-button').onclick = () => open('#sources-dialog');
    $('#help-button').onclick = () => open('#help-dialog');
    $$('[data-close]').forEach((button) => { button.onclick = () => button.closest('dialog').close(); });
    $$('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => {
      if (event.target !== dialog) return;
      const r = dialog.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
    }));
    const animate = (node) => { node.classList.remove('is-changing'); void node.offsetWidth; node.classList.add('is-changing'); };
    function bindChoices(selector, key, update) {
      $$(selector).forEach((button) => button.addEventListener('click', () => {
        $$(selector).forEach((other) => { other.classList.toggle('is-selected', other === button); other.setAttribute('aria-pressed', String(other === button)); });
        update(button.dataset[key]);
      }));
    }
    bindChoices('[data-market]', 'market', (i) => { $('#market-insight').textContent = data.market[i]; animate($('#market-insight')); });
    bindChoices('[data-request]', 'request', (i) => {
      $('#request-bubble').textContent = data.requests[i][0]; animate($('#request-bubble'));
    });
    bindChoices('.speech-controls [data-speech]', 'speech', (key) => {
      $('.speech-stage').dataset.speech = key; $('#speech-phrase').textContent = data.speech[key][0];
      animate($('#speech-phrase'));
    });
    bindChoices('.room-list [data-room]', 'room', (i) => {
      const room = data.rooms[i]; $('#room-scene').dataset.room = i;
      $('#room-prompt').textContent = room.prompt;
      $('#room-output').textContent = room.output; animate($('#room-prompt'));
    });
    for (let i = 0; i < 35; i++) {
      const bar = document.createElement('i'); bar.style.setProperty('--i', i);
      bar.style.height = (10 + Math.abs(Math.sin(i * 1.7)) * 75) + 'px'; $('.speech-wave').append(bar);
    }
    $('#presenter-button').onclick = () => {
      if (speakerWindow && !speakerWindow.closed) { speakerWindow.focus(); syncSpeaker(); return; }
      const url = new URL('index.html', location.href); url.search = '?presenter=1'; url.hash = number(current);
      speakerWindow = window.open(url.href, 'sparkie-speaker', 'popup,width=1250,height=850');
      if (!speakerWindow) $('#slide-announcement').textContent = 'Allow pop-ups for this page to open speaker view.';
    };
    $('#fullscreen-button').onclick = async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
        else $('#slide-announcement').textContent = 'Use your browser fullscreen command.';
      } catch { $('#slide-announcement').textContent = 'Use your browser fullscreen command.'; }
    };
    const video = $('#demo-video'); let objectURL;
    function loadVideo(src) {
      video.pause(); $('#media-error').hidden = true; video.hidden = false; $('#video-placeholder').hidden = true;
      video.src = src; video.load();
    }
    video.addEventListener('error', () => {
      video.hidden = true; $('#video-placeholder').hidden = false;
      $('#media-error').textContent = 'This recording could not be played. Choose a browser-compatible video such as H.264 MP4.';
      $('#media-error').hidden = false;
    });
    $('#choose-video').onclick = $('#replace-video').onclick = () => $('#video-input').click();
    $('#video-input').onchange = (event) => {
      const file = event.target.files[0]; if (!file) return;
      if (objectURL) URL.revokeObjectURL(objectURL);
      objectURL = URL.createObjectURL(file); loadVideo(objectURL); event.target.value = '';
    };
    const media = window.SPARKIE_MEDIA || {};
    if (media.demoVideo) loadVideo(media.demoVideo);
    [['meetingImage', '#meeting-image', 'meeting-placeholder.svg'], ['artifactImage', '#artifact-image', 'artifact-placeholder.svg']].forEach(([key, selector, fallback]) => {
      if (!media[key]) return;
      const img = $(selector);
      img.onerror = () => { img.onerror = null; img.src = 'assets/' + fallback; img.alt = 'Media placeholder.'; if (key === 'artifactImage') $('#artifact-label').textContent = 'File placeholder'; };
      if (key === 'artifactImage') $('#artifact-label').textContent = 'The result.';
      img.src = media[key]; img.alt = key === 'meetingImage' ? 'Real Zoom meeting capture.' : 'Actual generated project artifact.';
    });
    window.addEventListener('beforeunload', () => { if (objectURL) URL.revokeObjectURL(objectURL); });
    let touch;
    $('#deck').addEventListener('touchstart', (event) => {
      if (event.target.closest('button,a,video,input') || event.touches.length !== 1) { touch = null; return; }
      touch = {x: event.touches[0].clientX, y: event.touches[0].clientY};
    }, {passive: true});
    $('#deck').addEventListener('touchend', (event) => {
      if (!touch) return;
      const dx = event.changedTouches[0].clientX - touch.x, dy = event.changedTouches[0].clientY - touch.y;
      if (Math.abs(dx) > 65 && Math.abs(dx) > Math.abs(dy) * 1.7) go(current + (dx < 0 ? 1 : -1));
      touch = null;
    }, {passive: true});
    renderSlide(false);
  }
  function renderSlide(changed) {
    const slides = $$('.slide'), focusedSlide = document.activeElement.closest('.slide');
    if (focusedSlide && focusedSlide !== slides[current]) document.activeElement.blur();
    slides.forEach((slide, i) => {
      const wasActive = slide.classList.contains('is-active');
      slide.classList.toggle('is-active', i === current); slide.inert = i !== current;
      slide.setAttribute('aria-hidden', String(i !== current));
      slide.querySelectorAll('[data-morph]').forEach((node) => { node.style.viewTransitionName = i === current ? node.dataset.morph : 'none'; });
      if (i === current) { slide.classList.remove('is-exiting'); if (changed) slide.scrollTop = 0; }
      else if (wasActive && changed) {
        slide.classList.add('is-exiting'); setTimeout(() => slide.classList.remove('is-exiting'), 650);
      }
    });
    document.body.dataset.theme = slides[current].dataset.theme;
    $('#previous').disabled = current === 0; $('#next').disabled = current === 9;
    $('#current-slide').textContent = number(current); $('#chapter-label').textContent = data.slides[current].chapter;
    $('#progress-fill').style.width = ((current + 1) * 10) + '%';
    $('#slide-announcement').textContent = 'Slide ' + (current + 1) + ' of 10. ' + data.slides[current].title;
    $$('.overview-card').forEach((card, i) => card.setAttribute('aria-current', String(i === current)));
    if (current !== 4) $('#demo-video').pause();
  }
  document.addEventListener('keydown', (event) => {
    if (preview || event.ctrlKey || event.metaKey || event.altKey || $('dialog[open]')) return;
    if (event.target.closest('input,textarea,select,video,[contenteditable="true"]')) return;
    if (event.target.closest('button,a') && [' ', 'Enter'].includes(event.key)) return;
    const key = event.key.toLowerCase();
    const actions = {
      arrowright: () => go(current + 1), pagedown: () => go(current + 1),
      ' ': () => go(current + (event.shiftKey ? -1 : 1)),
      arrowleft: () => go(current - 1), pageup: () => go(current - 1),
      home: () => go(0), end: () => go(9), t: toggleTimer
    };
    if (!presenter) Object.assign(actions, {o: () => $('#overview-button').click(), s: () => $('#sources-button').click(), p: () => $('#presenter-button').click(), f: () => $('#fullscreen-button').click(), '?': () => $('#help-button').click()});
    if (actions[key]) { event.preventDefault(); actions[key](); }
  });
})();
