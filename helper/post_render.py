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


def render_post(fmt, which, season, episode):
    """
    which = 'main' | 'sub'. Formats saved with the new panel keep your Telegram styling
    (stored as HTML, flag main_html/sub_html); older formats keep the R<...>R behaviour.
    """
    raw = fmt['main_post'] if which == 'main' else fmt['sub_post']
    filled = fill(raw, season, episode)
    if fmt.get('main_html' if which == 'main' else 'sub_html'):
        return filled
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
