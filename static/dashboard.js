(() => {
  document.querySelectorAll('select[name="task_type"]').forEach((select) => {
    [
      'Homework', 'Study / Revision', 'Lab Work', 'Record Writing',
      'Presentation', 'Viva', 'Notes', 'Research', 'Coding', 'Debugging',
      'Submission', 'Quiz', 'Report', 'Group Work', 'Interview Prep',
      'Certification', 'Quiz', 'Daily Task', 'Academic Event',
    ].forEach((type) => {
      if (![...select.options].some((option) => option.value === type)) {
        select.add(new Option(type, type));
      }
    });
  });
  document.querySelectorAll('form[action$="/tasks"]').forEach((form) => {
    const addField = (labelText, name, element) => {
      if (form.querySelector(`[name="${name}"]`)) return;
      const label = document.createElement('label');
      label.textContent = labelText;
      element.name = name;
      label.append(element);
      form.insertBefore(label, form.querySelector('button[type="submit"]'));
    };
    const description = document.createElement('textarea');
    description.rows = 2;
    description.placeholder = 'What needs to be done?';
    addField('Description', 'description', description);
    const progress = document.createElement('input');
    progress.type = 'number';
    progress.min = '0';
    progress.max = '100';
    progress.value = '0';
    addField('Current progress %', 'progress', progress);
    const status = document.createElement('select');
    ['Not started', 'In progress', 'Waiting', 'Ready to submit'].forEach((value) => status.add(new Option(value, value)));
    addField('Status', 'status', status);
    const category = document.createElement('select');
    ['Assignment', 'Homework', 'Project', 'Practical', 'Quiz', 'Daily Task', 'Academic Event'].forEach((value) => category.add(new Option(value, value)));
    addField('Workspace', 'category', category);
    const submissionStatus = document.createElement('select');
    ['Not submitted', 'Ready to submit', 'Submitted', 'Returned'].forEach((value) => submissionStatus.add(new Option(value, value)));
    addField('Submission status', 'submission_status', submissionStatus);
    const teacher = document.createElement('input');
    teacher.placeholder = 'Optional teacher name';
    addField('Teacher', 'teacher', teacher);
    const submissionLink = document.createElement('input');
    submissionLink.type = 'url';
    submissionLink.placeholder = 'Submission link';
    addField('Submission link', 'submission_link', submissionLink);
  });
  const tasks = window.deadlineTasks || [];
  const detailsDialog = document.querySelector('#task-details-dialog');
  const detail = (id) => document.querySelector(`#detail-${id}`);
  const breakdownButton = document.createElement('button');
  breakdownButton.type = 'button';
  breakdownButton.className = 'filter-button';
  breakdownButton.textContent = 'Generate checklist';
  detailsDialog?.append(breakdownButton);
  let selectedDetailTask = null;
  breakdownButton.addEventListener('click', async () => {
    if (!selectedDetailTask) return;
    const response = await fetch(
      `/api/tasks/${selectedDetailTask.id}/breakdown`,
      { method: 'POST' },
    );
    if (response.ok) {
      breakdownButton.textContent = 'Checklist generated';
      toast('Task checklist generated. Open Focus Mode to use it.');
    }
  });
  document.querySelectorAll('.insight-box').forEach((box) => box.addEventListener('click', () => {
    const task = tasks.find((item) => String(item.id) === box.dataset.taskId);
    if (!task || !detailsDialog) return;
    selectedDetailTask = task;
    breakdownButton.textContent = 'Generate checklist';
    detail('title').textContent = task.title;
    detail('course').textContent = task.course;
    detail('category').textContent = task.category || task.task_type;
    detail('deadline').textContent = task.days_left < 0 ? `${Math.abs(task.days_left)} days overdue` : task.days_left === 0 ? 'Due today' : `${task.days_left} days left`;
    detail('hours').textContent = `${task.estimated_hours} hours · difficulty ${task.difficulty}/5`;
    detail('score').textContent = `${task.risk_score}%`;
    detail('load').style.width = `${task.load_ratio}%`;
    detail('risk').textContent = task.completed ? 'Completed' : task.risk_label;
    detail('notes').textContent = task.notes || 'No notes added for this task yet.';
    detail('edit').href = `/tasks/${task.id}/edit`;
    detailsDialog.showModal();
  }));
  document.querySelector('#close-task-details')?.addEventListener('click', () => detailsDialog?.close());
  const urgentTasks = tasks.filter((task) => !task.completed && task.days_left <= 2);
  const reminderBell = document.querySelector('#reminder-bell');
  if (reminderBell && urgentTasks.length) reminderBell.classList.add('has-reminders');
  reminderBell?.addEventListener('click', async () => {
    if (!urgentTasks.length) {
      alert('You are clear for now. No urgent deadlines.');
      return;
    }
    const message = urgentTasks.map((task) => `${task.title} (${task.days_left <= 0 ? 'due now' : `${task.days_left}d left`})`).join('\n');
    alert(`DeadlineSOS reminders:\n\n${message}`);
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('DeadlineSOS reminder', { body: urgentTasks[0].title });
    }
  });
  const rows = [...document.querySelectorAll('.task-row')];
  const search = document.querySelector('#task-search');
  const riskFilter = document.querySelector('#risk-filter');
  const toast = (message) => {
    const node = document.createElement('div');
    node.className = 'flash success';
    node.textContent = message;
    document.querySelector('.flash-stack')?.append(node) || document.body.append(node);
    setTimeout(() => node.remove(), 3000);
  };

  const applyFilters = () => {
    const term = (search?.value || '').toLowerCase().trim();
    const filter = riskFilter?.value || 'all';
    rows.forEach((row) => {
      const text = row.textContent.toLowerCase();
      const completed = row.classList.contains('is-complete');
      const risk = row.querySelector('.risk-dot')?.className || '';
      const matchesTerm = !term || text.includes(term);
      const matchesFilter = filter === 'all' || (filter === 'completed' && completed) || (filter === 'pending' && !completed) || risk.includes(filter);
      row.hidden = !(matchesTerm && matchesFilter);
    });
  };
  search?.addEventListener('input', applyFilters);
  riskFilter?.addEventListener('change', applyFilters);

  rows.forEach((row) => {
    const form = row.querySelector('form[action*="/complete"]');
    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const id = form.action.match(/tasks\/(\d+)\/complete/)?.[1];
      if (!id) return;
      const response = await fetch(`/api/tasks/${id}/complete`, { method: 'POST' });
      if (!response.ok) return;
      const result = await response.json();
      row.classList.toggle('is-complete', result.completed);
      const check = row.querySelector('.check-button');
      if (check) check.textContent = result.completed ? '✓' : '';
      toast(result.completed ? 'Task completed.' : 'Task moved back to pending.');
      applyFilters();
    });
  });

  const tabs = [...document.querySelectorAll('.view-tab')];
  const listTools = document.querySelector('.list-tools');
  const calendarPanel = document.querySelector('.calendar-panel');
  const analyticsPanel = document.querySelector('.analytics-panel');
  let chartReady = false;
  tabs.forEach((tab) => tab.addEventListener('click', () => {
    tabs.forEach((item) => item.classList.toggle('active', item === tab));
    const view = tab.dataset.view;
    if (listTools) listTools.hidden = view !== 'list';
    if (calendarPanel) calendarPanel.hidden = view !== 'calendar';
    if (analyticsPanel) analyticsPanel.hidden = view !== 'analytics';
    if (view === 'calendar') renderCalendar();
    if (view === 'analytics' && !chartReady) renderCharts();
  }));

  const calendarTitle = document.querySelector('#calendar-title');
  const calendarGrid = document.querySelector('#calendar-grid');
  let calendarDate = new Date();
  const renderCalendar = () => {
    if (!calendarGrid || !calendarTitle) return;
    const year = calendarDate.getFullYear();
    const month = calendarDate.getMonth();
    calendarTitle.textContent = calendarDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    const firstDay = new Date(year, month, 1).getDay();
    const offset = firstDay === 0 ? 6 : firstDay - 1;
    const days = new Date(year, month + 1, 0).getDate();
    calendarGrid.innerHTML = '';
    for (let i = 0; i < offset; i += 1) calendarGrid.insertAdjacentHTML('beforeend', '<div class="calendar-day muted"></div>');
    for (let day = 1; day <= days; day += 1) {
      const key = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const dayTasks = tasks.filter((task) => task.due_date === key);
      const dots = dayTasks.map((task) => `<span class="calendar-dot ${task.risk_tone}" title="${task.title}"></span>`).join('');
      calendarGrid.insertAdjacentHTML('beforeend', `<div class="calendar-day"><b>${day}</b><div>${dots}</div>${dayTasks.length ? `<small>${dayTasks.length} task${dayTasks.length > 1 ? 's' : ''}</small>` : ''}</div>`);
    }
  };
  document.querySelector('#previous-month')?.addEventListener('click', () => { calendarDate.setMonth(calendarDate.getMonth() - 1); renderCalendar(); });
  document.querySelector('#next-month')?.addEventListener('click', () => { calendarDate.setMonth(calendarDate.getMonth() + 1); renderCalendar(); });

  const renderCharts = () => {
    if (!window.Chart) return;
    const completed = tasks.filter((task) => task.completed).length;
    const riskCounts = ['critical', 'warning', 'healthy'].map((tone) => tasks.filter((task) => task.risk_tone === tone).length);
    const base = { responsive: true, plugins: { legend: { labels: { color: '#71807b', font: { family: 'DM Sans' } } } } };
    new Chart(document.querySelector('#progress-chart'), { type: 'doughnut', data: { labels: ['Completed', 'Pending'], datasets: [{ data: [completed, tasks.length - completed], backgroundColor: ['#286c68', '#d8eee5'], borderWidth: 0 }] }, options: { ...base, cutout: '70%', plugins: { ...base.plugins, title: { display: true, text: 'Completion progress', color: '#18211f', font: { family: 'Space Grotesk', size: 15 } } } } });
    new Chart(document.querySelector('#risk-chart'), { type: 'bar', data: { labels: ['High risk', 'Watch', 'On track'], datasets: [{ label: 'Tasks', data: riskCounts, backgroundColor: ['#e97860', '#f3c867', '#72b89e'], borderRadius: 4 }] }, options: { ...base, scales: { y: { beginAtZero: true, ticks: { stepSize: 1, color: '#91a09a' }, grid: { color: '#e4ebe6' } }, x: { ticks: { color: '#71807b' }, grid: { display: false } } } } });
    chartReady = true;
  };

  document.querySelector('#enable-reminders')?.addEventListener('click', async (event) => {
    if (!('Notification' in window)) { toast('Browser notifications are not supported here.'); return; }
    const permission = await Notification.requestPermission();
    if (permission === 'granted') {
      event.currentTarget.textContent = 'Reminders enabled';
      const urgent = tasks.filter((task) => !task.completed && task.days_left <= 1);
      if (urgent.length) new Notification('DeadlineSOS', { body: `${urgent[0].title} needs attention.` });
    }
  });

  const dialog = document.querySelector('#focus-dialog');
  const timerDisplay = document.querySelector('#timer-display');
  const timerToggle = document.querySelector('#timer-toggle');
  const picker = document.querySelector('#focus-task-picker');
  const subtaskPanel = document.querySelector('#subtask-panel');
  const subtaskList = document.querySelector('#subtask-list');
  const subtaskInput = document.querySelector('#subtask-input');
  let selectedTaskId = null;
  let seconds = 25 * 60;
  let timer = null;
  const updateTimer = () => { if (timerDisplay) timerDisplay.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; };
  const renderSubtasks = (task) => {
    if (!subtaskList || !subtaskPanel) return;
    subtaskPanel.hidden = false;
    subtaskList.innerHTML = (task.subtasks || []).map((subtask) => `<button class="subtask-row ${subtask.completed ? 'done' : ''}" data-subtask-id="${subtask.id}"><span>${subtask.completed ? '✓' : '○'}</span>${subtask.title}</button>`).join('');
    subtaskList.querySelectorAll('.subtask-row').forEach((item) => item.addEventListener('click', async () => {
      const response = await fetch(`/api/subtasks/${item.dataset.subtaskId}/complete`, { method: 'POST' });
      if (!response.ok) return;
      const result = await response.json();
      item.classList.toggle('done', result.completed);
      item.querySelector('span').textContent = result.completed ? '✓' : '○';
    }));
  };
  const openFocus = () => {
    if (!dialog) return;
    picker.innerHTML = tasks.filter((task) => !task.completed).map((task) => `<button class="focus-task" data-task="${task.title}">${task.title}<small>${task.estimated_hours}h · ${task.risk_label}</small></button>`).join('') || '<p>No pending tasks yet.</p>';
    picker.querySelectorAll('.focus-task').forEach((item) => item.addEventListener('click', () => { document.querySelector('#focus-task-name').textContent = item.dataset.task; selectedTaskId = tasks.find((task) => task.title === item.dataset.task)?.id; picker.hidden = true; renderSubtasks(tasks.find((task) => task.id === selectedTaskId)); }));
    picker.hidden = false;
    dialog.showModal();
  };
  document.querySelector('#open-focus')?.addEventListener('click', openFocus);
  document.querySelector('#close-focus')?.addEventListener('click', () => dialog?.close());
  timerToggle?.addEventListener('click', () => {
    if (timer) { clearInterval(timer); timer = null; timerToggle.textContent = 'Resume'; return; }
    timerToggle.textContent = 'Pause';
    timer = setInterval(() => { seconds -= 1; updateTimer(); if (seconds <= 0) { clearInterval(timer); timer = null; timerToggle.textContent = 'Start'; toast('Focus session complete. Take a short break.'); } }, 1000);
  });
  document.querySelector('#timer-reset')?.addEventListener('click', () => { clearInterval(timer); timer = null; seconds = 25 * 60; updateTimer(); if (timerToggle) timerToggle.textContent = 'Start'; });
  document.querySelector('#subtask-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!selectedTaskId || !subtaskInput?.value.trim()) return;
    const response = await fetch(`/api/tasks/${selectedTaskId}/subtasks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: subtaskInput.value.trim() }) });
    if (!response.ok) return;
    const created = await response.json();
    const task = tasks.find((item) => item.id === selectedTaskId);
    task.subtasks = [...(task.subtasks || []), created];
    subtaskInput.value = '';
    renderSubtasks(task);
  });
  updateTimer();
})();
