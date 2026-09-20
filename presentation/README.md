# Sparkie — the presentation and project homepage

Two standalone English experiences with the same forest-green, warm-paper and amber visual language:

- **[index.html](index.html)** — ten interactive slides and 24 item states: motivation, competition, product evidence, architecture, limitations and outlook.
- **[home.html](home.html)** — the project homepage, with a scroll-driven meeting-to-artifact sequence, interactive scenarios, a demo slot and repository/setup links.
- **[speaker-notes.md](speaker-notes.md)** — the English speaking outline, demo cues and implementation boundaries.
- **[research.md](research.md)** — official market sources, fair competitor positioning, code evidence, scenario boundaries and motion references.

The revised slides use sourced scene photographs, official product icons and website captures, real product captures, illustrative Gemini routing examples, and progressively illuminated system diagrams. The projected slides keep large, essential text. Supporting explanations live in the separate speaker view and documents. Slide visibility and content update synchronously, with CSS fades and item-level animations. This avoids hidden text when items are selected during slide entry. The homepage pairs text and screenshots vertically on phones, with a sticky screenshot sequence on larger screens.

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

Open http://localhost:8088/ for the slides or http://localhost:8088/home.html for the homepage. The interactive deck is published at https://bowenyu066.github.io/sparkie/; the project website is https://hope7happiness.github.io/sparkie/. The directory can also be hosted as static files. To use the homepage as a site's landing page, configure the static host to serve home.html at its root.

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

Open speaker view from P or the split-panel toolbar icon, then share only the audience window. The speaker window shows an audience-layout preview, the English script, cues, time allocation and next slide. Both slide and item navigation synchronize in both directions. A URL such as index.html#04/4 opens slide 4 at item 4. Browser Back/Forward also restores that item. Its rehearsal timer is independent of the optional audience-window timer. If pop-ups are blocked, allow the speaker window, or open index.html?presenter=1 for a standalone rehearsal view.

The interactive scenarios and waveforms are **illustrations**; clicking them does not run an agent, join a meeting, record audio or call a model. The homepage retains six inspiration choices. The slide deck shows four real frontend views, then the supplied video. Its architecture section separates the system overview, Gemini participation decisions, and asynchronous task execution. The landscape shows overlapping focuses; it does not imply that competitors cannot execute work.

## Narrative order

1. The goal: a teammate with meeting context.
2. Motivation: act on the discussion while the team keeps talking.
3. Competitive context, immediately after motivation.
4. What we built: workspace, transcript, tasks and artifacts.
5. Supplied Zoom demo video.
6. Architecture overview: audio → words / turn completion → router → voice / worker.
7. Main challenge: Gemini decides whether the current turn invites a response.
8. Separate voice and background task execution.
9. Current limitations, including setup that is not one click.
10. Outlook: guided setup, conversation evaluation and recovery, clearer task updates.

On slide 7, Active and Quiet describe the decision for each turn. The router sees the current utterance, speaker identity and up to eight recent conversation entries. It does not grant permanent speaking permission. Illustrative cases cover a third-person mention, a contextual follow-up without a name, and an ambiguous recipient. Speech completion and interruption are separate mechanisms. Speaker notes cite the relevant implementation files.

## Demo media and product captures

The demo is configured to https://youtu.be/-kOeUK9_kIs. Click Play to load the YouTube player, or use Open on YouTube. Both slides and the local homepage accept a YouTube URL or a local video path. The play cover uses the real local voice workspace capture; it is labelled as a product preview, not a Zoom video frame. The adjacent About Sparkie report is from that separate local session and opens at full size when clicked. The Sparkie comparison also uses the real workspace screenshot. Editorial scene photos and conceptual diagrams remain illustrations.

1. Put a real session recording and a real artifact screenshot in assets/. Use shareable, reviewed media rather than an unreviewed session dump.
2. Edit media-config.js. Example:

```js
window.SPARKIE_MEDIA = {
  demoVideo: 'assets/zoom-demo.mp4',
  demoPoster: 'assets/zoom-still.png',
  demoPosterAlt: 'Still from the supplied Zoom recording.',
  demoPosterLabel: 'Zoom recording',
  meetingImage: 'assets/zoom-still.png',
  meetingImageAlt: 'Still from the supplied Zoom recording.',
  artifactImage: 'assets/actual-outline.png',
  artifactImageAlt: 'The outline generated in this recorded session.',
  artifactLabel: 'Outline from this recording',
  artifactTitle: 'Demo outline'
};
```

3. Reload. Both pages use the configured video. The slides also use the meeting still and artifact screenshot.

Alternatively, choose a local recording in the demo slot. This creates a temporary browser object URL. Nothing is uploaded, the choice is not stored, and reloading restores the configuration. Use a browser-compatible recording such as H.264 MP4. Leaving the demo slide pauses local video and unloads the YouTube player so its audio cannot continue. The homepage does the same when its video leaves the viewport. Returning to a YouTube demo shows its Play cover and starts a new playback when clicked.

Aim for a 60-second excerpt showing: **delegation → real Tasks activity during role discussion → presented outline → confirmed roles → update activity → latest artifact**. Keep the actual agent voice and readable result. Label shortened waits; the excerpt budget is not an execution-time promise. Verify the artifact is from the intended task and that other Zoom participants can see the selected share. If voice presentation fails, Present or manual sharing is a fallback, not proof that voice presentation worked. The [continuous three-person rehearsal script](demo-script.html) describes the longer session and is a self-contained HTML file. Creation and follow-up tasks must return the full Markdown body as well as save the file.

## Edit content and design

- index.html: projected content and slide structure.
- deck-data.js: shared homepage scenarios and official sources.
- story-data.js: current presentation notes, product tradeoffs, product captures, routing examples and per-slide item counts.
- deck.js: navigation, shared-element transitions, speaker view and local media.
- styles.css, stage.css, story.css and narrative.css: base layout, diagrams and the current narrative pages.
- home.html, home.css and home.js: homepage layout, scroll choreography and interactions.
- assets/: official product assets, sourced Pexels photographs, original placeholders and the repository's Sparkie icon. See assets/CREDITS.md for provenance. No image-generation API was called.

The notes in story-data.js power the current speaker view. Keep speaker-notes.md aligned when changing the talk. Font stacks are local Arial/Helvetica, Georgia and system monospace. There are no CDNs, analytics, external fonts or animation dependencies. YouTube loads only after clicking Play; no external player scripts or thumbnails load before that. The direct YouTube link remains available if embedding is blocked.

## Verification and limits

The current deck was checked in Chrome at 1440×900, 1280×720, 768×1024 and 390×844. Checks cover all ten slides and 24 item states, product screenshot loading and enlargement, all three Gemini examples, speaker notes and two-way speaker navigation, and video removal on slide exit. Desktop layouts fit without vertical scrolling; phone slides can scroll. Offline checks confirm that product assets remain local; inserting the requested YouTube embed is checked without claiming successful network playback.

Reduced-motion preferences disable the animated choreography. Navigation does not depend on asynchronous View Transition snapshots. Mobile slides can scroll vertically when needed. Chrome is the tested browser; Safari and Firefox have not been separately verified. The presentation does not establish new backend or real-Zoom behavior, and no core runtime files are changed.

## Publishing the interactive deck

Maintain the interactive presentation in this repository under presentation/. Do not copy it into ../personal_website. That repository hosts the separate standalone product homepage at /sparkie/. The deck can be served locally with the command above; publishing it elsewhere is a separate step.

The old /sparky/ address redirects to /sparkie/ and preserves the slide hash and speaker-view query parameters.
