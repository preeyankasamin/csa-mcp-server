"""
CSA Aerotherm - Notification Preferences
Decides WHO gets notified for a given alert, and HOW to reach them.
Two paths:
  1. Admin contacts (Preeyanka + MD) - fixed, for business-wide alerts.
  2. Work order contacts - looked up live from Odoo's employee_assigned_ids.
"""

# Hardcoded admin contacts (not in this Odoo company's employee list - CSBS, not CS Aerotherm)
PREEYANKA = {
    "name": "Preeyanka Samin",
    "mobile_phone": "919019178578",
    "work_email": "preeyanka@mechtrace.com",
}

# Karthik S - Senior Purchase Executive - hr.employee id 973 in CS Aerotherm
KARTHIK_EMPLOYEE_ID = 973
# Pranav Jairam - Managing Director - hr.employee id 995 in CS Aerotherm
MD_EMPLOYEE_ID = 995


def get_admin_contacts(conn) -> list[dict]:
    """
    Return contact info for Preeyanka + MD, for business-wide alerts
    (low_stock, po_pending_approval, missing_vendor).
    conn -- an authenticated OdooConnection
    """
    contacts = [PREEYANKA]

    md_records = conn.search_read(
        "hr.employee",
        [["id", "=", MD_EMPLOYEE_ID]],
        fields=["name", "mobile_phone", "work_email"],
    )
    if md_records:
        md = md_records[0]
        contacts.append({
            "name": md["name"],
            "mobile_phone": md.get("mobile_phone"),
            "work_email": md.get("work_email"),
        })

    return contacts

def get_karthik_contact(conn) -> dict | None:
    """
    Return contact info for Karthik S (Senior Purchase Executive).
    Used for work_order_stuck alerts.
    conn -- an authenticated OdooConnection
    """
    records = conn.search_read(
        "hr.employee",
        [["id", "=", KARTHIK_EMPLOYEE_ID]],
        fields=["name", "mobile_phone", "work_email"],
    )
    if not records:
        return None
    k = records[0]
    return {
        "name": k["name"],
        "mobile_phone": k.get("mobile_phone"),
        "work_email": k.get("work_email"),
    }


def get_work_order_contacts(conn, work_order_id: int) -> dict:
    """
    Look up who is assigned to a specific work order, and their contact info.
    conn           -- an authenticated OdooConnection
    work_order_id  -- the mrp.workorder record id

    Returns:
        {
            "reachable": [ {"name": ..., "mobile_phone": ..., "work_email": ...}, ... ],
            "unreachable": [ "Employee Name", ... ]   # no phone AND no email
        }
    """
    workorders = conn.search_read(
        "mrp.workorder",
        [["id", "=", work_order_id]],
        fields=["employee_assigned_ids"],
    )
    if not workorders:
        return {"reachable": [], "unreachable": []}

    employee_ids = workorders[0]["employee_assigned_ids"]
    if not employee_ids:
        return {"reachable": [], "unreachable": []}

    employees = conn.search_read(
        "hr.employee",
        [["id", "in", employee_ids]],
        fields=["name", "mobile_phone", "work_email"],
    )

    reachable = []
    unreachable = []
    for emp in employees:
        phone = emp.get("mobile_phone")
        email = emp.get("work_email")
        if not phone and not email:
            unreachable.append(emp["name"])
        else:
            reachable.append({
                "name": emp["name"],
                "mobile_phone": phone,
                "work_email": email,
            })

    return {"reachable": reachable, "unreachable": unreachable}