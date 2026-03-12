import { supabase } from '../supabase.js';

export async function getUserAndTasks(targetUser = 'Asif') {
    const { data: userData } = await supabase.from('users').select('id').ilike('name', `%${targetUser}%`).limit(1);
    if (!userData || userData.length === 0) return { error: 'No tasks found for user: ' + targetUser };
    const userId = userData[0].id;

    const { data: tasks, error } = await supabase
        .from('tasks')
        .select('*, projects(name), updates(progress, blockers)')
        .eq('assigned_to', userId)
        .order('created_at', { ascending: true });

    if (error) return { error: 'Failed to fetch tasks.' };
    return { userId, tasks: tasks || [] };
}

export function findTaskByEntities(tasks, entities) {
    if (entities.task_id) {
        // Assume task_id represents the 1-based index in the user's task list (derived from "Here are open tasks: 1. ...")
        const match = entities.task_id.toString().match(/\d+/);
        if (match) {
            const idx = parseInt(match[0], 10) - 1;
            if (idx >= 0 && idx < tasks.length) return tasks[idx];
        }
    }
    
    if (entities.task_name) {
        const lowerName = entities.task_name.toLowerCase();
        return tasks.find(t => t.name.toLowerCase().includes(lowerName));
    }
    
    // Fallback: check raw message for a leading number
    if (entities.raw_message) {
        const match = entities.raw_message.match(/^(\d+)/);
        if (match) {
            const idx = parseInt(match[1], 10) - 1;
            if (idx >= 0 && idx < tasks.length) return tasks[idx];
        }
    }

    return null;
}

export function findTicketByEntities(tickets, entities) {
    if (entities.ticket_id || entities.task_id || entities.task_number) {
        const numStr = (entities.ticket_id || entities.task_id || entities.task_number).toString();
        const match = numStr.match(/\d+/);
        if (match) {
            const idx = parseInt(match[0], 10) - 1;
            if (idx >= 0 && idx < tickets.length) return tickets[idx];
        }
    }
    
    // Fallback: check raw message for a leading number
    if (entities.raw_message) {
        const match = entities.raw_message.match(/^(\d+)/);
        if (match) {
            const idx = parseInt(match[1], 10) - 1;
            if (idx >= 0 && idx < tickets.length) return tickets[idx];
        }
    }

    return null;
}

export const fmtDate = (dStr) => {
    if (!dStr) return 'Not set';
    const d = new Date(dStr);
    return `${d.getDate()} ${d.toLocaleString('default', { month: 'short' }) + ' ' + d.getFullYear()}`;
};

export function buildGroupedTasksList(tasks) {
    if (!tasks || tasks.length === 0) return "No tasks found.";
    
    let msg = '';
    const groupedTasks = {};

    tasks.forEach((t, idx) => {
        const number = idx + 1;
        const projName = t.projects?.name || 'No Project';

        if (!groupedTasks[projName]) groupedTasks[projName] = [];

        const updates = t.updates || [];
        const progress = t.progress !== undefined && t.progress !== null ? t.progress : (updates.length > 0 ? Math.max(...updates.map(u => u.progress || 0)) : 0);
        const blockerCount = updates.filter(u => u.blockers && u.blockers.toLowerCase() !== 'none').length;

        groupedTasks[projName].push({
            number,
            name: t.name,
            deadline: t.deadline,
            progress,
            blockerCount
        });
    });

    for (const [projName, projTasks] of Object.entries(groupedTasks)) {
        msg += `**${projName}**\n`;
        projTasks.forEach(t => {
            const dlDate = t.deadline ? new Date(t.deadline) : null;
            const deadlineStr = dlDate ? `${dlDate.getDate()} ${dlDate.toLocaleString('default', { month: 'short' })}` : 'No deadline';
            msg += `${t.number}. ${t.name} – Deadline: ${deadlineStr} | ${t.progress}% done | ${t.blockerCount} blocker(s)\n`;
        });
        msg += `\n`;
    }
    return msg.trim();
}

export const buildOpenTasksList = buildGroupedTasksList;
