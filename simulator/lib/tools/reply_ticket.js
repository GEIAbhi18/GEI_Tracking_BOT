import { supabase } from '../supabase.js';
import { findTicketByEntities } from './utils.js';

export async function replyTicketTool(entities) {
    const { data: tickets, error: ticketErr } = await supabase
        .from('tickets')
        .select('id, status, created_at')
        .eq('status', 'open')
        .order('created_at', { ascending: false });

    if (ticketErr || !tickets || tickets.length === 0) {
        return "Couldn't find any open tickets to reply to.";
    }

    const ticket = findTicketByEntities(tickets, entities);
    if (!ticket) {
        return "I couldn't identify which ticket you are replying to. Please use the number (e.g., '1. message').";
    }

    const replyText = entities.ticket_message || entities.raw_message;
    if (!replyText || replyText.match(/^\d+\.?$/)) {
        return "Please provide a message for your reply.";
    }

    // Clean reply text if it starts with "N. "
    const cleanedReply = replyText.replace(/^\d+\.\s*/, '').trim();

    const userName = entities.userName || 'Asif';
    const { data: userData } = await supabase.from('users').select('id').ilike('name', `%${userName}%`).limit(1);
    const userId = userData?.[0]?.id;

    const { error: replyErr } = await supabase.from('ticket_messages').insert([{
        ticket_id: ticket.id,
        message_text: cleanedReply,
        sender_id: userId
    }]);

    if (replyErr) return "Failed to post reply.";

    // Fetch updated ticket history for display
    const { data: updatedTicket } = await supabase
        .from('tickets')
        .select(`
            id,
            status,
            created_at,
            projects (name),
            tasks (name),
            users:created_by (name),
            ticket_messages (
                message_text,
                timestamp,
                sender:sender_id (name)
            )
        `)
        .eq('id', ticket.id)
        .single();

    if (!updatedTicket) return `Reply attached to ticket successfully by ${userName}.`;

    const pName = updatedTicket.projects?.name || 'N/A';
    const tName = updatedTicket.tasks?.name || 'N/A';
    const uName = updatedTicket.users?.name || 'Unknown';
    const date = new Date(updatedTicket.created_at);
    const dateStr = isNaN(date.getTime()) ? 'Recently' : `${date.getDate()} ${date.toLocaleString('default', { month: 'short' })}`;

    const sortedMessages = (updatedTicket.ticket_messages || []).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    let historyText = sortedMessages.map(m => `   • ${m.sender?.name || 'Unknown'}: ${m.message_text}`).join('\n');

    return `✅ Reply saved to Ticket\n\n**Project: ${pName}**\n   Task: ${tName}\n   By: ${uName} | Date: ${dateStr}\n   --- History ---\n${historyText}`;
}
