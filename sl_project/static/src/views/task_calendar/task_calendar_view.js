/** @odoo-module **/

import { registry } from "@web/core/registry";
import { projectTaskCalendarView } from "@project/views/project_task_calendar/project_task_calendar_view";
import { SlProjectTaskCalendarController } from "./task_calendar_controller";
import { SlProjectTaskCalendarModel } from "./task_calendar_model";

// Extend Odoo's own project task calendar variant (keeps its filter panel,
// labels, sub-task delete behaviour, arch parser, renderer and props) and only
// swap in our controller (adds the date-field selector) and model (switches the
// date_start at runtime).
export const slProjectTaskCalendarView = {
    ...projectTaskCalendarView,
    Controller: SlProjectTaskCalendarController,
    Model: SlProjectTaskCalendarModel,
};

registry.category("views").add("sl_project_task_calendar", slProjectTaskCalendarView);
