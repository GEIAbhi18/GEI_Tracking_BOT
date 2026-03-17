import Fuse from 'fuse.js';

const PROJECTS = [
    'Top Terrace',
    '9TH FLOOR (CENTRIC)'
];

const TASKS = [
    'tile', 'membrane', 'malba', 'slope', 'solar', 'waterproof', 'ponding'
];

export function parseUpdateMessage(message) {
    if (!message) return { confidence: 'Low', missing: ['message'] };

    const parsed = {
        project: null,
        task: null,
        progress: null,
        blocker: null,
        confidence: 'Low'
    };

    // Extract progress % using regex
    const progressMatch = message.match(/(\d+)%\s*(?:completed|done)?/i) || message.match(/(\d+)\s*percent/i);
    if (progressMatch) {
        parsed.progress = parseInt(progressMatch[1], 10);
    }

    // Extract project using Fuse.js
    const projectFuse = new Fuse(PROJECTS, { includeScore: true, threshold: 0.4 });
    const projectHits = projectFuse.search(message);
    if (projectHits.length > 0) {
        parsed.project = projectHits[0].item;
    }

    // Extract task using Fuse.js
    const taskFuse = new Fuse(TASKS, { includeScore: true, threshold: 0.4 });
    // Tokenize message to check each word for tasks to avoid missing them in a long string
    const words = message.split(/[\s,.-]+/);
    let bestTask = null;
    let bestTaskScore = 1;
    for (const word of words) {
        const hits = taskFuse.search(word);
        if (hits.length > 0 && hits[0].score < bestTaskScore) {
            bestTaskScore = hits[0].score;
            bestTask = hits[0].item;
        }
    }
    if (!bestTask) {
        // try matching the whole message if words didn't catch it
        const tkHits = taskFuse.search(message);
        if (tkHits.length > 0) {
            bestTask = tkHits[0].item;
        }
    }
    parsed.task = bestTask;

    // Extract blocker (simple heuristic: look for sentences or keywords after "delay", "blocked", "issue")
    const blockerMatch = message.match(/(?:delay|blocked|issue|blocker)[:\s]+([^.]+)/i);
    if (blockerMatch) {
        parsed.blocker = blockerMatch[1].trim();
    }

    // Determine confidence
    if (parsed.project && parsed.task && parsed.progress !== null) {
        parsed.confidence = 'High';
    } else if (parsed.task && parsed.progress !== null) {
        parsed.confidence = 'Medium';
    } else {
        parsed.confidence = 'Low';
    }

    return parsed;
}
