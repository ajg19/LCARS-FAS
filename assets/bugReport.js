// BUG REPORT pop-up form. Lazy-loaded by openBugReport() in lcars.js the
// first time the spine button is pressed. Builds a native <dialog> (Esc
// closes it, focus stays inside), checks each field in the browser, then
// POSTs JSON to /api/bug-report, which checks everything again and appends
// the report to the server's own bugReports.db (see server.py). The fields
// are the user-entered columns of the project bug log (bugsDB.xlsx).

const BUG_FIELDS = [
    { name: 'title', label: 'TITLE', kind: 'text', required: true, min: 5, max: 120,
      tip: "A short summary, like a headline. For example: \"Map won't zoom on GRD-TRACK\"." },
    { name: 'bugOrFeature', label: 'TYPE', kind: 'select', required: true,
      options: [['Bug', 'Bug'], ['Feature-Request', 'Feature request']],
      tip: "Bug: something doesn't work as it should. Feature request: something you would like FAS to do." },
    { name: 'severity', label: 'SEVERITY', kind: 'select', required: true,
      options: [['Low', 'Low'], ['Medium', 'Medium'], ['High', 'High']],
      tip: 'Low: cosmetic or minor. Medium: a feature is hard to use or gives wrong results. High: a section will not load, data is clearly wrong, or the page breaks.' },
    { name: 'component', label: 'SECTION', kind: 'select', required: true,
      options: ['Home page', 'NEWS', 'GRD-TRACK', 'ON-ORBIT', 'GS OPS', 'GRD VIEW', 'LAUNCHES', 'GRND SGMNT',
                'ORGANISATIONS', 'WEATHER', 'EO', 'ACKNOWLEDGMENTS', 'Whole site / other'].map(v => [v, v]),
      tip: 'Where you were when it happened. Filled in with the section you have open; change it if needed.' },
    { name: 'description', label: 'DESCRIPTION', kind: 'textarea', rows: 4, required: true, min: 10, max: 2000,
      tip: 'What happened, in your own words. Anything that seems relevant helps.' },
    { name: 'stepsToReproduce', label: 'STEPS TO REPRODUCE', kind: 'textarea', rows: 3, max: 2000,
      tip: 'The clicks or actions that lead to the problem, one per line, so we can make it happen ourselves. Optional.' },
    { name: 'expectedBehaviour', label: 'EXPECTED BEHAVIOUR', kind: 'textarea', rows: 2, max: 1000,
      tip: 'What you thought would happen. Optional.' },
    { name: 'actualBehaviour', label: 'ACTUAL BEHAVIOUR', kind: 'textarea', rows: 2, max: 1000,
      tip: 'What happened instead, including any error message you saw. Optional.' },
    { name: 'foundBy', label: 'YOUR NAME', kind: 'text', max: 60,
      tip: 'Your name or a nickname, so we can credit you. Optional: leave it blank to stay anonymous.' },
];

// data-section id of the visible section -> SECTION option.
const BUG_SECTION_NAMES = {
    'news': 'NEWS', 'grd-track': 'GRD-TRACK', 'on-orbit': 'ON-ORBIT', 'gs-ops': 'GS OPS',
    'grd-view': 'GRD VIEW', 'launches': 'LAUNCHES', 'infrastructure': 'GRND SGMNT',
    'organisations': 'ORGANISATIONS', 'sw-drivers': 'WEATHER', 'sw-fcst': 'WEATHER', 'eo': 'EO',
    'acknowledgments': 'ACKNOWLEDGMENTS',
};

let bugDialog = null;

function showBugReportForm() {
    if (!bugDialog) {
        bugDialog = buildBugDialog();
        document.body.appendChild(bugDialog);
    }
    resetBugForm();
    bugDialog.querySelector('[name="component"]').value = currentBugSection();
    bugDialog.showModal();
    bugDialog.querySelector('[name="title"]').focus();
}

function currentBugSection() {
    const visible = Array.from(document.querySelectorAll('main [data-section]'))
        .find(el => el.style.display === 'block');
    return (visible && BUG_SECTION_NAMES[visible.dataset.section]) || 'Home page';
}

function buildBugDialog() {
    const dialog = document.createElement('dialog');
    dialog.className = 'bug-dialog';
    dialog.setAttribute('aria-labelledby', 'bug-dialog-heading');

    const form = document.createElement('form');
    form.noValidate = true;  // our own checks and messages, not the browser's
    form.innerHTML =
        '<div class="bug-dialog-head"><h2 id="bug-dialog-heading">BUG REPORT</h2>' +
        '<button type="button" class="bug-close" aria-label="Close">&times;</button></div>' +
        '<p class="bug-intro">Found something wrong, or have an idea? Tell us here. Hover or tap a field name for help. ' +
        'Fields marked * are required.</p>';

    BUG_FIELDS.forEach(field => form.appendChild(buildBugField(field)));

    // Honeypot: hidden from people (and screen readers); bots fill it in.
    form.insertAdjacentHTML('beforeend',
        '<div class="bug-hp" aria-hidden="true"><label>Website <input name="website" tabindex="-1" autocomplete="off"></label></div>' +
        '<p class="bug-privacy">Your browser type and screen size are sent with the report to help us reproduce it. ' +
        'Your IP address is not stored.</p>' +
        '<p class="bug-form-error" role="alert"></p>' +
        '<div class="bug-actions">' +
        '<button type="button" class="bug-cancel">CANCEL</button>' +
        '<button type="submit" class="bug-submit">SUBMIT</button></div>');

    const done = document.createElement('div');
    done.className = 'bug-done';
    done.hidden = true;
    done.innerHTML =
        '<div class="bug-dialog-head"><h2>REPORT RECEIVED</h2></div>' +
        '<p class="bug-done-text"></p>' +
        '<div class="bug-actions"><button type="button" class="bug-another">REPORT ANOTHER</button>' +
        '<button type="button" class="bug-finish">CLOSE</button></div>';

    dialog.append(form, done);

    form.querySelector('.bug-close').addEventListener('click', () => dialog.close());
    form.querySelector('.bug-cancel').addEventListener('click', () => dialog.close());
    done.querySelector('.bug-finish').addEventListener('click', () => dialog.close());
    done.querySelector('.bug-another').addEventListener('click', () => {
        resetBugForm();
        form.querySelector('[name="title"]').focus();
    });
    form.addEventListener('submit', event => {
        event.preventDefault();
        submitBugReport(form, done);
    });
    // Re-check a field as soon as the user leaves it, and clear its error as they fix it.
    form.addEventListener('focusout', event => {
        const field = BUG_FIELDS.find(f => f.name === event.target.name);
        if (field) showBugFieldError(form, field.name, checkBugField(field, event.target.value));
    });
    form.addEventListener('input', event => {
        const field = BUG_FIELDS.find(f => f.name === event.target.name);
        if (!field) return;
        updateBugCounter(form, field, event.target.value);
        if (!checkBugField(field, event.target.value)) showBugFieldError(form, field.name, '');
    });
    return dialog;
}

function buildBugField(field) {
    const wrap = document.createElement('div');
    wrap.className = 'bug-field';
    const id = 'bug-' + field.name;

    const label = document.createElement('label');
    label.htmlFor = id;
    const tip = document.createElement('span');
    tip.className = 'bug-tip';
    tip.tabIndex = 0;  // so keyboard and touch users can open the tooltip too
    tip.dataset.tip = field.tip;
    tip.textContent = field.label + (field.required ? ' *' : '');
    label.appendChild(tip);
    wrap.appendChild(label);

    let input;
    if (field.kind === 'select') {
        input = document.createElement('select');
        input.innerHTML = '<option value="">-- choose --</option>' +
            field.options.map(([value, text]) => `<option value="${value}">${text}</option>`).join('');
    } else if (field.kind === 'textarea') {
        input = document.createElement('textarea');
        input.rows = field.rows;
    } else {
        input = document.createElement('input');
        input.type = 'text';
    }
    input.id = id;
    input.name = field.name;
    if (field.max) input.maxLength = field.max;
    input.setAttribute('aria-describedby', `${id}-help ${id}-error`);
    wrap.appendChild(input);

    // The tooltip text again, for screen readers (the CSS tooltip is visual only).
    const help = document.createElement('span');
    help.className = 'bug-sr';
    help.id = id + '-help';
    help.textContent = field.tip;
    wrap.appendChild(help);

    const foot = document.createElement('div');
    foot.className = 'bug-field-foot';
    foot.innerHTML = `<span class="bug-error" id="${id}-error"></span>` +
        (field.max ? `<span class="bug-count">0 / ${field.max}</span>` : '');
    wrap.appendChild(foot);
    return wrap;
}

// Mirrors the server's rules (validate_bug_report() in server.py).
function checkBugField(field, rawValue) {
    const value = (rawValue || '').trim();
    if (field.required && !value) return field.kind === 'select' ? 'Please choose one.' : 'Required.';
    if (value && field.min && value.length < field.min) return `At least ${field.min} characters, please.`;
    if (field.max && value.length > field.max) return `At most ${field.max} characters.`;
    return '';
}

function showBugFieldError(form, name, message) {
    const input = form.querySelector(`[name="${name}"]`);
    form.querySelector(`#bug-${name}-error`).textContent = message;
    input.classList.toggle('bug-invalid', Boolean(message));
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
}

function updateBugCounter(form, field, value) {
    if (!field.max) return;
    const counter = form.querySelector(`[name="${field.name}"]`).closest('.bug-field').querySelector('.bug-count');
    counter.textContent = `${value.length} / ${field.max}`;
}

function resetBugForm() {
    const form = bugDialog.querySelector('form');
    const component = form.querySelector('[name="component"]').value;
    form.reset();
    form.querySelector('[name="component"]').value = component || currentBugSection();
    BUG_FIELDS.forEach(field => {
        showBugFieldError(form, field.name, '');
        updateBugCounter(form, field, '');
    });
    form.querySelector('.bug-form-error').textContent = '';
    form.querySelector('.bug-submit').disabled = false;
    form.hidden = false;
    bugDialog.querySelector('.bug-done').hidden = true;
}

async function submitBugReport(form, done) {
    let firstBad = null;
    BUG_FIELDS.forEach(field => {
        const message = checkBugField(field, form.querySelector(`[name="${field.name}"]`).value);
        showBugFieldError(form, field.name, message);
        if (message && !firstBad) firstBad = field.name;
    });
    const formError = form.querySelector('.bug-form-error');
    if (firstBad) {
        formError.textContent = 'Please check the highlighted fields.';
        form.querySelector(`[name="${firstBad}"]`).focus();
        return;
    }

    const payload = { website: form.querySelector('[name="website"]').value,
                      userAgent: navigator.userAgent, viewport: `${window.innerWidth}x${window.innerHeight}` };
    BUG_FIELDS.forEach(field => { payload[field.name] = form.querySelector(`[name="${field.name}"]`).value.trim(); });

    const submit = form.querySelector('.bug-submit');
    submit.disabled = true;
    formError.textContent = 'Sending...';
    try {
        const response = await fetch('api/bug-report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json().catch(() => ({}));
        if (response.ok && result.ok) {
            form.hidden = true;
            done.hidden = false;
            done.querySelector('.bug-done-text').textContent = result.id
                ? `Thank you. Your report is number ${result.id}.` : 'Thank you.';
            done.querySelector('.bug-finish').focus();
            return;
        }
        const errors = result.errors || {};
        Object.entries(errors).forEach(([name, message]) => {
            if (BUG_FIELDS.some(f => f.name === name)) showBugFieldError(form, name, message);
        });
        formError.textContent = errors.form || 'Please check the highlighted fields.';
    } catch (err) {
        formError.textContent = 'Could not reach the server. Please check your connection and try again.';
    }
    submit.disabled = false;
}
