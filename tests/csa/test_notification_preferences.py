"""
Tests for csa_notification_preferences.py
No live Odoo calls — all tests use FakeConn.
"""
import pytest
from mcp_server_odoo.csa_notification_preferences import (
    get_admin_contacts,
    get_karthik_contact,
    get_work_order_contacts,
    PREEYANKA,
    KARTHIK_EMPLOYEE_ID,
    MD_EMPLOYEE_ID,
)


class FakeConn:
    def search_read(self, model, domain, fields):
        if model == "hr.employee":
            employee_id = domain[0][2]

            if employee_id == MD_EMPLOYEE_ID:
                return [{"id": 995, "name": "Pranav Jairam", "mobile_phone": "919999999999", "work_email": "md@csaerotherm.in"}]

            if employee_id == KARTHIK_EMPLOYEE_ID:
                return [{"id": 973, "name": "Karthik S", "mobile_phone": "917010161852", "work_email": "karthik@csaerotherm.in"}]

        if model == "mrp.workorder":
            return [{"employee_assigned_ids": [101, 102]}]

        if model == "hr.employee" and domain[0][0] == "id" and domain[0][1] == "in":
            return [
                {"id": 101, "name": "Employee A", "mobile_phone": "911111111111", "work_email": "a@csaerotherm.in"},
                {"id": 102, "name": "Employee B", "mobile_phone": None, "work_email": None},
            ]

        return []


# --- get_admin_contacts ---

def test_admin_contacts_returns_two():
    conn = FakeConn()
    result = get_admin_contacts(conn)
    assert len(result) == 2

def test_admin_contacts_first_is_preeyanka():
    conn = FakeConn()
    result = get_admin_contacts(conn)
    assert result[0]["name"] == "Preeyanka Samin"

def test_admin_contacts_second_is_md():
    conn = FakeConn()
    result = get_admin_contacts(conn)
    assert result[1]["name"] == "Pranav Jairam"

def test_admin_contacts_preeyanka_has_phone():
    conn = FakeConn()
    result = get_admin_contacts(conn)
    assert result[0]["mobile_phone"] == "919019178578"

def test_admin_contacts_md_has_email():
    conn = FakeConn()
    result = get_admin_contacts(conn)
    assert result[1]["work_email"] == "md@csaerotherm.in"


# --- get_karthik_contact ---

def test_karthik_contact_returns_dict():
    conn = FakeConn()
    result = get_karthik_contact(conn)
    assert result is not None

def test_karthik_contact_name():
    conn = FakeConn()
    result = get_karthik_contact(conn)
    assert result["name"] == "Karthik S"

def test_karthik_contact_phone():
    conn = FakeConn()
    result = get_karthik_contact(conn)
    assert result["mobile_phone"] == "917010161852"

def test_karthik_contact_email():
    conn = FakeConn()
    result = get_karthik_contact(conn)
    assert result["work_email"] == "karthik@csaerotherm.in"

def test_karthik_returns_none_when_not_found():
    class EmptyConn:
        def search_read(self, model, domain, fields):
            return []
    result = get_karthik_contact(EmptyConn())
    assert result is None


# --- get_work_order_contacts ---

def test_work_order_contacts_no_workorder():
    class EmptyConn:
        def search_read(self, model, domain, fields):
            return []
    result = get_work_order_contacts(EmptyConn(), 999)
    assert result == {"reachable": [], "unreachable": []}

def test_work_order_contacts_no_employees_assigned():
    class NoEmpConn:
        def search_read(self, model, domain, fields):
            if model == "mrp.workorder":
                return [{"employee_assigned_ids": []}]
            return []
    result = get_work_order_contacts(NoEmpConn(), 42)
    assert result == {"reachable": [], "unreachable": []}