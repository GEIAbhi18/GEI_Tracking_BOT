import { supabase } from '../supabase.js';

export async function assignTaskTool(entities) {
    if (!entities.assignee) return "Whom do you want to assign this task to?";
    if (!entities.task_name && !entities.task_id) return "Which task are you referring to?";

    const { data: users, error: uErr } = await supabase.from('users').select('id, name').ilike('name', `%${entities.assignee}%`).limit(1);
    if (uErr || !users || users.length === 0) return `User "${entities.assignee}" not found.`;
    
    // In our simplified mock, any task can just be assigned if we find it in global task list
    const { data: globalTasks } = await supabase.from('tasks').select('id, name');
    
    let task = null;
    if (entities.task_name) {
        task = globalTasks.find(t => t.name.toLowerCase().includes(entities.task_name.toLowerCase()));
    } else if (entities.task_id) {
        // Less likely to know the global ID, but we try
        task = globalTasks.find(t => t.id === entities.task_id);
    }
    
    if (!task) return `I couldn't find a task matching "${entities.task_name}".`;
    
    await supabase.from('tasks').update({ assigned_to: users[0].id }).eq('id', task.id);
    
    return `Assigned "${task.name}" to ${users[0].name}.`;
}
