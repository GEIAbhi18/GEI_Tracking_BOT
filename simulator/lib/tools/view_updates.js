import { supabase } from '../supabase.js';

export async function viewUpdatesTool(entities) {
    const rawMsg = entities.raw_message || '';

    // Attempt to extract project if they asked 'updates for x'
    const projMatch = rawMsg.match(/updates for (.*)/i) || rawMsg.match(/updates on (.*)/i);
    const projectName = projMatch ? projMatch[1].trim() : null;

    let query = supabase.from('updates').select('*').order('timestamp', { ascending: false }).limit(10);

    if (projectName) {
        query = query.ilike('project', `%${projectName}%`);
    }

    const { data: updates, error } = await query;

    if (error || !updates || updates.length === 0) {
        return projectName
            ? `No recent updates found for project: ${projectName}.`
            : `No recent updates found in the system.`;
    }

    let msg = `Recent Updates${projectName ? ` for ${projectName}` : ''}:\n\n`;
    updates.forEach((u, i) => {
        const d = new Date(u.timestamp);
        msg += `${i + 1}. [${u.project}] ${u.task}\n   Progress: ${u.progress}% | RAG: ${u.rag}\n   Notes: ${u.raw_message}\n   (Data: ${d.toLocaleString()})\n\n`;
    });

    return msg;
}
