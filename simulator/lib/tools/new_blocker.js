import { supabase } from '../supabase.js';
import { getUserAndTasks, findTaskByEntities, buildGroupedTasksList } from './utils.js';

export async function addBlockerTool(entities) {
    const targetUser = entities.assignee || 'Asif';
    const result = await getUserAndTasks(targetUser);
    if (result.error) return result.error;

    if (!entities.blocker_name) {
        return 'What is the exact issue holding this task?';
    }

    const task = findTaskByEntities(result.tasks, entities);
    if (!task) {
        return `Please select which task is blocked:\n\n${buildGroupedTasksList(result.tasks.filter(t => t.status !== 'completed'))}`;
    }

    const blockerReason = entities.blocker_name;

    await supabase.from('tasks').update({
        is_blocked: true,
        blocker_reason: blockerReason
    }).eq('id', task.id);

    // Save update
    await supabase.from('updates').insert([{
        task_id: task.id,
        employee_id: result.userId,
        progress: task.progress || 0,
        blockers: blockerReason,
        images: task.attachments || [],
        rag: 'RED'
    }]);

    return `Added blocker "${blockerReason}" to task "${task.name}".`;
}

export async function checkBlockersTool(entities) {
    const { data: usersData } = await supabase.from('users').select('id, name');
    if (!usersData || usersData.length === 0) return 'No users found.';

    let resMsg = `Blocker Status:\n`;
    
    for (const u of usersData) {
        const { data: tasks } = await supabase
            .from('tasks')
            .select('name, blocker_reason, project_id, projects(name)')
            .eq('assigned_to', u.id)
            .eq('is_blocked', true);
            
        if (tasks && tasks.length > 0) {
            resMsg += `\n**${u.name}**\n`;
            for (const t of tasks) {
                resMsg += `- Task: ${t.name} (Project: ${t.projects?.name || 'Unknown'})\n  Blocker: ${t.blocker_reason}\n`;
            }
        }
    }
    
    if (resMsg === `Blocker Status:\n`) {
        resMsg = `No blockers currently reported by anyone.`;
    }
    
    return resMsg;
}
