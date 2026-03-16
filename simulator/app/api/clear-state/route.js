import { NextResponse } from 'next/server';
import { clearState } from '@/lib/conversation-state';

export async function POST(req) {
    try {
        const body = await req.json();
        const { userName } = body;

        if (userName) {
            clearState(userName);
        } else {
            // Clear both users on a general reset
            clearState('Asif');
            clearState('Kanav');
        }

        return NextResponse.json({ ok: true });
    } catch (err) {
        return NextResponse.json({ ok: false }, { status: 500 });
    }
}
