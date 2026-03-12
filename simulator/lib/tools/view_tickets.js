import { supabase } from '../supabase.js';

export async function viewTicketsTool(entities) {
    const { data: tickets, error } = await supabase
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
        .eq('status', 'open')
        .order('created_at', { ascending: false });

    if (error || !tickets || tickets.length === 0) {
        return "No open tickets found.";
    }

    let msg = "Here are the open tickets:\n\n";
    tickets.forEach((t, i) => {
        const pName = t.projects?.name || "Unknown Project";
        const tName = t.tasks?.name || "N/A";
        const uName = t.users?.name || "Unknown";
        const date = new Date(t.created_at);
        const dateStr = isNaN(date.getTime()) ? 'Recently' : `${date.getDate()} ${date.toLocaleString('default', { month: 'short' })}`;

        msg += `${i + 1}. **Project: ${pName}**\n   Task: ${tName}\n   By: ${uName} | Date: ${dateStr}\n   --- History ---\n`;
        
        const sortedMessages = (t.ticket_messages || []).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        if (sortedMessages.length === 0) {
            msg += `   (No messages)\n`;
        } else {
            sortedMessages.forEach(m => {
                const sender = m.sender?.name || "Unknown";
                msg += `   • ${sender}: ${m.message_text}\n`;
            });
        }
        msg += `\n`;
    });

    msg += `*To reply, type: "number. message" (e.g. "1. Working on it")*\n*To close, type: "close ticket number" (e.g. "close ticket 1")*`;

    return msg.trim();
}
