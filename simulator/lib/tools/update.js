export async function reportUpdateTool(entities) {
    let msg = "Simulated update recorded:\n";
    if (entities.project) msg += `- Project: ${entities.project}\n`;
    if (entities.task) msg += `- Task: ${entities.task}\n`;
    if (entities.status) msg += `- Status: ${entities.status}\n`;
    if (entities.blocker) msg += `- Blocker/Notes: ${entities.blocker}\n`;

    if (!entities.project && !entities.task) {
        msg = "We received your update, but we couldn't strongly identify the exact project or task. (Simulation Fallback)";
    }

    return msg;
}
