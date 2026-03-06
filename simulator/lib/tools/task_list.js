import { supabase } from '../supabase';

export async function taskListTool(entities) {
    const targetUser = entities.target_user || 'Asif';

    // Fetch user id
    const { data: userData } = await supabase.from('users').select('id').ilike('name', targetUser).limit(1);
    if (!userData || userData.length === 0) return 'No tasks found for user: ' + targetUser;

    const userId = userData[0].id;

    // Fetch all active tasks for user ordered by deadline or created_at to keep index consistent
    const { data: tasks, error } = await supabase
        .from('tasks')
        .select('*, projects(name)')
        .eq('assigned_to', userId)
        .order('created_at', { ascending: true });

    if (error || !tasks || tasks.length === 0) {
        return 'No tasks currently assigned to ' + targetUser;
    }

    let msg = `Here are the tasks currently assigned to ${targetUser}:\n\n`;

    tasks.forEach((t, idx) => {
        const number = idx + 1;
        const projName = t.projects?.name ? `[${t.projects.name}] ` : '';
        const dlDate = t.deadline ? new Date(t.deadline) : null;
        const deadlineStr = dlDate ? `${dlDate.getDate()} ${dlDate.toLocaleString('default', { month: 'short' })}` : 'No deadline';

        msg += `${number}. ${projName}${t.name} – Deadline: ${deadlineStr}\n`;
    });

    msg += `\nYou can update tasks by typing the number (e.g. "1. 60% done no blocker")`;
    return msg;
}
