(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const brandMention = document.querySelector('.brand-mention');
  function renderBrandedText(element, text) {
    const parts = text.split(/\bSparkie\b/g);
    element.replaceChildren();
    parts.forEach((part, index) => {
      if (index) element.append(brandMention.cloneNode(true));
      element.append(document.createTextNode(part));
    });
  }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  if (!reduced.matches && 'IntersectionObserver' in window) {
    document.body.classList.add('motion-ready');
    const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
      if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); }
    }), {threshold: .12});
    document.querySelectorAll('.reveal').forEach((node) => observer.observe(node));
  }
  const steps = [...document.querySelectorAll('.story-step')];
  let pending = false;
  function updateStory() {
    pending = false;
    const middle = innerHeight * .43;
    let nearest = 0, distance = Infinity;
    steps.forEach((step, i) => {
      const rect = step.getBoundingClientRect();
      const d = Math.abs(rect.top + rect.height * .35 - middle);
      if (d < distance) { distance = d; nearest = i; }
    });
    $('.story-visual').dataset.state = nearest;
  }
  addEventListener('scroll', () => { if (!pending) { pending = true; requestAnimationFrame(updateStory); } }, {passive:true});
  addEventListener('resize', updateStory); updateStory();
  $('.hero').addEventListener('pointermove', (event) => {
    if (reduced.matches || event.pointerType !== 'mouse') return;
    const box = $('.hero').getBoundingClientRect();
    $('.hero-universe').style.setProperty('--tilt-x', ((event.clientX / box.width - .5) * 8) + 'deg');
    $('.hero-universe').style.setProperty('--tilt-y', (-(event.clientY - box.top) / box.height * 5) + 'deg');
  });
  $('.hero').addEventListener('pointerleave', () => {
    $('.hero-universe').style.setProperty('--tilt-x', '0deg'); $('.hero-universe').style.setProperty('--tilt-y', '0deg');
  });
  document.querySelectorAll('.room-picker button').forEach((button) => button.addEventListener('click', () => {
    document.querySelectorAll('.room-picker button').forEach((other) => other.setAttribute('aria-pressed', String(other === button)));
    const room = window.SPARKIE_DECK.rooms[Number(button.dataset.room)];
    $('.possibility-stage').dataset.room = button.dataset.room;
    renderBrandedText($('#home-room-prompt'), room.prompt); $('#home-room-output').textContent = room.output;
    if (!reduced.matches) $('.possibility-copy').animate([{opacity:.2,transform:'translateY(12px)'},{opacity:1,transform:'translateY(0)'}],{duration:450,easing:'ease-out'});
  }));
  const video = $('#home-video'); let objectURL;
  const loadVideo = (src) => { $('#home-media-error').hidden = true; $('#home-demo-placeholder').hidden = true; video.hidden = false; video.src = src; video.load(); };
  $('#home-choose-video').onclick = () => $('#home-video-input').click();
  $('#home-video-input').onchange = (event) => {
    const file = event.target.files[0]; if (!file) return;
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = URL.createObjectURL(file); loadVideo(objectURL); event.target.value = '';
  };
  video.addEventListener('error', () => {
    video.hidden = true; $('#home-demo-placeholder').hidden = false;
    $('#home-media-error').textContent = 'Could not play this recording. Try an H.264 MP4 file.'; $('#home-media-error').hidden = false;
  });
  if (window.SPARKIE_MEDIA.demoVideo) loadVideo(window.SPARKIE_MEDIA.demoVideo);
  if ('IntersectionObserver' in window) new IntersectionObserver((entries) => {
    if (!entries[0].isIntersecting) video.pause();
  }, {threshold:.1}).observe(video);
  addEventListener('pagehide', () => video.pause());
  addEventListener('beforeunload', () => { if (objectURL) URL.revokeObjectURL(objectURL); });
})();
