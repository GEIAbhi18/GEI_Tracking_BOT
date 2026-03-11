import { supabase } from '../supabase';

export async function taskListTool(entities) {
    const targetUser = entities.target_user || 'Asif';

    // Fetch user id
    const { data: userData } = await supabase.from('users').select('id').ilike('name', targetUser).limit(1);
    if (!userData || userData.length === 0) return 'No tasks found for user: ' + targetUser;

    const userId = userData[0].id;

    // Fetch all active tasks for user ordered by deadline or created_at to keep index consistent
    // Including updates to get progress and blockers count
    const { data: tasks, error } = await supabase
        .from('tasks')
        .select('*, projects(name), updates(progress, blockers)')
        .eq('assigned_to', userId)
        .order('created_at', { ascending: true });

    if (error || !tasks || tasks.length === 0) {
        return 'No tasks currently assigned to ' + targetUser;
    }

    let msg = `Here are the tasks currently assigned to ${targetUser}:\n\n`;

    const groupedTasks = {};

    tasks.forEach((t, idx) => {
        const number = idx + 1;
        const projName = t.projects?.name || 'No Project';

        if (!groupedTasks[projName]) {
            groupedTasks[projName] = [];
        }

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

    msg += `You can update tasks by typing the number (e.g. "1. 60% done no blocker")`;
    return msg;
}
