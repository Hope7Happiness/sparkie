"""Snapshot explicitly declared worker documents; never read paths from socket messages."""
import json
import os
from pathlib import Path
import re
import stat


ARTIFACT_INSTRUCTIONS = (
    '\nIf you create or update a Markdown document as the task deliverable, append '
    'one fenced block with language sparkie-artifact to your final response, containing '
    'JSON {"path": "/absolute/path/to/document.md"}. Declare only the primary document '
    'you actually produced for this request, never input/reference files. Keep the '
    'completion summary outside this block. Save presentable Markdown deliverables '
    'in the project workspace or the user Desktop. If no file is produced, return '
    'the answer itself. Do not create a wrapper document describing another file.\n'
)
_DECLARATION = re.compile(r'^```sparkie-artifact[ \t]*\n(.*?)^```[ \t]*$', re.M | re.S)
MAX_DOCUMENT_BYTES = 128 * 1024


def materialize_result(result, workspace):
    """Return summary plus optional artifact/error. Plain answers stay compatible."""
    matches = list(_DECLARATION.finditer(result))
    if not matches:
        if '```sparkie-artifact' in result:
            return {'result': result, 'artifact_error': 'invalid_artifact_declaration'}
        return {'result': result}
    summary = _DECLARATION.sub('', result).strip()
    if len(matches) != 1:
        return {'result': summary, 'artifact_error': 'expected_one_primary_document'}
    try:
        declaration = json.loads(matches[0].group(1))
        raw_path = declaration['path']
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError('invalid_document_path')
        root = Path(workspace).resolve()
        path = Path(raw_path).expanduser()
        path = (root / path).resolve()
        if not any(path.is_relative_to(allowed) for allowed in (root, (Path.home() / 'Desktop').resolve())):
            raise ValueError('document_outside_output_roots')
        if path.suffix.lower() not in ('.md', '.markdown'):
            raise ValueError('unsupported_document_type')
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('document_not_regular_file')
            data = stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            raise ValueError('document_too_large')
        markdown = data.decode('utf-8')
        if not markdown.strip():
            raise ValueError('document_empty')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        error = str(exc) if type(exc) is ValueError else type(exc).__name__
        return {'result': summary, 'artifact_error': error}
    return {'result': summary, 'artifact': {
        'content': {'markdown': markdown}, 'source_path': str(path)}}
