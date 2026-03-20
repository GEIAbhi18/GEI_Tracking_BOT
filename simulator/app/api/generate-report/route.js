import { NextResponse } from 'next/server';
import { supabase } from '@/lib/supabase';
import { jsPDF } from 'jspdf';
import fs from 'fs';
import path from 'path';

export async function POST(req) {
  try {
    const { userName } = await req.json();

    // Access control: only Kanav can generate the report
    if (userName !== 'Kanav') {
      return NextResponse.json({ error: 'Unauthorized access. Only Kanav can generate this report.' }, { status: 403 });
    }

    // Fetch projects
    const { data: projects, error: pErr } = await supabase.from('projects').select('*');
    if (pErr) return NextResponse.json({ error: 'Failed to fetch projects.' }, { status: 500 });

    // Fetch tasks
    const { data: tasks, error: tErr } = await supabase.from('tasks').select('*');
    if (tErr) return NextResponse.json({ error: 'Failed to fetch tasks.' }, { status: 500 });

    // Process data for summaries
    const totalTasks = tasks ? tasks.length : 0;
    let completedTasks = 0;
    let blockedTasks = 0;

    tasks?.forEach(t => {
      if (t.is_blocked) blockedTasks++;
      else if (t.status === 'completed') completedTasks++;
    });

    const inProgressTasks = totalTasks - completedTasks - blockedTasks;

    let healthStatus = 'Good';
    if (blockedTasks > 0) healthStatus = 'At Risk (Blocked Tasks)';
    else if (inProgressTasks > 0) healthStatus = 'In Progress';

    // Create reports directory if it doesn't exist
    const reportsDir = path.join(process.cwd(), 'reports');
    if (!fs.existsSync(reportsDir)) {
      fs.mkdirSync(reportsDir, { recursive: true });
    }

    // Generate PDF file name
    const date = new Date();
    const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    const fileName = `${dateStr}-report.pdf`;
    const filePath = path.join(reportsDir, fileName);

    // Generate PDF using jsPDF
    const doc = new jsPDF();
    let y = 20;
    const margin = 15;
    const pageHeight = doc.internal.pageSize.height;

    const checkPageBreak = (spaceNeeded) => {
      if (y + spaceNeeded > pageHeight - margin) {
        doc.addPage();
        y = 20;
      }
    };

    doc.setFontSize(20);
    doc.text(`Daily Project Report - ${dateStr}`, 105, y, { align: 'center' });
    y += 15;

    if (!projects || projects.length === 0) {
      doc.setFontSize(12);
      doc.text('No projects found.', margin, y);
      y += 10;
    } else {
      projects.forEach((proj) => {
        const projTasks = tasks.filter(t => t.project_id === proj.id);

        let projRed = 0;
        let projAmber = 0;
        let projGreen = 0;

        projTasks.forEach(t => {
          if (t.is_blocked) projRed++;
          else if (t.status === 'completed') projGreen++;
          else projAmber++; // pending or in_progress
        });

        let projRag = 'Green';
        if (projRed > 0) projRag = 'Red';
        else if (projAmber > 0) projRag = 'Amber';

        checkPageBreak(30);
        doc.setFontSize(16);
        doc.setFont('helvetica', 'bold');
        doc.text(`Project: ${proj.name}`, margin, y);
        y += 8;
        doc.setFontSize(12);
        doc.text(`Overall Project RAG: `, margin, y);
        if (projRag === 'Red') doc.setTextColor(220, 0, 0);
        else if (projRag === 'Green') doc.setTextColor(0, 180, 0);
        else doc.setTextColor(200, 150, 0);
        doc.text(projRag, margin + 48, y);
        doc.setTextColor(0, 0, 0);
        y += 10;

        if (projTasks.length === 0) {
          doc.setFont('helvetica', 'normal');
          doc.text('No tasks for this project.', margin + 5, y);
          y += 10;
        } else {
          projTasks.forEach((t, idx) => {
            checkPageBreak(40);
            doc.setFontSize(14);
            doc.setFont('helvetica', 'bold');
            doc.text(`Task: ${t.name}`, margin + 5, y);
            y += 6;

            let tStatus = t.status || 'pending';
            let tRag = 'Amber';
            if (t.status === 'completed') tRag = 'Green';
            if (t.is_blocked) tRag = 'Red';

            doc.setFontSize(12);
            doc.setFont('helvetica', 'normal');
            
            const progress = t.progress || 0;
            const deadline = t.deadline || 'None';
            doc.text(`Status: ${tStatus} | Progress: ${progress}% | Deadline: ${deadline}`, margin + 5, y);
            y += 6;
            
            doc.text(`RAG: `, margin + 5, y);
            if (tRag === 'Red') doc.setTextColor(220, 0, 0);
            else if (tRag === 'Green') doc.setTextColor(0, 180, 0);
            else doc.setTextColor(200, 150, 0);
            doc.text(tRag, margin + 18, y);
            doc.setTextColor(0, 0, 0);
            y += 6;

            const blockerTxt = t.is_blocked ? t.blocker_reason || 'Unknown blocker' : 'None';
            doc.text(`Blocker: ${blockerTxt}`, margin + 5, y);
            y += 6;

            if (t.attachments && t.attachments.length > 0) {
              doc.setTextColor(0, 0, 255); // Blue color for links
              doc.textWithLink('View Proof Image', margin + 5, y, { url: t.attachments[0] });
              doc.setTextColor(0, 0, 0); // Reset to black
              y += 6;
            }
            y += 4;
          });
        }
        y += 5;
      });
    }

    // End of report summary
    checkPageBreak(50);
    doc.setFontSize(16);
    doc.setFont('helvetica', 'bold');
    doc.text('End-of-Report Summary', margin, y);
    y += 10;

    doc.setFontSize(12);
    doc.setFont('helvetica', 'normal');
    doc.text(`Total Tasks Worked On Today: ${totalTasks}`, margin, y);
    y += 6;
    doc.text(`Completed Tasks: ${completedTasks}`, margin, y);
    y += 6;
    doc.text(`Tasks In Progress: ${inProgressTasks}`, margin, y);
    y += 6;
    doc.text(`Blocked Tasks: ${blockedTasks}`, margin, y);
    y += 6;
    
    doc.text(`Overall Project Health Status: `, margin, y);
    if (healthStatus.includes('At Risk')) doc.setTextColor(220, 0, 0);
    else if (healthStatus.includes('Good')) doc.setTextColor(0, 180, 0);
    else doc.setTextColor(200, 150, 0);
    doc.text(healthStatus, margin + 57, y);
    doc.setTextColor(0, 0, 0);

    const pdfBuffer = Buffer.from(doc.output('arraybuffer'));
    fs.writeFileSync(filePath, pdfBuffer);

    return NextResponse.json({ message: 'Report generated successfully', fileName });
  } catch (error) {
    console.error('Report Generation Error:', error);
    return NextResponse.json({ error: 'Failed to generate report.' }, { status: 500 });
  }
}
