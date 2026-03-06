const cron = require('node-cron');
const fs = require('fs');
const path = require('path');
const PDFDocument = require('pdfkit');
const { createClient } = require('@supabase/supabase-js');
require('dotenv').config({ path: '.env.local' });

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://iymesslajpqkvxdhjwmy.supabase.co';
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5bWVzc2xhanBxa3Z4ZGhqd215Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE5OTY4NzEsImV4cCI6MjA4NzU3Mjg3MX0.smGizS-ECU3iad9wCoVlgCHWJxgZAsH_IDddWZ7shbE';
const supabase = createClient(supabaseUrl, supabaseKey);

async function generateDailyReport() {
    console.log('Generating Daily Project Report at 6 PM...');
    try {
        // Fetch projects
        const { data: projects, error: pErr } = await supabase.from('projects').select('*');
        if (pErr) {
            console.error('Error fetching projects for report:', pErr);
            return;
        }

        // Fetch tasks
        const { data: tasks, error: tErr } = await supabase.from('tasks').select('*');
        if (tErr) {
            console.error('Error fetching tasks for report:', tErr);
            return;
        }

        const totalTasks = tasks ? tasks.length : 0;
        let completedTasks = 0;
        let blockedTasks = 0;

        tasks?.forEach(t => {
            if (t.is_blocked) blockedTasks++;
            else if (t.status === 'completed') completedTasks++;
        });

        const inProgressTasks = totalTasks - completedTasks - blockedTasks;

        let healthStatus = '🟢 Good';
        if (blockedTasks > 0) healthStatus = '🔴 At Risk (Blocked Tasks)';
        else if (inProgressTasks > 0) healthStatus = '🟡 In Progress';

        const reportsDir = path.join(__dirname, 'reports');
        if (!fs.existsSync(reportsDir)) {
            fs.mkdirSync(reportsDir, { recursive: true });
        }

        const date = new Date();
        const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        const fileName = `${dateStr}-report.pdf`;
        const filePath = path.join(reportsDir, fileName);

        const doc = new PDFDocument({ margin: 50 });
        const stream = fs.createWriteStream(filePath);

        doc.pipe(stream);

        doc.fontSize(20).text(`Daily Project Report - ${dateStr}`, { align: 'center' });
        doc.moveDown();

        if (!projects || projects.length === 0) {
            doc.fontSize(12).text('No projects found.');
            doc.moveDown();
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

                doc.fontSize(16).font('Helvetica-Bold').text(`Project: ${proj.name}`);
                doc.fontSize(12).font('Helvetica').text(`Overall Project RAG: ${projRag}`);
                doc.moveDown();

                if (projTasks.length === 0) {
                    doc.font('Helvetica').text('No tasks for this project.', { indent: 20 });
                    doc.moveDown();
                } else {
                    projTasks.forEach((t) => {
                        doc.fontSize(14).font('Helvetica-Bold').text(`Task: ${t.name}`, { indent: 20 });

                        let tStatus = t.status || 'pending';
                        let tRag = 'Amber';
                        if (t.status === 'completed') tRag = 'Green';
                        if (t.is_blocked) tRag = 'Red';

                        doc.fontSize(12).font('Helvetica');
                        doc.text(`Status: ${tStatus}`, { indent: 20 });
                        doc.text(`RAG: ${tRag}`, { indent: 20 });

                        const blockerTxt = t.is_blocked ? t.blocker_reason || 'Unknown blocker' : 'None';
                        doc.text(`Blocker: ${blockerTxt}`, { indent: 20 });
                        doc.moveDown();
                    });
                }
                doc.moveDown();
            });
        }

        doc.moveDown();
        doc.fontSize(16).font('Helvetica-Bold').text('End-of-report summary');
        doc.fontSize(12).font('Helvetica');
        doc.text(`Total tasks worked on today: ${totalTasks}`);
        doc.text(`Completed tasks: ${completedTasks}`);
        doc.text(`Tasks in progress: ${inProgressTasks}`);
        doc.text(`Blocked tasks: ${blockedTasks}`);
        doc.text(`Overall project health status: ${healthStatus}`);

        doc.end();

        stream.on('finish', () => {
            console.log(`Report generated successfully at: ${filePath}`);
        });

    } catch (error) {
        console.error('Scheduler Report Generation Error:', error);
    }
}

// Scheduled for 6:00 PM every day
cron.schedule('0 18 * * *', () => {
    generateDailyReport();
});

console.log('Daily Report Scheduler started. It will generate reports at 6 PM daily.');
