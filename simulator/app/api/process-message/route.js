import { NextResponse } from 'next/server';
import { extractIntentWithLLM } from '@/lib/llm';
import { routeToTool } from '@/lib/mcp-router';
import { supabase } from '@/lib/supabase';
import { ruleBasedNLP } from '@/lib/nlp';
import { getState, setState, clearState } from '@/lib/conversation-state';
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
        const { message, userName = 'Asif', chatHistory = [], attachments = [] } = body;

        if (!message || message.trim() === '') {
            return NextResponse.json({ reply: "I didn't catch that. Please send a valid message." });
        }

        const rawText = message.trim();
        const lowerText = rawText.toLowerCase();

        // 1. Conversation State Manager (HIGHEST PRIORITY)
        const state = getState(userName);
        if (state) {
            if (state.action === 'add_blocker') {
                if (state.step === 'waiting_for_task') {
                    state.task_query = rawText;
                    state.step = 'waiting_for_description';
                    setState(userName, state);
                    return NextResponse.json({ reply: "What is the issue holding this task?" });
                } else if (state.step === 'waiting_for_description') {
                    const intent = {
                        intent: 'add_blocker',
                        entities: { task_name: state.task_query, blocker_name: rawText, assignee: userName, attachments }
                    };
                    clearState(userName);
                    const response = await routeToTool(intent);
                    if (typeof response === 'string' && response.includes("please upload an image proof")) {
                        setState(userName, { action: 'upload_proof', task_query: state.task_query });
                    }
                    return NextResponse.json({ reply: response, nlpData: intent });
                }
            } else if (state.action === 'update_task') {
                if (state.step === 'waiting_for_task') {
                    state.task_query = rawText;
                    state.step = 'waiting_for_progress';
                    setState(userName, state);
                    return NextResponse.json({ reply: "What is the progress %?" });
                } else if (state.step === 'waiting_for_progress') {
                    const intent = {
                        intent: 'update_task',
                        entities: { task_name: state.task_query, completion_percent: rawText, assignee: userName, attachments }
                    };
                    clearState(userName);
                    const response = await routeToTool(intent);
                    if (typeof response === 'string' && response.includes("please upload an image proof")) {
                        setState(userName, { action: 'upload_proof', task_query: state.task_query });
                    }
                    return NextResponse.json({ reply: response, nlpData: intent });
                }
            } else if (state.action === 'complete_task') {
                if (state.step === 'waiting_for_project') {
                    state.project_query = rawText;
                    state.step = 'waiting_for_task';
                    setState(userName, state);
                    const { data: tasks } = await supabase.from('tasks').select('name, projects(name)').ilike('projects.name', `%${rawText}%`).neq('status', 'completed');
                    const taskList = tasks && tasks.length > 0 ? tasks.map(t => `- ${t.name}`).join('\n') : "No pending tasks found for this project.";
                    return NextResponse.json({ reply: `Which task should I complete in "${rawText}"?\n\n${taskList}` });
                } else if (state.step === 'waiting_for_task') {
                    const intent = {
                        intent: 'complete_task',
                        entities: { project_name: state.project_query, task_name: rawText, assignee: userName, attachments }
                    };
                    clearState(userName);
                    const response = await routeToTool(intent);
                    if (typeof response === 'string' && response.includes("please upload an image proof")) {
                        setState(userName, { action: 'upload_proof', task_query: rawText, project_query: state.project_query });
                    }
                    return NextResponse.json({ reply: response, nlpData: intent });
                }
            } else if (state.action === 'create_task') {
                if (state.step === 'waiting_for_project') {
                    state.project_query = rawText;
                    state.step = 'waiting_for_task_name';
                    setState(userName, state);
                    return NextResponse.json({ reply: "What is the name of the new task?" });
                } else if (state.step === 'waiting_for_task_name') {
                    const intent = {
                        intent: 'create_task',
                        entities: { project_name: state.project_query, task_name: rawText, assignee: userName }
                    };
                    clearState(userName);
                    const response = await routeToTool(intent);
                    return NextResponse.json({ reply: response, nlpData: intent });
                }
            } else if (state.action === 'create_project_step') {
                if (state.step === 'waiting_for_name') {
                    const intent = {
                        intent: 'create_project',
                        entities: { raw_message: `Project: ${rawText}`, target_user: userName }
                    };
                    clearState(userName);
                    const response = await routeToTool(intent);
                    return NextResponse.json({ reply: response, nlpData: intent });
                }
            } else if (state.action === 'upload_proof') {
                if (attachments && attachments.length > 0) {
                    const intent = {
                        intent: 'complete_task',
                        entities: { project_name: state.project_query, task_name: state.task_query, completion_percent: '100', assignee: userName, attachments }
                    };
                    clearState(userName);
                    const response = await routeToTool(intent);
                    return NextResponse.json({ reply: response, nlpData: intent });
                } else {
                    return NextResponse.json({ reply: "Please upload the image proof (attachment) to mark the task as 100% complete. 📸" });
                }
            } else if (state.action === 'create_ticket') {
                if (state.step === 'waiting_for_project') {
                    state.project_query = rawText;
                    state.step = 'waiting_for_description';
                    setState(userName, state);
                    return NextResponse.json({ reply: "What is the issue or concern?" });
                } else if (state.step === 'waiting_for_description') {
                    const intent = {
                        intent: 'create_ticket',
                        entities: { project_name: state.project_query, ticket_name: rawText, assignee: userName }
                    };
                    clearState(userName);
                    const response = await routeToTool(intent);
                    return NextResponse.json({ reply: response, nlpData: intent });
                }
            }
        }

        let finalIntent = null;

        // 2. Command Mode Bypass
        if (rawText.startsWith('/')) {
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

            const allowedCommands = ['update_task', 'add_blocker', 'create_ticket', 'create_task', 'assign_task', 'mark_done', 'list_tasks', 'check_blockers', 'query_blockers', 'task_details', 'upload_deliverable', 'view_projects', 'view_tickets', 'request_report', 'reply_ticket', 'close_ticket'];
            
            if (allowedCommands.includes(cmd)) {
                let targetAssignee = userName;
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

        // 3. Rule-based NLP as Deterministic Layer (BEFORE LLM)
        if (!finalIntent) {
            const nlpResult = ruleBasedNLP(message);
            // High confidence threshold for automatic transition
            if (nlpResult.confidence >= 0.7) {
                finalIntent = nlpResult;
            }
        }

        // 4. LLM Intent Parser (Fallback for complex natural language)
        if (!finalIntent) {
            const llmResult = await extractIntentWithLLM(message, chatHistory);

            if (llmResult && llmResult.intent && llmResult.intent !== 'unknown') {
                finalIntent = llmResult;
                
                if (userName === 'Kanav' && 
                    ['list_tasks', 'create_task', 'update_task', 'task_details'].includes(finalIntent.intent) && 
                    !finalIntent.entities.assignee) {
                    finalIntent.entities.assignee = 'Asif';
                }
            }
        }

        if (finalIntent) {
            if (!finalIntent.entities.assignee) finalIntent.entities.assignee = userName;
            finalIntent.entities.userName = userName;
            finalIntent.entities.raw_message = message;
            finalIntent.entities.attachments = attachments;
        }

        // 5. Final Intent Router & State Initiation
        if (finalIntent) {
            // Check for missing slots to initiate state
            if (finalIntent.intent === 'add_blocker') {
                if (!finalIntent.entities.task_name && !finalIntent.entities.task_id) {
                    const { data: tasks } = await supabase.from('tasks').select('name, projects(name)').neq('status', 'completed');
                    const taskList = tasks.map(t => `- ${t.name} (${t.projects?.name})`).join('\n');
                    setState(userName, { action: 'add_blocker', step: 'waiting_for_task' });
                    return NextResponse.json({ reply: `Which task is blocked?\n\n${taskList}`, nlpData: finalIntent });
                }
                if (!finalIntent.entities.blocker_name) {
                    setState(userName, { action: 'add_blocker', step: 'waiting_for_description', task_query: finalIntent.entities.task_name });
                    return NextResponse.json({ reply: "What is the issue holding this task?", nlpData: finalIntent });
                }
            } else if (finalIntent.intent === 'update_task') {
                if (!finalIntent.entities.task_name && !finalIntent.entities.task_id) {
                    const { data: tasks } = await supabase.from('tasks').select('name, projects(name)').neq('status', 'completed');
                    const taskList = tasks.map(t => `- ${t.name} (${t.projects?.name})`).join('\n');
                    setState(userName, { action: 'update_task', step: 'waiting_for_task' });
                    return NextResponse.json({ reply: `Which task do you want to update?\n\n${taskList}`, nlpData: finalIntent });
                }
            } else if (finalIntent.intent === 'create_task') {
                if (!finalIntent.entities.project_name) {
                    const { data: projects } = await supabase.from('projects').select('name');
                    const projectList = projects.map(p => `- ${p.name}`).join('\n');
                    setState(userName, { action: 'create_task', step: 'waiting_for_project' });
                    return NextResponse.json({ reply: `Which project should this task be added to?\n\n${projectList}`, nlpData: finalIntent });
                }
                if (!finalIntent.entities.task_name) {
                    setState(userName, { action: 'create_task', step: 'waiting_for_task_name', project_query: finalIntent.entities.project_name });
                    return NextResponse.json({ reply: "What is the name of the new task?", nlpData: finalIntent });
                }
            } else if (finalIntent.intent === 'create_project') {
                const projMatch = finalIntent.entities.raw_message?.match(/Project\s*:?\s*(.+?)(?:\n|$)/i) || 
                                finalIntent.entities.raw_message?.match(/create project (.*)/i);
                if (!projMatch) {
                    setState(userName, { action: 'create_project_step', step: 'waiting_for_name' });
                    return NextResponse.json({ reply: "What is the name of the new project?", nlpData: finalIntent });
                }
            } else if (finalIntent.intent === 'complete_task' || finalIntent.intent === 'mark_done') {
                if (!finalIntent.entities.project_name) {
                    const { data: projects } = await supabase.from('projects').select('name');
                    const projectList = (projects || []).map(p => `- ${p.name}`).join('\n');
                    setState(userName, { action: 'complete_task', step: 'waiting_for_project' });
                    return NextResponse.json({ reply: `Which project is the task in?\n\n${projectList}`, nlpData: finalIntent });
                }
                if (!finalIntent.entities.task_name && !finalIntent.entities.task_id) {
                    const { data: tasks } = await supabase.from('tasks').select('name, projects(name)').ilike('projects.name', `%${finalIntent.entities.project_name}%`).neq('status', 'completed');
                    const taskList = tasks && tasks.length > 0 ? tasks.map(t => `- ${t.name}`).join('\n') : "No pending tasks found for this project.";
                    setState(userName, { action: 'complete_task', step: 'waiting_for_task', project_query: finalIntent.entities.project_name });
                    return NextResponse.json({ reply: `Which task should I complete in "${finalIntent.entities.project_name}"?\n\n${taskList}`, nlpData: finalIntent });
                }
            } else if (finalIntent.intent === 'create_ticket') {
                if (!finalIntent.entities.project_name) {
                    const { data: projects } = await supabase.from('projects').select('name');
                    const projectList = (projects || []).map(p => `- ${p.name}`).join('\n');
                    setState(userName, { action: 'create_ticket', step: 'waiting_for_project' });
                    return NextResponse.json({ reply: `Which project is this for?\n\n${projectList}`, nlpData: finalIntent });
                }
            }

            const response = await routeToTool(finalIntent);
            if (typeof response === 'string' && response.includes("please upload an image proof")) {
                setState(userName, { 
                    action: 'upload_proof', 
                    task_query: finalIntent.entities.task_name || finalIntent.entities.task_id 
                });
            }
            return NextResponse.json({ reply: response, nlpData: finalIntent });
        }

        // Handle unknown
        const isLLMNatural = lowerText.includes('llm usage') || lowerText.includes('llm costing') || lowerText.includes('llm cost');
        if (isLLMNatural) {
            if (userName !== 'Kanav') return NextResponse.json({ reply: "Access denied." });
            const costFile = path.join(process.cwd(), 'reports', 'llm_cost_summary.txt');
            let summary = fs.existsSync(costFile) ? fs.readFileSync(costFile, 'utf-8') : "No data.";
            return NextResponse.json({ reply: `LLM Usage Stats:\n\n${summary}` });
        }

        await logUnknown(message, {}, userName);
        return NextResponse.json({
            reply: "I couldn't specify your request intent. Please try standard formats or commands.",
            nlpData: { intent: 'unknown' }
        });

    } catch (err) {
        console.error("Message processing error:", err);
        return NextResponse.json({ reply: "An error occurred while processing your request." }, { status: 500 });
    }
}

