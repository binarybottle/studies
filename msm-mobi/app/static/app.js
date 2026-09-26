/* Scenario-conversation task: the browser side.
 *
 * The server owns the flow: this script renders what it is handed, collects
 * one input at a time, and posts it back. It never knows the Stance, the
 * assignment, or what comes next.
 *
 * Two constraints shape the input handling:
 *   1. Own words only -- paste and drop are blocked in the text fields, so a
 *      response cannot be pasted in from elsewhere.
 *   2. Forward-only navigation -- there is no back affordance, and a
 *      submitted value can never be revisited.
 *
 * A participant who reloads or returns later is resumed by the server at the
 * step they were on; the current block's transcript is replayed for them.
 */
'use strict';

const els = {};
const state = {
  config: null,
  pid: document.body.dataset.pid || '',
  token: null,          // session token from POST /api/session
  input: null,          // the InputSpec currently being collected
  busy: false,          // a request is in flight; blocks double-submits
  thinkingTimer: null,
  userMsgSeq: 1,
  statusText: '',
  unfocusedSince: null,
};

document.addEventListener('DOMContentLoaded', init);

function init() {
  for (const id of [
    'start-screen', 'start-title', 'start-body', 'start-error', 'start-button',
    'task-screen', 'statusbar', 'status-block', 'transcript', 'transcript-scroll',
    'composer', 'numeric-form', 'numeric-input', 'numeric-submit', 'numeric-error',
    'numeric-low', 'numeric-high',
    'text-form', 'text-input', 'text-submit', 'text-error', 'word-count',
    'gate-form', 'gate-button', 'thinking', 'thinking-text',
    'fatal', 'fatal-text', 'fatal-retry',
    'end-screen', 'end-title', 'end-body', 'finish-link',
    'fixation', 'fixation-mark',
  ]) {
    els[id] = document.getElementById(id);
  }

  hardenInput(els['numeric-input']);
  hardenInput(els['text-input']);

  els['start-button'].addEventListener('click', onStart);
  els['numeric-form'].addEventListener('submit', onNumericSubmit);
  els['numeric-input'].addEventListener('input', onNumericInput);
  els['numeric-input'].addEventListener('keydown', enterSubmits(els['numeric-form']));
  els['text-form'].addEventListener('submit', onTextSubmit);
  els['text-input'].addEventListener('input', onTextInput);
  els['text-input'].addEventListener('keydown', onTextKeydown);
  els['gate-form'].addEventListener('submit', onGateSubmit);
  els['fatal-retry'].addEventListener('click', () => hide(els['fatal']));
  els['finish-link'].href = `/finish?pid=${encodeURIComponent(state.pid)}`;

  // Forward-only: neutralize the browser back gesture within the task.
  history.pushState(null, '', location.href);
  window.addEventListener('popstate', () => history.pushState(null, '', location.href));
  window.addEventListener('beforeunload', (e) => {
    if (state.token) { e.preventDefault(); e.returnValue = ''; }
  });

  // The composer grows (textarea auto-height, inline errors, scale anchors).
  // Re-pin the transcript so the newest message is never hidden behind it.
  if (window.ResizeObserver) {
    new ResizeObserver(() => scrollToBottom()).observe(els['composer']);
  }

  installFocusLogging();
  loadConfig();
}

/* Enter submits every field. Handled explicitly rather than relying on
 * implicit form submission, which varies across browsers. */
function enterSubmits(form) {
  return (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  };
}

/* ---------- input hardening ---------- */

function hardenInput(el) {
  for (const evt of ['paste', 'drop', 'dragover']) {
    el.addEventListener(evt, (e) => { e.preventDefault(); reportBlockedInput(evt); });
  }
  // Catches paste routes that bypass the paste event (menus, IME, autofill).
  el.addEventListener('beforeinput', (e) => {
    if (e.inputType && /paste|drop/i.test(e.inputType)) {
      e.preventDefault();
      reportBlockedInput(e.inputType);
    }
  });
  el.setAttribute('autocomplete', 'off');
  el.setAttribute('autocorrect', 'off');
  el.setAttribute('autocapitalize', 'off');
  el.setAttribute('spellcheck', 'false');
  el.setAttribute('data-gramm', 'false');
  el.setAttribute('data-1p-ignore', 'true');
  el.setAttribute('data-lpignore', 'true');
}

function reportBlockedInput(kind) {
  sendEvent('validation_blocked', { reason: 'paste_blocked', kind });
}

/* ---------- API ---------- */

async function api(path, options = {}) {
  const res = await fetch(path, {
    method: options.method || 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let payload = null;
  try { payload = await res.json(); } catch (_) { /* non-JSON error page */ }
  if (!res.ok) {
    const err = new Error((payload && (payload.detail || payload.message)) || `Request failed (${res.status})`);
    err.status = res.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

function sendEvent(event, detail = {}) {
  if (!state.token) return;
  // Fire-and-forget: a log entry must never delay the participant's next action.
  fetch(`/api/session/${state.token}/event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event, detail }),
    keepalive: true,
  }).catch(() => {});
}

async function loadConfig() {
  let status;
  try {
    state.config = await api('/api/config', { method: 'GET' });
    status = await api(`/api/status?pid=${encodeURIComponent(state.pid)}`, { method: 'GET' });
  } catch (err) {
    els['start-screen'].hidden = false;
    show(els['start-error'], 'Could not reach the study server. Please reload the page.');
    els['start-button'].disabled = true;
    console.error('[msm] config load failed', err);
    return;
  }
  els['start-title'].textContent = state.config.copy.start_title;
  els['start-body'].textContent = state.config.copy.start_body;
  els['end-title'].textContent = state.config.copy.end_title;
  els['end-body'].textContent = state.config.copy.end_body;

  if (status.stage === 'in_task') {
    // Already underway: skip the instructions and pick up where they were.
    await beginSession();
    return;
  }
  els['start-screen'].hidden = false;
  els['start-button'].focus();
}

/* ---------- Start ---------- */

async function onStart() {
  if (state.busy) return;
  await beginSession();
}

async function beginSession() {
  state.busy = true;
  els['start-button'].disabled = true;
  try {
    const view = await api('/api/session', { body: { pid: state.pid } });
    state.token = view.session;
    hide(els['start-screen']);
    els['task-screen'].hidden = false;
    sendEvent('start_screen_shown', { resumed: Boolean(view.resumed) });
    if (view.resumed) flashStatusNotice('Welcome back — continuing where you left off');
    await applyView(view);
  } catch (err) {
    els['start-screen'].hidden = false;
    show(els['start-error'], err.message);
    els['start-button'].disabled = false;
  } finally {
    state.busy = false;
  }
}

/* Re-fetch the current view from the server. Used after a flow conflict (a
 * double submit, or a second tab), which means this tab's idea of the step is
 * stale rather than that anything went wrong. */
async function resync() {
  const view = await api('/api/session', { body: { pid: state.pid } });
  state.token = view.session;
  await applyView(view);
}

/* ---------- Rendering ---------- */

async function applyView(view) {
  setStatus(view.is_practice
    ? 'Practice'
    : `Scenario ${view.block_index} of ${view.progress.total_blocks}`);

  // Blocks are self-contained: opening one clears everything before it. The
  // fixation cross is held over the cleared screen before the Scenario renders.
  if (view.reset_transcript) {
    clearTranscript();
    await showFixationCross();
  }

  if (view.messages && view.messages.length) {
    appendMessages(view.messages);
  }

  if (view.done) {
    finishSession();
    return;
  }
  if (view.awaiting_llm) {
    runLLMTurn();
    return;
  }
  showInput(view.input);
}

function appendMessages(messages) {
  for (const m of messages) {
    els['transcript'].appendChild(buildMessage(m));
  }
  scrollToBottom();
}

function buildMessage(m) {
  const node = document.createElement('div');
  node.className = `msg msg-${m.kind}`;
  node.dataset.messageId = m.id;

  if (m.kind === 'scenario') {
    // Scenario and Question appear together, with the Question's own 0/100 anchors.
    const text = document.createElement('p');
    text.className = 'scenario-text';
    text.textContent = m.text;
    node.appendChild(text);

    if (m.question) {
      const q = document.createElement('p');
      q.className = 'scenario-question';
      q.textContent = m.question;
      node.appendChild(q);
    }
    if (m.scale_low || m.scale_high) {
      const scale = document.createElement('div');
      scale.className = 'scenario-scale';
      const low = document.createElement('span');
      low.innerHTML = '<b>0</b> = ';
      low.append(m.scale_low || '');
      const high = document.createElement('span');
      high.innerHTML = '<b>100</b> = ';
      high.append(m.scale_high || '');
      scale.append(low, high);
      node.appendChild(scale);
    }
    return node;
  }

  // Replayed participant answers (on resume) render as user bubbles.
  if (m.kind === 'user-numeric' || m.kind === 'user-text') {
    node.className = 'msg msg-user' + (m.kind === 'user-numeric' ? ' numeric' : '');
  }
  node.textContent = m.text;
  return node;
}

function clearTranscript() {
  els['transcript'].replaceChildren();
  els['transcript-scroll'].scrollTop = 0;
}

function appendUserMessage(text, numeric) {
  const node = document.createElement('div');
  node.className = 'msg msg-user' + (numeric ? ' numeric' : '');
  node.dataset.messageId = `u${state.userMsgSeq++}`;
  node.textContent = text;
  els['transcript'].appendChild(node);
  scrollToBottom();
}

function scrollToBottom() {
  const scroller = els['transcript-scroll'];
  const pin = () => { scroller.scrollTop = scroller.scrollHeight; };
  requestAnimationFrame(pin);
  setTimeout(pin, 90);
}

/* ---------- Inter-block fixation cross ---------- */

function showFixationCross() {
  return new Promise((resolve) => {
    const hold = state.config.fixation_cross_ms;
    if (!hold) { resolve(); return; }
    els['fixation'].hidden = false;
    const shownAt = performance.now();
    sendEvent('fixation_cross_shown', { hold_ms: hold });
    setTimeout(() => {
      els['fixation'].hidden = true;
      sendEvent('fixation_cross_hidden', { actual_hold_ms: Math.round(performance.now() - shownAt) });
      resolve();
    }, hold);
  });
}

/* ---------- Status bar ---------- */

function setStatus(text) {
  state.statusText = text;
  els['status-block'].textContent = text;
}

let statusNoticeTimer = null;
function flashStatusNotice(text, ms = 6000) {
  els['status-block'].textContent = text;
  if (statusNoticeTimer) clearTimeout(statusNoticeTimer);
  statusNoticeTimer = setTimeout(() => {
    statusNoticeTimer = null;
    els['status-block'].textContent = state.statusText;
  }, ms);
}

/* ---------- Focus logging ---------- */

/* Logging only: never pauses the flow or blocks input. Records intervals when
 * the participant was away from the page, which is useful when judging data
 * quality later. */
function installFocusLogging() {
  const lost = (reason) => {
    if (state.unfocusedSince !== null) return;
    state.unfocusedSince = Date.now();
    sendEvent('window_focus_lost', { reason });
  };
  const regained = (reason) => {
    if (state.unfocusedSince === null) return;
    const unfocusedMs = Date.now() - state.unfocusedSince;
    state.unfocusedSince = null;
    sendEvent('window_focus_regained', { reason, unfocused_ms: unfocusedMs });
  };
  window.addEventListener('blur', () => lost('blur'));
  window.addEventListener('focus', () => regained('focus'));
  document.addEventListener('visibilitychange', () => {
    sendEvent('visibility_changed', { visibility: document.visibilityState });
    if (document.visibilityState === 'hidden') lost('hidden');
    else regained('visible');
  });
}

/* ---------- Input handling ---------- */

function showInput(spec) {
  hideAllEntries();
  state.input = spec;
  // The session is only ready for a submission once an input is on screen.
  state.busy = !spec;
  if (!spec) return;

  if (spec.type === 'numeric') {
    els['numeric-low'].textContent = spec.scale_low;
    els['numeric-high'].textContent = spec.scale_high;
    els['numeric-input'].value = '';
    els['numeric-input'].classList.remove('invalid');
    hide(els['numeric-error']);
    els['numeric-form'].hidden = false;
    els['numeric-input'].focus();
  } else if (spec.type === 'text') {
    els['text-input'].value = '';
    els['text-input'].classList.remove('invalid');
    els['text-input'].style.height = '';
    // The LLM's own reply asks for responses 2 and 3, so there is no prompt
    // message above the box. The placeholder is what tells the participant
    // the box is theirs if a reply ever fails to close on a question.
    els['text-input'].placeholder = spec.placeholder || 'Type your response...';
    hide(els['text-error']);
    updateWordCount();
    els['text-form'].hidden = false;
    els['text-input'].focus();
  } else if (spec.type === 'gate') {
    els['gate-button'].textContent = spec.button || 'Continue';
    els['gate-form'].hidden = false;
    els['gate-button'].focus();
  }
}

function hideAllEntries() {
  state.input = null;
  els['numeric-form'].hidden = true;
  els['text-form'].hidden = true;
  els['gate-form'].hidden = true;
  els['thinking'].hidden = true;
}

/* Numeric: whole numbers 0-100, blocked inline before submission. */

function validateNumeric(raw) {
  const text = raw.trim();
  if (!text) return 'Enter a number.';
  if (!/^\d+$/.test(text)) return 'Enter a whole number between 0 and 100, with no decimal point.';
  const value = Number(text);
  const lo = state.config.score_min, hi = state.config.score_max;
  if (value < lo || value > hi) return `Enter a number between ${lo} and ${hi}.`;
  return null;
}

function onNumericInput() {
  const error = validateNumeric(els['numeric-input'].value);
  els['numeric-input'].classList.toggle('invalid', Boolean(error) && els['numeric-input'].value.trim() !== '');
  if (!error) hide(els['numeric-error']);
}

async function onNumericSubmit(e) {
  e.preventDefault();
  if (state.busy || !state.input) return;
  const raw = els['numeric-input'].value.trim();
  const error = validateNumeric(raw);
  if (error) {
    els['numeric-input'].classList.add('invalid');
    show(els['numeric-error'], error);
    sendEvent('validation_blocked', { step: state.input.step, reason: error });
    return;
  }
  appendUserMessage(raw, true);
  await submit(state.input.step, raw, els['numeric-error'], els['numeric-input']);
}

/* Free text: >= 15 whitespace-delimited words; Enter submits, Shift+Enter newline. */

function wordCount(text) {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function updateWordCount() {
  const n = wordCount(els['text-input'].value);
  const min = state.config.min_response_words;
  els['word-count'].textContent = n >= min ? `${n} words` : `${n} of ${min} words minimum`;
  els['word-count'].className = 'word-count ' + (n >= min ? 'met' : 'short');
}

function onTextInput() {
  updateWordCount();
  const ta = els['text-input'];
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 220) + 'px';
  if (wordCount(ta.value) >= state.config.min_response_words) {
    ta.classList.remove('invalid');
    hide(els['text-error']);
  }
}

function onTextKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    els['text-form'].requestSubmit();
  }
}

async function onTextSubmit(e) {
  e.preventDefault();
  if (state.busy || !state.input) return;
  const raw = els['text-input'].value.trim();
  const n = wordCount(raw);
  const min = state.config.min_response_words;
  if (n < min) {
    els['text-input'].classList.add('invalid');
    show(els['text-error'], `Please write at least ${min} words (${n} so far).`);
    sendEvent('validation_blocked', { step: state.input.step, reason: 'below_min_words', words: n });
    return;
  }
  appendUserMessage(raw, false);
  await submit(state.input.step, raw, els['text-error'], els['text-input']);
}

async function onGateSubmit(e) {
  e.preventDefault();
  if (state.busy || !state.input) return;
  await submit('gate', true, null, null);
}

async function submit(step, value, errorEl, inputEl) {
  const spec = state.input;
  state.busy = true;
  hideAllEntries();
  try {
    const view = await api(`/api/session/${state.token}/submit`, { body: { step, value } });
    await applyView(view);   // releases `busy` once the next input is shown
  } catch (err) {
    if (err.status === 422 && errorEl && inputEl) {
      // The server is the authority on validity; let them correct it in place.
      removeLastUserMessage();
      showInput(spec);
      inputEl.value = value;
      inputEl.classList.add('invalid');
      show(errorEl, err.message);
      if (inputEl === els['text-input']) updateWordCount();
    } else if (err.status === 409) {
      // This tab is behind the server (double submit, second tab). Catch up.
      try { await resync(); } catch (e2) { showFatal(e2, () => resync()); }
    } else {
      showFatal(err, () => { showInput(spec); });
    }
  }
}

function removeLastUserMessage() {
  const nodes = els['transcript'].querySelectorAll('.msg-user');
  if (nodes.length) nodes[nodes.length - 1].remove();
}

/* ---------- LLM turn ---------- */

async function runLLMTurn() {
  state.busy = true;   // held until the reply arrives and the next input appears
  showThinking();
  try {
    const view = await api(`/api/session/${state.token}/llm`);
    clearThinking();
    await applyView(view);
  } catch (err) {
    clearThinking();
    showFatal(err, () => runLLMTurn());
  }
}

function showThinking() {
  hideAllEntries();
  els['thinking-text'].textContent = 'Thinking';
  els['thinking'].hidden = false;
  sendEvent('thinking_shown', { state: 'thinking' });
  // Soft threshold, not a cutoff: the real response replaces the indicator
  // whenever it arrives.
  state.thinkingTimer = setTimeout(() => {
    els['thinking-text'].textContent = 'Hang on, still thinking';
    sendEvent('thinking_slow_state', { state: 'still_thinking', after_ms: state.config.thinking_slow_after_ms });
  }, state.config.thinking_slow_after_ms);
}

function clearThinking() {
  if (state.thinkingTimer) { clearTimeout(state.thinkingTimer); state.thinkingTimer = null; }
  els['thinking'].hidden = true;
}

/* ---------- End Screen ---------- */

function finishSession() {
  hideAllEntries();
  els['task-screen'].hidden = true;
  els['end-screen'].hidden = false;
  sendEvent('end_screen_shown', {});
  state.token = null;   // releases the beforeunload guard
  els['finish-link'].focus();
}

/* ---------- Errors ---------- */

/* Participants never see internal error text. The detail goes to the log;
 * the screen shows a plain, calm message and a retry. */
function showFatal(err, retry) {
  const detail = (err && err.message) || String(err);
  hideAllEntries();
  els['fatal-text'].textContent =
    'Something went wrong on our end. Please try again in a moment.';
  els['fatal-retry'].hidden = !retry;
  els['fatal-retry'].onclick = retry
    ? () => { hide(els['fatal']); retry(); }
    : () => hide(els['fatal']);
  els['fatal'].hidden = false;
  state.busy = true;
  sendEvent('validation_blocked', { reason: 'request_failed', detail: detail.slice(0, 200) });
  console.error('[msm]', detail, err);
}

function show(el, text) {
  if (text !== undefined) el.textContent = text;
  el.hidden = false;
}

function hide(el) { el.hidden = true; }
