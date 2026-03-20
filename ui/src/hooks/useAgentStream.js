import { useState, useCallback, useRef } from 'react';

const MOCK_MODE = import.meta.env.VITE_MOCK_MODE === 'true';

// ── Mock stream builder ───────────────────────────────────────────
export function buildStream(query) {
  const q = query.toLowerCase();
  const isRefi     = q.includes('refinanc') || q.includes('irrrl');
  const isSchedule = q.includes('schedule') || q.includes('book') || q.includes('thursday') || q.includes('call');
  const isReuse    = q.includes('second time') || q.includes('again') || q.includes('reuse');

  const events = [
    { type: 'orchestrator_start', message: 'Query received — analyzing intent...' },
  ];

  if (isRefi && isSchedule) {
    events.push({ type: 'orchestrator_route', message: 'Routing to: VA Loan Advisor Agent + Loan Action Agent' });
    events.push({ type: 'advisor_start', message: 'VA Loan Advisor Agent activated' });
    events.push({ type: 'advisor_source', message: 'va_guidelines.md', detail: 'Querying IRRRL eligibility rules' });
    events.push({ type: 'advisor_source', message: 'lender_products.md', detail: 'Querying lender IRRRL product terms' });
    events.push({ type: 'advisor_result', message: 'IRRRL eligibility confirmed', detail: '2 sources cited • Must have existing VA loan • Rate reduction required • No recoup period violation' });
    events.push({ type: 'handoff', message: 'VA Loan Advisor → Loan Action Agent' });
    events.push({ type: 'action_start', message: 'Loan Action Agent activated' });
    events.push({ type: 'action_tool_call', message: 'refi_savings_calculator', inputs: { current_rate: '6.8%', new_rate: '6.1%', balance: '$320,000', remaining_term: '27 years' } });
    events.push({ type: 'action_tool_result', message: 'Monthly savings: $142 • Annual: $1,704 • Break-even: 19 months' });
    events.push({ type: 'action_tool_call', message: 'appointment_scheduler', inputs: { day: 'Thursday', time: '2:00 PM', officer: 'Next available' } });
    events.push({ type: 'action_tool_result', message: 'Confirmed: Thu Mar 26 @ 2:00 PM • Ref #LOAN-84921' });
    events.push({ type: 'orchestrator_synthesize', message: 'Merging advisor answer + action results...' });
    events.push({ type: 'complete', message: 'Response ready' });
    events.push({
      type: 'final_response',
      content: `**Yes, you appear eligible for an IRRRL (Interest Rate Reduction Refinance Loan).**

Based on VA guidelines and our lender product terms, you qualify if you currently hold an active VA loan and the new rate is lower than your existing rate — both conditions are met here.

**Your estimated savings:**
- Monthly savings: **$142**
- Annual savings: **$1,704**
- Break-even point: **19 months** — meaning you'd recoup closing costs in under two years

**Your appointment is confirmed:**
📅 Thursday, March 26 at 2:00 PM
Your loan officer will walk you through next steps and lock your rate.
Confirmation #: **LOAN-84921**

*Sources: VA Lender's Handbook (Ch. 6 — IRRRL), Lender IRRRL product guidelines*`,
    });
  } else if (isRefi || isReuse) {
    events.push({ type: 'orchestrator_route', message: 'Routing to: VA Loan Advisor Agent' });
    events.push({ type: 'advisor_start', message: 'VA Loan Advisor Agent activated' });
    if (isRefi) {
      events.push({ type: 'advisor_source', message: 'va_guidelines.md', detail: 'Querying IRRRL eligibility rules' });
      events.push({ type: 'advisor_source', message: 'lender_products.md', detail: 'Querying lender IRRRL product overlay' });
      events.push({ type: 'advisor_result', message: 'IRRRL answer composed', detail: '1 knowledge source cited' });
    } else {
      events.push({ type: 'advisor_source', message: 'loan_process_faq.md', detail: 'Querying VA benefit reuse rules' });
      events.push({ type: 'advisor_source', message: 'va_guidelines.md', detail: 'Querying entitlement restoration' });
      events.push({ type: 'advisor_result', message: 'Benefit reuse answer composed', detail: '2 sources cited' });
    }
    events.push({ type: 'orchestrator_synthesize', message: 'Formatting response...' });
    events.push({ type: 'complete', message: 'Response ready' });
    events.push({
      type: 'final_response',
      content: isRefi
        ? `**IRRRL Eligibility**

Yes — if you currently have an active VA loan, you may be eligible for an IRRRL (VA Streamline Refinance). The key requirements are:

- You must already have a VA loan on the property
- The new interest rate must be lower than your current rate
- The refinance must meet VA's recoupment period requirements

You do **not** need a new Certificate of Eligibility (COE) or a new appraisal in most cases.

*Want me to calculate your estimated savings and book a call? Just ask.*

*Sources: VA Lender's Handbook (Ch. 6), VU IRRRL product guidelines*`
        : `**Yes — you can absolutely use your VA loan benefit more than once.**

The VA home loan benefit is a lifetime benefit, not a one-time use. You can reuse it as long as:

- Your previous VA loan has been paid off **and** the property sold, **or**
- You've had your entitlement formally restored through the VA
- In some cases, you can have two VA loans active at the same time

This is one of the most common misconceptions about the VA loan program.

*Sources: VA Lender's Handbook (Entitlement chapter), Lender Borrower FAQ*`,
    });
  } else {
    events.push({ type: 'orchestrator_route', message: 'Routing to: VA Loan Advisor Agent' });
    events.push({ type: 'advisor_start', message: 'VA Loan Advisor Agent activated' });
    events.push({ type: 'advisor_source', message: 'loan_process_faq.md', detail: 'Searching knowledge base...' });
    events.push({ type: 'advisor_result', message: 'Answer composed from knowledge base' });
    events.push({ type: 'orchestrator_synthesize', message: 'Formatting response...' });
    events.push({ type: 'complete', message: 'Response ready' });
    events.push({
      type: 'final_response',
      content: `I'm here to help with your VA loan questions. Based on your query, here's what the lender knowledge base says:

VA loans are one of the most powerful home financing benefits available to Veterans and active service members. They offer $0 down payment, no private mortgage insurance (PMI), and competitive interest rates backed by the Department of Veterans Affairs.

For more specific guidance, try asking about eligibility, the IRRRL refinance program, or how to reuse your VA loan benefit.

*Sources: Lender Borrower FAQ*`,
    });
  }

  return events;
}

// ── Initial welcome message ───────────────────────────────────────
const INITIAL_MESSAGES = [
  {
    role: 'assistant',
    content: "Welcome to VA Loan Concierge. I'm here to help with your VA loan questions — from eligibility and refinancing to scheduling time with a loan officer. How can I help you today?",
  },
];

// ── Hook ──────────────────────────────────────────────────────────
export function useAgentStream() {
  const [messages,   setMessages]   = useState(INITIAL_MESSAGES);
  const [flowEvents, setFlowEvents] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const isRunning = useRef(false);

  const sendQuery = useCallback(async (query) => {
    if (!query || isRunning.current) return;
    isRunning.current = true;
    setFlowEvents([]);
    setMessages(prev => [...prev, { role: 'user', content: query }]);
    setIsStreaming(true);

    if (MOCK_MODE) {
      await _runMock(query, setFlowEvents, setMessages);
    } else {
      await _runLive(query, setFlowEvents, setMessages);
    }

    setIsStreaming(false);
    isRunning.current = false;
  }, []);

  const clearEvents = useCallback(() => setFlowEvents([]), []);

  return { messages, flowEvents, isStreaming, sendQuery, clearEvents };
}

// ── Mock runner ───────────────────────────────────────────────────
async function _runMock(query, setFlowEvents, setMessages) {
  const events = buildStream(query);
  let finalContent = '';
  let id = Date.now();

  for (const evt of events) {
    await new Promise(r => setTimeout(r, 420 + Math.random() * 280));
    if (evt.type === 'final_response') {
      finalContent = evt.content;
    } else {
      setFlowEvents(prev => [...prev, { ...evt, id: id++ }]);
    }
  }

  if (finalContent) {
    setMessages(prev => [...prev, { role: 'assistant', content: finalContent }]);
  }
}

// ── Live SSE runner ───────────────────────────────────────────────
async function _runLive(query, setFlowEvents, setMessages) {
  let id = Date.now();
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalContent = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const json = line.slice(6).trim();
        if (!json) continue;
        try {
          const evt = JSON.parse(json);
          if (evt.type === 'final_response') {
            finalContent = evt.content;
          } else {
            setFlowEvents(prev => [...prev, { ...evt, id: id++ }]);
          }
        } catch { /* skip malformed frames */ }
      }
    }

    if (finalContent) {
      setMessages(prev => [...prev, { role: 'assistant', content: finalContent }]);
    }
  } catch (err) {
    setFlowEvents(prev => [...prev, {
      type: 'error',
      message: `Connection error: ${err.message}`,
      id: id++,
    }]);
  }
}
