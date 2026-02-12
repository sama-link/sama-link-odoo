import { useState, onWillStart } from "@odoo/owl";
import { usePopover } from "@web/core/popover/popover_hook";
import { FloatTimeSelectionField } from "@hr_holidays/components/float_time_selection/float_time_selection";

import { FloatCivilianTimeSelectionPopover } from "./float_time_selection_popover";
import { floatTimeField } from "@web/views/fields/float_time/float_time_field";
import { registry } from "@web/core/registry";


function floatToCivilianHoursMinutes(floatValue) {
    let hours = Math.floor(floatValue);
    const minutes = Math.round((floatValue - hours) * 60);
    let meridiem = 'AM';
    if (hours > 12) {
        hours -= 12;
        meridiem = 'PM';
    }
    if (hours === 12) {
        meridiem = 'PM';
    }
    else if (hours === 0) {
        hours = 12;
    }
    return { hours: String(hours).padStart(2, "0"), minutes: String(minutes).padStart(2, "0"), meridiem };
}

function civilianHoursMinutesToFloat(hours, minutes, meridiem) {
    if (meridiem === 'PM' && parseInt(hours) < 12) {
        hours = String(parseInt(hours) + 12);
    }
    else if (meridiem === 'AM' && parseInt(hours) === 12) {
        hours = '0';
    }
    return parseInt(hours) + minutes / 60;
}

export class FloatCivilianTimeSelectionField extends FloatTimeSelectionField {
    static template = "sl_hr_holidays.FloatCivilianTimeSelectionField";

    setup() {
        super.setup();
        this.popover = usePopover(FloatCivilianTimeSelectionPopover, {
            onClose: this.onClose.bind(this),
        });
        this.timeValues = useState({
            hours: "12",
            minutes: "00",
            meridiem: 'AM',
            floatValue: 0,
        });

        onWillStart(() => {
            this.setTime();
        });
    }

    onCharHoursClick(ev) {
        ev.preventDefault();
        const timeValues = this.getTime();
        this.popover.open(ev.currentTarget, {
            timeValues: timeValues,
            onTimeChange: this.onTimeChange.bind(this),
        });
    }

    onTimeChange(newTimeValues) {
        super.onTimeChange(newTimeValues);
        this.timeValues.meridiem = newTimeValues.meridiem;
        this.timeValues.floatValue = civilianHoursMinutesToFloat(newTimeValues.hours, newTimeValues.minutes, newTimeValues.meridiem);
    }

    setTime() {
        const initialValue = this.props.record.data[this.props.name];
        const { hours, minutes, meridiem } = floatToCivilianHoursMinutes(initialValue);
        this.timeValues.hours = hours;
        this.timeValues.minutes = minutes;
        this.timeValues.meridiem = meridiem;
        this.timeValues.floatValue = initialValue;
    }
    
    getTime() {
        const initialValue = this.props.record.data[this.props.name];
        const { hours, minutes, meridiem } = floatToCivilianHoursMinutes(initialValue);
        return {
            hours,
            minutes,
            meridiem,
            floatValue: initialValue,
        }
    }

    get formattedValue() {
        const { hours, minutes, meridiem } = this.getTime();
        return `${hours}:${minutes} ${meridiem}`;
    }
}

export const charHours = {
    ...floatTimeField,
    component: FloatCivilianTimeSelectionField,
};

registry.category("fields").add("float_civilian_time_selection", charHours);