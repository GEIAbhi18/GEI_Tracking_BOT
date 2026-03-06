import { supabase } from '../supabase';

export async function createTaskTool(entities) {
    const rawMsg = entities.raw_message || '';
    const creator = entities.target_user || 'Kanav';

    // Example: "Task Waterproffing \n End date 08/03/2025 \n Project top terrace"
    const taskMatch = rawMsg.match(/Task:?\s*(.+?)(?:\n|$)/i) || rawMsg.match(/create task (.*?) (?:for|in|deadline)/i) || rawMsg.match(/create a task for (.*?) now/i);
    const deadlineMatch = rawMsg.match(/End date:?\s*(.+?)(?:\n|$)/i) || rawMsg.match(/Deadline:?\s*(.+?)(?:\n|$)/i);
    const projMatch = rawMsg.match(/Project:?\s*(.+?)(?:\n|$)/i) || rawMsg.match(/in project:?\s*(.+?)(?:\n|$)/i);

    // We assume default project if none specified or we fail stringency
    let projectName = projMatch ? projMatch[1].trim() : 'Top Terrace';
    const taskName = taskMatch ? taskMatch[1].trim() : null;
    let deadlineStr = deadlineMatch ? deadlineMatch[1].trim() : null;

    if (!taskName) {
        return "To create a task, please use this format:\n\nTask: <Name>\nEnd date: <DD MMM>\nProject: <Name>";
    }

    // Try finding the project
    let { data: projData } = await supabase.from('projects').select('id').ilike('name', `%${projectName}%`).limit(1);
    if (!projData || projData.length === 0) {
        // Fallback to exactly 'Top Terrace'
        const { data: fallback } = await supabase.from('projects').select('id').eq('name', 'Top Terrace').limit(1);
        if (fallback?.length) projData = fallback;
        else return "Could not locate project to assign. Please ensure the project exists.";
    }

    const projectId = projData[0].id;

    // Create task
    let deadlineDate = null;
    if (deadlineStr) {
        deadlineDate = new Date(`${deadlineStr} 2026`); // Simplified handling matching GEI timeline
    }

    await supabase.from('tasks').insert([{
        project_id: projectId,
        name: taskName,
        deadline: deadlineDate ? deadlineDate.toISOString() : null,
        status: 'pending'
    }]);

    return `Task "${taskName}" has been successfully created in Project. Remember to view it using the task list!`;
}
