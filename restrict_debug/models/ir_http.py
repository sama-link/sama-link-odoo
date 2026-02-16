<<<<<<< HEAD
from odoo import models
from odoo.http import request

class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _handle_debug(cls):
        user = request.env.user
        if not user:
            user_id = request.session.uid
            user = request.env['res.users'].sudo().search([('id', '=', user_id)], limit=1)
        if user.has_group("base.group_system"):
            return super(IrHttp, cls)._handle_debug()
        else:
            request.session.debug = ''
=======
from odoo import models
from odoo.http import request

class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _handle_debug(cls):
        user = request.env.user
        if not user:
            user_id = request.session.uid
            user = request.env['res.users'].sudo().search([('id', '=', user_id)], limit=1)
        if user.has_group("base.group_system"):
            return super(IrHttp, cls)._handle_debug()
        else:
            request.session.debug = ''
>>>>>>> 4717772238b15978793a2220ea43cb98d4ca4deb
