from flask import Blueprint, request, jsonify
from auth.guards import require_permission
from auth.permissions import Permission
from teams.repository import create_team, get_all_teams, get_team_by_id, update_team, delete_team
from teams.validation import validate_team_name

teams_bp = Blueprint('teams', __name__, url_prefix='/api/teams')

@teams_bp.route('/', methods=['GET'])
# Notice we don't have a VIEW_TEAMS permission currently, but Employees and Directors have other permissions we can check.
# The prompt specified Directors and Employees can see teams. 
# Alternatively, we could create a new Permission, but for now we'll allow standard users to list them.
# The RBAC design allows anyone authenticated to list teams, but strictly restricts modification.
def list_teams():
    """List all teams. Available to authenticated users."""
    try:
        teams = get_all_teams()
        return jsonify({"status": "success", "data": teams}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@teams_bp.route('/', methods=['POST'])
@require_permission(Permission.SYSTEM_ADMINISTRATION)
def add_team():
    """Create a new team. Restricted to Developer."""
    body = request.get_json()
    if not body:
        return jsonify({"status": "error", "message": "Missing JSON body"}), 400
        
    raw_name = body.get("name")
    is_valid, sanitized_name, error_msg = validate_team_name(raw_name)
    
    if not is_valid:
        return jsonify({"status": "error", "message": error_msg}), 400
        
    try:
        team = create_team(sanitized_name)
        return jsonify({"status": "success", "data": team}), 201
    except Exception as e:
        if "duplicate key value" in str(e).lower() or "unique constraint" in str(e).lower():
            return jsonify({"status": "error", "message": f"Team '{sanitized_name}' already exists."}), 409
        return jsonify({"status": "error", "message": str(e)}), 500

@teams_bp.route('/<team_id>', methods=['GET'])
def get_team(team_id):
    """Get a specific team."""
    try:
        team = get_team_by_id(team_id)
        if not team:
            return jsonify({"status": "error", "message": "Team not found"}), 404
        return jsonify({"status": "success", "data": team}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@teams_bp.route('/<team_id>', methods=['PUT'])
@require_permission(Permission.SYSTEM_ADMINISTRATION)
def edit_team(team_id):
    """Update a team's name. Restricted to Developer."""
    body = request.get_json()
    if not body:
        return jsonify({"status": "error", "message": "Missing JSON body"}), 400
        
    raw_name = body.get("name")
    is_valid, sanitized_name, error_msg = validate_team_name(raw_name)
    
    if not is_valid:
        return jsonify({"status": "error", "message": error_msg}), 400
        
    try:
        team = update_team(team_id, sanitized_name)
        if not team:
            return jsonify({"status": "error", "message": "Team not found"}), 404
        return jsonify({"status": "success", "data": team}), 200
    except Exception as e:
        if "duplicate key value" in str(e).lower() or "unique constraint" in str(e).lower():
            return jsonify({"status": "error", "message": f"Team '{sanitized_name}' already exists."}), 409
        return jsonify({"status": "error", "message": str(e)}), 500

@teams_bp.route('/<team_id>', methods=['DELETE'])
@require_permission(Permission.SYSTEM_ADMINISTRATION)
def remove_team(team_id):
    """Delete a team. Restricted to Developer."""
    try:
        team = delete_team(team_id)
        if not team:
            return jsonify({"status": "error", "message": "Team not found"}), 404
        return jsonify({"status": "success", "message": "Team deleted successfully"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
