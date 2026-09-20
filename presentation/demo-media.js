/* Shared player for a YouTube demo or a local recording. */
(() => {
  'use strict';
  window.createSparkieDemoPlayer = ({video, placeholder, error}) => {
    const host = document.createElement('div');
    host.className = 'youtube-demo'; host.hidden = true;
    video.after(host);
    let youtubeId = null, iframe = null;
    const youtubeID = (source) => {
      try {
        const url = new URL(source);
        const path = url.pathname.split('/');
        const id = url.hostname === 'youtu.be' ? url.pathname.slice(1) :
          ['youtube.com', 'www.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname) ?
            (url.searchParams.get('v') || (['embed', 'shorts'].includes(path[1]) ? path[2] : null)) : null;
        return /^[A-Za-z0-9_-]{11}$/.test(id || '') ? id : null;
      } catch { return null; }
    };
    function cover() {
      host.replaceChildren(); iframe = null;
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'youtube-demo-play';
      button.setAttribute('aria-label', 'Play the Sparkie demo video');
      const mark = document.createElement('span'); mark.className = 'youtube-play-mark';
      mark.textContent = '▶'; mark.setAttribute('aria-hidden', 'true');
      const label = document.createElement('strong'); label.textContent = 'Watch Sparkie in action';
      button.append(mark, label);
      button.onclick = () => {
        iframe = document.createElement('iframe');
        iframe.title = 'Sparkie — real Zoom demo';
        iframe.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
        iframe.allowFullscreen = true;
        iframe.referrerPolicy = 'strict-origin-when-cross-origin';
        iframe.src = 'https://www.youtube-nocookie.com/embed/' + youtubeId + '?autoplay=1&rel=0';
        button.replaceWith(iframe);
        iframe.focus();
      };
      const link = document.createElement('a');
      link.className = 'youtube-demo-link'; link.textContent = 'Open on YouTube ↗';
      link.href = 'https://youtu.be/' + youtubeId; link.target = '_blank'; link.rel = 'noopener noreferrer';
      host.append(button, link);
    }
    function pause() {
      video.pause();
      // Remove the embed to stop audio even if the player cannot receive API commands.
      // Returning to the slide shows the play cover again; YouTube restarts on play.
      if (iframe) cover();
    }
    function load(source) {
      pause(); youtubeId = youtubeID(source);
      error.hidden = true; placeholder.hidden = true;
      video.hidden = Boolean(youtubeId); host.hidden = !youtubeId;
      if (youtubeId) {
        video.removeAttribute('src'); video.load(); cover();
      } else {
        host.replaceChildren(); video.src = source; video.load();
      }
    }
    video.addEventListener('error', () => {
      if (youtubeId) return;
      video.hidden = true; placeholder.hidden = false;
      error.textContent = 'Could not play this recording. Try an H.264 MP4 file.';
      error.hidden = false;
    });
    addEventListener('pagehide', pause);
    return {load, pause};
  };
})();
