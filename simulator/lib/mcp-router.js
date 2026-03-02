import { checkBlockerTool } from './tools/blocker';
import { greetingTool } from './tools/greeting';
import { helpTool } from './tools/help';

export const mcpTools = {
    check_blocker_status: checkBlockerTool,
    greeting: greetingTool,
    help: helpTool
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
