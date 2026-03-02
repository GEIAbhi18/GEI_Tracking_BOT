import { NextResponse } from 'next/server';
import { detectIntent } from '@/lib/nlp';
import { routeToTool } from '@/lib/mcp-router';
import { supabase } from '@/lib/supabase';

export async function POST(req) {
    try {
        const body = await req.json();
        const { message, userName = 'Kanav' } = body;

        if (!message || message.trim() === '') {
            return NextResponse.json({ reply: "I didn't catch that. Please send a valid message." });
        }

        const nlpData = detectIntent(message);

        if (nlpData.intent === 'unknown' || nlpData.confidence < 0.6) {
            nlpData.intent = 'unknown'; // normalize just in case
            try {
                await supabase.from('unknown_commands').insert([{
                    message_text: message,
                    detected_intent: 'unknown',
                    confidence: nlpData.confidence,
                    user_name: userName,
                }]);
            } catch (err) {
                console.error("Failed to log unknown query:", err);
            }
        }

        const reply = await routeToTool(nlpData);

        return NextResponse.json({ reply, nlpData });
    } catch (err) {
        console.error("Message processing error:", err);
        return NextResponse.json({ reply: "An error occurred while processing your request." }, { status: 500 });
    }
}
