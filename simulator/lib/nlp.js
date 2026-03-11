export function ruleBasedNLP(text) {
    const lowerText = text.toLowerCase();

    const intents = {
        check_blocker_status: ['show blockers', 'what are the blockers', 'status'],
        greeting: ['hi', 'hello', 'hey', 'namaste', 'morning', 'evening'],
        help: ['help', 'support', 'commands', 'what can you do'],
        task_list: ['task list', 'show me tasks', 'get task', 'tasks', 'get_task'],
        create_task: ['create task', 'new task', 'add task', 'create a task'],
        create_project: ['create project', 'new project', 'add project', 'project:'],
        request_report: ['report', 'can i get the report', 'send today\'s report', 'daily report'],
        view_tickets: ['show tickets', 'view tickets', 'open tickets', 'tickets', 'show me tickets', 'show ticket', 'view ticket', 'ticket'],
        raise_ticket: ['raise ticket', 'create ticket', 'raise a ticket', 'create new ticket', 'raise new ticket', 'new ticket', 'add ticket'],
        view_updates: ['show updates', 'view updates', 'get updates', 'updates for'],
        view_projects: ['show projects', 'view projects', 'projects', 'show me projects'],
        info_numbered_task: ['show me info about task', 'info task', 'task info', 'details about task'],
        prompt_task_complete: ['complete task', 'complete a task', 'mark task complete'],
        prompt_task_update: ['update task', 'update a task', 'asking for your current update', 'asking for updates', 'send update'],
        prompt_task_blocker: ['add blocker', 'i have a blocker', 'add new blocker', 'report blocker', 'blocker', 'issue', 'problem', 'rukawat', 'dikkat']
    };

    let bestIntent = 'unknown';
    let bestScore = 0;

    // Check for numbered update format or update task format
    let isNumberedUpdate = false;
    let upNum = null;
    let upText = null;

    const addBlockerMatch = /^(?:add blocker to task\s+)?(\d+)[\.\:]?\s+(.*)/i.exec(text.trim());
    const completeTaskMatch = /^complete\s+(?:task\s+)?(\d+)/i.exec(text.trim());
    const updateTaskMatch = /^(?:update\s+(?:task\s+)?)?(\d+)[\.\:]?\s+(.*)/i.exec(text.trim());
    const traditionalMatch = /^(\d+)\.\s+(.*)/i.exec(text.trim());
    const justNumberMatch = /^\s*(\d+)\s*$/i.exec(text.trim());

    if (justNumberMatch) {
        // If they just type a number, we assume they are answering the complete task prompt
        isNumberedUpdate = true;
        upNum = justNumberMatch[1];
        upText = "100% done";
    } else if (completeTaskMatch) {
        isNumberedUpdate = true;
        upNum = completeTaskMatch[1];
        upText = "100% done";
    } else if (addBlockerMatch && text.toLowerCase().includes('blocker')) {
        isNumberedUpdate = true;
        upNum = addBlockerMatch[1];
        upText = "blocker: " + addBlockerMatch[2];
    } else if (updateTaskMatch && text.toLowerCase().includes('update')) {
        isNumberedUpdate = true;
        upNum = updateTaskMatch[1];
        upText = updateTaskMatch[2];
    } else if (traditionalMatch && (text.includes('%') || text.includes('done') || text.includes('blocker') || text.includes('delay') || text.includes('percent'))) {
        isNumberedUpdate = true;
        upNum = traditionalMatch[1];
        upText = traditionalMatch[2];
    }

    // Check for standard multi-line implicit task creation format:
    const isImplicitProjectCreate = /^\s*project\s*:/i.test(text) && /end date:?\s*/i.test(text);
    const isImplicitTaskCreate = !isImplicitProjectCreate && /end date:?\s*/i.test(text) && /project:?\s*/i.test(text);

    // Check for info task format e.g., "show me info about task 1"
    const isInfoTask = /show me info about task (\d+)/i.exec(text.trim());

    // Check for explicit ticket creation
    const isNewTicketComplete = /create new ticket for (.+) called "(.+)"/i.exec(text.trim())
        || /raise new ticket for (.+) called "(.+)"/i.exec(text.trim());
    
    // Support simpler raise ticket format e.g. "raise ticket for task 1: need materials"
    const isNewTicketTask = /^(?:raise|create|add)\s+ticket\s+(?:for\s+task\s+)?(\d+)[\:\s]+(.*)/i.exec(text.trim());

    // Check for just "add new ticket" or "raise ticket" prompt
    const isNewTicketPrompt = /^(?:add|create|raise)(?:\s+a|\s+new)?\s+ticket(?:s)?(?:\s+for\s+task)?$/i.test(text.trim());

    if (isNumberedUpdate) {
        bestIntent = 'update_numbered_task';
        bestScore = 1;
    } else if (isInfoTask) {
        bestIntent = 'info_numbered_task';
        bestScore = 1;
    } else if (isNewTicketComplete) {
        bestIntent = 'raise_ticket';
        bestScore = 1;
    } else if (isNewTicketTask) {
        bestIntent = 'raise_ticket';
        bestScore = 1;
    } else if (isNewTicketPrompt) {
        bestIntent = 'raise_ticket';
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
            raw_message: isNumberedUpdate ? `${upNum}. ${upText}` : text,
            task_number: isInfoTask ? parseInt(isInfoTask[1]) : (isNewTicketTask ? parseInt(isNewTicketTask[1]) : null),
            ticket_project: isNewTicketComplete ? isNewTicketComplete[1].trim() : null,
            ticket_message: isNewTicketComplete ? isNewTicketComplete[2].trim() : (isNewTicketTask ? isNewTicketTask[2].trim() : null)
        }
    };
}
