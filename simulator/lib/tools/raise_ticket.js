import { supabase } from '../supabase.js';
import { taskListTool } from './task_list';

export async function raiseTicketTool(entities) {
    const targetUser = entities.target_user || 'Asif';
    const message = entities.ticket_message;
    const taskNum = entities.task_number;
    const projectPhrase = entities.ticket_project;

    // If no specific details provided, ask user which task to create ticket for.
    if (!message && !taskNum && !projectPhrase) {
        let msg = "Which task would you like to create a ticket for?\n\nPlease reply with the task number and ticket message (e.g. \"raise ticket for task 1: need more materials\").\n\n";
        const taskListStr = await taskListTool(entities);
        let cleanedList = taskListStr.replace(`Here are the tasks currently assigned to ${targetUser}:\n\n`, '');
        cleanedList = cleanedList.replace('You can update tasks by typing the number (e.g. "1. 60% done no blocker")', '');
        return msg + cleanedList;
    }

    if (taskNum) {
        // Find task based on number
        const { data: userData } = await supabase.from('users').select('id').ilike('name', targetUser).limit(1);
        if (!userData || userData.length === 0) return 'No tasks found for user: ' + targetUser;
        const userId = userData[0].id;

        const { data: tasks, error } = await supabase
            .from('tasks')
            .select('*, projects(name)')
            .eq('assigned_to', userId)
            .order('created_at', { ascending: true });

        const taskIndex = taskNum - 1;
        if (error || !tasks || tasks.length <= taskIndex || taskIndex < 0) {
            return `Task number ${taskNum} not found.`;
        }
        const task = tasks[taskIndex];

        // Insert Ticket
        const { data: ticket, error: tErr } = await supabase.from('tickets').insert([{
            project_id: task.project_id,
            task_id: task.id,
            status: 'open'
        }]).select().single();

        if (tErr) return "Failed to create ticket.";

        if (message) {
            await supabase.from('ticket_messages').insert([{
                ticket_id: ticket.id,
                message_text: message,
            }]);
        }

        return `Ticket #${ticket.id.substring(0,8)} created for task "${task.name}" successfully:\n\n${message || "No message provided."}`;
    }

    // Attempting Project-based ticket
    if (!projectPhrase || !message) {
         return "I need more details. E.g. \"raise ticket for project top terrace called 'need materials'\".";
    }

    const { data: projData } = await supabase.from('projects').select('id, name');
    let projId = null;
    let projNameMatch = null;
    if (projData) {
        for (const p of projData) {
            if (projectPhrase.toLowerCase().includes(p.name.toLowerCase())) {
                projId = p.id;
                projNameMatch = p.name;
                break;
            }
        }
    }

    if (!projId && projData && projData.length > 0) {
        projId = projData[0].id;
        projNameMatch = projData[0].name;
    }
    if (!projId) return "Could not find a project to attach the ticket to.";

    const { data: ticket, error: tErr } = await supabase.from('tickets').insert([{
        project_id: projId,
        status: 'open'
    }]).select().single();

    if (tErr) return "Failed to create ticket.";

    await supabase.from('ticket_messages').insert([{
        ticket_id: ticket.id,
        message_text: message,
    }]);

    return `Ticket #${ticket.id.substring(0,8)} created for ${projNameMatch} successfully:\n\n${message}`;
}
