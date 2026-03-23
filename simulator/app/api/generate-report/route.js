import { NextResponse } from 'next/server';

export async function POST(req) {
  try {
    const { userName } = await req.json();

    // Access control: only Kanav can generate the report
    if (userName !== 'Kanav') {
      return NextResponse.json({ error: 'Unauthorized access. Only Kanav can generate this report.' }, { status: 403 });
    }

    // Generate PDF file name
    const date = new Date();
    const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    const fileName = `${dateStr}-report.pdf`;

    return NextResponse.json({ message: 'Report generated successfully', fileName });
  } catch (error) {
    console.error('Report Generation Error:', error);
    return NextResponse.json({ error: 'Failed to generate report.' }, { status: 500 });
  }
}
