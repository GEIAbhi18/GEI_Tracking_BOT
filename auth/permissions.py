from enum import Enum

class Role(str, Enum):
    GUEST = "Guest"
    CLIENT = "Client"
    EMPLOYEE = "Employee"
    DIRECTOR = "Director"
    DEVELOPER = "Developer"

class Permission(str, Enum):
    VIEW_COMPANY_INFO = "VIEW_COMPANY_INFO"
    ACCESS_COMPLAINTS = "ACCESS_COMPLAINTS"
    CREATE_TEAM_TASKS = "CREATE_TEAM_TASKS"
    ASSIGN_TEAM_TASKS = "ASSIGN_TEAM_TASKS"
    MANAGE_OWN_PERSONAL_TASKS = "MANAGE_OWN_PERSONAL_TASKS"
    VIEW_OWN_TEAM_TASKS = "VIEW_OWN_TEAM_TASKS"
    VIEW_REPORTS = "VIEW_REPORTS"
    VIEW_ANALYTICS = "VIEW_ANALYTICS"
    SYSTEM_ADMINISTRATION = "SYSTEM_ADMINISTRATION"

# The Permission Matrix
ROLE_PERMISSIONS = {
    Role.GUEST: [
        Permission.VIEW_COMPANY_INFO
    ],
    Role.CLIENT: [
        Permission.ACCESS_COMPLAINTS
    ],
    Role.EMPLOYEE: [
        Permission.CREATE_TEAM_TASKS,
        Permission.ASSIGN_TEAM_TASKS,
        Permission.MANAGE_OWN_PERSONAL_TASKS,
        Permission.VIEW_OWN_TEAM_TASKS
    ],
    Role.DIRECTOR: [
        Permission.CREATE_TEAM_TASKS,
        Permission.ASSIGN_TEAM_TASKS,
        Permission.MANAGE_OWN_PERSONAL_TASKS,
        Permission.VIEW_OWN_TEAM_TASKS,
        Permission.VIEW_REPORTS,
        Permission.VIEW_ANALYTICS
    ],
    Role.DEVELOPER: [
        Permission.SYSTEM_ADMINISTRATION
    ]
}

def get_permissions_for_role(role: str) -> list:
    """Returns the list of permissions for a given role string."""
    try:
        r = Role(role)
        return ROLE_PERMISSIONS.get(r, [])
    except ValueError:
        return []
