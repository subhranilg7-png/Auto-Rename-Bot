"""Rendering of Main/Sub post text for a saved format."""
import re
import html


def fill(template, season, episode):
    return (template
            .replace('{season}', str(season) if season else 'XX')
            .replace('{episode}', str(episode) if episode else 'XX'))


def render_bold(text):
    """Old style: everything bold except text wrapped in R<...>R."""
    rendered = ''
    last_end = 0
    for match in re.finditer(r'R<(.*?)>R', text, flags=re.DOTALL):
        bold_part = text[last_end:match.start()]
        if bold_part:
            rendered += f'<b>{html.escape(bold_part)}</b>'
        normal_part = match.group(1)
        if normal_part:
            rendered += html.escape(normal_part)
        last_end = match.end()
    tail = text[last_end:]
    if tail:
        rendered += f'<b>{html.escape(tail)}</b>'
    return rendered


from html.parser import HTMLParser

_ALLOWED_TAGS = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'a',
                 'code', 'pre', 'tg-spoiler', 'blockquote'}


class _TagCheck(HTMLParser):
    """Collects whether the text uses Telegram HTML tags and whether they are properly nested."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack, self.tags, self.ok = [], 0, True

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED_TAGS:
            self.ok = False
            return
        self.tags += 1
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag not in _ALLOWED_TAGS or not self.stack or self.stack[-1] != tag:
            self.ok = False
            return
        self.stack.pop()


def looks_like_html(text):
    """True when the text contains Telegram HTML tags and they are balanced."""
    checker = _TagCheck()
    try:
        checker.feed(text)
        checker.close()
    except Exception:
        return False
    return checker.tags > 0 and checker.ok and not checker.stack


_BARE_AMP = re.compile(r'&(?!(?:amp|lt|gt|quot|#\d+);)')


def render_post(fmt, which, season, episode):
    """
    which = 'main' | 'sub'. Formats saved with the new panel keep your Telegram styling
    (stored as HTML, flag main_html/sub_html); older formats keep the R<...>R behaviour.
    """
    raw = fmt['main_post'] if which == 'main' else fmt['sub_post']
    filled = fill(raw, season, episode)
    if fmt.get('main_html' if which == 'main' else 'sub_html'):
        return filled
    if looks_like_html(filled):
        # Older formats were typed with <b>...</b> (the old wizard said HTML was supported, but
        # the text was escaped, so the tags showed up literally). Render them as the HTML they are.
        return _BARE_AMP.sub('&amp;', filled)
    return render_bold(filled)


PLACEHOLDER_RE = re.compile(r'\{[^{}]*\}')
ALLOWED_POST_PLACEHOLDERS = ('{season}', '{episode}')


def check_post_text(html_text, plain_text):
    """Returns an error string, or None when the post text is fine."""
    for ph in PLACEHOLDER_RE.findall(html_text):
        if '<' in ph:
            return ("A placeholder is split by formatting (e.g. only half of `{episode}` is bold). "
                    "Apply the style to the whole placeholder.")
        if ph not in ALLOWED_POST_PLACEHOLDERS:
            return f"Unknown placeholder `{ph}`. Only `{{season}}` and `{{episode}}` work in posts."
    if len(plain_text) > 1000:
        return (f"That's {len(plain_text)} characters. Telegram limits a photo caption to 1024, "
                "so the post would fail. Please shorten it.")
    return None
