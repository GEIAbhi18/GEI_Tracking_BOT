import { supabase } from '../supabase.js';

export async function createTaskTool(entities) {
    const rawMsg = entities.raw_message || '';
    const creator = entities.target_user || 'Kanav';

    // Check for "Task:" pattern or implicit first line formatting
    let taskName = null;
    let deadlineStr = null;
    let projectName = null;

    const lines = rawMsg.split('\n').map(l => l.trim()).filter(l => l);

    // Pattern matches
    const taskMatch = rawMsg.match(/Task\s*:?\s*(.+?)(?:\n|$)/i);
    const deadlineMatch = rawMsg.match(/End date\s*:?\s*(.+?)(?:\n|$)/i) || rawMsg.match(/Deadline\s*:?\s*(.+?)(?:\n|$)/i);
    const projMatch = rawMsg.match(/Project\s*:?\s*(.+?)(?:\n|$)/i) || rawMsg.match(/in project\s*:?\s*(.+?)(?:\n|$)/i);

    if (taskMatch) {
        taskName = taskMatch[1].trim();
    } else if (lines.length >= 2 && !rawMsg.match(/create task/i)) {
        // If no explicit 'Task:' but user pasted lines like:
        // To live the telegram bot
        // End date 15 Mar
        // Project : Test Project
        taskName = lines[0]; // First line is the task name
    } else {
        // Single sentence fallback
        const inlineMatch = rawMsg.match(/create task (.*?) (?:for|in|deadline)/i) || rawMsg.match(/create a task for (.*?) now/i);
        if (inlineMatch) taskName = inlineMatch[1].trim();
    }

    deadlineStr = deadlineMatch ? deadlineMatch[1].trim() : null;
    projectName = projMatch ? projMatch[1].trim() : 'Top Terrace';

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

    // Try finding assignee user
    let assigneeName = 'Asif';
    if (/for kanav/i.test(rawMsg)) assigneeName = 'Kanav';
    const { data: userData } = await supabase.from('users').select('id').ilike('name', `%${assigneeName}%`).limit(1);
    const assignedToId = (userData && userData.length) ? userData[0].id : null;

    // Create task
    let deadlineDate = null;
    if (deadlineStr) {
        deadlineDate = new Date(`${deadlineStr} 2026`); // Simplified handling matching GEI timeline
    }

    await supabase.from('tasks').insert([{
        project_id: projectId,
        assigned_to: assignedToId,
        name: taskName,
        deadline: deadlineDate ? deadlineDate.toISOString() : null,
        planned_start_date: new Date().toISOString(),
        planned_end_date: deadlineDate ? deadlineDate.toISOString() : null,
        actual_start_date: null,
        actual_end_date: null,
        status: 'pending'
    }]);

    return `Task "${taskName}" has been successfully created and assigned to ${assigneeName}! Remember to view it using the task list!`;
}
