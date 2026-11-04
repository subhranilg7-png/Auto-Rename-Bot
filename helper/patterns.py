"""
Custom filename patterns written with placeholders, e.g.
    [SubsPlease] * - {episode} ({quality}) *
    * S{season} - {episode} [{quality}]
Compiled to regexes here; the built-in patterns in plugins/file_rename.py stay locked.
"""
import re
import logging

logger = logging.getLogger(__name__)

_custom = []   # [{'id','template','enabled','order','regex'}]

_TOKEN_RE = re.compile(r'(\{season\}|\{episode\}|\{quality\}|\*|\s+)')
_GROUPS = {
    '{season}': r'(?<!\d)(?P<season>\d{1,2})(?!\d)',
    '{episode}': r'(?<!\d)(?P<episode>\d{1,4})(?!\d)',
    '{quality}': r'(?P<quality>\d{3,4}[pP]|[24][kK])',
}


def compile_template(template):
    """Returns compiled regex, or raises ValueError with a plain-language reason."""
    template = (template or '').strip()
    if not template:
        raise ValueError("The pattern is empty.")
    if len(template) > 120:
        raise ValueError("The pattern is too long (max 120 characters).")
    if template.count('{episode}') != 1:
        raise ValueError("The pattern must contain `{episode}` exactly once.")
    for ph in ('{season}', '{quality}'):
        if template.count(ph) > 1:
            raise ValueError(f"`{ph}` can only appear once.")
    leftover = _TOKEN_RE.sub('', template)
    if '{' in leftover or '}' in leftover:
        raise ValueError("Only `{season}`, `{episode}` and `{quality}` can be used in braces.")
    if not leftover.strip():
        raise ValueError("Add some fixed text around the placeholders (e.g. ` - {episode}`), "
                         "otherwise the pattern would match every number.")
    parts = []
    for token in _TOKEN_RE.split(template):
        if not token:
            continue
        if token in _GROUPS:
            parts.append(_GROUPS[token])
        elif token == '*':
            parts.append(r'.*?')
        elif token.isspace():
            parts.append(r'[\s._]+')
        else:
            parts.append(re.escape(token))
    try:
        return re.compile(''.join(parts), re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"The pattern couldn't be compiled: {e}")


def fields_in(template):
    return [f for f in ('season', 'episode', 'quality') if '{' + f + '}' in template]


async def reload_patterns(db):
    global _custom
    docs = await db.patterns_all()
    loaded = []
    for d in docs:
        try:
            loaded.append({'id': d['_id'], 'template': d['template'],
                           'enabled': d.get('enabled', True), 'order': d.get('order', 0),
                           'regex': compile_template(d['template'])})
        except ValueError as e:
            logger.error(f"Skipping broken pattern {d.get('_id')}: {e}")
    _custom = loaded


def match_custom(text):
    """First enabled custom pattern that matches, as a dict, or None."""
    if not text:
        return None
    for p in _custom:
        if not p['enabled']:
            continue
        m = p['regex'].search(text)
        if m:
            groups = m.groupdict()
            quality = groups.get('quality')
            return {
                'season': groups.get('season'), 'episode': groups.get('episode'),
                'quality': quality.lower() if quality else None,
                'pattern_id': p['id'], 'template': p['template'],
            }
    return None
