import { useState, Component } from "@odoo/owl";

const numberRange = (min, max) => [...Array(max - min)].map((_, i) => i + min);

const HOURS = numberRange(1, 13).map((hour) => [hour, String(hour)]);
const MINUTES = numberRange(0, 60).map((minute) => [minute, String(minute || 0).padStart(2, "0")]);

export class FloatCivilianTimeSelectionPopover extends Component {
    static template = "sl_hr_holidays.FloatCivilianTimeSelectionPopover";

    static props = {
        close: { type: Function },
        onTimeChange: { type: Function },
        timeValues: {
            type: Object,
            shape: {
                hours: "12",
                minutes: "00",
                meridiem: 'AM',
                floatValue: 0,
            },
        },
    };

    setup() {
        this.availableHours = HOURS;
        this.availableMinutes = MINUTES;
        this.state = useState({
            selectedHours: this.props.timeValues.hours,
            selectedMinutes: this.props.timeValues.minutes,
            selectedMeridiem: this.props.timeValues.meridiem,
        });
    }

    onTimeChange() {
        let hours = parseInt(this.state.selectedHours);
        if (this.state.selectedMeridiem === 'PM' && hours < 12) {
            hours += 12;
        }

        this.props.onTimeChange({
            hours: hours,
            minutes: this.state.selectedMinutes,
            meridiem: this.state.selectedMeridiem,
        });
    }
}