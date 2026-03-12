import { supabase } from '../supabase.js';
import { fmtDate, getUserAndTasks, findTaskByEntities, buildGroupedTasksList } from './utils.js';

export async function taskDetailsTool(entities) {
    const targetUser = entities.assignee || 'Asif';
    const result = await getUserAndTasks(targetUser);
    if (result.error) return result.error;

    if (!entities.task_name && !entities.task_id) {
        return `Please select a task to see its details:\n\n${buildGroupedTasksList(result.tasks.filter(t => t.status !== 'completed'))}`;
    }

    const task = findTaskByEntities(result.tasks, entities);
    if (!task) {
        return `Task not found. Please select from the available tasks:\n\n${buildGroupedTasksList(result.tasks.filter(t => t.status !== 'completed'))}`;
    }

    let msg = `**Project:** ${task.projects?.name || 'No Project'}\n`;
    msg += `**Task:** ${task.name}\n`;
    msg += `**Status:** ${task.status}\n`;
    msg += `**Completion:** ${task.progress || 0}%\n`;
    
    // Explicit round 1 requirement format
    msg += `**Planned Start Date:** ${fmtDate(task.planned_start_date)}\n`;
    msg += `**Planned End Date:** ${fmtDate(task.planned_end_date || task.deadline)}\n`;
    msg += `**Actual Start Date:** ${fmtDate(task.actual_start_date)}\n`;
    msg += `**Actual End Date:** ${fmtDate(task.actual_end_date)}\n`;

    // Rule: Delay = comparison between planned vs actual.
    let delayStr = "None";
    const plannedEnd = new Date(task.planned_end_date || task.deadline);
    if (!isNaN(plannedEnd.getTime())) {
        const actualEnd = task.actual_end_date ? new Date(task.actual_end_date) : new Date();
        const delayDays = Math.ceil((actualEnd.getTime() - plannedEnd.getTime()) / (1000 * 3600 * 24));
        if (delayDays > 0) {
            delayStr = `${delayDays} day(s) delayed`;
        } else {
            delayStr = "On track or early";
        }
    }
    msg += `**Delay:** ${delayStr}\n`;
    
    const updates = task.updates || [];
    const blockerCount = updates.filter(u => u.blockers && u.blockers.toLowerCase() !== 'none').length;
    msg += `**Blockers:** ${blockerCount > 0 ? blockerCount : (task.is_blocked ? 1 : 0)}\n`;
    
    // Explicit deliverables check
    const attachments = task.attachments || [];
    if (attachments.length > 0) {
        msg += `**Deliverables:**\n${attachments.map(a => `- ${a}`).join('\n')}\n`;
    }

    return msg;
}
