-- ==============================================================================
-- Phase 9: Reporting RPCs
-- ==============================================================================

-- 1. get_dashboard_stats
CREATE OR REPLACE FUNCTION get_dashboard_stats(timeframe text)
RETURNS jsonb AS $$
DECLARE
    start_date timestamp;
    result jsonb;
    v_total_tasks int;
    v_completed_tasks int;
    v_pending_tasks int;
    v_overdue_tasks int;
    v_avg_completion_time_hours numeric;
BEGIN
    IF timeframe = 'today' THEN
        start_date := current_date;
    ELSIF timeframe = 'weekly' THEN
        start_date := date_trunc('week', current_date);
    ELSIF timeframe = 'monthly' THEN
        start_date := date_trunc('month', current_date);
    ELSE
        start_date := '1970-01-01'::timestamp;
    END IF;

    SELECT count(*) INTO v_total_tasks 
    FROM tasks 
    WHERE created_at >= start_date AND task_type != 'PERSONAL';

    SELECT count(*) INTO v_completed_tasks 
    FROM tasks 
    WHERE created_at >= start_date AND status IN ('Closed', 'Completed') AND task_type != 'PERSONAL';

    SELECT count(*) INTO v_pending_tasks 
    FROM tasks 
    WHERE created_at >= start_date AND status IN ('Pending', 'In Progress', 'Accepted') AND task_type != 'PERSONAL';

    SELECT count(*) INTO v_overdue_tasks 
    FROM tasks 
    WHERE due_date < current_date AND status NOT IN ('Closed', 'Completed') AND task_type != 'PERSONAL';

    SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (closed_at - created_at)) / 3600), 0) INTO v_avg_completion_time_hours
    FROM tasks
    WHERE created_at >= start_date AND status IN ('Closed', 'Completed') AND task_type != 'PERSONAL';

    result := jsonb_build_object(
        'total_tasks', v_total_tasks,
        'completion_percentage', CASE WHEN v_total_tasks > 0 THEN ROUND((v_completed_tasks::numeric / v_total_tasks * 100), 2) ELSE 0 END,
        'pending_percentage', CASE WHEN v_total_tasks > 0 THEN ROUND((v_pending_tasks::numeric / v_total_tasks * 100), 2) ELSE 0 END,
        'average_completion_time_hours', ROUND(v_avg_completion_time_hours, 2),
        'overdue_tasks', v_overdue_tasks
    );
    RETURN result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- 2. get_team_reports
CREATE OR REPLACE FUNCTION get_team_reports(timeframe text)
RETURNS jsonb AS $$
DECLARE
    start_date timestamp;
    result jsonb;
BEGIN
    IF timeframe = 'today' THEN
        start_date := current_date;
    ELSIF timeframe = 'weekly' THEN
        start_date := date_trunc('week', current_date);
    ELSIF timeframe = 'monthly' THEN
        start_date := date_trunc('month', current_date);
    ELSE
        start_date := '1970-01-01'::timestamp;
    END IF;

    SELECT jsonb_agg(
        jsonb_build_object(
            'team_id', t.id,
            'team_name', t.name,
            'total_tasks', COALESCE(stat.total, 0),
            'completion_percentage', CASE WHEN stat.total > 0 THEN ROUND((stat.completed::numeric / stat.total * 100), 2) ELSE 0 END,
            'pending_percentage', CASE WHEN stat.total > 0 THEN ROUND((stat.pending::numeric / stat.total * 100), 2) ELSE 0 END,
            'overdue_tasks', COALESCE(stat.overdue, 0),
            'average_completion_time_hours', ROUND(COALESCE(stat.avg_time, 0), 2)
        )
    ) INTO result
    FROM teams t
    LEFT JOIN (
        SELECT 
            team_id, 
            COUNT(*) as total,
            COUNT(CASE WHEN status IN ('Closed', 'Completed') THEN 1 END) as completed,
            COUNT(CASE WHEN status IN ('Pending', 'In Progress', 'Accepted') THEN 1 END) as pending,
            COUNT(CASE WHEN due_date < current_date AND status NOT IN ('Closed', 'Completed') THEN 1 END) as overdue,
            COALESCE(AVG(EXTRACT(EPOCH FROM (closed_at - created_at)) / 3600), 0) as avg_time
        FROM tasks
        WHERE created_at >= start_date AND task_type != 'PERSONAL'
        GROUP BY team_id
    ) stat ON t.id = stat.team_id;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- 3. get_employee_reports
CREATE OR REPLACE FUNCTION get_employee_reports(timeframe text)
RETURNS jsonb AS $$
DECLARE
    start_date timestamp;
    result jsonb;
BEGIN
    IF timeframe = 'today' THEN
        start_date := current_date;
    ELSIF timeframe = 'weekly' THEN
        start_date := date_trunc('week', current_date);
    ELSIF timeframe = 'monthly' THEN
        start_date := date_trunc('month', current_date);
    ELSE
        start_date := '1970-01-01'::timestamp;
    END IF;

    SELECT jsonb_agg(
        jsonb_build_object(
            'employee_id', u.id,
            'employee_name', u.name,
            'total_tasks', COALESCE(stat.total, 0),
            'completion_percentage', CASE WHEN stat.total > 0 THEN ROUND((stat.completed::numeric / stat.total * 100), 2) ELSE 0 END,
            'pending_percentage', CASE WHEN stat.total > 0 THEN ROUND((stat.pending::numeric / stat.total * 100), 2) ELSE 0 END,
            'overdue_tasks', COALESCE(stat.overdue, 0),
            'average_completion_time_hours', ROUND(COALESCE(stat.avg_time, 0), 2)
        )
    ) INTO result
    FROM users u
    LEFT JOIN (
        SELECT 
            assigned_to, 
            COUNT(*) as total,
            COUNT(CASE WHEN status IN ('Closed', 'Completed') THEN 1 END) as completed,
            COUNT(CASE WHEN status IN ('Pending', 'In Progress', 'Accepted') THEN 1 END) as pending,
            COUNT(CASE WHEN due_date < current_date AND status NOT IN ('Closed', 'Completed') THEN 1 END) as overdue,
            COALESCE(AVG(EXTRACT(EPOCH FROM (closed_at - created_at)) / 3600), 0) as avg_time
        FROM tasks
        WHERE created_at >= start_date AND task_type != 'PERSONAL' AND assigned_to IS NOT NULL
        GROUP BY assigned_to
    ) stat ON u.id = stat.assigned_to
    WHERE u.role = 'Employee';

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- 4. get_most_active_employee
CREATE OR REPLACE FUNCTION get_most_active_employee(timeframe text)
RETURNS jsonb AS $$
DECLARE
    start_date timestamp;
    result jsonb;
BEGIN
    IF timeframe = 'today' THEN
        start_date := current_date;
    ELSIF timeframe = 'weekly' THEN
        start_date := date_trunc('week', current_date);
    ELSIF timeframe = 'monthly' THEN
        start_date := date_trunc('month', current_date);
    ELSE
        start_date := '1970-01-01'::timestamp;
    END IF;

    WITH update_counts AS (
        SELECT employee_id as uid, count(*) as c 
        FROM updates 
        WHERE timestamp >= start_date 
        GROUP BY employee_id
    ),
    daily_update_counts AS (
        SELECT user_id as uid, count(*) as c 
        FROM daily_updates 
        WHERE timestamp >= start_date 
        GROUP BY user_id
    ),
    combined AS (
        SELECT COALESCE(u.uid, d.uid) as uid, COALESCE(u.c, 0) + COALESCE(d.c, 0) as total_activity
        FROM update_counts u
        FULL OUTER JOIN daily_update_counts d ON u.uid = d.uid
    )
    SELECT jsonb_build_object(
        'employee_id', usr.id,
        'employee_name', usr.name,
        'activity_count', c.total_activity
    ) INTO result
    FROM combined c
    JOIN users usr ON c.uid = usr.id
    ORDER BY c.total_activity DESC
    LIMIT 1;

    RETURN result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- 5. get_task_timeline
CREATE OR REPLACE FUNCTION get_task_timeline(target_task_id uuid)
RETURNS jsonb AS $$
DECLARE
    result jsonb;
BEGIN
    WITH events AS (
        SELECT 
            'Audit' as event_type,
            changed_at as event_time,
            u.name as actor_name,
            jsonb_build_object(
                'old_status', old_status, 
                'new_status', new_status, 
                'changes', changes
            ) as details
        FROM tasks_audit ta
        LEFT JOIN users u ON ta.changed_by = u.id
        WHERE task_id = target_task_id
        
        UNION ALL
        
        SELECT 
            'Update' as event_type,
            timestamp as event_time,
            u.name as actor_name,
            jsonb_build_object(
                'progress', progress, 
                'blockers', blockers, 
                'note', note
            ) as details
        FROM updates upd
        LEFT JOIN users u ON upd.employee_id = u.id
        WHERE task_id = target_task_id
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'event_type', event_type,
            'event_time', event_time,
            'actor_name', actor_name,
            'details', details
        ) ORDER BY event_time ASC
    ) INTO result
    FROM events;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
