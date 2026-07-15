from flask import Blueprint, request, jsonify
from auth.guards import require_permission
from auth.permissions import Permission
from auth.context import get_current_user
from tasks.service import orchestrate_task_creation, orchestrate_status_update, orchestrate_task_assignment
from tasks.repository import get_tasks_by_team, get_task_by_id
from tasks.timeline import get_task_timeline

tasks_bp = Blueprint('tasks', __name__, url_prefix='/api/tasks')

@tasks_bp.route('/', methods=['POST'])
# We allow any authenticated user to create a task. If they are a Client/Guest, they won't reach here in a real scenario 
# since they don't have Employee permissions, but we can specifically restrict this.
@require_permission(Permission.CREATE_TEAM_TASKS)
def create_new_task():
    try:
        user = get_current_user()
        data = request.get_json()
        if not data: return jsonify({"status": "error", "message": "Missing JSON body"}), 400
        
        task = orchestrate_task_creation(user, data)
        return jsonify({"status": "success", "data": task}), 201
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@tasks_bp.route('/team/<team_id>', methods=['GET'])
@require_permission(Permission.VIEW_OWN_TEAM_TASKS)
def list_team_tasks(team_id):
    try:
        user = get_current_user()
        # Security check: Employees can only view their own team's tasks unless Developer/Director
        if user.get("role") not in ["Developer", "Director"] and user.get("team_id") != team_id:
            return jsonify({"status": "error", "message": "Unauthorized to view this team's tasks."}), 403
            
        tasks = get_tasks_by_team(team_id)
        return jsonify({"status": "success", "data": tasks}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@tasks_bp.route('/<task_id>', methods=['GET'])
def get_task(task_id):
    try:
        task = get_task_by_id(task_id)
        if not task: return jsonify({"status": "error", "message": "Task not found"}), 404
        return jsonify({"status": "success", "data": task}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@tasks_bp.route('/<task_id>/status', methods=['PATCH'])
def change_status(task_id):
    try:
        user = get_current_user()
        data = request.get_json()
        new_status = data.get("status")
        note = data.get("note")
        proof_url = data.get("completion_proof")
        
        if not new_status: return jsonify({"status": "error", "message": "Status is required."}), 400
        
        updated = orchestrate_status_update(user, task_id, new_status, note, proof_url)
        return jsonify({"status": "success", "data": updated}), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@tasks_bp.route('/<task_id>/assign', methods=['PATCH'])
@require_permission(Permission.ASSIGN_TEAM_TASKS)
def assign_task(task_id):
    try:
        user = get_current_user()
        data = request.get_json()
        new_assignee_id = data.get("assigned_to")
        
        if not new_assignee_id: return jsonify({"status": "error", "message": "assigned_to is required."}), 400
        
        updated = orchestrate_task_assignment(user, task_id, new_assignee_id)
        return jsonify({"status": "success", "data": updated}), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@tasks_bp.route('/<task_id>/timeline', methods=['GET'])
def get_timeline(task_id):
    try:
        timeline = get_task_timeline(task_id)
        return jsonify({"status": "success", "data": timeline}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
