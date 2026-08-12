{
    'name': "Samalink eLearning - HTML Document Preview",
    'summary': "Upload and preview self-contained HTML files as eLearning course material",
    'description': """
Samalink eLearning - HTML Document Preview
==========================================

Lets instructors upload a self-contained ``.html`` file as course content
(Document category) and have it rendered/previewed inline in the course player,
the same way PDFs are previewed - instead of being a plain download link.

The HTML is served inside a sandboxed iframe context (enforced server-side via a
``Content-Security-Policy: sandbox`` response header) so embedded scripts cannot
reach the Odoo session, cookies or storage.

Only single, self-contained HTML files (inline CSS/JS) are supported.
""",
    'version': '18.0.1.0.3',
    'author': 'Samalink',
    'website': 'https://edara.digital',
    'license': 'LGPL-3',
    'category': 'Website/eLearning',
    'depends': ['website_slides'],
    'data': [],
    'assets': {
        'web.assets_frontend': [
            'sl_elearning_html/static/src/js/slide_upload_category_patch.js',
        ],
    },
    'installable': True,
    'application': False,
}
