const { createClient } = require('@supabase/supabase-js');
require('dotenv').config({ path: '.env.local' });
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://iymesslajpqkvxdhjwmy.supabase.co';
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5bWVzc2xhanBxa3Z4ZGhqd215Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE5OTY4NzEsImV4cCI6MjA4NzU3Mjg3MX0.smGizS-ECU3iad9wCoVlgCHWJxgZAsH_IDddWZ7shbE';
const supabase = createClient(supabaseUrl, supabaseKey);

async function test() {
  const { data: proj } = await supabase.from('projects').select('*');
  const { data: tasks } = await supabase.from('tasks').select('*');
  const { data: updates } = await supabase.from('updates').select('*');
  console.log('Projects:', proj);
  console.log('Tasks:', tasks);
  console.log('Updates:', updates);
}
test();
