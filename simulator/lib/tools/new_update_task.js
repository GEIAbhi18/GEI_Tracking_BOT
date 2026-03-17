import { supabase } from '../supabase.js';
import { getUserAndTasks, findTaskByEntities, fmtDate, buildGroupedTasksList } from './utils.js';

export async function updateTaskTool(entities) {
    const targetUser = entities.assignee || 'Asif';
    const result = await getUserAndTasks(targetUser);
    if (result.error) return result.error;

    const task = findTaskByEntities(result.tasks, entities);
    if (!task) {
        return `Please specify which task to update:\n\n${buildGroupedTasksList(result.tasks)}`;
    }

    let changed = false;
    let resMsg = `Task "${task.name}" updated successfully.`;
    
    let payload = {};

    let perc = null;
    if (entities.completion_percent) {
        perc = parseInt(entities.completion_percent, 10);
    } else if (entities.raw_message) {
        const pMatch = entities.raw_message.match(/(\d+)%\s*(?:completed|done)?/i) || entities.raw_message.match(/(\d+)\s*percent/i);
        if (pMatch) perc = parseInt(pMatch[1], 10);
    }

    let newProgress = task.progress || 0;
    if (perc !== null && !isNaN(perc)) {
        if (perc === 100) {
            const hasImages = (entities.attachments && entities.attachments.length > 0) || (task.attachments && task.attachments.length > 0);
            if (!hasImages) {
                return `To mark task "${task.name}" (Project: ${task.projects?.name || 'Unknown'}) as 100% complete, please upload an image proof (photo of the work). 📸`;
            }
            payload.status = 'completed';
        } else if (perc > 0 && task.status !== 'completed') {
            payload.status = 'in_progress';
        }
        newProgress = perc;
        changed = true;
        resMsg = `Task "${task.name}" updated successfully.\nCompletion updated to ${perc}%`;
    }
    
    let rawDeadline = entities.deadline;
    if (!rawDeadline && entities.raw_message) {
        const dMatch = entities.raw_message.match(/(?:deadline)\s+(?:to\s+)?([0-9]{1,2}\s+[a-zA-Z]+)/i);
        if (dMatch) rawDeadline = dMatch[1];
    }

    if (rawDeadline) {
        // try parse deadline
        const newDeadline = new Date(rawDeadline + ' 2026').toISOString();
        if (newDeadline !== 'Invalid Date') {
            payload.deadline = newDeadline;
            payload.planned_end_date = newDeadline;
            changed = true;
            resMsg += `\nDeadline changed to: ${fmtDate(newDeadline)}`;
        }
    }

    if (!changed) {
        return `I'm not sure what to update. Which field did you want to change for "${task.name}"?`;
    }

    // Set actual dates
    if (payload.status === 'completed' && !task.actual_end_date) {
        payload.actual_end_date = new Date().toISOString();
    }
    if ((newProgress > 0 || payload.status === 'in_progress') && !task.actual_start_date) {
        payload.actual_start_date = new Date().toISOString();
    }

    if (perc !== null) {
        payload.progress = newProgress;
    }

    if (entities.attachments && entities.attachments.length > 0) {
        // Merge or replace attachments
        payload.attachments = [...(task.attachments || []), ...entities.attachments];
    }

    const { error: updateErr } = await supabase.from('tasks').update(payload).eq('id', task.id);
    if (updateErr) {
        console.error("Task update error:", updateErr);
        // Fallback: try updating without 'progress' or 'deadline' if they are missing columns
        // But for now, we want to know if it failed.
        return `Failed to update task record: ${updateErr.message}`;
    }

    // Add update entry
    const { error: insertErr } = await supabase.from('updates').insert([{
        task_id: task.id,
        employee_id: result.userId,
        progress: newProgress,
        blockers: task.blocker_reason || 'none',
        images: entities.attachments || [],
        rag: payload.status === 'completed' ? 'GREEN' : 'AMBER'
    }]);

    if (insertErr) {
        console.error("Update history insert error:", insertErr);
        return `Task updated, but failed to log history: ${insertErr.message}`;
    }

    return resMsg;
}

export async function markDoneTool(entities) {
    const targetUser = entities.assignee || 'Asif';
    const result = await getUserAndTasks(targetUser);
    if (result.error) return result.error;

    // Filter open tasks
    const openTasks = result.tasks.filter(t => t.status !== 'completed');

    const task = findTaskByEntities(openTasks, entities);
    if (!task) {
        return `Please provide the project and task name (or select by number) to mark it complete. Also upload an image proof (photo of the work) to finalize. 📸\n\n${buildGroupedTasksList(openTasks)}`;
    }

    const hasImages = (entities.attachments && entities.attachments.length > 0) || (task.attachments && task.attachments.length > 0);
    if (!hasImages) {
        return `To mark task "${task.name}" (Project: ${task.projects?.name || 'Unknown'}) as 100% complete, please upload an image proof (photo of the work). 📸`;
    }

    const payload = {
        status: 'completed',
        progress: 100,
        attachments: [...(task.attachments || []), ...(entities.attachments || [])]
    };
    if (!task.actual_start_date) payload.actual_start_date = new Date().toISOString();
    if (!task.actual_end_date) payload.actual_end_date = new Date().toISOString();

    const { error: updateErr } = await supabase.from('tasks').update(payload).eq('id', task.id);
    if (updateErr) return `Failed to mark task as done: ${updateErr.message}`;

    const { error: insertErr } = await supabase.from('updates').insert([{
        task_id: task.id,
        employee_id: result.userId,
        progress: 100,
        blockers: 'none',
        images: entities.attachments || [],
        rag: 'GREEN'
    }]);

    if (insertErr) return `Task marked as done, but history log failed: ${insertErr.message}`;

    return `Task "${task.name}" has been marked as 100% complete.\nDates Breakdown:\n- Planned Start Date: ${fmtDate(task.planned_start_date)}\n- Planned End Date: ${fmtDate(task.planned_end_date || task.deadline)}\n- Actual Start Date: ${fmtDate(payload.actual_start_date || task.actual_start_date)}\n- Actual End Date: ${fmtDate(payload.actual_end_date)}`;
}
