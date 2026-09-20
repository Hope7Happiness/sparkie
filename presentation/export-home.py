#!/usr/bin/env python3
"""Export the product homepage as one HTML file, without the slide deck.

Usage: python3 presentation/export-home.py ../personal_website/sparkie/index.html
YouTube playback still requires internet. No third-party Python packages needed.
"""
import argparse
import base64
import mimetypes
from pathlib import Path
import re


def export_home(destination: Path) -> None:
    source = Path(__file__).resolve().parent
    html = (source / 'home.html').read_text()
    # The public page has no links to repository-local documents or file picker.
    html = re.sub(r'<a href="research\.md">.*?</a>', '', html)
    html = re.sub(r'<button id="home-choose-video".*?</button>', '', html)
    html = re.sub(r'<input id="home-video-input"[^>]*>', '', html)
    scripts = []

    def inline_style(match: re.Match) -> str:
        return '<style>\n' + (source / match[1]).read_text().replace('@charset "UTF-8";', '') + '\n</style>'

    def collect_script(match: re.Match) -> str:
        code = (source / match[1]).read_text()
        if match[1] == 'deck-data.js':
            # Only the homepage scenarios are used; omit speaker notes and slides.
            rooms = re.search(r'  rooms: (\[.*?\n  \]),\n  sources:', code, re.S)
            if not rooms:
                raise ValueError('Cannot find homepage room scenarios in deck-data.js')
            code = 'window.SPARKIE_DECK = {rooms: ' + rooms[1] + '};'
        scripts.append(code)
        return ''

    html = re.sub(r'<link rel="stylesheet" href="([^"/]+\.css)">', inline_style, html)
    html = re.sub(r'<script src="([^"/]+\.js)" defer></script>', collect_script, html)
    html = html.replace('</body>', '<script>\n' + '\n'.join(scripts) + '\n</script>\n</body>')

    def embed_asset(match: re.Match) -> str:
        relative = match[0]
        asset = source / relative
        if not asset.is_file():
            raise FileNotFoundError(asset)
        mime = mimetypes.guess_type(asset.name)[0] or 'application/octet-stream'
        return 'data:' + mime + ';base64,' + base64.b64encode(asset.read_bytes()).decode('ascii')

    html = re.sub(r'assets/[A-Za-z0-9_./-]+\.(?:webp|svg|png|jpe?g|ico)', embed_asset, html)
    html = html.replace('<html lang="en">', '<html lang="en">\n<!-- Generated from hackmit/presentation/home.html with export-home.py.\nStyles, scripts and product captures are embedded. YouTube playback requires internet. -->')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html)
    print(f'Exported {destination} ({len(html.encode()):,} bytes)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    export_home(parser.parse_args().destination)
