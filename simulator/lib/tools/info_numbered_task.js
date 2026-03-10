import { supabase } from '../supabase';

export async function infoNumberedTaskTool(entities) {
    const targetUser = entities.target_user || 'Asif';
    const taskNumber = entities.task_number;

    if (!taskNumber) {
        return "Could not understand which task you want info about. Please say 'show me info about task 1'.";
    }

    const taskIndex = parseInt(taskNumber, 10) - 1;

    // Fetch user id
    const { data: userData } = await supabase.from('users').select('id').ilike('name', targetUser).limit(1);
    if (!userData || userData.length === 0) return 'No tasks found for user: ' + targetUser;

    const userId = userData[0].id;

    // Fetch all active tasks for user ordered by deadline or created_at to keep index consistent
    const { data: tasks, error } = await supabase
        .from('tasks')
        .select('*, projects(name), updates(progress, blockers, images)')
        .eq('assigned_to', userId)
        .order('created_at', { ascending: true });

    if (error || !tasks || tasks.length <= taskIndex || taskIndex < 0) {
        return `Task number ${taskIndex + 1} not found. Please type "task list" to see your tasks.`;
    }

    const t = tasks[taskIndex];
    const projName = t.projects?.name || 'No Project';

    const fmtDate = (dStr) => {
        if (!dStr) return 'Not set';
        const d = new Date(dStr);
        return `${d.getDate()} ${d.toLocaleString('default', { month: 'short' })}`;
    };

    const plannedStart = fmtDate(t.planned_start_date);
    const plannedEnd = fmtDate(t.planned_end_date || t.deadline);
    const actualStart = fmtDate(t.actual_start_date || t.created_at);
    const actualEnd = fmtDate(t.actual_end_date);

    // Get blockers from updates
    const updates = t.updates || [];
    const blockerUpdates = updates.filter(u => u.blockers && u.blockers.toLowerCase() !== 'none');

    let blockersStr = 'None';
    if (t.is_blocked || blockerUpdates.length > 0) {
        blockersStr = t.blocker_reason ? t.blocker_reason : '';
        if (blockerUpdates.length > 0) {
            blockersStr += (blockersStr ? ', ' : '') + blockerUpdates.map(u => u.blockers).join(', ');
        }
    }

    let completionPercent = 0;
    if (updates.length > 0) {
        completionPercent = Math.max(...updates.map(u => u.progress || 0));
    }

    const allImages = updates.flatMap(u => (u.images || []));
    let attachmentsStr = 'None';
    if (allImages.length > 0 || (t.attachments && t.attachments.length > 0)) {
        attachmentsStr = 'Yes (Images/Reports attached)';
    }

    let msg = `Task ${taskIndex + 1} info:\n`;
    msg += `Project name: ${projName}\n`;
    msg += `Task: ${t.name}\n`;
    msg += `Completion: ${completionPercent}%\n`;
    msg += `Planned start date: ${plannedStart}\n`;
    msg += `Planned end date: ${plannedEnd}\n`;
    msg += `Actual Start date: ${actualStart}\n`;
    msg += `Actual End date: ${actualEnd}\n`;
    msg += `Blockers: ${blockersStr}\n`;
    msg += `Attachments/Deliverables: ${attachmentsStr}\n`;

    return msg;
}
