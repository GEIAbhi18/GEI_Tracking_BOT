import { supabase } from '../supabase.js';
import { getUserAndTasks, findTaskByEntities } from './utils.js';

export async function createTicketTool(entities) {
    // If the user just said "raise ticket", don't treat that as the issue name
    const rawMsg = (entities.raw_message || "").toLowerCase().trim();
    const isGeneric = ['raise ticket', 'create ticket', 'new ticket', 'issue'].includes(rawMsg);
    
    let ticketMsg = entities.ticket_name;
    if (isGeneric || !ticketMsg) ticketMsg = null;

    if (!entities.project_name) {
        return 'Which project is this ticket for?';
    }

    if (!ticketMsg) {
        return 'What is the exact issue or concern you want to raise?';
    }

    const { data: projData, error: projErr } = await supabase
        .from('projects')
        .select('*')
        .ilike('name', `%${entities.project_name}%`)
        .limit(1);

    if (projErr || !projData || projData.length === 0) {
        return `Project "${entities.project_name}" not found. Cannot create ticket.`;
    }

    const projId = projData[0].id;
    let taskId = null;

    if (entities.task_name || entities.task_id) {
        const targetUser = entities.assignee || 'Asif';
        const result = await getUserAndTasks(targetUser);
        if (!result.error) {
            const task = findTaskByEntities(result.tasks, entities);
            if (task) taskId = task.id;
        }
    }

    // Get current user ID
    const senderName = entities.userName || entities.assignee || 'Asif';
    const { data: userData } = await supabase.from('users').select('id').ilike('name', `%${senderName}%`).limit(1);
    const userId = userData?.[0]?.id;

    // Get Kanav ID for assignment
    const { data: kanav } = await supabase.from('users').select('id').eq('name', 'Kanav').limit(1);
    const kanavId = kanav[0]?.id;

    const { data: ticket, error: tErr } = await supabase.from('tickets').insert([{
        project_id: projId,
        task_id: taskId,
        created_by: userId || kanavId,
        assigned_to: kanavId
    }]).select('id');

    if (tErr) return 'Failed to raise ticket.';

    const ticketId = ticket[0].id;

    await supabase.from('ticket_messages').insert([{
        ticket_id: ticketId,
        message_text: ticketMsg,
        sender_id: userId || kanavId
    }]);

    return `Ticket for project "${projData[0].name}" has been generated successfully.`;
}

async function getUserId(name) {
    const { data } = await supabase.from('users').select('id').ilike('name', `%${name}%`).limit(1);
    return data && data.length > 0 ? data[0].id : null;
}
