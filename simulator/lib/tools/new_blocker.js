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
    const { data: tasks, error } = await supabase
        .from('tasks')
        .select('*, projects(name), users(name), updates(blockers)')
        .order('created_at', { ascending: true });

    if (error) return 'Failed to fetch blockers.';

    // Filter tasks that have at least one reported blocker
    const tasksWithBlockers = tasks.filter(t => {
        const hasHistoryBlockers = t.updates && t.updates.some(u => u.blockers && u.blockers.toLowerCase() !== 'none');
        return (t.blocker_reason && t.blocker_reason.toLowerCase() !== 'none') || hasHistoryBlockers;
    });

    if (tasksWithBlockers.length === 0) return 'No blockers currently reported by anyone. 🟢';

    const groupedByProject = {};
    // We want global task numbers based on the full task list
    const taskToNumber = new Map();
    tasks.forEach((t, idx) => taskToNumber.set(t.id, idx + 1));

    tasksWithBlockers.forEach(t => {
        const projectName = t.projects?.name || 'Unassigned Project';
        if (!groupedByProject[projectName]) groupedByProject[projectName] = [];
        groupedByProject[projectName].push(t);
    });

    let resMsg = `🛑 **Project-Wise Blockers:**\n\n`;
    for (const [project, projectTasks] of Object.entries(groupedByProject)) {
        resMsg += `**${project}**\n`;
        projectTasks.forEach(t => {
            const taskNum = taskToNumber.get(t.id);
            const blockerReports = (t.updates || [])
                .filter(u => u.blockers && u.blockers.toLowerCase() !== 'none')
                .map(u => u.blockers);
            
            // Also include current blocker_reason if it's not already in the last history record
            if (t.blocker_reason && t.blocker_reason.toLowerCase() !== 'none') {
                // If it's not the same as any report, add it (usually it IS one of them)
                if (!blockerReports.includes(t.blocker_reason)) {
                    blockerReports.push(t.blocker_reason);
                }
            }

            resMsg += `${taskNum}. **${t.name}** (Assigned to: ${t.users?.name || 'Unknown'})\n`;
            blockerReports.forEach(b => {
                resMsg += `  ⚠️ Blocker: ${b}\n`;
            });
        });
        resMsg += `\n`;
    }

    return resMsg.trim();
}
