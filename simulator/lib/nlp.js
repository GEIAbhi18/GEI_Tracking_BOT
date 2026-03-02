export function detectIntent(text) {
    const lowerText = text.toLowerCase();

    const intents = {
        check_blocker_status: ['blocker', 'issue', 'problem', 'rukawat', 'dikkat', 'status'],
        greeting: ['hi', 'hello', 'hey', 'namaste', 'morning', 'evening'],
        help: ['help', 'support', 'commands', 'what can you do']
    };

    let bestIntent = 'unknown';
    let bestScore = 0;

    for (const [intent, keywords] of Object.entries(intents)) {
        let matches = 0;
        for (const kw of keywords) {
            if (lowerText.includes(kw)) {
                matches += 1;
            }
        }
        const score = matches / Math.min(keywords.length, 2); // basic text matching heuristic
        if (score > bestScore) {
            bestScore = score;
            bestIntent = intent;
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
            date
        }
    };
}
