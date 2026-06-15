import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Button, Card, Title } from 'animal-island-ui';
import 'animal-island-ui/style';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';
const DEFAULT_SERVICE_BASE_URL = 'https://hdu.huitu.zhishulib.com';
const DEFAULT_DURATION_HOURS = 1;
const MAP_DEFAULT_ZOOM = 0.75;
const MAP_MIN_ZOOM = 0.45;
const MAP_MAX_ZOOM = 1.8;
const MAP_ZOOM_STEP = 0.15;
const MAP_LABEL_ZOOM = 0.75;

function today() {
  return localDateString(new Date());
}

function defaultStartTimeForDate(dateValue) {
  if (dateValue !== today()) return '08:00';
  const now = new Date();
  return `${String(now.getHours()).padStart(2, '0')}:00`;
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }
  return data;
}

function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [studentId, setStudentId] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [autoLogin, setAutoLogin] = useState(false);
  const [baseUrl] = useState(DEFAULT_SERVICE_BASE_URL);
  const [message, setMessage] = useState('准备就绪');
  const [loading, setLoading] = useState(false);
  const [activeView, setActiveView] = useState('seats');

  const [areas, setAreas] = useState([]);
  const [selectedAreaKey, setSelectedAreaKey] = useState('');
  const initialDate = today();
  const initialStartTime = defaultStartTimeForDate(initialDate);
  const [date, setDate] = useState(initialDate);
  const [startTime, setStartTime] = useState(initialStartTime);
  const [endTime, setEndTime] = useState(addHoursToTime(initialStartTime, DEFAULT_DURATION_HOURS));
  const [durationHours, setDurationHours] = useState(DEFAULT_DURATION_HOURS);
  const [seats, setSeats] = useState([]);
  const [selectedSeatId, setSelectedSeatId] = useState(null);
  const [venueFilter, setVenueFilter] = useState('');

  const [openTime, setOpenTime] = useState('20:00:00');
  const [preTriggerSeconds, setPreTriggerSeconds] = useState(3);
  const [maxRetries, setMaxRetries] = useState(30);
  const [retryIntervalSeconds, setRetryIntervalSeconds] = useState(1);
  const [concurrentRequests, setConcurrentRequests] = useState(3);
  const [primarySeats, setPrimarySeats] = useState([]);
  const [backupSeats, setBackupSeats] = useState([]);
  const [candidateMode, setCandidateMode] = useState('primary');
  const [tasks, setTasks] = useState([]);
  const [notice, setNotice] = useState(null);
  const taskStatusRef = useRef(new Map());

  useEffect(() => {
    request('/api/config')
      .then((data) => {
        setStudentId(data.studentId || '');
        setRemember(Boolean(data.remember));
        setAutoLogin(Boolean(data.autoLogin));
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    const timer = setInterval(loadTasks, 2500);
    return () => clearInterval(timer);
  }, [loggedIn]);

  const selectedArea = useMemo(() => {
    return areas.find((area) => areaKey(area) === selectedAreaKey) || null;
  }, [areas, selectedAreaKey]);

  const venues = useMemo(() => {
    return Array.from(new Set(seats.map((seat) => seat.areaName || '未知场馆'))).sort();
  }, [seats]);

  const venueStats = useMemo(() => {
    return venues.map((venue) => {
      const venueSeats = seats.filter((seat) => (seat.areaName || '未知场馆') === venue);
      return {
        venue,
        total: venueSeats.length,
        available: venueSeats.filter((seat) => seat.status === 1).length,
      };
    });
  }, [seats, venues]);

  const visibleSeats = useMemo(() => {
    return venueFilter
      ? seats.filter((seat) => (seat.areaName || '未知场馆') === venueFilter)
      : seats;
  }, [seats, venueFilter]);

  const availableSeats = visibleSeats.filter((seat) => seat.status === 1);
  const selectedSeat = seats.find((seat) => seat.seatId === selectedSeatId);

  function updateStartTime(value) {
    setStartTime(value);
    setEndTime(addHoursToTime(value, durationHours));
  }

  function updateEndTime(value) {
    setEndTime(value);
    setDurationHours(timeRangeHours(startTime, value));
  }

  function updateDurationHours(value) {
    const duration = clampDuration(value);
    setDurationHours(duration);
    setEndTime(addHoursToTime(startTime, duration));
  }

  function updateDate(value) {
    setDate(value);
    const nextStartTime = defaultStartTimeForDate(value);
    setStartTime(nextStartTime);
    setEndTime(addHoursToTime(nextStartTime, durationHours));
  }

  function updateSelectedAreaKey(value) {
    setSelectedAreaKey(value);
    setSeats([]);
    setSelectedSeatId(null);
    setVenueFilter('');
    setPrimarySeats([]);
    setBackupSeats([]);
    setMessage('已切换区域，请重新查询座位');
  }

  async function handleLogin(event) {
    event.preventDefault();
    setLoading(true);
    setMessage('正在登录...');
    try {
      await request('/api/login', {
        method: 'POST',
        body: JSON.stringify({
          studentId,
          password,
          remember,
          autoLogin,
          baseUrl,
        }),
      });
      setLoggedIn(true);
      setMessage(`登录成功，欢迎 ${studentId}`);
      await loadAreas();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    await request('/api/logout', { method: 'POST' }).catch(() => {});
    setLoggedIn(false);
    setSeats([]);
    setTasks([]);
    setMessage('已退出');
  }

  async function loadAreas() {
    const data = await request('/api/areas');
    setAreas(data.areas || []);
    if (data.areas?.length) {
      setSelectedAreaKey(areaKey(data.areas[0]));
    }
  }

  async function loadArea() {
    if (!selectedArea) return;
    setLoading(true);
    try {
      const data = await request('/api/areas/load', {
        method: 'POST',
        body: JSON.stringify({
          categoryId: selectedArea.categoryId,
          contentId: selectedArea.contentId,
        }),
      });
      setMessage(data.uidReady ? '区域已加载，可以查询座位' : '区域已加载，但 uid 未就绪');
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function searchSeats() {
    if (!selectedArea) return;
    setLoading(true);
    setMessage('正在查询座位...');
    try {
      const data = await request('/api/seats/search', {
        method: 'POST',
        body: JSON.stringify({
          categoryId: selectedArea.categoryId,
          contentId: selectedArea.contentId,
          date,
          startTime,
          durationHours,
        }),
      });
      setSeats(data.seats || []);
      setSelectedSeatId(null);
      const venueNames = Array.from(new Set((data.seats || []).map((seat) => seat.areaName || '未知场馆'))).sort();
      setVenueFilter(venueNames.length > 0 ? venueNames[0] : '');
      const counts = summarizeVenueCounts(data.seats || []);
      setMessage(`共 ${data.seats?.length || 0} 个座位，可预约 ${data.availableCount || 0} 个${counts ? ` | ${counts}` : ''}`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function bookSelectedSeat() {
    if (!selectedSeat) return;
    setLoading(true);
    setMessage(`正在预约 ${selectedSeat.seatLabel}...`);
    try {
      const result = await request('/api/seats/book', {
        method: 'POST',
        body: JSON.stringify({
          seatId: selectedSeat.seatId,
          date,
          startTime,
          durationHours,
        }),
      });
      const nextMessage = result.success ? `预约成功：${selectedSeat.seatLabel}` : `预约失败：${result.message}`;
      setMessage(nextMessage);
      setNotice({
        type: result.success ? 'success' : 'failed',
        title: result.success ? '预约成功' : '预约失败',
        message: nextMessage,
      });
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleCandidate(seat) {
    const key = `${seat.areaName || '未知场馆'}|${seat.seatLabel}`;
    const removeFrom = (items) => items.filter((item) => item !== key);
    if (primarySeats.includes(key) || backupSeats.includes(key)) {
      setPrimarySeats(removeFrom);
      setBackupSeats(removeFrom);
      return;
    }
    if (candidateMode === 'primary') {
      setPrimarySeats((items) => [...items, key]);
    } else {
      setBackupSeats((items) => [...items, key]);
    }
  }

  async function createTask() {
    if (!selectedArea) return;
    setLoading(true);
    try {
      await request('/api/tasks', {
        method: 'POST',
        body: JSON.stringify({
          categoryId: selectedArea.categoryId,
          contentId: selectedArea.contentId,
          openTime,
          startTime,
          endTime,
          preTriggerSeconds: Number(preTriggerSeconds),
          maxRetries: Number(maxRetries),
          retryIntervalSeconds: Number(retryIntervalSeconds),
          concurrentRequests: Number(concurrentRequests),
          primarySeats,
          backupSeats,
        }),
      });
      setMessage('定时任务已创建');
      await loadTasks();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadTasks() {
    const data = await request('/api/tasks');
    const nextTasks = data.tasks || [];
    const previous = taskStatusRef.current;
    nextTasks.forEach((task) => {
      const oldStatus = previous.get(task.taskId);
      if (oldStatus && oldStatus !== task.status && ['success', 'failed'].includes(task.status)) {
        setNotice({
          type: task.status,
          title: task.status === 'success' ? '定时任务预约成功' : '定时任务预约失败',
          message: task.statusMessage || (task.status === 'success' ? '预约已完成' : '任务执行失败'),
        });
      }
    });
    taskStatusRef.current = new Map(nextTasks.map((task) => [task.taskId, task.status]));
    setTasks(nextTasks);
  }

  async function taskAction(taskId, action) {
    const path = action === 'delete' ? `/api/tasks/${taskId}` : `/api/tasks/${taskId}/${action}`;
    try {
      await request(path, { method: action === 'delete' ? 'DELETE' : 'POST' });
      setMessage(action === 'run-now' ? '任务已开始立即执行' : '任务状态已更新');
      await loadTasks();
    } catch (error) {
      setMessage(error.message);
      setNotice({
        type: 'failed',
        title: '操作失败',
        message: error.message,
      });
    }
  }

  if (!loggedIn) {
    return (
      <main className="login-shell">
        <section className="login-hero">
          <div className="ribbon">HDU Library</div>
          <h1>图书馆预约小岛</h1>
          <p>登录后查询座位、点击选座，并设置每日定时抢座任务。</p>
        </section>
        <Card color="default" className="login-card">
          <Title color="app-teal" size="medium">用户登录</Title>
          <form onSubmit={handleLogin} className="form-stack">
            <label>
              学号
              <input value={studentId} onChange={(event) => setStudentId(event.target.value)} placeholder="请输入学号" />
            </label>
            <label>
              密码
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="请输入数字杭电密码" />
            </label>
            <label>
              API 地址
              <input value={baseUrl} readOnly aria-readonly="true" />
            </label>
            <div className="inline-options">
              <label><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> 记住密码</label>
              <label><input type="checkbox" checked={autoLogin} onChange={(event) => setAutoLogin(event.target.checked)} /> 自动登录</label>
            </div>
            <Button htmlType="submit" type="primary" disabled={loading}>{loading ? '登录中...' : '登录'}</Button>
            <p className="status-line">{message}</p>
          </form>
        </Card>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="ribbon compact">HDU Library</div>
          <h1>图书馆预约小岛</h1>
        </div>
        <div className="top-actions">
          <span>{studentId}</span>
          <Button onClick={handleLogout}>退出登录</Button>
        </div>
      </header>

      <nav className="island-tabs">
        <button className={activeView === 'seats' ? 'active' : ''} onClick={() => setActiveView('seats')}>座位预约</button>
        <button className={activeView === 'tasks' ? 'active' : ''} onClick={() => setActiveView('tasks')}>定时抢座</button>
      </nav>

      <section className="workspace">
        <Card className="control-card">
          <Title color="app-yellow" size="small">查询条件</Title>
          <div className="control-grid">
            <label>
              预约区域
              <select value={selectedAreaKey} onChange={(event) => updateSelectedAreaKey(event.target.value)}>
                {areas.map((area) => (
                  <option key={areaKey(area)} value={areaKey(area)}>{area.name}{area.space ? `（${area.space}）` : ''}</option>
                ))}
              </select>
            </label>
            <label>
              日期
              <input type="date" value={date} onChange={(event) => updateDate(event.target.value)} />
            </label>
            <TimeRangeField
              startTime={startTime}
              endTime={endTime}
              setStartTime={updateStartTime}
              setEndTime={updateEndTime}
              setDurationHours={updateDurationHours}
              durationHours={durationHours}
            />
          </div>
          <div className="button-row">
            <Button onClick={loadArea}>加载区域</Button>
            <Button type="primary" onClick={searchSeats} disabled={loading}>查询座位</Button>
            <span className="status-line">{message}</span>
          </div>
        </Card>

        {activeView === 'seats' ? (
          <SeatsView
            seats={visibleSeats}
            allSeats={seats}
            venues={venues}
            venueStats={venueStats}
            venueFilter={venueFilter}
            setVenueFilter={setVenueFilter}
            selectedSeatId={selectedSeatId}
            setSelectedSeatId={setSelectedSeatId}
            selectedSeat={selectedSeat}
            bookSelectedSeat={bookSelectedSeat}
          />
        ) : (
          <TasksView
            seats={visibleSeats}
            allSeats={seats}
            venues={venues}
            venueStats={venueStats}
            venueFilter={venueFilter}
            setVenueFilter={setVenueFilter}
            primarySeats={primarySeats}
            backupSeats={backupSeats}
            clearCandidates={() => {
              setPrimarySeats([]);
              setBackupSeats([]);
            }}
            candidateMode={candidateMode}
            setCandidateMode={setCandidateMode}
            toggleCandidate={toggleCandidate}
            openTime={openTime}
            setOpenTime={setOpenTime}
            startTime={startTime}
            setStartTime={updateStartTime}
            endTime={endTime}
            setEndTime={updateEndTime}
            durationHours={durationHours}
            setDurationHours={updateDurationHours}
            preTriggerSeconds={preTriggerSeconds}
            setPreTriggerSeconds={setPreTriggerSeconds}
            maxRetries={maxRetries}
            setMaxRetries={setMaxRetries}
            retryIntervalSeconds={retryIntervalSeconds}
            setRetryIntervalSeconds={setRetryIntervalSeconds}
            concurrentRequests={concurrentRequests}
            setConcurrentRequests={setConcurrentRequests}
            createTask={createTask}
            tasks={tasks}
            taskAction={taskAction}
            loadTasks={loadTasks}
            areas={areas}
            selectedAreaKey={selectedAreaKey}
            setSelectedAreaKey={updateSelectedAreaKey}
            loadArea={loadArea}
            searchSeats={searchSeats}
            loading={loading}
          />
        )}
      </section>
      {notice ? (
        <div className="notice-backdrop" role="dialog" aria-modal="true" aria-labelledby="notice-title">
          <div className={`notice-dialog ${notice.type === 'success' ? 'success' : 'failed'}`}>
            <h2 id="notice-title">{notice.title}</h2>
            <p>{notice.message}</p>
            <button onClick={() => setNotice(null)}>知道了</button>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function TimeRangeField({ startTime, endTime, setStartTime, setEndTime, durationHours, setDurationHours }) {
  return (
    <fieldset className="time-range-field">
      <legend>预约时段</legend>
      <label>
        开始时间
        <input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
      </label>
      <span className="time-arrow">至</span>
      <label>
        结束时间
        <input type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
      </label>
      <label>
        持续时间
        <input
          type="number"
          min="1"
          max="15"
          step="1"
          value={durationHours}
          onChange={(event) => setDurationHours(event.target.value)}
        />
      </label>
    </fieldset>
  );
}

function SeatsView({ seats, allSeats, venues, venueStats, venueFilter, setVenueFilter, selectedSeatId, setSelectedSeatId, selectedSeat, bookSelectedSeat }) {
  const availableSeats = seats.filter((seat) => seat.status === 1);
  const allAvailableCount = allSeats.filter((seat) => seat.status === 1).length;

  function changeVenue(nextVenue) {
    setVenueFilter(nextVenue);
    if (selectedSeat && nextVenue && (selectedSeat.areaName || '未知场馆') !== nextVenue) {
      setSelectedSeatId(null);
    }
  }

  return (
    <div className="content-grid">
      <Card className="map-card">
        <div className="card-heading">
          <Title color="app-teal" size="small">座位地图</Title>
          <select value={venueFilter} onChange={(event) => changeVenue(event.target.value)}>
            <option value="">全部场馆</option>
            {venues.map((venue) => <option key={venue} value={venue}>{venue}</option>)}
          </select>
        </div>
        <div className="venue-stats">
          <button className={!venueFilter ? 'active' : ''} onClick={() => changeVenue('')}>
            全部 <strong>{allAvailableCount}</strong><span>/{allSeats.length}</span>
          </button>
          {venueStats.map((item) => (
            <button
              key={item.venue}
              className={venueFilter === item.venue ? 'active' : ''}
              onClick={() => changeVenue(item.venue)}
            >
              {item.venue} <strong>{item.available}</strong><span>/{item.total}</span>
            </button>
          ))}
        </div>
        <SeatMap seats={seats} selectedSeatId={selectedSeatId} onSeatClick={setSelectedSeatId} />
        <div className="legend">
          <span><i className="dot available" /> 可预约</span>
          <span><i className="dot busy" /> 不可约</span>
          <span><i className="dot selected" /> 已选</span>
        </div>
      </Card>
      <Card className="side-card">
        <Title color="app-pink" size="small">{venueFilter || '全部场馆'}可预约座位</Title>
        <div className="selected-box">
          {selectedSeat ? `${selectedSeat.areaName} ${selectedSeat.seatLabel}` : '还没有选择座位'}
        </div>
        <Button type="primary" onClick={bookSelectedSeat} disabled={!selectedSeat}>预约选中座位</Button>
        <div className="seat-list">
          {availableSeats.slice(0, 180).map((seat) => (
            <button
              key={seat.seatId}
              className={seat.seatId === selectedSeatId ? 'seat-row active' : 'seat-row'}
              onClick={() => setSelectedSeatId(seat.seatId)}
            >
              <strong>{seat.seatLabel}</strong>
              <span>{seat.areaName || '未知场馆'}</span>
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}

function TasksView({
  seats,
  allSeats,
  venues,
  venueStats,
  venueFilter,
  setVenueFilter,
  primarySeats,
  backupSeats,
  clearCandidates,
  candidateMode,
  setCandidateMode,
  toggleCandidate,
  openTime,
  setOpenTime,
  startTime,
  setStartTime,
  endTime,
  setEndTime,
  durationHours,
  setDurationHours,
  preTriggerSeconds,
  setPreTriggerSeconds,
  maxRetries,
  setMaxRetries,
  retryIntervalSeconds,
  setRetryIntervalSeconds,
  concurrentRequests,
  setConcurrentRequests,
  createTask,
  tasks,
  taskAction,
  loadTasks,
  areas,
  selectedAreaKey,
  setSelectedAreaKey,
  loadArea,
  searchSeats,
  loading,
}) {
  const allAvailableCount = allSeats.filter((seat) => seat.status === 1).length;

  function changeVenue(nextVenue) {
    setVenueFilter(nextVenue);
    clearCandidates();
  }

  return (
    <div className="content-grid">
      <Card className="map-card">
        <div className="card-heading">
          <Title color="app-orange" size="small">抢座候选</Title>
          <select value={venueFilter} onChange={(event) => changeVenue(event.target.value)}>
            <option value="">全部场馆</option>
            {venues.map((venue) => <option key={venue} value={venue}>{venue}</option>)}
          </select>
        </div>
        <div className="venue-stats">
          <button className={!venueFilter ? 'active' : ''} onClick={() => changeVenue('')}>
            全部 <strong>{allAvailableCount}</strong><span>/{allSeats.length}</span>
          </button>
          {venueStats.map((item) => (
            <button
              key={item.venue}
              className={venueFilter === item.venue ? 'active' : ''}
              onClick={() => changeVenue(item.venue)}
            >
              {item.venue} <strong>{item.available}</strong><span>/{item.total}</span>
            </button>
          ))}
        </div>
        <div className="segmented candidate-mode-tabs">
          <button className={candidateMode === 'primary' ? 'active' : ''} onClick={() => setCandidateMode('primary')}>主选</button>
          <button className={candidateMode === 'backup' ? 'active' : ''} onClick={() => setCandidateMode('backup')}>备选</button>
        </div>
        <SeatMap seats={seats} selectedSeatId={null} onSeatClick={(seatId) => {
          const seat = seats.find((item) => item.seatId === seatId);
          if (seat?.status === 1) toggleCandidate(seat);
        }} primarySeats={primarySeats} backupSeats={backupSeats} />
        <div className="candidate-pills">
          <span>主选：{primarySeats.length ? primarySeats.join('、') : '自动选择'}</span>
          <span>备选：{backupSeats.length ? backupSeats.join('、') : '无'}</span>
        </div>
      </Card>
      <Card className="side-card">
        <Title color="lime-green" size="small">任务设置</Title>
        <div className="form-stack compact-form">
          <label>
            抢座区域
            <select value={selectedAreaKey} onChange={(event) => setSelectedAreaKey(event.target.value)}>
              {areas.map((area) => (
                <option key={areaKey(area)} value={areaKey(area)}>{area.name}{area.space ? `（${area.space}）` : ''}</option>
              ))}
            </select>
          </label>
          <div className="button-row task-area-actions">
            <button onClick={loadArea} disabled={loading}>加载区域</button>
            <button onClick={searchSeats} disabled={loading}>查询候选座位</button>
          </div>
          <label>开放时间<input value={openTime} onChange={(event) => setOpenTime(event.target.value)} /></label>
          <TimeRangeField
            startTime={startTime}
            endTime={endTime}
            setStartTime={setStartTime}
            setEndTime={setEndTime}
            durationHours={durationHours}
            setDurationHours={setDurationHours}
          />
          <div className="advanced-grid">
            <label>提前触发（秒）<input type="number" min="0" max="30" value={preTriggerSeconds} onChange={(event) => setPreTriggerSeconds(event.target.value)} /></label>
            <label>最大重试（次）<input type="number" min="1" max="100" value={maxRetries} onChange={(event) => setMaxRetries(event.target.value)} /></label>
            <label>重试间隔（秒）<input type="number" min="0" max="10" value={retryIntervalSeconds} onChange={(event) => setRetryIntervalSeconds(event.target.value)} /></label>
            <label>并发提交（个）<input type="number" min="1" max="10" value={concurrentRequests} onChange={(event) => setConcurrentRequests(event.target.value)} /></label>
          </div>
          <Button type="primary" onClick={createTask}>添加定时任务</Button>
        </div>
        <div className="button-row task-toolbar">
          <button onClick={loadTasks}>刷新任务</button>
          <button onClick={() => Promise.all(tasks.map((task) => taskAction(task.taskId, 'cancel')))}>停止全部</button>
        </div>
        <div className="task-list">
          {tasks.map((task) => (
            <div className="task-item" key={task.taskId}>
              <strong>{task.startTime}-{task.endTime}</strong>
              <span>{task.status} · {task.statusMessage || '等待调度'}</span>
              <div className="mini-actions">
                <button onClick={() => taskAction(task.taskId, 'run-now')}>立即执行</button>
                <button onClick={() => taskAction(task.taskId, 'cancel')}>取消</button>
                <button onClick={() => taskAction(task.taskId, 'delete')}>删除</button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function SeatMap({ seats, selectedSeatId, onSeatClick, primarySeats = [], backupSeats = [] }) {
  const groups = useMemo(() => groupSeatsByVenue(seats), [seats]);
  const [zoom, setZoom] = useState(MAP_DEFAULT_ZOOM);
  const showLabels = zoom >= MAP_LABEL_ZOOM;

  function updateZoom(nextZoom) {
    setZoom(Math.min(MAP_MAX_ZOOM, Math.max(MAP_MIN_ZOOM, Number(nextZoom.toFixed(2)))));
  }

  if (!seats.length) {
    return <div className="empty-map">查询后座位会出现在这里</div>;
  }

  const zoomControls = (
    <div className="map-toolbar" aria-label="地图缩放">
      <button onClick={() => updateZoom(zoom - MAP_ZOOM_STEP)} disabled={zoom <= MAP_MIN_ZOOM}>-</button>
      <span>{Math.round(zoom * 100)}%</span>
      <button onClick={() => updateZoom(zoom + MAP_ZOOM_STEP)} disabled={zoom >= MAP_MAX_ZOOM}>+</button>
      <button onClick={() => updateZoom(MAP_DEFAULT_ZOOM)}>重置</button>
    </div>
  );

  if (groups.length > 1) {
    return (
      <div className="seat-map grouped-seat-map">
        {zoomControls}
        <div className="venue-sections">
          {groups.map(({ venue, seats: venueSeats }) => (
            <section className="venue-section" key={venue}>
              <div className="venue-section-header">
                <strong>{venue}</strong>
                <span>{venueSeats.filter((seat) => seat.status === 1).length} / {venueSeats.length} 可约</span>
              </div>
              <SeatCanvas
                seats={venueSeats}
                selectedSeatId={selectedSeatId}
                onSeatClick={onSeatClick}
                primarySeats={primarySeats}
                backupSeats={backupSeats}
                compact
                zoom={zoom}
                showLabels={showLabels}
              />
            </section>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="seat-map single-seat-map">
      {zoomControls}
      <SeatCanvas
        seats={seats}
        selectedSeatId={selectedSeatId}
        onSeatClick={onSeatClick}
        primarySeats={primarySeats}
        backupSeats={backupSeats}
        zoom={zoom}
        showLabels={showLabels}
      />
    </div>
  );
}

function SeatCanvas({ seats, selectedSeatId, onSeatClick, primarySeats = [], backupSeats = [], compact = false, zoom = 1, showLabels = true }) {
  const scale = (compact ? 9 : 18) * zoom;
  const padding = compact ? 18 : 36;
  const bounds = useMemo(() => {
    const minX = Math.min(...seats.map((seat) => seat.x));
    const minY = Math.min(...seats.map((seat) => seat.y));
    const maxX = Math.max(...seats.map((seat) => seat.x + Math.max(seat.width, 1)));
    const maxY = Math.max(...seats.map((seat) => seat.y + Math.max(seat.height, 1)));
    const contentWidth = Math.max(80, maxX - minX);
    const contentHeight = Math.max(60, maxY - minY);
    return {
      minX,
      minY,
      width: Math.max(compact ? 520 : 900, contentWidth * scale + padding * 2),
      height: Math.max(compact ? 340 : 560, contentHeight * scale + padding * 2),
    };
  }, [compact, padding, scale, seats]);

  return (
    <div
      className={compact ? 'seat-canvas compact-canvas' : 'seat-canvas'}
      style={{ width: `${bounds.width}px`, height: `${bounds.height}px` }}
    >
      {seats.map((seat) => {
        const key = `${seat.areaName || '未知场馆'}|${seat.seatLabel}`;
        const classes = [
          'seat-dot',
          seat.status === 1 ? 'available' : 'busy',
          showLabels ? '' : 'hide-label',
          selectedSeatId === seat.seatId ? 'selected' : '',
          primarySeats.includes(key) ? 'primary-candidate' : '',
          backupSeats.includes(key) ? 'backup-candidate' : '',
        ].filter(Boolean).join(' ');
        return (
          <button
            key={seat.seatId}
            title={`${seat.areaName || ''} ${seat.seatLabel}`}
            className={classes}
            style={{
              left: `${padding + (seat.x - bounds.minX) * scale}px`,
              top: `${padding + (seat.y - bounds.minY) * scale}px`,
              width: `${Math.max(compact ? 30 : 46, Math.max(seat.width, 2) * scale)}px`,
              height: `${Math.max(compact ? 24 : 36, Math.max(seat.height, 2) * scale)}px`,
            }}
            onClick={() => onSeatClick(seat.seatId)}
          >
            {showLabels ? seat.seatLabel : ''}
          </button>
        );
      })}
    </div>
  );
}

function areaKey(area) {
  return `${area.categoryId}:${area.contentId}`;
}

function groupSeatsByVenue(seats) {
  const groups = new Map();
  seats.forEach((seat) => {
    const venue = seat.areaName || '未知场馆';
    if (!groups.has(venue)) groups.set(venue, []);
    groups.get(venue).push(seat);
  });
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b, 'zh-CN'))
    .map(([venue, groupedSeats]) => ({ venue, seats: groupedSeats }));
}

function summarizeVenueCounts(seats) {
  return groupSeatsByVenue(seats)
    .map(({ venue, seats: groupedSeats }) => {
      const available = groupedSeats.filter((seat) => seat.status === 1).length;
      return `${venue} ${available}/${groupedSeats.length}`;
    })
    .join('，');
}

function localDateString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function timeRangeHours(startTime, endTime) {
  const [startHour, startMinute] = startTime.split(':').map(Number);
  const [endHour, endMinute] = endTime.split(':').map(Number);
  const start = startHour * 60 + startMinute;
  const end = endHour * 60 + endMinute;
  return Math.max(1, Math.round((end - start) / 60));
}

function addHoursToTime(time, hours) {
  const [hour, minute] = time.split(':').map(Number);
  const total = (hour * 60 + minute + hours * 60) % (24 * 60);
  const nextHour = Math.floor(total / 60);
  const nextMinute = total % 60;
  return `${String(nextHour).padStart(2, '0')}:${String(nextMinute).padStart(2, '0')}`;
}

function clampDuration(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(15, Math.round(parsed)));
}

createRoot(document.getElementById('root')).render(<App />);
