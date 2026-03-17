import { supabase } from '../supabase.js';
import { taskListTool } from './task_list';

export async function promptTaskTool(entities, actionType) {
    const targetUser = entities.target_user || 'Asif';
    
    let msg = "";
    if (actionType === 'complete') {
        msg = `Which task should I complete?\n\nPlease reply with the number (e.g. "1").\n\n`;
    } else if (actionType === 'update') {
        msg = `Which task would you like to update?\n\nPlease reply with the task number and update (e.g. "1. 50% done").\n\n`;
    } else if (actionType === 'blocker') {
        msg = `Which task has a blocker?\n\nPlease reply with the task number and blocker (e.g. "1. blocker: no material").\n\n`;
    }

    // Append the list of open tasks
    const taskListStr = await taskListTool(entities);
    
    // Replace the default taskListTool message if needed
    let cleanedList = taskListStr.replace(`Here are the tasks currently assigned to ${targetUser}:\n\n`, '');
    cleanedList = cleanedList.replace('You can update tasks by typing the number (e.g. "1. 60% done no blocker")', '');
    
    return msg + cleanedList;
}

export async function promptTaskCompleteTool(entities) {
    return await promptTaskTool(entities, 'complete');
}
export async function promptTaskUpdateTool(entities) {
    return await promptTaskTool(entities, 'update');
}
export async function promptTaskBlockerTool(entities) {
    return await promptTaskTool(entities, 'blocker');
}
