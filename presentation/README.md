# Sparkie — the presentation and project homepage

Two standalone English experiences with the same forest-green, warm-paper and amber visual language:

- **[index.html](index.html)** — ten interactive slides, paced for **6:05**, including a 75-second real-demo slot.
- **[home.html](home.html)** — the project homepage, with a scroll-driven meeting-to-artifact sequence, interactive scenarios, a demo slot and repository/setup links.
- **[speaker-notes.md](speaker-notes.md)** — the English speaking outline, per-slide timing, demo cues and Q&A boundaries.
- **[research.md](research.md)** — official market sources, fair competitor positioning, code evidence, scenario boundaries and motion references.

The projected slides keep only large, essential text. Supporting explanations live in the separate speaker view and documents. Circles, the Sparkie mark and artifact panels move between scenes using shared-element View Transitions. The homepage has ordinary scrolling with a sticky illustration that changes state as the story progresses.

## Open locally

No install, build, API keys or network connection are required.

On macOS, from the repository root:

```bash
open presentation/index.html
open presentation/home.html
```

Or serve the folder:

```bash
python3 -m http.server 8088 --directory presentation
```

Open http://localhost:8088/ for the slides or http://localhost:8088/home.html for the homepage. The directory can also be hosted as static files; nothing has been published by this change. To use the homepage as a site's landing page, configure the static host to serve home.html at its root.

## Present

| Control | Action |
| --- | --- |
| Left / Right, Page Up / Page Down | Previous / next slide |
| Space / Shift + Space | Next / previous slide |
| Home / End | First / last slide |
| O | Slide overview |
| S | Official research sources |
| P | Separate speaker window |
| F | Fullscreen, where supported |
| T | Start / pause a rehearsal timer |
| ? | Keyboard guide |
| Horizontal swipe | Navigate on a touch screen |

Arrow controls and toolbar buttons have accessible names and tooltips. Dialogs close with Escape. Controls keep their normal keyboard activation behavior. Slides never advance automatically.

Open speaker view from P or the split-panel toolbar icon, then share only the audience window. The speaker window shows an audience-layout preview, the English script, cues, time allocation and next slide. Navigation synchronizes in both directions. Its rehearsal timer is independent of the optional audience-window timer. If pop-ups are blocked, allow the speaker window, or open index.html?presenter=1 for a standalone rehearsal view.

The interactive scenarios and waveforms are **illustrations**; clicking them does not run an agent, join a meeting, record audio or call a model. The six scenario outputs start with “Imagine.” The landscape shows overlapping focuses; it does not imply that competitors cannot execute work.

## Replace the real-media placeholders

The default recording and artifact images are clearly labelled placeholders. Do not present them as evidence of a successful Zoom interaction.

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

Alternatively, choose a local recording in the demo slot. This creates a temporary browser object URL. Nothing is uploaded, the choice is not stored, and reloading restores the configuration. Use a browser-compatible recording such as H.264 MP4. Leaving the demo slide pauses playback; the homepage pauses it when it leaves the viewport.

Aim for a 60–75 second excerpt showing: **discussion → explicit delegation → actual file → follow-up edit**. Keep the agent's audible response and enough of the real result to assess it. Label shortened waits. A human opens and shares the file. The existing [shooting script](../docs/sparkie-demo-script.html) describes the longer session.

## Edit content and design

- index.html: projected content and slide structure.
- deck-data.js: speaker notes, scene choices and official sources.
- deck.js: navigation, shared-element transitions, speaker view and local media.
- styles.css and stage.css: base layout and the minimal projection layer.
- home.html, home.css and home.js: homepage layout, scroll choreography and interactions.
- assets/: original SVG illustrations and the repository's Sparkie icon.

The notes in deck-data.js power speaker view. Keep speaker-notes.md aligned when changing the talk. Font stacks are local Arial/Helvetica, Georgia and system monospace. There are no CDNs, analytics, external fonts or animation dependencies. External links load only when deliberately opened.

## Verification and limits

Validated in installed Chrome through Playwright, over HTTP and offline file URLs. Checks cover all ten slides, bounds and rapid navigation, hashes, dialogs, scenario controls, speaker-window synchronization, rehearsal timers, a generated local video clip, invalid-media recovery and reduced motion. Homepage checks cover scenario controls, all three scroll states and disclosure content. Layout checks cover 1920×1080, 1440×900, 1280×720, 768×1024 and 390×844.

View Transitions require browser support; other browsers fall back to ordinary slide transitions. Reduced-motion preferences disable the animated choreography. Mobile slides can scroll vertically when needed. Chrome is the tested browser; Safari and Firefox have not been separately verified. The presentation does not establish new backend or real-Zoom behavior, and no core runtime files are changed.
