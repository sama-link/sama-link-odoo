# -*- coding: utf-8 -*-
#############################################################################
#    A part of Open HRMS Project <https://www.openhrms.com>
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import fields, models


class IrAttachment(models.Model):
    """This class inherits from 'ir.attachment' and introduces two many-to-many
     relationships: 'doc_attach_rel' for associating HR employee documents and
    'attach_rel' for attaching general HR documents to a record."""
    _inherit = 'ir.attachment'

    doc_attach_rel = fields.Many2many('hr.employee.document',
                                      'doc_attachment_ids',
                                      'attach_id3', 'doc_id',
                                      string="Attachment", invisible=1,
                                      help='This field allows you to associate'
                                           'HR employee documents with the '
                                           'record.')
    attach_rel = fields.Many2many('hr.document',
                                  'attach_ids', 'attachment_id3',
                                  'document_id',
                                  string="Attachment", invisible=1,
                                  help='This field allows you to attach HR '
                                       'documents to the record.')

    def check(self, mode, values=None):
        """Override to allow HR users/managers access to attachments.
        Odoo's default check() method enforces Python-level security
        on ir.attachment that is independent of ir.rule record rules.
        This override bypasses that check for HR users/managers (native and
        Samalink groups) for attachments linked to HR document records.
        """
        user = self.env.user
        is_hr_role = any([
            user.has_group('hr.group_hr_user'),
            user.has_group('hr.group_hr_manager'),
            user.has_group('samalink_security_groups.group_samalink_hr_officer'),
            user.has_group('samalink_security_groups.group_samalink_administrator'),
            user.has_group('samalink_security_groups.group_sl_general_manager'),
        ])
        if is_hr_role:
            # Allow only attachments actually linked to HR document models.
            allowed = self.filtered(lambda att: (
                att.res_model in ('hr.employee.document', 'hr.document')
                or bool(att.doc_attach_rel)
                or bool(att.attach_rel)
            ))
            if len(allowed) == len(self):
                return
        return super().check(mode, values)
