export async function extractIntentWithLLM(message) {
    const providers = [
        { name: 'openai', fn: callOpenAI },
        { name: 'gemini', fn: callGemini },
        { name: 'huggingface', fn: callHuggingFace }
    ];

    for (const provider of providers) {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout

            const result = await provider.fn(message, controller.signal);
            clearTimeout(timeoutId);

            if (result && typeof result === 'object' && 'intent' in result && 'confidence' in result) {
                return {
                    intent: result.intent,
                    confidence: result.confidence,
                    entities: result.entities || { target_user: null, date: "today" },
                    provider_used: provider.name
                };
            }
        } catch (err) {
            console.error(`Provider ${provider.name} failed:`, err.message || err);
        }
    }

    return null;
}

const COMMON_PROMPT = `You are a strict JSON extractor.

Extract intent and entities from the message.

Supported intents:
- check_blocker_status
- greeting
- help
- unknown

Return ONLY valid JSON:
{
  "intent": string,
  "confidence": number (0-1),
  "entities": {
    "target_user": string or null,
    "date": string or "today"
  }
}

Message:
`;

async function callOpenAI(message, signal) {
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) throw new Error("Missing OPENAI_API_KEY");

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
                { role: "user", content: `"${message}"` }
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

async function callGemini(message, signal) {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) throw new Error("Missing GEMINI_API_KEY");

    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            contents: [{
                parts: [{ text: COMMON_PROMPT + `"${message}"` }]
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

async function callHuggingFace(message, signal) {
    const apiKey = process.env.HUGGINGFACE_API_KEY;
    if (!apiKey) throw new Error("Missing HUGGINGFACE_API_KEY");

    const res = await fetch("https://api-inference.huggingface.co/models/meta-llama/Llama-2-7b-chat-hf", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${apiKey}`
        },
        body: JSON.stringify({
            inputs: COMMON_PROMPT + `"${message}"\n\nOutput JSON:`,
            parameters: { max_new_tokens: 100, temperature: 0.1, return_full_text: false }
        }),
        signal
    });

    if (!res.ok) throw new Error(`HuggingFace error: ${res.statusText}`);
    const data = await res.json();
    let outputText = Array.isArray(data) ? data[0].generated_text : data.generated_text;

    // Basic cleanup in case HF returns markdown wrapped
    if (outputText.includes("```json")) {
        outputText = outputText.split("```json")[1].split("```")[0].trim();
    }

    return JSON.parse(outputText);
}
