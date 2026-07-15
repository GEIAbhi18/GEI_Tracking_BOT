import logging
from flask import Blueprint, jsonify, request
from reports.service import (
    get_dashboard_stats,
    get_team_reports,
    get_employee_reports,
    get_most_active_employee,
    get_task_timeline
)

logger = logging.getLogger(__name__)

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")

def get_timeframe(req):
    return req.args.get("timeframe", "all_time")

@reports_bp.route("/dashboard", methods=["GET"])
def api_dashboard_stats():
    timeframe = get_timeframe(request)
    stats = get_dashboard_stats(timeframe)
    active = get_most_active_employee(timeframe)
    
    if stats is None:
        return jsonify({"error": "Failed to fetch dashboard stats"}), 500
        
    return jsonify({
        "stats": stats,
        "most_active_employee": active
    }), 200

@reports_bp.route("/teams", methods=["GET"])
def api_team_reports():
    timeframe = get_timeframe(request)
    teams = get_team_reports(timeframe)
    return jsonify(teams), 200

@reports_bp.route("/employees", methods=["GET"])
def api_employee_reports():
    timeframe = get_timeframe(request)
    employees = get_employee_reports(timeframe)
    return jsonify(employees), 200

@reports_bp.route("/tasks/<task_id>/timeline", methods=["GET"])
def api_task_timeline(task_id):
    timeline = get_task_timeline(task_id)
    return jsonify(timeline), 200
