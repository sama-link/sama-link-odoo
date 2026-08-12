import base64

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.http import request


class SlideSlide(models.Model):
    _inherit = 'slide.slide'

    # New document slide type for self-contained HTML files. It stays inside the
    # 'document' slide_category so all the existing list UI / icons / ordering /
    # completion tracking keep working unchanged.
    slide_type = fields.Selection(
        selection_add=[('html', 'HTML Page')],
        # The base slide_type field defines no default, so 'set default' is invalid.
        # slide_type is computed, so clearing it (set null) is safe - it recomputes.
        ondelete={'html': 'set null'},
    )

    def _is_html_document(self):
        """ Sniff whether the uploaded local file is an HTML document.

        The model stores no filename, so we inspect the decoded content. Looking
        at the first bytes is enough for self-contained HTML files.

        ``bin_size=False`` is essential, not defensive: under the ``bin_size``
        context the web client sets on nearly every record read, a binary field
        returns its human-readable SIZE (b'2.72 Kb') instead of its content, the
        decode below fails, and this reports "not HTML". Because slide_type is
        stored, one recompute in such a request permanently demotes the slide to
        the PDF viewer - the file previews until some unrelated read flips it. """
        self.ensure_one()
        content = self.with_context(bin_size=False).binary_content
        if not content:
            return False
        try:
            head = base64.b64decode(content)[:2048].lower()
        except Exception:
            return False
        return b'<!doctype html' in head or b'<html' in head or b'<body' in head

    def init(self):
        """ Heal slides demoted by the bin_size bug described above: they hold
        an HTML file but a stored slide_type pointing at another viewer. """
        super().init()
        stale = self.search([
            ('slide_category', '=', 'document'),
            ('source_type', '=', 'local_file'),
            ('slide_type', '!=', 'html'),
        ]).filtered(lambda slide: slide._is_html_document())
        if stale:
            stale.slide_type = 'html'

    @api.depends('slide_category', 'source_type', 'video_source_type', 'binary_content')
    def _compute_slide_type(self):
        # Re-declare the full original depends set (overriding the method replaces
        # its dependencies) and add 'binary_content' so detection re-runs on upload.
        super()._compute_slide_type()
        for slide in self:
            if (slide.slide_category == 'document'
                    and slide.source_type == 'local_file'
                    and slide._is_html_document()):
                slide.slide_type = 'html'

    @api.depends('slide_category', 'google_drive_id', 'video_source_type', 'youtube_id', 'slide_type')
    def _compute_embed_code(self):
        super()._compute_embed_code()
        request_base_url = request.httprequest.url_root if request else False
        for slide in self:
            if not (slide.slide_type == 'html'
                    and slide.slide_category == 'document'
                    and slide.source_type == 'local_file'):
                continue
            base_url = request_base_url or slide.get_base_url()
            if base_url and base_url[-1] == '/':
                base_url = base_url[:-1]
            slide_url = base_url + self.env['ir.http']._url_for('/slides/slide/%s/html_content' % slide.id)
            # The fullscreen player rebuilds the iframe from only the src, so the
            # sandbox is also enforced server-side via a CSP header on the route.
            # The sandbox attribute here still applies on the non-fullscreen
            # detail page where the raw embed_code is injected.
            embed_code = Markup(
                '<iframe src="%s" class="o_wslides_iframe_viewer" '
                'sandbox="allow-scripts allow-popups allow-forms" '
                'allowFullScreen="true" height="%s" width="%s" frameborder="0" '
                'aria-label="%s"></iframe>'
            ) % (slide_url, 315, 420, _('HTML content'))
            slide.embed_code = embed_code
            slide.embed_code_external = embed_code
