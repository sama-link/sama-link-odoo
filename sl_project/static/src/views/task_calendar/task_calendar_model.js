/** @odoo-module **/

import { ProjectTaskCalendarModel } from "@project/views/project_task_calendar/project_task_calendar_model";

export class SlProjectTaskCalendarModel extends ProjectTaskCalendarModel {
    /**
     * On the first load, read the global (all-users) calendar date field and use
     * it as the calendar's date_start. All candidate fields are declared as
     * invisible fields in the arch, so they are present in both meta.fields
     * (metadata) and meta.fieldNames (read spec) — switching the mapping and
     * reloading is enough for the range domain and event placement to recompute.
     * @override
     */
    async load(params = {}) {
        if (!this._slDateFieldLoaded) {
            this._slDateFieldLoaded = true;
            try {
                const info = await this.orm.call(
                    "project.task",
                    "get_calendar_date_field_info",
                    []
                );
                const field = info && info.field;
                if (field && field in this.meta.fields) {
                    this.meta.fieldMapping.date_start = field;
                }
            } catch (e) {
                // Keep the arch's default date_start on any failure.
            }
        }
        return super.load(params);
    }

    /**
     * Switch the calendar to another date field and reload. The first-load guard
     * is already set, so this does not re-fetch and override the chosen field.
     */
    async setDateStartField(fieldName) {
        if (fieldName && fieldName in this.meta.fields) {
            this.meta.fieldMapping.date_start = fieldName;
            await this.load();
        }
    }
}
