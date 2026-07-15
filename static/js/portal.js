/* ─── Robo Pirate Employee Portal JS ─── */

(function() {
  'use strict';

  const RP = window.RP = window.RP || {};

  /* ─── Utilities ─── */
  RP.csrfToken = function() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  };

  RP.timeToMins = function(t) {
    if (!t || typeof t !== 'string' || !t.includes(':')) return null;
    const [h, m] = t.split(':').map(Number);
    if (isNaN(h) || isNaN(m)) return null;
    return h * 60 + m;
  };

  RP.formatTime = function(date) {
    return date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  };

  RP.capitalize = function(s) {
    return String(s || '').replace(/\b\w/g, c => c.toUpperCase());
  };

  /* ─── Toast / Feedback ─── */
  function ensureToast() {
    let el = document.getElementById('rp-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'rp-toast';
      document.body.appendChild(el);
    }
    return el;
  }

  let toastTimer = null;
  RP.toast = function(message, type) {
    type = type || 'info';
    const wrap = ensureToast();
    wrap.innerHTML = '<div class="rp-alert rp-alert-' + type + '"><i class="bi bi-' +
      (type === 'success' ? 'check-circle-fill' : type === 'danger' ? 'x-circle-fill' : type === 'warning' ? 'exclamation-triangle-fill' : 'info-circle-fill') +
      '"></i><span>' + message + '</span></div>';
    wrap.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => wrap.classList.remove('show'), 4000);
  };

  RP.showInlineFeedback = function(elementId, message, type) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.innerHTML = '<div class="rp-alert rp-alert-' + (type || 'info') + '">' + message + '</div>';
  };

  RP.clearInlineFeedback = function(elementId) {
    const el = document.getElementById(elementId);
    if (el) el.innerHTML = '';
  };

  /* ─── Greeting ─── */
  RP.setGreeting = function(name) {
    const hour = new Date().getHours();
    let text = 'Good evening';
    if (hour < 12) text = 'Good morning';
    else if (hour < 17) text = 'Good afternoon';
    const el = document.getElementById('rp-greeting');
    if (el) el.textContent = text + (name ? ', ' + name + '!' : '!');
  };

  /* ─── API wrapper ─── */
  RP.api = async function(url, options) {
    options = options || {};
    const headers = Object.assign({
      'Content-Type': 'application/json',
      'X-CSRFToken': RP.csrfToken()
    }, options.headers || {});

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options.timeout || 25000);

    try {
      const res = await fetch(url, Object.assign({}, options, {
        headers: headers,
        signal: controller.signal
      }));
      clearTimeout(timeoutId);
      const text = await res.text();
      let data = null;
      try { data = JSON.parse(text); } catch (e) {}
      return { ok: res.ok, status: res.status, data: data };
    } catch (err) {
      clearTimeout(timeoutId);
      return { ok: false, error: err.name === 'AbortError' ? 'Request timed out' : (err.message || 'Network error') };
    }
  };

  /* ─── Punch ─── */
  window.doPunch = function(action, options) {
    options = options || {};
    const btn = document.getElementById(options.btnId || 'rp-punch-btn');
    const feedbackId = options.feedbackId || 'rp-punch-feedback';
    const onSuccess = options.onSuccess || function() { setTimeout(() => location.reload(), 1400); };

    if (btn) {
      btn.disabled = true;
      btn.dataset.prevHtml = btn.innerHTML;
      btn.innerHTML = '<div class="spinner-border" style="width:2rem;height:2rem;border-color:#fff transparent;border-width:3px;"></div>';
    }
    RP.clearInlineFeedback(feedbackId);
    RP.showInlineFeedback(feedbackId, '<i class="bi bi-geo-alt me-1"></i>Getting GPS location…', 'info');

    if (!navigator.geolocation) {
      RP.showInlineFeedback(feedbackId, 'GPS not supported by this browser.', 'danger');
      resetPunchBtn(btn);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      async function(pos) {
        RP.showInlineFeedback(feedbackId, '<i class="bi bi-wifi me-1"></i>Sending punch…', 'info');
        const res = await RP.api(options.apiUrl || '/api/punch', {
          method: 'POST',
          body: JSON.stringify({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            action: action
          })
        });

        if (!res.ok || !res.data) {
          RP.showInlineFeedback(feedbackId, res.error || 'Server returned unexpected response. Please try again.', 'danger');
          resetPunchBtn(btn);
          return;
        }

        if (res.data.success) {
          const icon = res.data.location_type === 'field' ? 'bi-geo-alt' : 'bi-check-circle-fill';
          const type = res.data.location_type === 'field' ? 'warning' : 'success';
          RP.showInlineFeedback(feedbackId, '<i class="bi ' + icon + ' me-1"></i>' + res.data.message, type);
          onSuccess(res.data);
        } else {
          RP.showInlineFeedback(feedbackId, '<i class="bi bi-x-circle-fill me-1"></i>' + (res.data.message || 'Punch failed.'), 'danger');
          resetPunchBtn(btn);
        }
      },
      function(err) {
        const msgs = {
          1: 'Location access denied. Enable GPS in browser settings.',
          2: 'Location unavailable. Try outdoors or near a window.',
          3: 'Location request timed out. Please try again.'
        };
        RP.showInlineFeedback(feedbackId, '<i class="bi bi-geo-alt me-1"></i>' + (msgs[err.code] || 'Location error — please try again.'), 'warning');
        resetPunchBtn(btn);
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
    );
  };

  function resetPunchBtn(btn) {
    if (!btn) return;
    btn.disabled = false;
    if (btn.dataset.prevHtml) btn.innerHTML = btn.dataset.prevHtml;
  }

  window.resetPunchBtn = resetPunchBtn;

  /* ─── Dashboard updater ─── */
  RP.updateDashboard = async function(punchData) {
    // Optimistically update status chips and button from punch response
    if (punchData) {
      updateStatusFromPunch(punchData);
    }
    // Refresh full dashboard state from server
    const res = await RP.api('/api/today-status', { method: 'POST' });
    if (res.ok && res.data && res.data.success) {
      renderDashboardState(res.data);
    }
  };

  function updateStatusFromPunch(data) {
    const actionMatch = (data.message || '').match(/Punched (IN|OUT)/i);
    if (!actionMatch) return;
    const action = actionMatch[1].toLowerCase();
    const nowStr = RP.formatTime(new Date());

    const checkInEl = document.getElementById('rp-checkin');
    const checkOutEl = document.getElementById('rp-checkout');
    if (action === 'in' && checkInEl) checkInEl.textContent = nowStr;
    if (action === 'out' && checkOutEl) checkOutEl.textContent = nowStr;
  }

  function renderDashboardState(data) {
    const t = data.today_att || {};
    const s = data.summary || {};
    const recent = data.recent_activity || [];

    // Status pill
    const statusPill = document.getElementById('rp-status-pill');
    if (statusPill) {
      if (t.check_in && t.check_out) {
        statusPill.className = 'rp-pill rp-status-completed';
        statusPill.textContent = 'Completed';
      } else if (t.check_in) {
        statusPill.className = 'rp-pill rp-status-onduty';
        statusPill.textContent = 'On Duty';
      } else {
        statusPill.className = 'rp-pill rp-status-notstarted';
        statusPill.textContent = 'Not Started';
      }
    }

    // Chips
    const checkInEl = document.getElementById('rp-checkin');
    const checkOutEl = document.getElementById('rp-checkout');
    if (checkInEl) checkInEl.textContent = t.check_in || '--:--';
    if (checkOutEl) checkOutEl.textContent = t.check_out || '--:--';

    // Punch button
    const btn = document.getElementById('rp-punch-btn');
    if (btn) {
      if (t.check_in && t.check_out) {
        setPunchButtonState('done');
      } else if (t.check_in) {
        setPunchButtonState('out', t.check_in);
      } else {
        setPunchButtonState('in');
      }
    }

    // Summary strip
    const presentEl = document.getElementById('rp-stat-present');
    const leaveEl = document.getElementById('rp-stat-leave');
    const holidayEl = document.getElementById('rp-stat-holidays');
    if (presentEl) presentEl.textContent = Number(s.present_this_month || 0).toFixed(1);
    if (leaveEl) leaveEl.textContent = Number(s.total_leave_remaining || 0).toFixed(0);
    if (holidayEl) holidayEl.textContent = Number(s.upcoming_holiday_count || 0);

    // Progress
    updateProgressBar(t.check_in, t.check_out, data.shift_start, data.shift_end, data.working_hours_per_day);

    // Recent activity
    const list = document.getElementById('rp-recent-list');
    if (list) {
      list.innerHTML = recent.map(buildActivityRow).join('') ||
        '<div class="rp-empty-state"><p class="mb-0">No recent activity.</p></div>';
    }
  }

  function setPunchButtonState(state, checkIn) {
    const btn = document.getElementById('rp-punch-btn');
    if (!btn) return;
    btn.disabled = false;
    btn.className = 'rp-btn rp-btn-lg-circle ' + (state === 'in' ? 'rp-btn-primary' : state === 'out' ? 'rp-btn-secondary' : 'rp-btn-success');
    btn.style.cursor = state === 'done' ? 'default' : 'pointer';
    btn.removeAttribute('onclick');

    const configs = {
      in:   { icon: 'bi-fingerprint',  lbl: 'Punch In',  sub: 'Tap to mark' },
      out:  { icon: 'bi-box-arrow-right', lbl: 'Punch Out', sub: 'Since ' + (checkIn || '') },
      done: { icon: 'bi-check-circle-fill', lbl: 'Done', sub: 'See you tomorrow' }
    };
    const c = configs[state] || configs.in;
    btn.innerHTML = '<i class="bi ' + c.icon + '"></i><span class="lbl">' + c.lbl + '</span><span class="sub">' + c.sub + '</span>';

    if (state !== 'done') {
      btn.onclick = function() { doPunch(state, { feedbackId: 'rp-punch-feedback', onSuccess: function(data) { RP.updateDashboard(data); } }); };
    } else {
      btn.disabled = true;
    }
  }

  function formatDuration(mins) {
    const h = Math.floor(mins / 60);
    const m = Math.round(mins % 60);
    return h + 'h' + (m ? ' ' + m + 'm' : '');
  }

  function updateProgressBar(checkIn, checkOut, shiftStart, shiftEnd, workingHours, fillId, textId) {
    const fill = document.getElementById(fillId || 'rp-progress-fill');
    const txt = document.getElementById(textId || 'rp-progress-text');
    if (!fill || !txt) return;

    const targetHours = workingHours || 8;
    const duration = Math.max(1, targetHours * 60);
    let pct = 0;
    let labelText = '0h 0m of ' + targetHours + 'h';

    if (checkIn) {
      const start = RP.timeToMins(checkIn) || (RP.timeToMins(shiftStart) || 8 * 60);
      let elapsed = 0;
      if (checkOut) {
        elapsed = Math.max(0, RP.timeToMins(checkOut) - start);
      } else {
        const now = new Date().getHours() * 60 + new Date().getMinutes();
        elapsed = Math.max(0, now - start);
      }
      pct = Math.min(100, Math.max(0, (elapsed / duration) * 100));
      labelText = formatDuration(elapsed) + ' of ' + targetHours + 'h';
    }

    fill.style.width = pct + '%';
    txt.textContent = labelText;
  }

  RP.setPunchButtonState = setPunchButtonState;
  RP.updateProgressBar = updateProgressBar;

  function buildActivityRow(att) {
    let badgeClass = 'rp-badge-' + (att.status === 'overtime' ? 'ot' : att.status);
    let label = RP.capitalize(att.status);
    if (att.location_type === 'field') { label += ' · Field'; }
    return '<div class="rp-list-item">' +
      '<div class="rp-list-main">' +
        '<div class="rp-list-title">' + att.day + ' <span style="font-weight:500;color:var(--rp-text-3);">' + att.date + '</span></div>' +
        (att.times ? '<div class="rp-list-meta">' + att.times + '</div>' : '') +
      '</div>' +
      '<span class="rp-badge ' + badgeClass + '">' + label + '</span>' +
    '</div>';
  }

  /* ─── Attendance page helpers ─── */
  RP.updateCurrentTime = function(elementId) {
    const el = document.getElementById(elementId || 'rp-current-time');
    if (!el) return;
    el.textContent = new Date().toLocaleTimeString('en-IN', { hour12: true });
  };

  /* ─── Service worker cache bust ─── */
  RP.checkForUpdates = function() {
    if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
      navigator.serviceWorker.ready.then(reg => reg.update());
    }
  };

  /* ─── Init ─── */
  document.addEventListener('DOMContentLoaded', function() {
    const nameMeta = document.querySelector('meta[name="employee-first-name"]');
    if (nameMeta) RP.setGreeting(nameMeta.getAttribute('content'));
    RP.checkForUpdates();
  });
})();
