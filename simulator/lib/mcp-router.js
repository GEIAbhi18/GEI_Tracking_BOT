import { getTasksTool } from './tools/new_tasks';
import { updateTaskTool, markDoneTool } from './tools/new_update_task';
import { createTaskTool } from './tools/new_create_task';
import { createTicketTool } from './tools/new_ticket';
import { checkBlockersTool, addBlockerTool } from './tools/new_blocker';
import { assignTaskTool } from './tools/new_assign';
import { uploadDeliverableTool } from './tools/new_deliverable';
import { taskDetailsTool } from './tools/new_task_details';
import { viewProjectsTool } from './tools/view_projects';
import { viewTicketsTool } from './tools/view_tickets';
import { replyTicketTool } from './tools/reply_ticket';
import { closeTicketTool } from './tools/close_ticket';
import { greetingTool } from './tools/greeting';
import { requestReportTool } from './tools/request_report';
import { createProjectTool } from './tools/create_project';

export const mcpTools = {
    create_task: createTaskTool,
    create_project: createProjectTool,
    create_ticket: createTicketTool,
    update_task: updateTaskTool,
    assign_task: assignTaskTool,
    mark_done: markDoneTool,
    complete_task: markDoneTool,
    list_tasks: getTasksTool,
    add_blocker: addBlockerTool,
    check_blockers: checkBlockersTool,
    query_blockers: checkBlockersTool,
    task_details: taskDetailsTool,
    upload_deliverable: uploadDeliverableTool,
    view_projects: viewProjectsTool,
    view_tickets: viewTicketsTool,
    request_report: requestReportTool,
    reply_ticket: replyTicketTool,
    close_ticket: closeTicketTool,
    greeting: greetingTool
};

export async function routeToTool(intentObj) {
    const { intent, entities } = intentObj;

    if (intent === 'unknown') {
        return "I couldn't understand that request. Please rephrase.";
    }

    const executor = mcpTools[intent];
    if (!executor) {
        return "I couldn't understand that request. Please rephrase.";
    }

    return await executor(entities);
}
