import uuid
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()

def create_mock_user(role="employee", telegram_id=None, whatsapp_number=None):
    return {
        "id": str(uuid.uuid4()),
        "name": fake.name(),
        "role": role,
        "telegram_id": telegram_id or fake.random_number(digits=10),
        "whatsapp_number": whatsapp_number or f"+9198{fake.random_number(digits=8)}",
        "last_activity_at": datetime.now().isoformat(),
        "created_at": datetime.now().isoformat()
    }

def create_mock_project(created_by_id):
    return {
        "id": str(uuid.uuid4()),
        "name": fake.company(),
        "description": fake.catch_phrase(),
        "status": "active",
        "created_by": created_by_id,
        "created_at": datetime.now().isoformat()
    }

def create_mock_task(project_id, assigned_to_id=None, status="Pending", task_type="PROJECT"):
    return {
        "id": str(uuid.uuid4()),
        "project_id": project_id,
        "assigned_to": assigned_to_id,
        "name": fake.sentence(nb_words=6),
        "title": fake.sentence(nb_words=6),
        "deadline": (datetime.now() + timedelta(days=7)).isoformat(),
        "status": status,
        "progress": 0 if status != "Completed" else 100,
        "task_type": task_type,
        "created_at": datetime.now().isoformat()
    }
