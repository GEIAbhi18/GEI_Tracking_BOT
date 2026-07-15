import pytest
from auth.permissions import get_permissions_for_role, Role, Permission
from auth.guards import require_permission
from auth.context import set_current_user

# Dummy function to protect
@require_permission(Permission.CREATE_TEAM_TASKS)
def create_task_action():
    return "Task Created"

@pytest.fixture(autouse=True)
def clean_context():
    set_current_user(None)
    yield
    set_current_user(None)

def test_get_permissions_for_role():
    guest_perms = get_permissions_for_role(Role.GUEST)
    assert Permission.VIEW_COMPANY_INFO in guest_perms
    assert Permission.CREATE_TEAM_TASKS not in guest_perms
    
    employee_perms = get_permissions_for_role(Role.EMPLOYEE)
    assert Permission.CREATE_TEAM_TASKS in employee_perms
    assert Permission.VIEW_REPORTS not in employee_perms
    
    director_perms = get_permissions_for_role(Role.DIRECTOR)
    assert Permission.VIEW_REPORTS in director_perms
    
    dev_perms = get_permissions_for_role(Role.DEVELOPER)
    assert Permission.SYSTEM_ADMINISTRATION in dev_perms

def test_guard_no_user(caplog):
    caplog.set_level("CRITICAL")
    result = create_task_action()
    assert "You do not have permission" in result

def test_guard_unauthorized_user(caplog):
    caplog.set_level("CRITICAL")
    # Guest trying to create a task
    set_current_user({
        "id": "123",
        "role": Role.GUEST.value,
        "permissions": get_permissions_for_role(Role.GUEST)
    })
    result = create_task_action()
    assert "You do not have permission" in result

def test_guard_authorized_user():
    # Employee trying to create a task
    set_current_user({
        "id": "123",
        "role": Role.EMPLOYEE.value,
        "permissions": get_permissions_for_role(Role.EMPLOYEE)
    })
    result = create_task_action()
    assert result == "Task Created"

def test_guard_developer_override():
    # Developer trying to do something without the specific permission in their list
    set_current_user({
        "id": "123",
        "role": Role.DEVELOPER.value,
        "permissions": get_permissions_for_role(Role.DEVELOPER)
    })
    result = create_task_action()
    assert result == "Task Created"

@pytest.mark.asyncio
async def test_guard_async_function(caplog):
    caplog.set_level("CRITICAL")
    @require_permission(Permission.VIEW_REPORTS)
    async def view_reports_action():
        return "Reports Viewed"
        
    set_current_user({
        "id": "123",
        "role": Role.EMPLOYEE.value,
        "permissions": get_permissions_for_role(Role.EMPLOYEE)
    })
    result = await view_reports_action()
    assert "You do not have permission" in result
    
    set_current_user({
        "id": "123",
        "role": Role.DIRECTOR.value,
        "permissions": get_permissions_for_role(Role.DIRECTOR)
    })
    result = await view_reports_action()
    assert result == "Reports Viewed"
