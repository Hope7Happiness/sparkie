# Sparkie — the presentation and project homepage

Two standalone English experiences with the same forest-green, warm-paper and amber visual language:

- **[index.html](index.html)** — ten interactive slides, paced for **6:10**, including a 60-second real-demo slot.
- **[home.html](home.html)** — the project homepage, with a scroll-driven meeting-to-artifact sequence, interactive scenarios, a demo slot and repository/setup links.
- **[speaker-notes.md](speaker-notes.md)** — the English speaking outline, per-slide timing, demo cues and Q&A boundaries.
- **[research.md](research.md)** — official market sources, fair competitor positioning, code evidence, scenario boundaries and motion references.

The revised slides use sourced scene photographs, official product icons and website captures, realistic staged dialogue, and progressively illuminated system diagrams. The projected slides keep large, essential text. Supporting explanations live in the separate speaker view and documents. Circles, the Sparkie mark and artifact panels move between scenes using shared-element View Transitions. The homepage has ordinary scrolling with a sticky illustration that changes state as the story progresses.

## Open locally

No install, build or API keys are required for the slides. The deck runs offline; the embedded YouTube demo requires a network connection.

On macOS, from the repository root:

```bash
open presentation/index.html
open presentation/home.html
```

Or serve the folder:

```bash
python3 -m http.server 8088 --directory presentation
```

Open http://localhost:8088/ for the slides or http://localhost:8088/home.html for the homepage. The interactive deck is published at https://bowenyu066.github.io/sparky/; the project website is https://hope7happiness.github.io/sparky. The directory can also be hosted as static files. To use the homepage as a site's landing page, configure the static host to serve home.html at its root.

## Present

| Control | Action |
| --- | --- |
| Left / Right | Previous / next item, then slide |
| Page Up / Page Down | Skip to previous / next slide |
| Space / Shift + Space | Next / previous item |
| Home / End | First / last slide |
| O | Slide overview |
| S | Official research sources |
| P | Separate speaker window |
| F | Fullscreen, where supported |
| T | Start / pause a rehearsal timer |
| ? | Keyboard guide |
| Horizontal swipe | Previous / next item on a touch screen |

Arrow controls and toolbar buttons have accessible names and tooltips. Dialogs close with Escape. Controls keep their normal keyboard activation behavior. Slides never advance automatically.

Open speaker view from P or the split-panel toolbar icon, then share only the audience window. The speaker window shows an audience-layout preview, the English script, cues, time allocation and next slide. Both slide and item navigation synchronize in both directions. A URL such as index.html#04/5 opens slide 4 at item 5. Browser Back/Forward also restores that item. Its rehearsal timer is independent of the optional audience-window timer. If pop-ups are blocked, allow the speaker window, or open index.html?presenter=1 for a standalone rehearsal view.

The interactive scenarios and waveforms are **illustrations**; clicking them does not run an agent, join a meeting, record audio or call a model. The homepage retains six inspiration choices. The slide deck now separates two contextual inspiration dialogues from three practical playbooks, with documented versus worked-scenario status visible. The landscape shows overlapping focuses; it does not imply that competitors cannot execute work.

## Replace the real-media placeholders

The demo is configured to https://youtu.be/-kOeUK9_kIs. Click Play to load the YouTube player, or use Open on YouTube. Both slides and the local homepage accept a YouTube URL or a local video path. Meeting and artifact stills remain labelled placeholders until replaced.

1. Put a real session recording and a real artifact screenshot in assets/. Use shareable, reviewed media rather than an unreviewed session dump.
2. Edit media-config.js. Example:

```js
window.SPARKIE_MEDIA = {
  demoVideo: 'assets/zoom-demo.mp4',
  meetingImage: 'assets/zoom-still.png',
  artifactImage: 'assets/actual-outline.png'
};
```

3. Reload. Both pages use the configured video. The slides also use the meeting still and artifact screenshot.

Alternatively, choose a local recording in the demo slot. This creates a temporary browser object URL. Nothing is uploaded, the choice is not stored, and reloading restores the configuration. Use a browser-compatible recording such as H.264 MP4. Leaving the demo slide pauses local video and unloads the YouTube player so its audio cannot continue. The homepage does the same when its video leaves the viewport. Returning to a YouTube demo shows its Play cover and starts a new playback when clicked.

Aim for a 60-second excerpt showing: **delegation → real Tasks activity during role discussion → presented outline → confirmed roles → update activity → latest artifact**. Keep the actual agent voice and readable result. Label shortened waits; the excerpt budget is not an execution-time promise. Verify the artifact is from the intended task and that other Zoom participants can see the selected share. If voice presentation fails, Present or manual sharing is a fallback, not proof that voice presentation worked. The [continuous three-person rehearsal script](demo-script.html) describes the longer session and is a self-contained HTML file. Creation and follow-up tasks must return the full Markdown body as well as save the file.

## Edit content and design

- index.html: projected content and slide structure.
- deck-data.js: shared homepage scenarios and official sources.
- story-data.js: current presentation notes, product tradeoffs, dialogues, playbooks and per-slide item counts.
- deck.js: navigation, shared-element transitions, speaker view and local media.
- styles.css, stage.css and story.css: base layout and the minimal projection layer.
- home.html, home.css and home.js: homepage layout, scroll choreography and interactions.
- assets/: official product assets, sourced Pexels photographs, original placeholders and the repository's Sparkie icon. See assets/CREDITS.md for provenance. No image-generation API was called.

The notes in story-data.js power the current speaker view. Keep speaker-notes.md aligned when changing the talk. Font stacks are local Arial/Helvetica, Georgia and system monospace. There are no CDNs, analytics, external fonts or animation dependencies. YouTube loads only after clicking Play; no external player scripts or thumbnails load before that. The direct YouTube link remains available if embedding is blocked.

## Verification and limits

Validated in installed Chrome through Playwright, over HTTP and offline file URLs. Checks cover all ten slides and all 28 item states forward/backward, bounds and rapid navigation, deep links and browser history, dialogs, direct scene controls, product-image loading, speaker-window item synchronization and reduced motion. Local video loading, playback and error recovery are also checked. Homepage checks cover scenario controls, all three scroll states and disclosure content. All item layouts were checked at 1920×1080, 1440×900, 1280×720 and 390×844. Diagram node spacing was also checked at 768×1024; homepage mobile overflow was checked at 390×900.

View Transitions require browser support; other browsers fall back to ordinary slide transitions. Reduced-motion preferences disable the animated choreography. Mobile slides can scroll vertically when needed. Chrome is the tested browser; Safari and Firefox have not been separately verified. The presentation does not establish new backend or real-Zoom behavior, and no core runtime files are changed.

## Publishing the interactive deck

The personal-site repository serves a static copy of this directory from public/sparky/. Its Astro build copies those files to /sparky/ without changing the deck or its relative assets. The directory index is the interactive presentation; home.html remains a separate optional page. Sync the presentation files into that directory before deploying changes to the personal site.
