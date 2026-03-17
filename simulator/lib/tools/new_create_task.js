import { supabase } from '../supabase.js';

export async function createTaskTool(entities) {
    if (!entities.task_name) return "What is the name of the new task?";
    if (!entities.project_name) return "Which project should this task be added to?";

    const { data: projData, error: projErr } = await supabase
        .from('projects')
        .select('id, name')
        .ilike('name', `%${entities.project_name}%`)
        .limit(1);

    if (projErr || !projData || projData.length === 0) {
        return `Project "${entities.project_name}" not found. Cannot create task.`;
    }

    const projId = projData[0].id;
    let assignedUserId = null;

    if (entities.assignee) {
        const { data: userData } = await supabase.from('users').select('id').ilike('name', `%${entities.assignee}%`).limit(1);
        if (userData && userData.length > 0) assignedUserId = userData[0].id;
    }

    let deadlineDate = null;
    if (entities.deadline) {
        const parsed = new Date(entities.deadline + ' 2026').toISOString();
        if (parsed !== 'Invalid Date') {
            deadlineDate = parsed;
        }
    }

    const payload = {
        project_id: projId,
        name: entities.task_name,
        assigned_to: assignedUserId,
        deadline: deadlineDate,
        planned_start_date: new Date().toISOString(),
        planned_end_date: deadlineDate,
        status: 'pending',
        progress: 0
    };

    const { data: newTask, error } = await supabase.from('tasks').insert([payload]).select('name').single();

    if (error) {
        return `Failed to create task.`;
    }

    return `Task "${newTask.name}" successfully created in project "${projData[0].name}"${entities.assignee ? ` and assigned to ${entities.assignee}.` : '.'}`;
}
