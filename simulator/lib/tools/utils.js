import { supabase } from '../supabase.js';

export async function getUserAndTasks(targetUser = 'Asif') {
    const { data: users } = await supabase.from('users').select('id, name').ilike('name', `%${targetUser}%`);
    if (!users || users.length === 0) return { error: 'User not found in database: ' + targetUser };
    
    // If multiple users match (e.g. duplicate Asifs), find the one who actually has tasks
    for (const user of users) {
        const { data: tasks, error } = await supabase
            .from('tasks')
            .select('*, projects(name), updates(progress, blockers)')
            .eq('assigned_to', user.id)
            .order('created_at', { ascending: true });
            
        if (tasks && tasks.length > 0) {
            return { userId: user.id, tasks };
        }
    }

    // Fallback: Use the first one found if none have tasks
    return { userId: users[0].id, tasks: [] };
}

export function findTaskByEntities(tasks, entities) {
    if (!tasks || tasks.length === 0) return null;

    // 1. Try task_id/task_number which are often pure numbers
    const idVal = entities.task_id || entities.task_number;
    if (idVal) {
        const match = idVal.toString().match(/\d+/);
        if (match) {
            const idx = parseInt(match[0], 10) - 1;
            if (idx >= 0 && idx < tasks.length) return tasks[idx];
        }
    }
    
    // 2. Try task_name - check for "Task 1" style references
    if (entities.task_name) {
        const lowerName = entities.task_name.toLowerCase().trim();
        
        // Handle "Task 1", "Task #1", etc.
        const taskRefMatch = lowerName.match(/^task\s*#?(\d+)$/);
        if (taskRefMatch) {
            const idx = parseInt(taskRefMatch[1], 10) - 1;
            if (idx >= 0 && idx < tasks.length) return tasks[idx];
        }

        // Handle pure number strings
        if (/^\d+$/.test(lowerName)) {
            const idx = parseInt(lowerName, 10) - 1;
            if (idx >= 0 && idx < tasks.length) return tasks[idx];
        }

        // Fuzzy inclusion match
        const found = tasks.find(t => t.name.toLowerCase().includes(lowerName));
        if (found) return found;
    }
    
    // 3. Last fallback: check raw message for any leading number if other entities failed
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
        
        let blockerCount = updates.filter(u => u.blockers && u.blockers.toLowerCase() !== 'none').length;
        if (t.blocker_reason && t.blocker_reason.toLowerCase() !== 'none' && !updates.some(u => u.blockers === t.blocker_reason)) {
            blockerCount += 1;
        }

        groupedTasks[projName].push({
            number,
            name: t.name,
            deadline: t.deadline,
            progress,
            blockerCount,
            attachments: t.attachments
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
