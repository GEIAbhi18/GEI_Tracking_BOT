export function ruleBasedNLP(text) {
    const lowerText = text.toLowerCase();

    const intents = {
        check_blocker_status: ['show blockers', 'what are the blockers', 'status'],
        greeting: ['hi', 'hello', 'hey', 'namaste', 'morning', 'evening'],
        help: ['help', 'support', 'commands', 'what can you do'],
        task_list: ['task list', 'show me tasks', 'get task', 'tasks', 'get_task'],
        create_task: ['create task', 'new task', 'add task', 'create a task'],
        request_report: ['report', 'can i get the report', 'send today\'s report', 'daily report'],
        view_tickets: ['show tickets', 'view tickets', 'open tickets', 'tickets', 'show me tickets', 'show ticket', 'view ticket', 'ticket'],
        create_ticket: ['raise ticket', 'create ticket', 'raise a ticket', 'create new ticket', 'raise new ticket', 'new ticket', 'add ticket'],
        close_ticket: ['close ticket', 'resolve ticket', 'ticket resolved', 'close it'],
        reply_ticket: ['reply to ticket', 'respond to ticket'],
        view_projects: ['show projects', 'view projects', 'projects', 'show me projects'],
        task_details: ['show me info about task', 'info task', 'task info', 'details about task']
    };

    let bestIntent = 'unknown';
    let bestScore = 0;

    // Check for numbered update format or update task format
    let isNumberedUpdate = false;
    let upNum = null;
    let upText = null;

    const closeTicketMatch = /close\s+ticket\s+(\d+)/i.exec(text.trim());
    const completeTaskMatch = /^complete\s+(?:task\s+)?(\d+)/i.exec(text.trim());
    const updateTaskMatch = /^(?:update\s+(?:task\s+)?)?(\d+)[\.\:]?\s+(.*)/i.exec(text.trim());
    const traditionalMatch = /^(\d+)\.\s+(.*)/i.exec(text.trim());
    const justNumberMatch = /^\s*(\d+)\s*$/i.exec(text.trim());

    if (closeTicketMatch) {
        bestIntent = 'close_ticket';
        bestScore = 1;
        upNum = closeTicketMatch[1];
    } else if (justNumberMatch) {
        isNumberedUpdate = true;
        upNum = justNumberMatch[1];
        upText = "100% done";
    } else if (completeTaskMatch) {
        isNumberedUpdate = true;
        upNum = completeTaskMatch[1];
        upText = "100% done";
    } else if (updateTaskMatch && text.toLowerCase().includes('update')) {
        isNumberedUpdate = true;
        upNum = updateTaskMatch[1];
        upText = updateTaskMatch[2];
    } else if (traditionalMatch) {
        // If it starts with "N. "
        const num = traditionalMatch[1];
        const content = traditionalMatch[2];
        
        // If it mentioned ticket/bug/issue, it's a ticket reply
        if (content.toLowerCase().match(/ticket|bug|issue|concern/)) {
            bestIntent = 'reply_ticket';
            bestScore = 1;
            upNum = num;
            upText = content;
        } else {
            isNumberedUpdate = true;
            upNum = num;
            upText = content;
        }
    }

    // Check for task details
    const isInfoTask = /show me info about task (\d+)/i.exec(text.trim()) || /task details (\d+)/i.exec(text.trim());

    if (bestIntent !== 'unknown') {
        // Already set
    } else if (isNumberedUpdate) {
        bestIntent = 'update_task'; // Match mcp-router name
        bestScore = 1;
    } else if (isInfoTask) {
        bestIntent = 'task_details';
        bestScore = 1;
        upNum = isInfoTask[1];
    } else if (lowerText.includes('report') || lowerText.includes('pdf')) {
        bestIntent = 'request_report';
        bestScore = 0.8;
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
            raw_message: isNumberedUpdate || bestIntent === 'reply_ticket' || bestIntent === 'close_ticket' ? `${upNum}. ${upText || ''}` : text,
            task_id: upNum ? parseInt(upNum) : null,
            ticket_id: upNum ? parseInt(upNum) : null,
            task_number: upNum ? parseInt(upNum) : null,
            ticket_name: bestIntent === 'reply_ticket' ? upText : null,
            ticket_message: bestIntent === 'reply_ticket' ? upText : null
        }
    };
}
