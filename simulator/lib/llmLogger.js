import fs from 'fs';
import path from 'path';

// ensure reports directory exists
const reportsDir = path.join(process.cwd(), 'reports');
if (!fs.existsSync(reportsDir)) {
    fs.mkdirSync(reportsDir, { recursive: true });
}

const LOG_FILE = path.join(reportsDir, 'llm_usage_log.jsonl');
const SUMMARY_FILE = path.join(reportsDir, 'llm_usage_summary.log');
const COST_FILE = path.join(reportsDir, 'llm_cost_summary.txt');

// Configurable rates per model (per token)
const RATES = {
    'gemini-flash-latest': { input: 0.075 / 1000000, output: 0.30 / 1000000 },
    'gemini-flash': { input: 0.075 / 1000000, output: 0.30 / 1000000 },
    'meta-llama/llama-3-8b-instruct': { input: 0.1 / 1000000, output: 0.1 / 1000000 },
    'gpt-3.5-turbo': { input: 0.50 / 1000000, output: 1.50 / 1000000 },
    'claude-3-sonnet-20240229': { input: 3.00 / 1000000, output: 15.00 / 1000000 }
};

function getRate(model) {
    if (RATES[model]) return RATES[model];
    const match = Object.keys(RATES).find(k => model.includes(k));
    return match ? RATES[match] : { input: 0, output: 0 };
}

export function logLLMUsageAsync(data) {
    // We do this synchronously to ensure the log is updated immediately and accurately
    // against potential race conditions from multiple simultaneous requests.
    // It's still lightweight as it only performs sync file appends/writes.
    try {
        const { provider, model, input_tokens, output_tokens, error, user_message, parsed_intent } = data;
        
        const timestamp = new Date().toISOString().replace('T', ' ').slice(0, 16); 

        if (error) {
            const errLog = {
                timestamp,
                provider,
                model: model || 'unknown',
                error_message: error,
                status: 'failed',
                user_message
            };
            // Log to JSONL
            fs.appendFileSync(LOG_FILE, JSON.stringify(errLog) + '\n');
            
            // Log failure to Summary log for easy reading
            const failSummary = `\n---[ FAILURE ]---\nTime: ${new Date().toLocaleTimeString('en-US', { hour12: false })}\nStatus: FAILED\nProvider: ${provider}\nError: ${error}\nUser Message: "${user_message}"\n------------------------\n`;
            fs.appendFileSync(SUMMARY_FILE, failSummary);
            return;
        }

        const rates = getRate(model);
        const input_cost = input_tokens * rates.input;
        const output_cost = output_tokens * rates.output;
        const estimated_cost = input_cost + output_cost;
        const total_tokens = input_tokens + output_tokens;

        const logEntry = {
            timestamp,
            provider,
            model,
            input_tokens,
            output_tokens,
            total_tokens,
            estimated_usd: Number(estimated_cost.toFixed(6)),
            estimated_inr: Number((estimated_cost * 83).toFixed(4)),
            user_message,
            intent: parsed_intent || "unknown"
        };

        // Write to JSONL
        fs.appendFileSync(LOG_FILE, JSON.stringify(logEntry) + '\n');

        // Write to Summary log
        const summaryText = `\n---\nTime: ${new Date().toLocaleTimeString('en-US', { hour12: false })}\nModel: ${model}\nIntent: ${logEntry.intent}\nInput Tokens: ${input_tokens}\nOutput Tokens: ${output_tokens}\nTotal Tokens: ${total_tokens}\nEstimated Cost: ₹${(estimated_cost * 83).toFixed(4)} INR\n------------------------\n`;
        fs.appendFileSync(SUMMARY_FILE, summaryText);

        // Update Daily Cost Summary
        updateDailyCostSummary(input_tokens, output_tokens, estimated_cost);

    } catch (err) {
        console.error("LLM Logging failed", err);
    }
}

function updateDailyCostSummary(input_tokens, output_tokens, estimated_cost) {
    const today = new Date().toISOString().split('T')[0];
    let dailyData = {
        date: today,
        calls: 0,
        input: 0,
        output: 0,
        total: 0,
        cost: 0
    };

    if (fs.existsSync(COST_FILE)) {
        const content = fs.readFileSync(COST_FILE, 'utf-8');
        const lines = content.split('\n');
        let fileDate = '';
        for (const line of lines) {
            if (line.startsWith('Date: ')) fileDate = line.split('Date: ')[1].trim();
            if (line.startsWith('Total LLM Calls: ')) dailyData.calls = parseInt(line.split(':')[1].trim());
            if (line.startsWith('Total Input Tokens: ')) dailyData.input = parseInt(line.split(':')[1].trim());
            if (line.startsWith('Total Output Tokens: ')) dailyData.output = parseInt(line.split(':')[1].trim());
            if (line.startsWith('Total Tokens: ')) dailyData.total = parseInt(line.split(':')[1].trim());
            if (line.startsWith('Estimated Cost Today: ₹')) dailyData.cost = parseFloat(line.split('₹')[1].trim()) / 83;
        }
        
        // Reset if new day
        if (fileDate !== today) {
            dailyData = { date: today, calls: 0, input: 0, output: 0, total: 0, cost: 0 };
        }
    }

    dailyData.calls += 1;
    dailyData.input += input_tokens;
    dailyData.output += output_tokens;
    dailyData.total += (input_tokens + output_tokens);
    dailyData.cost += estimated_cost;

    const inrCost = dailyData.cost * 83;
    const costText = `Date: ${today}\n\nTotal LLM Calls: ${dailyData.calls}\nTotal Input Tokens: ${dailyData.input}\nTotal Output Tokens: ${dailyData.output}\nTotal Tokens: ${dailyData.total}\n\nEstimated Cost Today: ₹${inrCost.toFixed(4)} INR\n`;
    fs.writeFileSync(COST_FILE, costText);
}
