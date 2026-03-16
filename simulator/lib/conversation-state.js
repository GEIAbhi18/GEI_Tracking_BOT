// In-memory conversation state for simulator
const states = {};
const TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes

export function getState(userId) {
    const stateObj = states[userId];
    if (!stateObj) return null;

    if (Date.now() - stateObj.timestamp > TIMEOUT_MS) {
        delete states[userId];
        return null;
    }
    return stateObj.state;
}

export function setState(userId, state) {
    states[userId] = {
        state: state,
        timestamp: Date.now()
    };
}

export function clearState(userId) {
    delete states[userId];
}

