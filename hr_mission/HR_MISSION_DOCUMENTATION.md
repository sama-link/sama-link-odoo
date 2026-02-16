# HR Mission Module - Complete Documentation

## Overview

The **HR Mission** module is a custom Odoo addon that allows organizations to manage and track employee missions with a simplified HR approval workflow. It integrates with the core HR module and automatically generates attendance records when missions are approved.

---

## Module Information

| Property | Value |
|----------|-------|
| **Name** | HR Mission |
| **Technical Name** | `hr_mission` |
| **Version** | 1.0.0 |
| **Category** | Human Resources |
| **Author** | 46-d-006 |
| **License** | LGPL-3 |
| **Dependencies** | `hr` (core), `hr_attendance_deviation` (for converter utilities) |

---

## Core Features

### 1. Mission Request Management
- Employees can create mission requests specifying destination, duration, and type
- Supports mission types: **Installation**, **Maintenance**, **Other**
- Date range selection for mission period
- Notes and additional information fields

### 2. Simplified Approval Workflow
The module implements a **2-stage workflow**:

```
Confirmed → HR Approved
    ↓           ↓
 Rejected    Cancelled
```

- Missions are created in **Confirmed** state (ready for HR review)
- HR approves or rejects the mission
- Approved missions can be cancelled if needed

### 3. Automatic Attendance Generation
When HR approves a mission, the system automatically creates attendance records for each day of the mission based on the employee's work schedule.

---

## Data Model

### Main Model: `hr.mission`

| Field | Type | Description |
|-------|------|-------------|
| `employee_id` | Many2one → `hr.employee` | The employee on mission (required, auto-defaults to current user) |
| `company_id` | Many2one → `res.company` | Related company (computed from employee) |
| `department_id` | Many2one → `hr.department` | Employee's department (related field) |
| `current_location_id` | Many2one → `hr.work.location` | Employee's work location (related field) |
| `manager_id` | Many2one → `hr.employee` | Employee's direct manager (related field) |
| `start_date` | Date | Mission start date (required) |
| `end_date` | Date | Mission end date (required) |
| `destination` | Char | Mission destination (required) |
| `mission_type` | Selection | Type: installation/maintenance/other (required) |
| `note` | Text | Additional notes from employee |
| `hr_reason` | Text | HR's approval/rejection reason |
| `state` | Selection | Current status (see workflow states) |
| `attendance_ids` | One2many → `hr.attendance` | Generated attendance records |

### Extended Model: `hr.attendance`

The module extends the standard `hr.attendance` model with:

| Field | Type | Description |
|-------|------|-------------|
| `mission_id` | Many2one → `hr.mission` | Links attendance record to related mission |

---

## Workflow States

| State | Description | Next Actions |
|-------|-------------|--------------|
| `confirmed` | Initial state - awaiting HR approval | HR Approve / Reject |
| `hr_approved` | HR has approved - mission active | Cancel |
| `rejected` | Request was rejected | - |
| `cancelled` | Approved mission was cancelled | - |

---

## Actions and Methods

### Workflow Actions

| Method | Description | Required Group |
|--------|-------------|----------------|
| `action_hr_approve()` | HR approval + creates attendance | Mission Manager (HR) |
| `action_reject()` | Reject the request | Mission Manager |
| `action_cancel()` | Cancel approved mission + delete attendance | Mission Manager |

### Helper Methods

| Method | Description |
|--------|-------------|
| `_create_attendance_records()` | Generates attendance records for each mission day |
| `_get_shift_start_end(date)` | Gets shift times from employee's contract calendar |
| `_get_shift_datetimes(shift, date)` | Converts shift to datetime objects |
| `_convert_float_to_time(float_time)` | Converts float hours to time object |
| `_convert_to_gmt_naive(date, time)` | Converts to naive UTC datetime |

### Constraints

| Constraint | Description |
|------------|-------------|
| `_check_one_mission()` | Prevents multiple confirmed missions per employee |

---

## Security Configuration

### Security Groups (Hierarchical)

```
┌─────────────────────────────────────────────────────┐
│ HR (group_hr_mission_manager)                       │
│   - Full access to all missions                     │
│   - Can create, read, write, and delete             │
│   - Approval authority                              │
│   - Includes: Admin, Root user                      │
├─────────────────────────────────────────────────────┤
│ Manager (group_hr_mission_officer)                  │
│   - Access to team's missions                       │
│   - Can create, read, write (no delete)             │
│   - Implies: User group                             │
├─────────────────────────────────────────────────────┤
│ User (group_hr_mission_user)                        │
│   - Access to own missions only                     │
│   - Can create, read, write (no delete)             │
└─────────────────────────────────────────────────────┘
```

### Record Rules

| Rule | Applies To | Domain |
|------|------------|--------|
| **Multi-company** | All users | Company-based filtering |
| **Own records only** | User group | `employee_id.user_id = current user` |
| **Team records only** | Manager group | `employee_id.parent_id.user_id = current user` |
| **All records** | HR group | Full access `(1, '=', 1)` |

### Access Rights (ir.model.access)

| Group | Read | Write | Create | Delete |
|-------|------|-------|--------|--------|
| User | ✓ | ✓ | ✓ | ✗ |
| Officer | ✓ | ✓ | ✓ | ✗ |
| Manager | ✓ | ✓ | ✓ | ✓ |

---

## User Interface

### Views

#### 1. Form View (`view_hr_mission_form`)
- **Header buttons**: Approve, Reject, Cancel (visibility based on state and HR group)
- **Status bar**: Shows workflow progress (Confirmed → HR Approved)
- **Employee Information group**: Employee, Department, Work Location, Manager
- **Mission Details group**: Type, Date Range (widget: daterange), Destination
- **Notebook pages**:
  - **Notes**: Employee notes, HR reason
  - **Attendance Records**: List of generated attendance (HR only)
- **Chatter**: For tracking and communication

#### 2. List View (`view_hr_mission_list`)
Columns: Employee, Work Location, Mission Type, Start Date, End Date, Destination, Status

#### 3. Search View (`view_hr_mission_search`)
- **Search fields**: Employee, Work Location, Destination
- **Filters**: Confirmed, HR Approved, Waiting for Approval (HR only)
- **Group by**: Work Location

### Menu Structure
```
HR Root Menu
└── Missions (menu_hr_mission)
    └── Action: action_hr_mission (list/form views)
```

**Default search filters**: Opens with pending missions for HR approval.

---

## Technical Dependencies

### External Module Dependency
```python
from odoo.addons.hr_attendance_deviation.tools import Converter
```

The module uses a `Converter` utility from `hr_attendance_deviation` for:
- `float_to_time_obj()`: Converting float hours to Python time objects
- `date_time_to_gmt_naive()`: Converting datetime to UTC naive format

### Model Inheritance
- Inherits `mail.thread` for chatter/tracking functionality
- All key fields have `tracking=True` for change logging

---

## File Structure

```
hr_mission/
├── __init__.py              # Package initialization
├── __manifest__.py          # Module manifest
├── models/
│   ├── __init__.py          # Models package init
│   ├── hr_mission.py        # Main mission model
│   └── hr_attendance.py     # Attendance extension
├── security/
│   ├── ir_groups.xml        # Security groups definition
│   ├── ir_rule.xml          # Record rules
│   └── ir.model.access.csv  # Access control list
└── views/
    └── hr_mission.xml       # All UI definitions
```

---

## Usage Flow

### For Employees
1. Navigate to **HR → Missions**
2. Click **Create** to start a new mission request
3. Fill in mission details (type, dates, destination)
4. Add any notes or additional information
5. **Save** - mission is immediately **Confirmed** and awaits HR approval

### For HR
1. Navigate to **HR → Missions** (auto-filtered to pending approvals)
2. Review confirmed mission requests
3. Provide a reason in the **HR Reason** field
4. Click **Approve** to finalize (creates attendance records) or **Reject**
5. Can **Cancel** approved missions if needed (deletes attendance)

---

## Important Business Rules

1. **One Confirmed Per Employee**: An employee cannot have multiple confirmed mission requests
2. **HR Only Approval**: Only users with HR Mission Manager group can approve/reject
3. **Attendance Auto-Generation**: Creates attendance records based on employee's contract calendar
4. **Cascade Delete on Cancel**: Cancelling a mission deletes all associated attendance records
5. **Working Days Only**: Attendance is only created for days matching the employee's shift schedule
