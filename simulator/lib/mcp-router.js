import { checkBlockerTool } from './tools/blocker';
import { greetingTool } from './tools/greeting';
import { helpTool } from './tools/help';
import { reportUpdateTool } from './tools/update';
import { taskListTool } from './tools/task_list';
import { updateNumberedTaskTool } from './tools/update_numbered_task';
import { createTaskTool } from './tools/create_task';
import { requestReportTool } from './tools/request_report';
import { createProjectTool } from './tools/create_project';
import { viewUpdatesTool } from './tools/view_updates';
import { viewProjectsTool } from './tools/view_projects';

export const mcpTools = {
    check_blocker_status: checkBlockerTool,
    greeting: greetingTool,
    help: helpTool,
    report_update: reportUpdateTool,
    task_list: taskListTool,
    update_numbered_task: updateNumberedTaskTool,
    create_task: createTaskTool,
    request_report: requestReportTool,
    create_project: createProjectTool,
    view_updates: viewUpdatesTool,
    view_projects: viewProjectsTool
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
