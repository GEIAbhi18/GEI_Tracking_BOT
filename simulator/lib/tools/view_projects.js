import { supabase } from '../supabase.js';

export async function viewProjectsTool(entities) {
    const { data: projects, error } = await supabase.from('projects').select('*').order('created_at', { ascending: false }).limit(20);
    if (error || !projects || projects.length === 0) {
        return "No projects found in the system.";
    }

    let msg = `Here are the current projects:\n\n`;
    projects.forEach((p, i) => {
        msg += `${i + 1}. ${p.name} (Status: ${p.status || 'active'})\n`;
    });

    return msg;
}
