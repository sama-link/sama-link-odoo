/** @odoo-module **/

import { onWillStart, useState } from "@odoo/owl";
import { ProjectTaskCalendarController } from "@project/views/project_task_calendar/project_task_calendar_controller";

export class SlProjectTaskCalendarController extends ProjectTaskCalendarController {
    static template = "sl_project.TaskCalendarController";

    setup() {
        super.setup();
        // Populated from the server so options/labels/permission are authoritative.
        this.dateFieldState = useState({
            field: "date_deadline",
            options: [],
            canEdit: false,
        });
        onWillStart(async () => {
            const info = await this.orm.call(
                "project.task",
                "get_calendar_date_field_info",
                []
            );
            if (info) {
                this.dateFieldState.field = info.field || "date_deadline";
                this.dateFieldState.options = info.options || [];
                this.dateFieldState.canEdit = Boolean(info.can_edit);
            }
        });
    }

    async onDateFieldChange(ev) {
        const value = ev.target.value;
        // Persist the global setting (server enforces admin-only) then re-render.
        await this.orm.call("project.task", "set_calendar_date_field", [value]);
        this.dateFieldState.field = value;
        await this.model.setDateStartField(value);
    }
}
