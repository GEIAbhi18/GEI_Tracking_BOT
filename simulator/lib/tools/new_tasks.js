import { getUserAndTasks, buildGroupedTasksList } from './utils.js';

export async function getTasksTool(entities) {
    const targetUser = entities.assignee || 'Asif';
    const result = await getUserAndTasks(targetUser);
    if (result.error) return result.error;

    const { tasks } = result;
    if (tasks.length === 0) return `No tasks currently assigned to ${targetUser}`;

    let msg = `Here are the tasks currently assigned to ${targetUser}:\n\n`;
    msg += buildGroupedTasksList(tasks);
    return msg.trim();
}
