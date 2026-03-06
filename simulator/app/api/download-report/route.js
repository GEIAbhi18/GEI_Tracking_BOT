import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET(req) {
    try {
        const { searchParams } = new URL(req.url);
        const userName = searchParams.get('userName');

        // Access control: only Kanav can download the report
        if (userName !== 'Kanav') {
            return NextResponse.json({ error: 'Unauthorized access. Only Kanav can download this report.' }, { status: 403 });
        }

        const date = new Date();
        const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        const fileName = `${dateStr}-report.pdf`;
        const filePath = path.join(process.cwd(), 'reports', fileName);

        if (!fs.existsSync(filePath)) {
            return NextResponse.json({ error: 'Report not found. Please generate it first.' }, { status: 404 });
        }

        const stat = fs.statSync(filePath);
        const stream = fs.createReadStream(filePath);

        return new NextResponse(stream, {
            headers: {
                'Content-Type': 'application/pdf',
                'Content-Length': stat.size,
                'Content-Disposition': `attachment; filename=${fileName}`,
            },
        });
    } catch (error) {
        console.error('Report Download Error:', error);
        return NextResponse.json({ error: 'Failed to download report.' }, { status: 500 });
    }
}
