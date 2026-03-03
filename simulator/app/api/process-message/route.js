import { NextResponse } from 'next/server';
import { ruleBasedNLP } from '@/lib/nlp';
import { extractIntentWithLLM } from '@/lib/llm';
import { routeToTool } from '@/lib/mcp-router';
import { supabase } from '@/lib/supabase';

async function logUnknown(message, llmResult = {}, userName = 'Kanav') {
    try {
        await supabase.from('unknown_commands').insert([{
            message_text: message,
            detected_intent: 'unknown',
            confidence: llmResult?.confidence || 0,
            provider_used: llmResult?.provider_used || 'ruleBased',
            user_name: userName,
        }]);
    } catch (err) {
        console.error("Failed to log unknown query:", err);
    }
}

export async function POST(req) {
    try {
        const body = await req.json();
        const { message, userName = 'Kanav' } = body;

        if (!message || message.trim() === '') {
            return NextResponse.json({ reply: "I didn't catch that. Please send a valid message." });
        }

        const nlpResult = ruleBasedNLP(message);
        let finalIntent;

        if (nlpResult.confidence >= 0.7) {
            finalIntent = nlpResult;
            finalIntent.provider_used = 'ruleBased';
        } else {
            const llmResult = await extractIntentWithLLM(message);

            if (llmResult && llmResult.confidence >= 0.6) {
                finalIntent = llmResult;
            } else {
                await logUnknown(message, llmResult || nlpResult, userName);
                return NextResponse.json({
                    reply: "I couldn't understand that request. Please rephrase.",
                    nlpData: { intent: 'unknown' }
                });
            }
        }

        const response = await mcpRouterWrapper(finalIntent);

        return NextResponse.json({ reply: response, nlpData: finalIntent });
    } catch (err) {
        console.error("Message processing error:", err);
        return NextResponse.json({ reply: "An error occurred while processing your request." }, { status: 500 });
    }
}

async function mcpRouterWrapper(finalIntent) {
    // Wrap to routeToTool inside standard MCP handling
    return await routeToTool(finalIntent);
}
