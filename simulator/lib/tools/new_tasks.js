import { getUserAndTasks, buildGroupedTasksList } from './utils.js';

function filterTasks(tasks, filters) {
    if (!filters) return tasks;
    
    let filtered = tasks;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    
    // Status filter
    if (filters.status) {
        if (filters.status === 'completed') filtered = filtered.filter(t => t.status === 'completed');
        else if (filters.status === 'pending') filtered = filtered.filter(t => t.status !== 'completed');
    }

    // Assignee filter
    // Assignee is already handled by pulling tasks for targetUser, but if all were requested:
    // This is optional if we already pulled specific user's tasks.

    // Progress filter
    if (filters.progress_lt !== undefined && filters.progress_lt !== null) {
        filtered = filtered.filter(t => (t.progress || 0) < filters.progress_lt);
    }

    // Blockers filter
    if (filters.has_blockers) {
        filtered = filtered.filter(t => t.is_blocked === true);
    }

    // No deadline include filter logic
    // If range is specified, we filter out null deadlines unless include_no_deadline is true
    if (filters.range) {
        filtered = filtered.filter(t => {
            if (!t.deadline) return filters.include_no_deadline === true;
            
            const dDate = new Date(t.deadline);
            const dlDateOnly = new Date(dDate.getFullYear(), dDate.getMonth(), dDate.getDate());
            
            if (filters.range === 'overdue') {
                return dlDateOnly < today && t.status !== 'completed';
            } else if (filters.range === 'today') {
                return dlDateOnly.getTime() === today.getTime();
            } else if (filters.range === 'tomorrow') {
                const tomorrow = new Date(today);
                tomorrow.setDate(tomorrow.getDate() + 1);
                return dlDateOnly.getTime() === tomorrow.getTime();
            } else if (filters.range === 'this_week') {
                const nextWeek = new Date(today);
                nextWeek.setDate(nextWeek.getDate() + 7);
                return dlDateOnly >= today && dlDateOnly <= nextWeek;
            } else if (filters.range === 'custom_range') {
                if (filters.start_date && filters.end_date) {
                    const start = new Date(filters.start_date);
                    const end = new Date(filters.end_date);
                    return dDate >= start && dDate <= end;
                }
            }
            return true;
        });
    } else if (filters.include_no_deadline) {
        filtered = filtered.filter(t => !t.deadline);
    }

    return filtered;
}

export async function getTasksByDateTool(entities) {
    const rawMessage = (entities.raw_message || '').toLowerCase();
    const requester = entities.userName || 'Asif';
    const filters = entities.query_filters || {};

    const explicitAssignee = (filters.assignee || entities.assignee || '').toLowerCase();
    let isAllTasksRequested = rawMessage.includes('all tasks') || rawMessage.includes('all task') || explicitAssignee === 'all';
    
    // Kanav is a manager. If he doesn't explicitly restrict to 'kanav' or 'asif', default to All Tasks.
    if (requester === 'Kanav' && !explicitAssignee) {
        isAllTasksRequested = true;
    }

    if (requester === 'Kanav' && isAllTasksRequested && explicitAssignee !== 'kanav' && explicitAssignee !== 'asif') {
        let msg = `**Tasks Assigned to Kanav**\n`;
        const kanavResult = await getUserAndTasks('Kanav');
        if (kanavResult.error || !kanavResult.tasks || kanavResult.tasks.length === 0) {
            msg += `No Tasks\n`;
        } else {
            const fTasks = filterTasks(kanavResult.tasks, filters);
            msg += fTasks.length ? buildGroupedTasksList(fTasks) + '\n' : 'No tasks match criteria\n';
        }

        msg += `\n**Tasks Assigned to Asif**\n`;
        const asifResult = await getUserAndTasks('Asif');
        if (asifResult.error || !asifResult.tasks || asifResult.tasks.length === 0) {
            msg += `No tasks`;
        } else {
            const fTasks = filterTasks(asifResult.tasks, filters);
            msg += fTasks.length ? buildGroupedTasksList(fTasks) : 'No tasks match criteria';
        }

        return msg.trim();
    }

    const targetUser = explicitAssignee || 'Asif';
    const result = await getUserAndTasks(targetUser);
    if (result.error) return result.error;

    const filteredTasks = filterTasks(result.tasks, filters);
    
    if (filteredTasks.length === 0) {
        return `No tasks found matching criteria for ${targetUser}`;
    }

    let msg = `Here are the tasks currently matching your query for ${targetUser}:\n\n`;
    msg += buildGroupedTasksList(filteredTasks);
    return msg.trim();
}

// Backward compatibility explicitly
export const getTasksTool = getTasksByDateTool;
