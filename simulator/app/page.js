'use client';

import { useState, useEffect, useRef } from 'react';
import {
  Send, Menu, Search, Paperclip, Smile, ArrowLeft,
  Check, CheckCheck, MoreVertical, Phone, Bot, X, Mic
} from 'lucide-react';
import { format } from "date-fns";
import { parseUpdateMessage } from '@/lib/messageParser';
import { supabase } from '@/lib/supabase';
import clsx from 'clsx';

const formatTime = (date) => {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

export default function SimulatorApp() {
  const [currentUser, setCurrentUser] = useState('Asif'); // 'Asif' or 'Kanav'
  const [mobileView, setMobileView] = useState('sidebar'); // 'sidebar' | 'chat'
  const [input, setInput] = useState('');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false); // Mobile drawer

  // Shared ticket state for simulation without Supabase
  const [globalTickets, setGlobalTickets] = useState([]);

  // Persistent states per user
  const [userStates, setUserStates] = useState({
    Asif: { messages: [], mode: 'normal', ticketState: { step: 0, project: '', task: '', message: '' } },
    Kanav: { messages: [], mode: 'normal', ticketState: { step: 0, project: '', task: '', message: '' } }
  });

  const endOfMessagesRef = useRef(null);

  const activeState = userStates[currentUser];
  const messages = activeState.messages;

  const setMessages = (updateFn) => {
    setUserStates((prev) => ({
      ...prev,
      [currentUser]: {
        ...prev[currentUser],
        messages: typeof updateFn === 'function' ? updateFn(prev[currentUser].messages) : updateFn
      }
    }));
  };

  const setMode = (mode) => {
    setUserStates((prev) => ({
      ...prev,
      [currentUser]: { ...prev[currentUser], mode }
    }));
  };

  const setTicketState = (updateFn) => {
    setUserStates((prev) => ({
      ...prev,
      [currentUser]: {
        ...prev[currentUser],
        ticketState: typeof updateFn === 'function' ? updateFn(prev[currentUser].ticketState) : updateFn
      }
    }));
  };

  useEffect(() => {
    endOfMessagesRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, mobileView]);

  // Initial bot message on load for each user if empty
  useEffect(() => {
    if (messages.length === 0) {
      const startText = currentUser === 'Asif'
        ? '🤖 Welcome! Available Commands:\n\n• /update_task\n• /raise_ticket\n• /view_tickets\n• /create_task\n• /create_project\n• /help'
        : '🤖 Welcome! Available Commands:\n\n• /get_report\n• /get_task\n• /create_task\n• /create_project\n• /view_tickets\n• /help';

      const buttons = currentUser === 'Asif'
        ? ['/update_task', '/raise_ticket', '/view_tickets', '/create_task', '/create_project', '/help']
        : ['/get_report', '/get_task', '/create_task', '/create_project', '/view_tickets', '/help'];

      setMessages([{ id: Date.now(), sender: 'bot', text: startText, buttons, time: formatTime(new Date()) }]);
    }
  }, [currentUser, messages.length]);

  const addBotMessage = (text, buttons = []) => {
    setMessages(prev => [...prev, { id: Date.now(), sender: 'bot', text, buttons, time: formatTime(new Date()) }]);
  };

  const addUserMessage = (text) => {
    setMessages(prev => [...prev, { id: Date.now(), sender: 'user', text, time: formatTime(new Date()), status: 'sent' }]);
    // Simulate read tick after a delay
    setTimeout(() => {
      setMessages(prev => prev.map(m => m.text === text && m.sender === 'user' ? { ...m, status: 'read' } : m));
    }, 1000);
  };

  const handleStart = () => {
    const text = currentUser === 'Asif'
      ? 'Available Commands:\n• /update_task\n• /raise_ticket\n• /view_tickets\n• /create_task\n• /create_project\n• /help'
      : 'Available Commands:\n• /get_report\n• /get_task\n• /create_task\n• /create_project\n• /view_tickets\n• /help';

    const buttons = currentUser === 'Asif'
      ? ['/update_task', '/raise_ticket', '/view_tickets', '/create_task', '/create_project', '/help']
      : ['/get_report', '/get_task', '/create_task', '/create_project', '/view_tickets', '/help'];

    setMode('normal');
    addBotMessage(text, buttons);
  };

  // Ticket Creation Flow
  const startRaiseTicket = () => {
    setMode('raise_ticket');
    setTicketState({ step: 1, project: '', task: '', message: '' });
    addBotMessage('Select Project for Ticket:', ['Top Terrace', '9TH FLOOR (CENTRIC)']);
  };

  const processRaiseTicket = async (text) => {
    const { step } = activeState.ticketState;
    if (step === 1) {
      setTicketState(prev => ({ ...prev, step: 2, project: text }));
      addBotMessage('Select Task (or type None):', ['tile', 'membrane', 'malba', 'slope', 'solar', 'waterproof', 'ponding', 'None']);
    } else if (step === 2) {
      setTicketState(prev => ({ ...prev, step: 3, task: text === 'None' ? '' : text }));
      addBotMessage('Enter ticket message detailed description:');
    } else if (step === 3) {
      const finalProject = activeState.ticketState.project;
      const finalTask = activeState.ticketState.task;

      setTicketState({ step: 0, project: '', task: '', message: '' });
      setMode('normal');

      const newTicket = { id: Date.now(), project_name: finalProject, task_name: finalTask, message: text, created_by: currentUser, status: 'open' };
      setGlobalTickets(prev => [...prev, newTicket]);

      try {
        // Query IDs
        let pId = null, tId = null, uId = null;
        let pData = await supabase.from('projects').select('id').ilike('name', `%${finalProject}%`).limit(1);
        if (pData.data && pData.data.length) pId = pData.data[0].id;
        let tData = await supabase.from('tasks').select('id').ilike('name', `%${finalTask}%`).limit(1);
        if (tData.data && tData.data.length) tId = tData.data[0].id;
        let uData = await supabase.from('users').select('id').ilike('name', currentUser).limit(1);
        if (uData.data && uData.data.length) uId = uData.data[0].id;

        await supabase.from('tickets').insert([{
          project_id: pId,
          task_id: tId,
          created_by: uId,
          status: 'open'
          // note: Supabase may not have a Message column for MVP in tickets, simulated in local state.
        }]);
      } catch (err) { }

      addBotMessage(`Ticket raised successfully for project ${finalProject}! ✅`);
    }
  };

  // Blocker Flow (Asif -> Kanav)
  const processSendBlocker = (text) => {
    const { step } = activeState.ticketState;
    if (step === 1) {
      setTicketState(prev => ({ ...prev, step: 2, project: text }));
      addBotMessage('Blocker targeted Task:', ['tile', 'membrane', 'malba', 'slope', 'solar', 'waterproof', 'ponding']);
    } else if (step === 2) {
      setTicketState(prev => ({ ...prev, step: 3, task: text }));
      addBotMessage('Please describe the blocker exactly:');
    } else if (step === 3) {
      const finalProject = activeState.ticketState.project;
      const finalTask = activeState.ticketState.task;

      setTicketState({ step: 0, project: '', task: '', message: '' });
      setMode('normal');

      addBotMessage('Blocker update securely sent to Kanav! ✅');

      // Append entirely into Kanav's message history to mimic real Telegram messaging across multiple clients.
      setUserStates(prev => ({
        ...prev,
        Kanav: {
          ...prev.Kanav,
          messages: [...prev.Kanav.messages, {
            id: Date.now(),
            sender: 'bot',
            text: `🚨 URGENT BLOCKER from Asif:\n\n📁 Project: ${finalProject}\n📋 Task: ${finalTask}\n🛑 Blocker Details: ${text}`,
            time: formatTime(new Date())
          }]
        }
      }));
    }
  };

  // View Tickets
  const handleViewTickets = async () => {
    addBotMessage('Fetching tickets...');
    let dbTickets = [];
    try {
      // Query tickets and join related string names to decode UUIDs
      const { data, error } = await supabase.from('tickets')
        .select(`
          id,
          status,
          created_at,
          projects:project_id(name),
          tasks:task_id(name),
          users:created_by(name)
        `)
        .eq('status', 'open').order('created_at', { ascending: false }).limit(10);
      if (!error && data && data.length > 0) dbTickets = data;
    } catch (err) { }

    const allOpen = globalTickets.filter(t => t.status === 'open');

    // We combine them, and prioritize the local 'message' simulating the MVP lacking message column
    let combinedTickets = {};
    dbTickets.forEach(t => combinedTickets[t.id] = { ...t, isDb: true });
    allOpen.forEach(t => {
      if (!combinedTickets[t.id]) combinedTickets[t.id] = t;
      else {
        // Merge simulated message into DB record
        combinedTickets[t.id].message = t.message;
        combinedTickets[t.id].task_name = t.task_name;
        combinedTickets[t.id].project_name = t.project_name;
        combinedTickets[t.id].created_by_name = t.created_by;
      }
    });

    const ticketsToShow = Object.values(combinedTickets).sort((a, b) => b.id - a.id);

    if (ticketsToShow.length === 0) {
      addBotMessage('No open tickets found.');
    } else {
      const formatted = ticketsToShow.map(t => {
        const pName = t.projects?.name || t.project_name || 'N/A';
        const tName = t.tasks?.name || t.task_name || 'N/A';
        const uName = t.users?.name || t.created_by_name || t.created_by || 'Unknown';
        const msgText = t.message || '(Ticket raised via system - see chat history)';
        return `🎫 Ticket #${t.id}\n📁 Project: ${pName}\n📋 Task: ${tName}\n💬 Message: ${msgText}\n👤 By: ${uName}`;
      }).join('\n\n---\n\n');
      addBotMessage(`Open Tickets:\n\n${formatted}`);

      ticketsToShow.forEach(t => {
        const btns = [`Reply to Ticket #${t.id}`];
        if (currentUser === 'Kanav') btns.push(`Close Ticket #${t.id}`);
        addBotMessage(`Actions for Ticket #${t.id}:`, btns);
      });
    }
  };

  // Update Task flow (Asif)
  const startUpdateTask = () => {
    setMode('update_task');
    setTicketState({ step: 1, project: '', task: '', message: '' });
    addBotMessage('Here are the Project details. Please select a project to update:', ['Top Terrace', '9TH FLOOR (CENTRIC)']);
  };

  const processUpdateTask = async (text) => {
    const { step } = activeState.ticketState;

    if (step === 1) {
      setTicketState(prev => ({ ...prev, step: 2, project: text }));
      addBotMessage(`Fetching tasks for ${text}...\nPlease choose the task you want to post an update for:`, ['tile', 'membrane', 'malba', 'slope', 'solar', 'waterproof', 'ponding']);
    } else if (step === 2) {
      setTicketState(prev => ({ ...prev, step: 3, task: text }));
      addBotMessage(`Selected Task: ${text}\nNow, please figure your input (e.g., progress percentage and blockers):`);
    } else if (step === 3) {
      const finalProject = activeState.ticketState.project;
      const finalTask = activeState.ticketState.task;

      const parsed = parseUpdateMessage(text);
      const progress = parsed?.progress !== null ? parsed.progress : 'Unknown';
      const blocker = parsed?.blocker || (text.toLowerCase().includes('blocker') ? text : 'None');

      setTicketState({ step: 0, project: '', task: '', message: '' });
      setMode('normal');

      try {
        let tId = null, eId = null;
        let tData = await supabase.from('tasks').select('id').ilike('name', `%${finalTask}%`).limit(1);
        if (tData.data && tData.data.length) tId = tData.data[0].id;
        let uData = await supabase.from('users').select('id').ilike('name', currentUser).limit(1);
        if (uData.data && uData.data.length) eId = uData.data[0].id;

        await supabase.from('updates').insert([{
          task_id: tId,
          employee_id: eId,
          progress: typeof progress === 'number' ? progress : 0,
          blockers: blocker.toString(),
          rag: 'AMBER'
        }]);
      } catch (err) { console.error(err) }

      addBotMessage(`Update logged ✅\nProject: ${finalProject}\nTask: ${finalTask}\nProgress: ${progress}%\nBlocker: ${blocker}`);

      // Forward to Kanav seamlessly
      setUserStates(prev => ({
        ...prev,
        Kanav: {
          ...prev.Kanav,
          messages: [...prev.Kanav.messages, {
            id: Date.now(),
            sender: 'bot',
            text: `📊 NEW DAILY UPDATE from Asif:\n\n📁 Project: ${finalProject}\n📋 Task: ${finalTask}\n📈 Progress: ${progress}%\n🛑 Blocker: ${blocker}\n📝 Raw Input: "${text}"`,
            time: formatTime(new Date())
          }]
        }
      }));
    }
  };

  // Get Report flow (Kanav)
  const startGetReport = () => {
    setMode('get_report');
    addBotMessage('Here is the Project-level RAG summary:\n\nTop Terrace → 🟢\n9TH FLOOR (CENTRIC) → 🔴\n\n(Note: If no update today, task marked RED. Asif did not respond today for 9TH FLOOR).', [
      'Top Terrace Details', '9TH FLOOR Details'
    ]);
  };

  const processReportDrilldown = (text) => {
    if (text === 'Top Terrace Details') {
      addBotMessage(`Project Name: Top Terrace\nOverall RAG: 🟢 Good\n\nTasks:\n- tile: Deadline Tomorrow, 80% 🟢\n- membrane: Deadline Today, 100% 🟢\n\nSummary:\n2 Green, 0 Amber, 0 Red, 0 Non-response`);
    } else if (text === '9TH FLOOR Details') {
      addBotMessage(`Project Name: 9TH FLOOR (CENTRIC)\nOverall RAG: 🔴 Critical\n\nTasks:\n- waterproofing: Deadline Today, 10% 🔴 (Blocker: material delay)\n- ponding: Deadline Yesterday, 0% 🔴 (Asif did not respond today)\n\nSummary:\n0 Green, 0 Amber, 2 Red, 1 Non-response`);
    } else {
      addBotMessage('Invalid report selection.');
    }
    setMode('normal');
  };

  const sendMessage = async (textOverride = null) => {
    let text = textOverride || input;
    if (!text.trim()) return;

    if (text === "Download Report") {
      window.location.href = `/api/download-report?userName=${currentUser}`;
      setInput('');
      return;
    }

    setInput('');
    addUserMessage(text);

    // Command handling
    if (text === '/start') {
      handleStart();
      return;
    }
    if (text === '/help') {
      addBotMessage('This is the GEI Tracking Bot Web Simulator. Use /start to see available commands.');
      return;
    }

    // Mode specific handling
    if (activeState.mode === 'raise_ticket') {
      processRaiseTicket(text);
      return;
    }

    if (activeState.mode === 'update_task') {
      processUpdateTask(text);
      return;
    }

    if (activeState.mode === 'get_report') {
      processReportDrilldown(text);
      return;
    }

    if (activeState.mode === 'send_blocker') {
      processSendBlocker(text);
      return;
    }

    // Dynamic Ticket Modes
    if (activeState.mode.startsWith('reply_ticket_')) {
      const tId = activeState.mode.split('_')[2];
      addBotMessage(`Reply recorded for Ticket #${tId}: "${text}"\nThe user will be notified.`);
      setMode('normal');
      return;
    }

    if (text.startsWith('Reply to Ticket #')) {
      const tId = text.split('#')[1];
      setMode(`reply_ticket_${tId}`);
      addBotMessage(`Enter your reply for Ticket #${tId}:`);
      return;
    }
    if (text.startsWith('Close Ticket #')) {
      const tId = text.split('#')[1];
      setGlobalTickets(prev => prev.map(t => t.id.toString() === tId ? { ...t, status: 'closed' } : t));
      addBotMessage(`Ticket #${tId} has been resolved and closed.`);
      return;
    }

    if (text === '/raise_ticket') return startRaiseTicket();
    if (text === '/update_task' && currentUser === 'Asif') return startUpdateTask();
    if (text === '/view_tickets') return handleViewTickets();
    if (text === '/create_task') {
      addBotMessage("To create a task, please use this format:\n\nTask: <Name>\nEnd date: <DD MMM/YYYY>\nProject: <Name>");
      return;
    }
    if (text === '/create_project') {
      addBotMessage("To create a project, please use this format:\n\nProject: <Name>\nEnd date: <DD MMM/YYYY>");
      return;
    }
    if (text === '/get_task') {
      text = "task list";
    }

    // Natural Language OR arbitrary slash command handling:
    try {
      addBotMessage('Processing intent...');
      // Strip slash if present so it acts as natural language for NLP matching
      const cleanMessage = text.replace(/^\//, '');

      const res = await fetch('/api/process-message', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: cleanMessage, userName: currentUser })
      });

      setMessages(prev => prev.filter(m => m.text !== 'Processing intent...'));

      if (res.ok) {
        const data = await res.json();
        const intent = data.nlpData?.intent;

        // UI triggers driven by NLP output
        if (intent === 'raise_ticket') {
          if (data.nlpData?.entities?.ticket_project && data.nlpData?.entities?.ticket_message) {
            const finalProject = data.nlpData.entities.ticket_project;
            const finalMessage = data.nlpData.entities.ticket_message;
            const newTicket = { id: Date.now(), project_name: finalProject, task_name: '', message: finalMessage, created_by: currentUser, status: 'open' };
            setGlobalTickets(prev => [...prev, newTicket]);

            supabase.from('projects').select('id').ilike('name', `%${finalProject}%`).limit(1).then(pData => {
              let pId = pData.data && pData.data.length ? pData.data[0].id : null;
              supabase.from('users').select('id').ilike('name', currentUser).limit(1).then(uData => {
                let uId = uData.data && uData.data.length ? uData.data[0].id : null;
                supabase.from('tickets').insert([{
                  project_id: pId,
                  created_by: uId,
                  status: 'open'
                }]).then();
              });
            });

            addBotMessage(`Ticket raised successfully for project ${finalProject}! ✅`);
            return;
          } else {
            return startRaiseTicket();
          }
        }

        if (intent === 'view_tickets') {
          return handleViewTickets();
        }

        if (data.reply && data.reply.startsWith('REPORT_READY_TRIGGER|')) {
          const actualMsg = data.reply.split('|')[1];
          // Generate report async and tell user to download it
          fetch('/api/generate-report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ userName: currentUser }) })
            .then(r => r.json())
            .then(d => {
              addBotMessage(`${actualMsg}\nFile: ${d.fileName}`, ["Download Report"]);
            });
          return;
        }

        addBotMessage(data.reply);
      } else {
        addBotMessage("System error. Please try again.");
      }
    } catch (err) {
      setMessages(prev => prev.filter(m => m.text !== 'Processing intent...'));
      addBotMessage("Connection to intelligence server failed.");
    }
  };

  const handleActionBtn = async () => {
    if (currentUser === 'Kanav') {
      addBotMessage('Update request sent to Asif.');
      try {
        const res = await fetch('/api/process-message', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: "update task", userName: "Asif" })
        });
        const data = await res.json();
        
        setUserStates(prev => ({
          ...prev,
          Asif: {
            ...prev.Asif,
            messages: [
              ...prev.Asif.messages,
              {
                id: Date.now(),
                sender: 'bot',
                text: '🔔 Kanav is asking for your current update',
                time: formatTime(new Date())
              },
              {
                id: Date.now() + 1,
                sender: 'bot',
                text: data.reply || "Please provide your task update.",
                time: formatTime(new Date())
              }
            ]
          }
        }));
      } catch (err) {
        setUserStates(prev => ({
          ...prev,
          Asif: {
            ...prev.Asif,
            messages: [...prev.Asif.messages, {
              id: Date.now(),
              sender: 'bot',
              text: '🔔 Kanav is asking for your current update',
              time: formatTime(new Date())
            }]
          }
        }));
      }
    } else {
      // currentUser === 'Asif'
      setMode('send_blocker');
      setTicketState({ step: 1, project: '', task: '', message: '' });
      addBotMessage('Send Blocker Update: Select Project:', ['Top Terrace', '9TH FLOOR (CENTRIC)']);
    }
  };

  // Switch user globally
  const switchUser = (user) => {
    setCurrentUser(user);
    setMobileView('chat');
    setIsSidebarOpen(false);
  };

  // Get last message for sidebar
  const getLastMessage = () => {
    if (messages.length === 0) return 'No messages yet';
    const last = messages[messages.length - 1];
    return last.sender === 'user' ? `You: ${last.text}` : last.text;
  };
  const getLastMessageTime = () => {
    if (messages.length === 0) return '';
    return messages[messages.length - 1].time;
  };

  return (
    <div className="flex h-[100dvh] w-full bg-slate-50 overflow-hidden font-sans text-slate-800 selection:bg-blue-200">

      {/* SIDEBAR */}
      <div className={clsx(
        "flex flex-col bg-white border-r border-slate-200 transition-all duration-300 md:w-[350px] lg:w-[420px] shrink-0 h-full relative z-20 shadow-[0_0_20px_rgba(0,0,0,0.03)]",
        mobileView === 'sidebar' ? "w-full" : "hidden md:flex"
      )}>
        {/* Sidebar Header */}
        <div className="flex items-center px-4 py-3 bg-white/80 backdrop-blur-xl sticky top-0 z-10 border-b border-slate-100/50">
          <button
            className="p-2 -ml-2 text-slate-500 hover:bg-slate-100 hover:text-blue-600 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500/50"
            onClick={() => setIsSidebarOpen(true)}
          >
            <Menu size={24} />
          </button>
          <div className="flex-1 relative ml-2 group">
            <input
              type="text"
              placeholder="Search chats"
              className="w-full bg-slate-100 hover:bg-slate-200/60 rounded-full py-2 pl-10 pr-4 text-[15px] focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:bg-white transition-all placeholder:text-slate-400"
            />
            <Search size={18} className="absolute left-3 top-2.5 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
          </div>
        </div>

        {/* Chat List */}
        <div className="flex-1 overflow-y-auto w-full">
          <div
            className="flex items-center px-3 py-3 mx-2 mt-2 rounded-2xl cursor-pointer bg-blue-500/10 hover:bg-blue-500/15 border border-blue-500/20 transition-all shadow-sm"
            onClick={() => setMobileView('chat')}
          >
            <div className="relative">
              <div className="w-14 h-14 rounded-full bg-gradient-to-tr from-blue-500 to-cyan-400 text-white flex items-center justify-center shrink-0 shadow-md shadow-blue-500/30">
                <Bot size={30} className="drop-shadow-sm" />
              </div>
              <div className="absolute bottom-0 right-0 w-3.5 h-3.5 bg-green-500 border-2 border-white rounded-full z-10"></div>
            </div>
            <div className="ml-3 flex-1 min-w-0 pr-1">
              <div className="flex justify-between items-baseline mb-0.5">
                <span className="font-semibold text-[16px] text-slate-800 truncate">GEI Tracking Bot</span>
                <span className="text-[13px] text-blue-600 font-medium shrink-0 ml-2">{getLastMessageTime()}</span>
              </div>
              <div className="text-[14px] text-slate-500 truncate mt-0.5 leading-snug">
                {getLastMessage()}
              </div>
            </div>
          </div>
        </div>

        {/* Sidebar Footer Controls */}
        <div className="p-4 border-t border-slate-100 bg-white/80 backdrop-blur-md pb-6 md:pb-4 flex flex-col gap-3">

          {/* Desktop User Switcher (Integrated) */}
          <div className="hidden md:flex bg-slate-50/80 rounded-2xl border border-slate-200/60 p-2 flex-col gap-1 w-full">
            <div className="px-3 py-1.5 text-[10px] font-extrabold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
              👤 Simulator Role
            </div>
            <div className="space-y-1">
              <button
                className={clsx("text-left px-3 py-2.5 w-full rounded-xl text-sm flex items-center gap-3 transition-all outline-none cursor-pointer", currentUser === 'Asif' ? "bg-white text-blue-700 font-semibold border border-blue-100 shadow-sm" : "hover:bg-white text-slate-600 font-medium border border-transparent")}
                onClick={() => switchUser('Asif')}
              >
                <div className="w-7 h-7 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center font-bold text-xs">A</div> Asif
              </button>
              <button
                className={clsx("text-left px-3 py-2.5 w-full rounded-xl text-sm flex items-center gap-3 transition-all outline-none cursor-pointer", currentUser === 'Kanav' ? "bg-white text-blue-700 font-semibold border border-blue-100 shadow-sm" : "hover:bg-white text-slate-600 font-medium border border-transparent")}
                onClick={() => switchUser('Kanav')}
              >
                <div className="w-7 h-7 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center font-bold text-xs">K</div> Kanav
              </button>
            </div>
          </div>

          {/* Reports Section for Kanav */}
          {currentUser === 'Kanav' && (
            <div className="bg-slate-50/80 rounded-2xl border border-slate-200/60 p-2 flex-col gap-1 w-full">
              <div className="px-3 py-1.5 text-[10px] font-extrabold text-slate-400 uppercase tracking-widest flex items-center gap-1.5">
                📊 Reports
              </div>
              <div className="space-y-1">
                <button
                  className="w-full bg-blue-50 hover:bg-blue-100 text-blue-700 font-semibold py-2 px-3 rounded-xl text-sm transition-all outline-none focus:ring-2 focus:ring-blue-400 shadow-sm"
                  onClick={async () => {
                    const res = await fetch('/api/generate-report', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ userName: currentUser })
                    });
                    if (res.ok) alert('Report generated successfully!');
                    else alert('Failed to generate report.');
                  }}
                >
                  Generate Report
                </button>
                <button
                  className="w-full bg-green-50 hover:bg-green-100 text-green-700 font-semibold py-2 px-3 rounded-xl text-sm transition-all outline-none focus:ring-2 focus:ring-green-400 shadow-sm"
                  onClick={() => {
                    window.location.href = `/api/download-report?userName=${currentUser}`;
                  }}
                >
                  Download Today's Report
                </button>
              </div>
            </div>
          )}

          <button
            onClick={handleActionBtn}
            className="w-full text-sm bg-gradient-to-r from-amber-400 to-amber-500 hover:from-amber-500 hover:to-amber-600 text-amber-950 px-4 py-3 rounded-xl font-bold shadow-md hover:shadow-lg transition-all flex items-center justify-center gap-2 outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-1 cursor-pointer transform hover:-translate-y-0.5 whitespace-normal leading-snug"
          >
            {currentUser === 'Kanav' ? 'Send your current updates for the task Asif' : 'Send Blocker Update to Kanav'}
          </button>
        </div>
      </div>

      {/* MAIN CHAT AREA */}
      <div className={clsx(
        "flex flex-col flex-1 h-full relative bg-[#e4ede6] z-10",
        mobileView === 'chat' ? "flex" : "hidden md:flex"
      )}>

        {/* Telegram light theme pattern overlay */}
        <div
          className="absolute inset-0 opacity-[0.35] pointer-events-none z-0"
          style={{ backgroundImage: "url('https://web.telegram.org/a/chat-bg-pattern-light.png')", backgroundSize: '400px' }}
        />

        {/* Chat Header */}
        <div className="flex items-center px-4 py-2 bg-white/85 backdrop-blur-xl border-b border-slate-200/60 z-20 shadow-sm h-[64px] shrink-0">
          <button
            className="p-2 -ml-2 mr-2 text-slate-500 hover:bg-slate-100 rounded-full md:hidden transition-colors"
            onClick={() => setMobileView('sidebar')}
          >
            <ArrowLeft size={24} />
          </button>

          <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-blue-500 to-cyan-400 text-white flex items-center justify-center shrink-0 shadow-sm cursor-pointer hover:opacity-90 transition-opacity">
            <Bot size={24} />
          </div>
          <div className="ml-3 flex-1 min-w-0 cursor-pointer group">
            <div className="font-semibold text-[16px] truncate text-slate-900 group-hover:text-blue-600 transition-colors">GEI Tracking Bot</div>
            <div className="text-[13px] text-blue-500 font-medium">bot</div>
          </div>

          <div className="flex items-center gap-1 text-slate-500">
            <div className="mr-3 text-xs font-semibold px-2.5 py-1.5 bg-blue-50 border border-blue-100 rounded-lg text-slate-600 shadow-sm hidden sm:block">
              👤 Logged in as: <span className="text-blue-700">{currentUser}</span>
            </div>
            <button className="p-2 hover:bg-slate-100 text-slate-400 hover:text-blue-600 rounded-full transition-colors"><Search size={20} /></button>
            <button className="p-2 hover:bg-slate-100 text-slate-400 hover:text-blue-600 rounded-full transition-colors hidden sm:block"><Phone size={20} /></button>
            <button className="p-2 hover:bg-slate-100 text-slate-400 hover:text-blue-600 rounded-full transition-colors"><MoreVertical size={20} /></button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 relative z-10 w-full max-w-4xl mx-auto">
          <div className="flex justify-center mb-6">
            <div className="font-medium text-[13px] text-white bg-black/20 backdrop-blur-sm rounded-full px-3 py-1 drop-shadow-sm border border-white/10 tracking-wide select-none">
              Today
            </div>
          </div>

          {messages.map((msg, i) => {
            const isUser = msg.sender === 'user';
            const showTail = i === messages.length - 1 || messages[i + 1].sender !== msg.sender;

            return (
              <div key={msg.id} className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={clsx(
                    "max-w-[88%] md:max-w-[75%] px-3.5 py-2 shadow-sm text-[15px] leading-[1.4] break-words relative",
                    isUser
                      ? "bg-[#e3fecb] text-slate-900 rounded-2xl" // Telegram green
                      : "bg-white text-slate-900 rounded-2xl border border-slate-100",
                    showTail && isUser ? "rounded-br-sm" : "",
                    showTail && !isUser ? "rounded-bl-sm" : ""
                  )}
                >
                  <div className="whitespace-pre-wrap">{msg.text}</div>

                  {msg.buttons && msg.buttons.length > 0 && (
                    <div className="mt-3 flex flex-col gap-1.5 w-full pb-3 border-t border-slate-100 pt-3">
                      {msg.buttons.map((btn, idx) => (
                        <button
                          key={idx}
                          onClick={() => sendMessage(btn)}
                          className="bg-blue-50 hover:bg-blue-100 text-blue-600 active:bg-blue-200 border border-blue-100 rounded-xl py-2.5 px-3 text-sm font-semibold text-center transition-all shadow-sm w-full outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-1"
                        >
                          {btn}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Meta details inside bubble at bottom right */}
                  <div className={clsx(
                    "text-[11px] flex items-center justify-end gap-1 mt-1 font-medium select-none float-right ml-3 translate-y-0.5",
                    isUser ? "text-green-600/80" : "text-slate-400"
                  )}>
                    <span>{msg.time}</span>
                    {isUser && (
                      <span className="text-green-600">
                        {msg.status === 'read' ? <CheckCheck size={15} /> : <Check size={15} />}
                      </span>
                    )}
                  </div>
                  {/* Clearfix for the float */}
                  <div className="clear-both"></div>
                </div>
              </div>
            );
          })}
          <div ref={endOfMessagesRef} className="h-6" />
        </div>

        {/* Input Bar */}
        <div className="bg-white px-2 py-2 flex items-end gap-2 z-20 shrink-0 shadow-[0_-1px_10px_rgba(0,0,0,0.03)] border-t border-slate-200/50 w-full max-w-4xl mx-auto pb-safe md:pb-4 md:px-6 md:rounded-t-2xl">
          <button className="text-slate-400 hover:text-blue-500 p-2 sm:mb-1 transition-colors shrink-0 outline-none rounded-full focus:bg-slate-100">
            <Paperclip size={26} strokeWidth={1.5} />
          </button>

          <div className="flex-1 bg-slate-100/80 border border-slate-200/60 relative rounded-2xl flex items-end shadow-inner transition-colors focus-within:bg-white focus-within:border-blue-300">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (input.trim()) sendMessage();
                }
              }}
              placeholder="Write a message..."
              className="w-full bg-transparent resize-none max-h-[150px] focus:outline-none py-3.5 pl-4 pr-12 text-[15px] leading-relaxed rounded-2xl font-sans placeholder:text-slate-400"
              rows={1}
              style={{ overflow: 'hidden' }}
              onInput={(e) => {
                e.target.style.height = 'auto';
                e.target.style.height = (e.target.scrollHeight) + 'px';
              }}
            />
            <button className="text-slate-400 hover:text-blue-500 p-2 absolute right-1 bottom-1.5 transition-colors outline-none rounded-full">
              <Smile size={24} strokeWidth={1.5} />
            </button>
          </div>

          {input.trim() ? (
            <button
              onClick={() => sendMessage()}
              className="bg-blue-500 hover:bg-blue-600 active:scale-95 text-white w-12 h-12 rounded-full transition-all flex items-center justify-center shrink-0 shadow-md shadow-blue-500/20 mb-[2px] outline-none"
            >
              <Send size={20} className="translate-x-0.5 translate-y-[1px]" strokeWidth={2} />
            </button>
          ) : (
            <button className="bg-slate-100 text-slate-400 hover:text-blue-500 hover:bg-slate-200 active:scale-95 w-12 h-12 rounded-full transition-all flex items-center justify-center shrink-0 mb-[2px] outline-none">
              <Mic size={22} strokeWidth={1.5} />
            </button>
          )}
        </div>

      </div>

      {/* Hamburger Drawer Overlay */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-slate-900/40 backdrop-blur-[2px] z-[100] md:hidden transition-opacity"
          onClick={() => setIsSidebarOpen(false)}
        >
          <div
            className="w-[300px] bg-white h-full shadow-2xl flex flex-col animate-in slide-in-from-left duration-300"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="bg-gradient-to-br from-blue-500 to-blue-600 p-5 text-white shadow-inner">
              <div className="flex justify-between items-start mb-6">
                <div className="w-16 h-16 rounded-full bg-white/20 border border-white/30 flex items-center justify-center text-2xl font-bold shadow-sm backdrop-blur-sm">
                  {currentUser.charAt(0)}
                </div>
                <button onClick={() => setIsSidebarOpen(false)} className="hover:bg-white/10 p-1.5 rounded-full transition-colors"><X size={24} /></button>
              </div>
              <div className="font-bold text-xl drop-shadow-sm">{currentUser}</div>
              <div className="text-blue-100 flex items-center gap-1.5 text-sm mt-1 opacity-90 font-medium">
                Switch Identity ▾
              </div>
            </div>

            <div className="p-3 flex-1 overflow-y-auto">
              <div className="px-3 py-3 text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">Available Users</div>
              <button
                className={clsx("w-full text-left px-4 py-3.5 rounded-2xl flex items-center gap-4 transition-all overflow-hidden cursor-pointer", currentUser === 'Asif' ? "bg-blue-50 border border-blue-100 shadow-sm" : "hover:bg-slate-50 border border-transparent")}
                onClick={() => switchUser('Asif')}
              >
                <div className="w-10 h-10 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center font-bold text-lg shadow-inner">A</div>
                <div className="flex flex-col">
                  <span className={clsx("font-semibold", currentUser === 'Asif' ? "text-blue-700" : "text-slate-700")}>Asif</span>
                  <span className="text-xs text-slate-500 font-medium">(Employee)</span>
                </div>
              </button>
              <button
                className={clsx("w-full text-left px-4 py-3.5 rounded-2xl flex items-center gap-4 transition-all overflow-hidden cursor-pointer mt-2", currentUser === 'Kanav' ? "bg-blue-50 border border-blue-100 shadow-sm" : "hover:bg-slate-50 border border-transparent")}
                onClick={() => switchUser('Kanav')}
              >
                <div className="w-10 h-10 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center font-bold text-lg shadow-inner">K</div>
                <div className="flex flex-col">
                  <span className={clsx("font-semibold", currentUser === 'Kanav' ? "text-blue-700" : "text-slate-700")}>Kanav</span>
                  <span className="text-xs text-slate-500 font-medium">(Director)</span>
                </div>
              </button>
            </div>
          </div>
        </div>
      )}



    </div>
  );
}
