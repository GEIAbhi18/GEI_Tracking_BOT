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
    } else if (noBlocker) {
        newBlocker = false;
        newReason = null;
    }

    // Check for new deadline
    let newDeadline = null;
    const deadlineMatch = updateText.match(/(?:new deadline|update deadline|set deadline|deadline)(?:\s+is|\s+to)?\s+([0-9]{1,2}\s+[a-zA-Z]+)(?:$|\n|\.)/i) || updateText.match(/(?:new deadline|update deadline|set deadline|deadline)(?:\s+is|\s+to)?\s+(.+?)(?:$|\n|\.)/i);
    if (deadlineMatch) {
        const dStr = deadlineMatch[1].trim();
        // Just parsing whatever they give + 2026. Or simply use the string if it's parseable.
        newDeadline = new Date(`${dStr} 2026`).toISOString();
    }

    // Check for attachments/deliverables
    let newAttachments = null;
    const attachmentMatch = updateText.match(/(?:attached|attachment|deliverable|proof)[s]?[:\s]+(\S+)/i);
    if (attachmentMatch) {
        newAttachments = [attachmentMatch[1].trim()];
    }

    // Enforce image proof for completed tasks
    if (newProgress === 100 && !newAttachments) {
        return `Please provide an image proof to mark task "${task.name}" as 100% completed. (e.g., "1. 100% done attached: https://link-to-image.com")`;
    }

    let actualStartDate = task.actual_start_date;
    if (newProgress > 0 && !actualStartDate) {
        actualStartDate = new Date().toISOString();
    }

    let actualEndDate = task.actual_end_date;
    if (newStatus === 'completed' && !actualEndDate) {
        actualEndDate = new Date().toISOString();
    }

    let payload = {
        status: newStatus,
        is_blocked: newBlocker,
        blocker_reason: newReason,
        actual_start_date: actualStartDate,
        actual_end_date: actualEndDate
    };
    if (newAttachments) {
        // if Postgres array, we either append or overwrite. 
        // We'll just overwrite or let the simulator handle it
        payload.attachments = task.attachments ? [...task.attachments, ...newAttachments] : newAttachments;
    }
    if (newDeadline) {
        payload.deadline = newDeadline;
        payload.planned_end_date = newDeadline;
    }

    await supabase.from('tasks').update(payload).eq('id', task.id);

    // Also record it into updates table
    await supabase.from('updates').insert([{
        task_id: task.id,
        employee_id: userId,
        progress: newProgress,
        blockers: newBlocker ? newReason : 'none',
        images: newAttachments || [],
        rag: newBlocker ? 'RED' : (newStatus === 'completed' ? 'GREEN' : 'AMBER')
    }]);

    const fmtDate = (dStr) => {
        if (!dStr) return 'Not set';
        const d = new Date(dStr);
        return `${d.getDate()} ${d.toLocaleString('default', { month: 'short' }) + ' ' + d.getFullYear()}`;
    };

    let res = `Task "${task.name}" updated successfully.`;
    if (progressMatch) res += `\nProgress: ${newProgress}%.`;
    if (newBlocker) res += `\nFlagged with blocker: ${newReason}`;
    if (newDeadline) res += `\nDeadline explicitly changed to: ${fmtDate(newDeadline)}`;
    if (newAttachments) res += `\nAttached Proof: ${newAttachments.join(', ')}`;

    res += `\n\nDates Breakdown:`;
    res += `\n- Planned Start Date: ${fmtDate(task.planned_start_date)}`;
    res += `\n- Planned End Date: ${fmtDate(newDeadline || task.planned_end_date || task.deadline)}`;
    res += `\n- Actual Start Date: ${fmtDate(actualStartDate)}`;
    res += `\n- Actual End Date: ${fmtDate(actualEndDate)}`;

    return res;
}
