import base64

from odoo import http
from odoo.http import request
from odoo.addons.website_slides.controllers.main import WebsiteSlides, handle_wslide_error


class WebsiteSlidesHtml(WebsiteSlides):

    @http.route('/slides/slide/<model("slide.slide"):slide>/html_content',
                type='http', auth="public", website=True, sitemap=False,
                handle_params_access_error=handle_wslide_error)
    def slide_get_html_content(self, slide):
        """ Serve a self-contained HTML slide for inline preview.

        Mirrors the access pattern of ``slide_get_pdf_content``. The content is
        served with a sandbox CSP so any embedded scripts run in an opaque origin
        and cannot reach the Odoo session/cookies/storage or the parent page.
        Using the header (rather than only the iframe ``sandbox`` attribute) keeps
        the sandbox effective even though the fullscreen player rebuilds the
        iframe from only the src. """
        if not slide.has_access('read'):
            return request.not_found()
        html_bytes = base64.b64decode(slide.binary_content or b'')
        return request.make_response(html_bytes, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Security-Policy', "sandbox allow-scripts allow-popups allow-forms"),
            ('X-Content-Type-Options', 'nosniff'),
        ])
