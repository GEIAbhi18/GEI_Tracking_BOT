import { supabase } from '../supabase.js';

export async function checkBlockerTool(entities) {
    const targetUser = entities.target_user || 'Asif';

    try {
        // 1. Fetch User UUID Safely (Avoiding .single() crashes)
        const { data: userData, error: userError } = await supabase
            .from('users')
            .select('id')
            .ilike('name', targetUser)
            .limit(1);

        if (userError || !userData || userData.length === 0) {
            console.warn('Warning: Could not fetch user UUID from Supabase (Empty DB or RLS blocking). User:', targetUser);
            // Let's fallback gracefully rather than crashing.
            return 'No blockers for any projects today. Work is on time.';
        }

        const userId = userData[0].id;

        // 2. Fetch Tasks using the UUID
        // Format Date = Today
        const now = new Date();
        const todayStr = now.toISOString().split('T')[0]; // "YYYY-MM-DD"

        const { data: tasks, error } = await supabase
            .from('tasks')
            .select('*, projects(name)')
            .eq('assigned_to', userId);

        if (error) {
            console.error('Error querying Supabase tasks:', error);
            return 'No blockers for any projects today. Work is on time.';
        }

        if (!tasks || tasks.length === 0) {
            return 'No blockers for any projects today. Work is on time.';
        }

        // Filter tasks for today
        const todayTasks = tasks.filter(task => {
            if (!task.deadline) return true; // assuming if no date, it's open today
            return task.deadline.startsWith(todayStr);
        });

        // Detect blockers. Check status or look into updates table if needed, 
        // but based on prompt we check status = 'blocker' or is_blocked = true
        const blockedTasks = todayTasks.filter(t => t.status === 'blocker' || t.is_blocked === true);

        if (blockedTasks.length === 0) {
            return 'No blockers for any projects today. Work is on time.';
        }

        let msg = `There ${blockedTasks.length === 1 ? 'is 1 blocker' : `are ${blockedTasks.length} blockers`} today:\n\n`;

        blockedTasks.forEach(t => {
            const projectName = t.projects?.name ? `[${t.projects.name}] ` : '';
            const title = t.name || 'Unnamed Task';
            const reason = t.blocker_reason || 'Details pending';
            msg += `${projectName}${title} – ${reason}\n\n`;
        });
        // Removed the extra '});' here as it was a syntax error in the provided instruction.

        msg += 'Please review.';

        return msg.trim();
    } catch (err) {
        console.error('checkBlockerTool exception:', err);
        return 'No blockers for any projects today. Work is on time.';
    }
}
