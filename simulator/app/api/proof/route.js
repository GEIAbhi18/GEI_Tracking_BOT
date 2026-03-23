import { NextResponse } from 'next/server';
import { supabase } from '@/lib/supabase';

export async function GET(req) {
    try {
        const { searchParams } = new URL(req.url);
        const taskId = searchParams.get('taskId');
        if (!taskId) return NextResponse.json({ error: 'Missing taskId' }, { status: 400 });

        const { data, error } = await supabase.from('tasks').select('attachments').eq('id', taskId).single();
        if (error || !data || !data.attachments || data.attachments.length === 0) {
            return NextResponse.json({ error: 'No proof image found' }, { status: 404 });
        }

        const url = data.attachments[0];
        
        if (url.startsWith('http')) {
            // Redirect to the actual HTTP URL (e.g. from Telegram)
            return NextResponse.redirect(url);
        }
        
        if (url.startsWith('data:image')) {
            // Return an HTML page with the image embedded
            const html = `
            <!DOCTYPE html>
            <html>
            <head>
                <title>Task Proof</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
            </head>
            <body style="margin: 0; display: flex; justify-content: center; align-items: center; min-height: 100vh; background-color: #f0f0f0;">
                <img src="${url}" style="max-width: 100%; max-height: 100vh; object-fit: contain; box-shadow: 0 4px 6px rgba(0,0,0,0.1);" />
            </body>
            </html>
            `;
            return new NextResponse(html, {
                headers: {
                    'Content-Type': 'text/html',
                },
            });
        }

        return NextResponse.json({ error: 'Invalid attachment format' }, { status: 400 });
    } catch (e) {
        console.error('Proof Fetch Error:', e);
        return NextResponse.json({ error: 'Failed to fetch proof Image' }, { status: 500 });
    }
}
