import { logLLMUsageAsync } from './llmLogger';

export async function extractIntentWithLLM(message, chatHistory = []) {
    const selectedProvider = process.env.LLM_PROVIDER || 'gemini';
    
    const providers = [
        { name: 'openrouter', fn: callOpenRouter, model: 'meta-llama/llama-3-8b-instruct' },
        { name: 'gemini', fn: callGemini, model: 'gemini-flash-latest' },
        { name: 'groq', fn: callGroq, model: 'llama3-8b-8192' },
        { name: 'anthropic', fn: callAnthropic, model: 'claude-3-sonnet-20240229' },
        { name: 'openai', fn: callOpenAI, model: 'gpt-3.5-turbo' },
        { name: 'huggingface', fn: callHuggingFace, model: 'meta-llama/Llama-2-7b-chat-hf' }
    ];

    // Reorder to put selected provider first
    const sortedProviders = [...providers].sort((a, b) => {
        if (a.name === selectedProvider) return -1;
        if (b.name === selectedProvider) return 1;
        return 0;
    });

    for (const provider of sortedProviders) {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000); // Increased to 10 seconds

            const { result, usage } = await provider.fn(message, controller.signal, chatHistory);
            clearTimeout(timeoutId);

            if (result && typeof result === 'object' && 'intent' in result) {
                // Map new schema keys to internal representation
                const rawEntities = {
                    ... (result.entities || {}),
                    task_name: result.task_reference || result.project_name || (result.entities?.task_name),
                    project_name: result.project_name || (result.entities?.project_name),
                    completion_percent: result.progress !== undefined ? result.progress : (result.entities?.completion_percent),
                    blocker_name: result.blocker_text || (result.entities?.blocker_name),
                    ticket_id: result.task_reference || (result.entities?.ticket_id),
                    ticket_name: result.blocker_text || (result.entities?.ticket_name)
                };
                
                // Robust Cleanups
                const cleanProgress = (rawEntities.completion_percent || "").toString().match(/\d+/)?. [0] || null;
                const cleanTaskId = (rawEntities.task_name || "").toString().match(/\d+/)?. [0] || null;

                return {
                    intent: result.intent,
                    confidence: result.confidence || 0.5,
                    entities: {
                        ...rawEntities,
                        assignee: rawEntities.assignee || null,
                        target_user: rawEntities.assignee || null,
                        task_number: cleanTaskId,
                        task_id: cleanTaskId && !isNaN(cleanTaskId) ? parseInt(cleanTaskId) : null,
                        ticket_id: cleanTaskId && !isNaN(cleanTaskId) ? parseInt(cleanTaskId) : null,
                        completion_percent: cleanProgress ? parseInt(cleanProgress) : null,
                        ticket_message: rawEntities.ticket_message || rawEntities.ticket_name || null,
                        ticket_project: rawEntities.project_name || null,
                        project_name: rawEntities.project_name || null,
                        task_name: rawEntities.task_name || null,
                        blocker_name: rawEntities.blocker_name || rawEntities.blocker_description || rawEntities.blocker_reason || null
                    },
                    provider_used: provider.name
                };
            }
        } catch (err) {
            console.error(`Provider ${provider.name} failed:`, err.message || err);
            logLLMUsageAsync({
                provider: provider.name,
                model: provider.model,
                error: err.message || String(err),
                user_message: message
            });
        }
    }

    return { intent: 'unknown', entities: {}, confidence: 'low' };
}

const COMMON_PROMPT = `You are an AI assistant for a construction task management system.

ROLE:
You classify user messages into intents and extract structured data.

INSTRUCTIONS:
* Identify the user intent
* Extract all relevant entities
* Return structured JSON only

ALLOWED INTENTS:
* task_update: For progress updates (e.g., "60% done")
* complete_task: To mark a task as finished
* add_blocker: To report a new blocker/issue
* remove_blocker: To resolve an existing blocker
* query_tasks: To list or find tasks (formerly list_tasks)
* query_blockers: To see current blockers
* greeting: For simple greetings (e.g. "hi", "hello")
* create_task: For adding new tasks
* create_ticket: For raising issues/concerns
* reply_ticket: For responding to an existing ticket by number
* close_ticket: For resolving/closing a ticket
* assign_task: For assigning a task
* request_report: For daily summaries/PDFs
* view_projects: For listing projects
* view_tickets: For showing open tickets
* task_details: For full dates/details of a specific task
* help: For assistance or commands
* clarify: If the message is ambiguous (formerly unknown)

CONSTRAINTS:
* Output must be valid JSON only
* Do not include any explanation text
* If uncertain, return intent = "clarify"
* Always include a confidence score between 0 and 1

FEW-SHOT EXAMPLES:
Example 1:
User: "complete task 2"
Output: {"intent": "complete_task", "task_reference": "task 2", "confidence": 0.95}

Example 2:
User: "add blocker no material found"
Output: {"intent": "add_blocker", "blocker_text": "no material found", "confidence": 0.9}

Example 3:
User: "show my tasks"
Output: {"intent": "query_tasks", "confidence": 0.98}

Example 4:
User: "Top Terrace waterproofing 60%"
Output: {"intent": "task_update", "project_name": "Top Terrace", "progress": 60, "confidence": 0.92}

OUTPUT FORMAT:
{
"intent": "",
"task_reference": "",
"project_name": "",
"progress": null,
"blocker_text": "",
"confidence": 0.0
}

IMPORTANT:
- If the user starts a message with a number (like "1. fix confirmed"), check history to decide if it is a reply or update.
- Return ONLY the JSON object. Do NOT include any conversational text.`;

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
    try {
        return {
            result: JSON.parse(data.choices[0].message.content),
            usage: {
                input_tokens: data.usage?.prompt_tokens || 0,
                output_tokens: data.usage?.completion_tokens || 0
            }
        };
    } catch (e) {
        console.error("Failed to parse OpenAI JSON:", data.choices[0].message.content);
        return { result: { intent: 'unknown' }, usage: { input_tokens: 0, output_tokens: 0 } };
    }
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
    try {
        return {
            result: JSON.parse(rawText),
            usage: {
                input_tokens: data.usageMetadata?.promptTokenCount || 0,
                output_tokens: data.usageMetadata?.candidatesTokenCount || 0
            }
        };
    } catch (e) {
        console.error("Failed to parse Gemini JSON:", rawText);
        return { result: { intent: 'unknown' }, usage: { input_tokens: 0, output_tokens: 0 } };
    }
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

    try {
        return {
            result: JSON.parse(text),
            usage: { input_tokens: 0, output_tokens: 0 }
        };
    } catch (e) {
        console.error("Failed to parse HuggingFace JSON:", text);
        return { result: { intent: 'unknown' }, usage: { input_tokens: 0, output_tokens: 0 } };
    }
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

    try {
        return {
            result: JSON.parse(text),
            usage: {
                input_tokens: data.usage?.input_tokens || 0,
                output_tokens: data.usage?.output_tokens || 0
            }
        };
    } catch (e) {
        console.error("Failed to parse Anthropic JSON:", text);
        return { result: { intent: 'unknown' }, usage: { input_tokens: 0, output_tokens: 0 } };
    }
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

    try {
        return {
            result: JSON.parse(text),
            usage: {
                input_tokens: data.usage?.prompt_tokens || 0,
                output_tokens: data.usage?.completion_tokens || 0
            }
        };
    } catch (e) {
        console.error("Failed to parse OpenRouter JSON:", text);
        return { result: { intent: 'unknown' }, usage: { input_tokens: 0, output_tokens: 0 } };
    }
}
async function callGroq(message, signal, chatHistory = []) {
    const apiKey = process.env.GROQCLOUD_API_KEY;
    if (!apiKey) throw new Error("Missing GROQCLOUD_API_KEY");

    const messages = [
        { role: "system", content: COMMON_PROMPT },
        ...chatHistory.slice(-6).map(msg => ({
            role: msg.sender === 'bot' ? 'assistant' : 'user',
            content: msg.text
        })),
        { role: "user", content: message }
    ];

    const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${apiKey}`
        },
        body: JSON.stringify({
            model: "llama3-8b-8192",
            temperature: 0,
            messages,
            response_format: { type: "json_object" }
        }),
        signal
    });

    if (!res.ok) throw new Error(`Groq error: ${res.statusText}`);
    const data = await res.json();
    let text = data.choices[0].message.content;

    try {
        return {
            result: JSON.parse(text),
            usage: {
                input_tokens: data.usage?.prompt_tokens || 0,
                output_tokens: data.usage?.completion_tokens || 0
            }
        };
    } catch (e) {
        console.error("Failed to parse Groq JSON:", text);
        return { result: { intent: 'clarify' }, usage: { input_tokens: 0, output_tokens: 0 } };
    }
}
