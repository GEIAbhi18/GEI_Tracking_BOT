import { supabase } from '../supabase';

export async function createProjectTool(entities) {
    const rawMsg = entities.raw_message || '';
    const creator = entities.target_user || 'Kanav';

    // Example: "Project: Dashboard \n End date: 30 Mar"
    const projMatch = rawMsg.match(/Project\s*:?\s*(.+?)(?:\n|$)/i) || rawMsg.match(/create project (.*?) (?:for|deadline|end date)/i) || rawMsg.match(/create project (.*)/i);
    const deadlineMatch = rawMsg.match(/End date\s*:?\s*(.+?)(?:\n|$)/i) || rawMsg.match(/Deadline\s*:?\s*(.+?)(?:\n|$)/i);

    const projectName = projMatch ? projMatch[1].trim() : null;
    let deadlineStr = deadlineMatch ? deadlineMatch[1].trim() : null;

    if (!projectName) {
        return "To create a project, please use this format:\n\nProject: <Name>\nEnd date: <DD MMM>";
    }

    const { data: userData } = await supabase.from('users').select('id').ilike('name', creator).limit(1);
    const userId = (userData && userData.length) ? userData[0].id : null;

    await supabase.from('projects').insert([{
        name: projectName,
        status: 'active',
        created_by: userId
    }]);

    return `Project "${projectName}" has been successfully created!`;
}
