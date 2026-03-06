import { supabase } from '../supabase';

export async function updateNumberedTaskTool(entities) {
    const rawMsg = entities.raw_message || '';
    const targetUser = entities.target_user || 'Asif';

    // Parse "1. 60% done no blocker"
    const match = rawMsg.match(/^(\d+)\.\s+(.*)/i);
    if (!match) return "Could not parse numbered update.";

    const taskIndex = parseInt(match[1], 10) - 1;
    const updateText = match[2];

    // Fetch all active tasks for user to map the index
    const { data: userData } = await supabase.from('users').select('id').ilike('name', targetUser).limit(1);
    if (!userData || userData.length === 0) return 'No tasks found for user: ' + targetUser;
    const userId = userData[0].id;

    const { data: tasks, error } = await supabase
        .from('tasks')
        .select('*, projects(name)')
        .eq('assigned_to', userId)
        .order('created_at', { ascending: true });

    if (error || !tasks || tasks.length <= taskIndex || taskIndex < 0) {
        return `Task number ${taskIndex + 1} not found. Please type "task list" to see your tasks.`;
    }

    const task = tasks[taskIndex];
    let newStatus = task.status;
    let newBlocker = task.is_blocked;
    let newReason = task.blocker_reason;
    let newProgress = 0;

    // Determine info from updateText
    const progressMatch = updateText.match(/(\d+)%\s*(?:completed|done)?/i) || updateText.match(/(\d+)\s*percent/i);
    if (progressMatch) newProgress = parseInt(progressMatch[1], 10);

    if (newProgress === 100) newStatus = 'completed';
    else if (newProgress > 0 && newProgress < 100) newStatus = 'in_progress';

    const isDelay = /(?:delay|blocked|issue|blocker)/i.test(updateText);
    const noBlocker = /(?:no blocker|none|no delay)/i.test(updateText);

    if (isDelay && !noBlocker) {
        newBlocker = true;
        const blockerReasonMatch = updateText.match(/(?:delay|blocked|issue|blocker)[:\s]+([^.]+)/i) || updateText.match(/(.*)/);
        newReason = blockerReasonMatch ? blockerReasonMatch[1].trim() : "Unknown blocker";
        if (newStatus !== 'completed') {
            // Let it be what it is, or force "pending/in_progress" based on previous
            // RAG logic handles "is_blocked = true" as RED.
        }
    } else if (noBlocker) {
        newBlocker = false;
        newReason = null;
    }

    await supabase.from('tasks').update({
        status: newStatus,
        is_blocked: newBlocker,
        blocker_reason: newReason
    }).eq('id', task.id);

    // Also record it into updates table
    await supabase.from('updates').insert([{
        task_id: task.id,
        employee_id: userId,
        progress: newProgress,
        blockers: newBlocker ? newReason : 'none',
        rag: newBlocker ? 'RED' : (newStatus === 'completed' ? 'GREEN' : 'AMBER')
    }]);

    let res = `Task "${task.name}" updated successfully. \nProgress: ${newProgress}%.`;
    if (newBlocker) res += `\nFlagged with blocker: ${newReason}`;
    return res;
}
