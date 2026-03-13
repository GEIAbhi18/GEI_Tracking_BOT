import { NextResponse } from 'next/server';
import { extractIntentWithLLM } from '@/lib/llm';
import { routeToTool } from '@/lib/mcp-router';
import { supabase } from '@/lib/supabase';
import { ruleBasedNLP } from '@/lib/nlp';
import fs from 'fs';
import path from 'path';

async function logUnknown(message, llmResult = {}, userName = 'Kanav') {
    try {
        await supabase.from('unknown_commands').insert([{
            message_text: message,
            detected_intent: 'unknown',
            confidence: llmResult?.confidence || 0,
            user_name: userName,
        }]);
    } catch (err) {
        console.error("Failed to log unknown query:", err);
    }
}

export async function POST(req) {
    try {
        const body = await req.json();
        const { message, userName = 'Asif', chatHistory = [] } = body;

        if (!message || message.trim() === '') {
            return NextResponse.json({ reply: "I didn't catch that. Please send a valid message." });
        }

        let finalIntent = null;
        const rawText = message.trim();
        const lowerText = rawText.toLowerCase();

        // 0. Rule-based NLP first (Deterministic High-Speed Layer)
        const nlpResult = ruleBasedNLP(message);
        
        // Disambiguation for "N. message"
        if (nlpResult.intent === 'update_task' || nlpResult.intent === 'reply_ticket') {
            const lastBotMsg = [...chatHistory].reverse().find(m => m.sender === 'bot')?.text || "";
            const isTicketContext = /ticket|issue|concern/i.test(lastBotMsg);
            const isTaskContext = /task|progress|assigned/i.test(lastBotMsg);

            if (nlpResult.intent === 'update_task' && isTicketContext && !isTaskContext) {
                nlpResult.intent = 'reply_ticket';
            } else if (nlpResult.intent === 'reply_ticket' && !isTicketContext && isTaskContext) {
                nlpResult.intent = 'update_task';
            }
        }

        if (nlpResult.confidence >= 0.8) {
            finalIntent = nlpResult;
        }

        // 1. Check for command mode bypassing LLM
        if (!finalIntent && rawText.startsWith('/')) {
            const parts = rawText.slice(1).split(' ');
            const cmd = parts[0].toLowerCase();
            const rest = parts.slice(1).join(' ');

            const isLLMUsage = cmd === 'llm_usage' || lowerText.includes('llm usage') || lowerText.includes('llm costing') || lowerText.includes('llm cost');

            if (isLLMUsage) {
                if (userName !== 'Kanav') {
                    return NextResponse.json({ reply: "Access denied. Only admins can use this command." });
                }
                const costFile = path.join(process.cwd(), 'reports', 'llm_cost_summary.txt');
                let summary = "No LLM usage recorded today.";
                if (fs.existsSync(costFile)) {
                    summary = fs.readFileSync(costFile, 'utf-8');
                }
                return NextResponse.json({ reply: `LLM Usage Stats:\n\n${summary}` });
            }

            const allowedCommands = ['update_task', 'add_blocker', 'create_ticket', 'create_task', 'assign_task', 'mark_done', 'list_tasks', 'check_blockers', 'task_details', 'upload_deliverable', 'view_projects', 'view_tickets', 'request_report', 'reply_ticket', 'close_ticket'];
            
            if (allowedCommands.includes(cmd)) {
                let targetAssignee = userName;
                // Manager check: Kanav sees Asif's tasks by default
                if (userName === 'Kanav' && ['list_tasks', 'create_task', 'update_task', 'task_details'].includes(cmd) && !rest.includes(targetAssignee)) {
                    targetAssignee = 'Asif';
                }

                finalIntent = {
                    intent: cmd,
                    confidence: 1,
                    entities: { assignee: targetAssignee, raw_message: rest, userName },
                    provider_used: 'command_mode'
                };
            }
        }

        // 2. Use LLM intent parser for natural language
        if (!finalIntent) {
            const llmResult = await extractIntentWithLLM(message, chatHistory);

            if (llmResult && llmResult.intent && llmResult.intent !== 'unknown') {
                finalIntent = llmResult;
                
                // Manager check: Kanav assigns to/views Asif's tasks by default
                if (userName === 'Kanav' && 
                    ['list_tasks', 'create_task', 'update_task', 'task_details'].includes(finalIntent.intent) && 
                    !finalIntent.entities.assignee) {
                    finalIntent.entities.assignee = 'Asif';
                }

                if (!finalIntent.entities.assignee) finalIntent.entities.assignee = userName;
                finalIntent.entities.userName = userName;
                finalIntent.entities.raw_message = message;
            } else {
                // Secondary check for LLM usage before falling back to unknown
                const isLLMNatural = lowerText.includes('llm usage') || lowerText.includes('llm costing') || lowerText.includes('llm cost');
                if (isLLMNatural) {
                    finalIntent = { intent: 'llm_usage', confidence: 1, entities: { userName } };
                } else {
                    await logUnknown(message, llmResult, userName);
                    return NextResponse.json({
                        reply: "I couldn't specify your request intent. Here are the allowed commands you can try or rephrase your message.",
                        nlpData: { intent: 'unknown' }
                    });
                }
            }
        }

        if (finalIntent?.intent === 'llm_usage') {
            if (userName !== 'Kanav') {
                return NextResponse.json({ reply: "Access denied. Only admins can use this command." });
            }
            const costFile = path.join(process.cwd(), 'reports', 'llm_cost_summary.txt');
            let summary = "No LLM usage recorded today.";
            if (fs.existsSync(costFile)) {
                summary = fs.readFileSync(costFile, 'utf-8');
            }
            return NextResponse.json({ reply: `LLM Usage Stats:\n\n${summary}` });
        }

        const response = await routeToTool(finalIntent);
        
        return NextResponse.json({ reply: response, nlpData: finalIntent });
    } catch (err) {
        console.error("Message processing error:", err);
        return NextResponse.json({ reply: "An error occurred while processing your request." }, { status: 500 });
    }
}
