const { createClient } = require('@supabase/supabase-js');

const supabaseUrl = 'https://iymesslajpqkvxdhjwmy.supabase.co';
const supabaseKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5bWVzc2xhanBxa3Z4ZGhqd215Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE5OTY4NzEsImV4cCI6MjA4NzU3Mjg3MX0.smGizS-ECU3iad9wCoVlgCHWJxgZAsH_IDddWZ7shbE';

const supabase = createClient(supabaseUrl, supabaseKey);

async function run() {
    const { data: tasks, error: err2 } = await supabase.from('tasks').select('*, projects(name)');
    console.log('TASKS:', tasks);
}

run();
