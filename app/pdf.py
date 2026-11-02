"""Server-side PDFs via WeasyPrint (imported lazily – it is slow to load)."""

from app.templating import templates


def _no_fetch(url: str, *args, **kwargs):
    # Spec: no outbound requests. PDF templates are self-contained; refuse anything else.
    raise ValueError(f"Externe Ressource blockiert: {url}")


def render_pdf(template_name: str, **context) -> bytes:
    from weasyprint import HTML

    html = templates.get_template(template_name).render(**context)
    return HTML(string=html, url_fetcher=_no_fetch).write_pdf()
