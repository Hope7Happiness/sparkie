# Image provenance

Retrieved September 20, 2026. Assets are saved locally so the presentation remains offline-capable.

## Editorial scene photographs

| Local file | Source photograph | Use |
| --- | --- | --- |
| scenes/meeting.jpg | [Pexels photo 3183150](https://www.pexels.com/photo/3183150/) | Meeting atmosphere, customer-call inspiration, opening image |
| scenes/planning.jpg | [Pexels photo 3184325](https://www.pexels.com/photo/3184325/) | Planning and product-decision inspiration |
| scenes/collaboration.jpg | [Pexels photo 3184357](https://www.pexels.com/photo/3184357/) | Collaboration, participation and closing image |

These images are distributed by Pexels under the [Pexels License](https://www.pexels.com/license/). Consult the linked photo pages for contributor attribution. Download URLs and sizes are recorded in [scenes/sources.json](scenes/sources.json). They are editorial illustrations: the people are not presented as Sparkie users, team members or endorsers, and the photos are not real Sparkie session evidence.

## Product comparison assets

Granola, Vapi and Zoom icons and social/product images were downloaded from their official sites. Exact asset URLs, formats and sizes are recorded in [market/sources.json](market/sources.json).

The corresponding website captures were taken in Chrome at 1440×960:

- market/granola-website.jpg — https://www.granola.ai/
- market/vapi-website.jpg — https://vapi.ai/
- market/zoom-website.jpg — https://www.zoom.com/en/products/ai-assistant/

These are screenshots of public product websites, not screenshots of independently tested product sessions. Each comparison links to the original product page. Product names, marks and screenshots remain associated with their respective owners and are used here for identification and comparison.

## Repository art

sparkie-mark.svg uses the presentation’s existing four-point star geometry, with the forest-green and amber brand colors. It is the shared mark for the homepage, presentation and favicons. The older sparkie-icon.png is retained as a legacy asset, reused from docs/assets/sparkie-icon.png in this repository. The original meeting and artifact SVG placeholders remain in the recording slot until replaced by real media.

No AI-generated images are included in this revision. The session did not expose a built-in image-generation tool; following the user's suggestion, the revision uses sourced web photography and official product assets. No image API was called.


## Product interface captures

The homepage uses four captures in product/, taken September 20, 2026 from the
running Sparkie workspace UI and an existing, completed local browser voice
session. They contain actual saved transcript, task and report data. No model
was called to prepare these captures and no task status or transcript text was
fabricated or rewritten for the screenshots.

- product/workspace.webp — workspace overview, cropped below the connection bar.
- product/transcript.webp — transcript panel, scrolled to the report request and responses; cropped above the speech simulation form.
- product/tasks.webp — completed tasks and the artifact catalog from the same session.
- product/report.webp — the saved About Sparkie document in the existing local presentation overlay.

Captured at 1440 × 1100 CSS pixels with device scale 2 and encoded as WebP.
Only viewport selection, scrolling and cropping were used. The connection bar,
server address and workspace ID are outside the published crops. The task
screens show completed work, not an invented in-progress state. These are local
voice product captures, not screenshots of a Zoom meeting or proof that a
remote Zoom participant saw an artifact. Scenario prompts on the homepage
remain illustrative; the adjacent screenshot is labelled as an example report.

The homepage now uses these product captures instead of the editorial photos
and meeting/document placeholders. The slide deck retains its own media slots.
