"""Small explicit desktop actions that do not need a second model round trip."""
import asyncio
from pathlib import Path
import shutil
import sys
from urllib.parse import unquote, urlsplit, urlunsplit


async def run_local_action(action, arguments):
    if action == 'create_desktop_file':
        filename, content = arguments.get('filename'), arguments.get('content')
        if (not isinstance(filename, str) or not filename.strip() or filename in ('.', '..') or
                '/' in filename or '\\' in filename or '\x00' in filename or
                not isinstance(content, str) or len(content.encode()) > 1_000_000):
            raise ValueError('invalid_file_request')
        target = Path.home() / 'Desktop' / filename
        def create():
            # Exclusive creation: a repeated voice request cannot overwrite a user's file.
            with target.open('x', encoding='utf-8') as stream:
                stream.write(content)
            if target.read_text(encoding='utf-8') != content:
                raise OSError('file_verification_failed')
            return f'Created and verified {target} ({len(content.encode())} bytes).'
        return await asyncio.to_thread(create)
    if action == 'open_website':
        url = arguments.get('url')
        if (not isinstance(url, str) or len(url) > 8192
                or any(ord(char) < 32 or ord(char) == 127 for char in url)):
            raise ValueError('invalid_url')
        parsed = urlsplit(url)
        if parsed.scheme == 'file':
            if parsed.netloc not in ('', 'localhost'):
                raise ValueError('invalid_local_html_url')
            filename = unquote(parsed.path, errors='strict')
            target = Path(filename)
            if '\x00' in filename or not target.is_absolute() or target.suffix.lower() not in ('.html', '.htm'):
                raise ValueError('invalid_local_html_url')
            target = target.resolve()
            if target.suffix.lower() not in ('.html', '.htm'):
                raise ValueError('invalid_local_html_url')
            if not target.is_file():
                raise FileNotFoundError('local_html_not_found')
            local = urlsplit(target.as_uri())
            url = urlunsplit((local.scheme, local.netloc, local.path, parsed.query, parsed.fragment))
        elif parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('invalid_url')
        launcher = 'open' if sys.platform == 'darwin' else 'xdg-open'
        executable = shutil.which(launcher)
        if not executable:
            raise OSError('browser_launcher_unavailable')
        process = await asyncio.create_subprocess_exec(executable, url,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            code = await process.wait()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            raise
        if code:
            raise OSError('browser_launcher_failed')
        return f'The system launcher accepted the request to open {url}. Page loading was not independently verified.'
    raise ValueError('unknown_local_action')
