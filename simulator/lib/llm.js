export async function extractIntentWithLLM(message, chatHistory = []) {
    const providers = [
        { name: 'openrouter', fn: callOpenRouter },
        { name: 'gemini', fn: callGemini },
        { name: 'anthropic', fn: callAnthropic },
        { name: 'openai', fn: callOpenAI },
        { name: 'huggingface', fn: callHuggingFace }
    ];

    for (const provider of providers) {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout

            const result = await provider.fn(message, controller.signal, chatHistory);
            clearTimeout(timeoutId);

            if (result && typeof result === 'object' && 'intent' in result) {
                const rawEntities = result.entities || {};
                
                // Robust Cleanups
                const cleanProgress = (rawEntities.completion_percent || "").toString().match(/\d+/)?. [0] || null;
                const cleanTaskId = (rawEntities.task_id || "").toString().match(/\d+/)?. [0] || null;

                return {
                    intent: result.intent,
                    confidence: result.confidence || "high",
                    entities: {
                        ...rawEntities,
                        assignee: rawEntities.assignee || null,
                        target_user: rawEntities.assignee || null,
                        task_number: cleanTaskId,
                        task_id: cleanTaskId ? parseInt(cleanTaskId) : null,
                        ticket_id: cleanTaskId ? parseInt(cleanTaskId) : null,
                        completion_percent: cleanProgress ? parseInt(cleanProgress) : null,
                        ticket_message: rawEntities.ticket_message || rawEntities.ticket_name || null,
                        ticket_project: rawEntities.project_name || null,
                        project_name: rawEntities.project_name || null,
                        task_name: rawEntities.task_name || null
                    },
                    provider_used: provider.name
                };
            }
        } catch (err) {
            console.error(`Provider ${provider.name} failed:`, err.message || err);
        }
    }

    return null;
}

const COMMON_PROMPT = `You are a construction project management assistant for GEI.
Analyze the user's message and chat conversation history to identify the intent and extract entities into JSON.

CONTEXT:
Kanav is the Manager/Director (handles assignment and reports).
Asif is an Employee (handles progress updates).

ALLOWED INTENTS:
- greeting: For simple greetings (e.g. "hi", "hello", "good morning").
- create_task: For adding new tasks (e.g. "create task for Asif", "add waterproof test").
- list_tasks: For showing/listing tasks (e.g. "show my tasks", "what is Asif doing?").
- update_task: For progress updates (e.g. "task 1 is 60% done").
- create_ticket: For raising issues/concerns (e.g. "raise ticket for Top Terrace", "issue with materials").
- reply_ticket: For responding to an existing ticket by its number (e.g. "1. I have fixed the leak", "reply to ticket 2: okay", "1. update completed").
- close_ticket: For resolving/closing a ticket (e.g. "close ticket 1", "ticket 2 is resolved").
- assign_task: For assigning a task (e.g. "assign the solar task to Asif").
- add_blocker: For reporting blockers (e.g. "task is blocked by rain").
- request_report: For daily summaries/PDFs (e.g. "give me report", "generate pdf").
- view_projects: For listing projects.
- view_tickets: For showing open tickets/issues.
- task_details: For seeing full dates/details of a specific task.
- unknown: Use if intent is unclear.

IMPORTANT:
- If the user starts a message with a number (like "1. fix confirmed"), check history:
  - If previous message was a list of tickets, use reply_ticket.
  - If previous message was tasks, use update_task.
- ENTITY PERSISTENCE: If an entity (like project_name or task_name) was identified in a previous turn of the same conversation and isn't mentioned again, keep it in the JSON unless the user explicitly changes it or starts a completely new intent.
- During create_ticket flow:
  1. Turn 1: "raise ticket" -> {intent: "create_ticket", entities: { ticket_name: null, project_name: null }}
  2. Turn 2: "New Project" -> {intent: "create_ticket", entities: { ticket_name: null, project_name: "New Project" }}
  3. Turn 3: "Pipe leak" -> {intent: "create_ticket", entities: { ticket_name: "Pipe leak", project_name: "New Project" }}

JSON Schema:
{
  "intent": "string",
  "entities": {
    "project_name": "string",
    "task_name": "string",
    "assignee": "string",
    "task_id": "number",
    "completion_percent": "number",
    "ticket_name": "string",
    "deadline": "string"
  },
  "confidence": "high|low"
}`;

async function callOpenAI(message, signal, chatHistory = []) {
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) throw new Error("Missing OPENAI_API_KEY");

    const messages = chatHistory.slice(-6).map(msg => ({
        role: msg.sender === 'bot' ? 'assistant' : 'user',
        content: msg.text
    }));
    messages.push({ role: "user", content: message });

    const res = await fetch("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${apiKey}`
        },
        body: JSON.stringify({
            model: "gpt-3.5-turbo",
            messages: [
                { role: "system", content: COMMON_PROMPT },
                ...messages
            ],
            temperature: 0,
            response_format: { type: "json_object" }
        }),
        signal
    });

    if (!res.ok) throw new Error(`OpenAI error: ${res.statusText}`);
    const data = await res.json();
    return JSON.parse(data.choices[0].message.content);
}

async function callGemini(message, signal, chatHistory = []) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) throw new Error("Missing GEMINI_API_KEY");

    const history = chatHistory.slice(-6).map(msg => `${msg.sender}: ${msg.text}`).join('\n');
    const prompt = `${COMMON_PROMPT}\n\nCONVERSATION HISTORY:\n${history}\n\nUSER MESSAGE: "${message}"\n\nReturn the result in raw JSON format.`;

    const res = await fetch("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-goog-api-key": apiKey
        },
        body: JSON.stringify({
            contents: [{
                parts: [{ text: prompt }]
            }],
            generationConfig: {
                responseMimeType: "application/json",
                temperature: 0
            }
        }),
        signal
    });

    if (!res.ok) throw new Error(`Gemini error: ${res.statusText}`);
    const data = await res.json();
    const rawText = data.candidates[0].content.parts[0].text;
    return JSON.parse(rawText);
}

async function callHuggingFace(message, signal, chatHistory = []) {
    const apiKey = process.env.HUGGINGFACE_API_KEY;
    if (!apiKey) throw new Error("Missing HUGGINGFACE_API_KEY");

    const history = chatHistory.slice(-3).map(msg => `${msg.sender}: ${msg.text}`).join('\n');
    const prompt = `${COMMON_PROMPT}\n\nRecent History:\n${history}\n\nInput: "${message}"\nOutput JSON:`;

    const res = await fetch("https://api-inference.huggingface.co/models/meta-llama/Llama-2-7b-chat-hf", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${apiKey}`
        },
        body: JSON.stringify({
            inputs: prompt,
            parameters: { max_new_tokens: 200, temperature: 0.1, return_full_text: false }
        }),
        signal
    });

    if (!res.ok) throw new Error(`HuggingFace error: ${res.statusText}`);
    const data = await res.json();
    let text = Array.isArray(data) ? data[0].generated_text : data.generated_text;

    if (text.includes("```json")) {
        text = text.split("```json")[1].split("```")[0].trim();
    } else if (text.includes("{") && text.includes("}")) {
        text = text.substring(text.indexOf("{"), text.lastIndexOf("}") + 1);
    }

    return JSON.parse(text);
}

async function callAnthropic(message, signal, chatHistory = []) {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) throw new Error("Missing ANTHROPIC_API_KEY");

    const messages = chatHistory.slice(-6).map(msg => ({
        role: msg.sender === 'bot' ? 'assistant' : 'user',
        content: msg.text
    }));
    messages.push({ role: "user", content: message });

    const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "x-api-key": apiKey,
            "anthropic-version": "2023-06-01"
        },
        body: JSON.stringify({
            model: "claude-3-sonnet-20240229",
            max_tokens: 500,
            temperature: 0,
            system: COMMON_PROMPT,
            messages
        }),
        signal
    });

    if (!res.ok) throw new Error(`Anthropic error: ${res.statusText}`);
    const data = await res.json();
    let text = data.content[0].text;

    if (text.includes("```json")) {
        text = text.split("```json")[1].split("```")[0].trim();
    } else if (text.includes("{") && text.includes("}")) {
        text = text.substring(text.indexOf("{"), text.lastIndexOf("}") + 1);
    }

    return JSON.parse(text);
}

async function callOpenRouter(message, signal, chatHistory = []) {
    const apiKey = process.env.OPENROUTER_API_KEY;
    if (!apiKey) throw new Error("Missing OPENROUTER_API_KEY");

    const messages = [
        { role: "system", content: COMMON_PROMPT },
        ...chatHistory.slice(-6).map(msg => ({
            role: msg.sender === 'bot' ? 'assistant' : 'user',
            content: msg.text
        })),
        { role: "user", content: message }
    ];

    const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${apiKey}`
        },
        body: JSON.stringify({
            model: "meta-llama/llama-3-8b-instruct",
            temperature: 0,
            messages
        }),
        signal
    });

    if (!res.ok) throw new Error(`OpenRouter error: ${res.statusText}`);
    const data = await res.json();
    let text = data.choices[0].message.content;

    if (text.includes("```json")) {
        text = text.split("```json")[1].split("```")[0].trim();
    } else if (text.includes("{") && text.includes("}")) {
        text = text.substring(text.indexOf("{"), text.lastIndexOf("}") + 1);
    }

    return JSON.parse(text);
}
