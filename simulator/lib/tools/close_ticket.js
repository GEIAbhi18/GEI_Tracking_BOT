import { supabase } from '../supabase.js';
import { findTicketByEntities } from './utils.js';

export async function closeTicketTool(entities) {
    const { data: tickets, error: ticketErr } = await supabase
        .from('tickets')
        .select('id, status, created_at')
        .eq('status', 'open')
        .order('created_at', { ascending: false });

    if (ticketErr || !tickets || tickets.length === 0) {
        return "No open tickets to close.";
    }

    const ticket = findTicketByEntities(tickets, entities);
    if (!ticket) {
        return "I couldn't identify which ticket you want to close. Please use the ticket number.";
    }

    const { error } = await supabase
        .from('tickets')
        .update({ status: 'closed' })
        .eq('id', ticket.id);

    if (error) return "Failed to close the ticket.";

    return `Ticket #${ticket.id.substring(0, 8)} has been marked as resolved and closed.`;
}
