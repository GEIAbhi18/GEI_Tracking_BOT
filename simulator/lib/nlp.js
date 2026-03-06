export function ruleBasedNLP(text) {
    const lowerText = text.toLowerCase();

    const intents = {
        check_blocker_status: ['blocker', 'issue', 'problem', 'rukawat', 'dikkat', 'status'],
        greeting: ['hi', 'hello', 'hey', 'namaste', 'morning', 'evening'],
        help: ['help', 'support', 'commands', 'what can you do'],
        task_list: ['task list', 'show me tasks', 'get task', 'tasks', 'get_task'],
        create_task: ['create task', 'new task', 'add task', 'create a task'],
        create_project: ['create project', 'new project', 'add project', 'project:'],
        request_report: ['report', 'can i get the report', 'send today\'s report', 'daily report'],
        view_tickets: ['show tickets', 'view tickets', 'open tickets', 'tickets', 'show me tickets', 'show ticket', 'view ticket', 'ticket'],
        raise_ticket: ['raise ticket', 'create ticket', 'raise a ticket'],
        view_updates: ['show updates', 'view updates', 'get updates', 'updates for'],
        view_projects: ['show projects', 'view projects', 'projects', 'show me projects']
    };

    let bestIntent = 'unknown';
    let bestScore = 0;

    // Check for numbered update format e.g., "1. 60% done"
    const isNumberedUpdate = /^\d+\.\s+.*(?:done|delay|blocker|percent|%)/i.test(text.trim());

    // Check for standard multi-line implicit task creation format:
    const isImplicitProjectCreate = /^\s*project\s*:/i.test(text) && /end date:?\s*/i.test(text);
    const isImplicitTaskCreate = !isImplicitProjectCreate && /end date:?\s*/i.test(text) && /project:?\s*/i.test(text);

    if (isNumberedUpdate) {
        bestIntent = 'update_numbered_task';
        bestScore = 1;
    } else if (isImplicitProjectCreate) {
        bestIntent = 'create_project';
        bestScore = 1;
    } else if (isImplicitTaskCreate && !lowerText.includes('create project')) {
        bestIntent = 'create_task';
        bestScore = 1;
    } else {

        for (const [intent, keywords] of Object.entries(intents)) {
            let matches = 0;
            for (const kw of keywords) {
                if (lowerText.includes(kw)) {
                    matches += 1;
                }
            }
            const score = matches / Math.min(keywords.length, 2);
            if (score > bestScore) {
                bestScore = score;
                bestIntent = intent;
            }
        }
    }

    // Adjust confidence dynamically based on word matches
    let confidence = Math.min(bestScore * 0.4 + 0.5, 0.99);

    if (confidence < 0.6 || bestScore === 0) {
        bestIntent = 'unknown';
        confidence = 0.5;
    }

    // Extract Target User
    let targetUser = 'Asif'; // default
    if (lowerText.includes('kanav')) targetUser = 'Kanav';

    // Extract Date
    let date = 'today';
    if (lowerText.includes('yesterday')) date = 'yesterday';
    if (lowerText.includes('tomorrow')) date = 'tomorrow';

    return {
        intent: bestIntent,
        confidence,
        entities: {
            target_user: targetUser,
            date,
            raw_message: text
        }
    };
}
