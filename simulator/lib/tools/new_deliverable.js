import { supabase } from '../supabase.js';
import { getUserAndTasks, findTaskByEntities, buildGroupedTasksList } from './utils.js';

export async function uploadDeliverableTool(entities) {
    const targetUser = entities.assignee || 'Asif';
    const result = await getUserAndTasks(targetUser);
    if (result.error) return result.error;

    if (!entities.deliverable_url) {
        return 'Please provide the URL of the deliverable (image, report, etc.).';
    }

    const task = findTaskByEntities(result.tasks, entities);
    if (!task) {
        return `Please select which task this deliverable belongs to:\n\n${buildGroupedTasksList(result.tasks)}`;
    }

    const attachments = task.attachments ? [...task.attachments, entities.deliverable_url] : [entities.deliverable_url];

    await supabase.from('tasks').update({
        attachments
    }).eq('id', task.id);

    // Save update
    await supabase.from('updates').insert([{
        task_id: task.id,
        employee_id: result.userId,
        progress: task.progress || 0,
        blockers: task.blocker_reason || 'none',
        images: [entities.deliverable_url],
        rag: task.progress === 100 ? 'GREEN' : 'AMBER'
    }]);

    return `Added deliverable to task "${task.name}".`;
}
