export function ruleBasedNLP(text) {
    const lowerText = text.toLowerCase();

    const intents = {
        query_blockers: ['show blockers', 'what are the blockers', 'show all blockers', 'blockers status', 'blockers list', 'project wise blocker', 'show project wise blocker', 'what blockers', 'blocker status', 'show blocker'],
        greeting: ['hi', 'hello', 'hey', 'namaste', 'morning', 'evening'],
        help: ['help', 'support', 'commands', 'what can you do'],
        create_task: ['create task', 'new task', 'add task', 'create a task'],
        request_report: ['report', 'can i get the report', 'send today\'s report', 'daily report'],
        view_tickets: ['show tickets', 'view tickets', 'open tickets', 'tickets', 'show me tickets', 'show ticket', 'view ticket', 'ticket'],
        create_ticket: ['raise ticket', 'create ticket', 'raise a ticket', 'create new ticket', 'raise new ticket', 'new ticket', 'add ticket'],
        close_ticket: ['close ticket', 'resolve ticket', 'ticket resolved', 'close it'],
        reply_ticket: ['reply to ticket', 'respond to ticket'],
        view_projects: ['show projects', 'view projects', 'projects', 'show me projects'],
        create_project: ['create project', 'new project', 'add project', 'create a project'],
        task_details: ['show me info about task', 'info task', 'task info', 'details about task'],
        complete_task: ['complete task', 'mark done', 'mark as complete', 'finish task'],
        llm_usage: ['llm usage', 'llm costing', 'llm cost', 'token usage', 'usage stats']
    };

    let bestIntent = 'unknown';
    let bestScore = 0;

    // Direct match for LLM usage admin queries
    if (lowerText.includes('llm usage') || lowerText.includes('llm costing') || lowerText.includes('llm cost')) {
        return {
            intent: 'llm_usage',
            confidence: 1,
            entities: { raw_message: text }
        };
    }

    // Check for numbered update format or update task format
    let isNumberedUpdate = false;
    let upNum = null;
    let upText = null;

    const closeTicketMatch = /close\s+ticket\s+(\d+)/i.exec(text.trim());
    const completeTaskMatch = /^complete\s+(?:task\s+)?(\d+)/i.exec(text.trim());
    const updateTaskMatch = /^(?:update\s+(?:task\s+)?)?(\d+)(?:[\.\:]?\s+(.*))?/i.exec(text.trim());
    const traditionalMatch = /^(\d+)\.\s+(.*)/i.exec(text.trim());
    const justNumberMatch = /^\s*(\d+)\s*$/i.exec(text.trim());
    const namedProjectTaskMatch = /^update\s+(.+)\s+task\s+(\d+)/i.exec(text.trim());

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
    } else {
        const numMatch = updateTaskMatch || traditionalMatch;
        if (namedProjectTaskMatch) {
            isNumberedUpdate = true;
            bestIntent = 'update_task';
            bestScore = 1;
            upNum = namedProjectTaskMatch[2];
            upText = "update"; // simple filler
        } else if (numMatch && !closeTicketMatch && !completeTaskMatch && !justNumberMatch) {
            const num = numMatch[1];
            const content = numMatch[2] || '';
            const lowerContent = content.toLowerCase();

            // Priority Check: Is it a ticket reply?
            // If it starts with a number and mentions ticket/bug/issue/blocker or user names
            if (lowerContent.match(/ticket|bug|issue|concern|blocker|asif|kanav/)) {
                bestIntent = 'reply_ticket';
                bestScore = 1;
                upNum = num;
                upText = content;
            } else if (text.toLowerCase().includes('update') || traditionalMatch) {
                isNumberedUpdate = true;
                upNum = num;
                upText = content;
            }
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
                if (lowerText === kw) {
                    matches = 2; // Exact full match
                    break;
                }
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

    // Adjust confidence: Max score 2 (exact) -> 1.0 confidence. Score 1 -> 0.85 confidence.
    let confidence = 0.5;
    if (bestScore >= 1) confidence = 0.95;
    else if (bestScore >= 0.5) confidence = 0.8;
    else if (bestScore > 0) confidence = 0.65;

    if (bestIntent === 'unknown' || confidence < 0.6) {
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
            project_name: namedProjectTaskMatch ? namedProjectTaskMatch[1].trim() : null,
            ticket_name: bestIntent === 'reply_ticket' ? upText : null,
            ticket_message: bestIntent === 'reply_ticket' ? upText : null
        }
    };
}
