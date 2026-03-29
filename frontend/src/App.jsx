import React, { useState, useEffect, useCallback, useRef } from 'react';
import Editor from '@monaco-editor/react';
import {
  Code2, Eye, MessageSquare, Users, Send, Bot, Sparkles,
  FileCode, FileText, Palette, ChevronRight, PanelLeftClose,
  PanelLeft, Play, RefreshCw, Save, Check,
} from 'lucide-react';
import useWebSocket from './useWebSocket';
import { fetchFiles, fetchFile, updateFile, sendAgentPrompt, fetchPreview, fetchConversationHistory } from './api';

const ROLES = { developer: '💻', designer: '🎨', product_manager: '📋' };
const ROLE_LABELS = { developer: 'Developer', designer: 'Designer', product_manager: 'PM' };

function randomId() {
  return Math.random().toString(36).slice(2, 10);
}

function fileIcon(name) {
  if (name.endsWith('.html')) return <FileCode size={14} className="text-orange-400" />;
  if (name.endsWith('.css')) return <Palette size={14} className="text-blue-400" />;
  if (name.endsWith('.js')) return <FileCode size={14} className="text-yellow-400" />;
  return <FileText size={14} className="text-slate-400" />;
}

function langFromPath(p) {
  if (p.endsWith('.css')) return 'css';
  if (p.endsWith('.js') || p.endsWith('.jsx')) return 'javascript';
  if (p.endsWith('.ts') || p.endsWith('.tsx')) return 'typescript';
  if (p.endsWith('.json')) return 'json';
  return 'html';
}

export default function App() {
  // ---- User setup (simple inline form) ------------------------------------
  const [user, setUser] = useState(null);
  const [setupName, setSetupName] = useState('');
  const [setupRole, setSetupRole] = useState('developer');

  // ---- Workspace state ----------------------------------------------------
  const spaceId = 'demo-space-001';
  const [files, setFiles] = useState([]);
  const [activeFile, setActiveFile] = useState(null);
  const [fileContents, setFileContents] = useState({});
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activePanel, setActivePanel] = useState('editor'); // editor | preview | chat
  const [chatInput, setChatInput] = useState('');
  const [agentInput, setAgentInput] = useState('');
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentHistory, setAgentHistory] = useState([]);
  const [previewFile, setPreviewFile] = useState('index.html');
  const [saveStatus, setSaveStatus] = useState(''); // '' | 'saving' | 'saved'
  const [dirtyFiles, setDirtyFiles] = useState(new Set());
  const chatEndRef = useRef(null);
  const agentEndRef = useRef(null);
  const editorRef = useRef(null);
  const previewRef = useRef(null);

  const { collaborators, messages, fileUpdates, cursors, sendFileUpdate, sendCursor, sendChat } =
    useWebSocket(spaceId, user);

  // ---- Load files on mount ------------------------------------------------
  useEffect(() => {
    if (!user) return;
    fetchFiles(spaceId).then((data) => {
      setFiles(data);
      if (data.length > 0 && !activeFile) {
        setActiveFile(data[0].path);
        fetchFile(spaceId, data[0].path).then((f) =>
          setFileContents((prev) => ({ ...prev, [data[0].path]: f.content }))
        );
      }
    });
    // Load conversation history from AgentCore Memory
    fetchConversationHistory(spaceId, user.user_id).then((data) => {
      const events = data.events || [];
      const history = [];
      for (const evt of events) {
        for (const p of evt.payload || []) {
          if (p.conversational) {
            const role = p.conversational.role === 'USER' ? 'user' : 'agent';
            history.push({ role, content: p.conversational.content?.text || '' });
          }
        }
      }
      if (history.length > 0) setAgentHistory(history);
    }).catch(() => {});
  }, [user]);

  // ---- Handle incoming file updates from collaborators --------------------
  useEffect(() => {
    if (fileUpdates && fileUpdates.file_path) {
      setFileContents((prev) => ({ ...prev, [fileUpdates.file_path]: fileUpdates.content }));
    }
  }, [fileUpdates]);

  // ---- Auto-scroll chat ---------------------------------------------------
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  useEffect(() => { agentEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [agentHistory]);

  // ---- File selection -----------------------------------------------------
  const selectFile = useCallback(async (path) => {
    setActiveFile(path);
    if (!fileContents[path]) {
      const f = await fetchFile(spaceId, path);
      setFileContents((prev) => ({ ...prev, [path]: f.content }));
    }
  }, [fileContents]);

  // ---- Editor change handler (debounced broadcast) -----------------------
  const changeTimer = useRef(null);
  const handleEditorChange = useCallback((value) => {
    if (!activeFile) return;
    setFileContents((prev) => ({ ...prev, [activeFile]: value }));
    setDirtyFiles((prev) => new Set(prev).add(activeFile));
    clearTimeout(changeTimer.current);
    changeTimer.current = setTimeout(() => {
      sendFileUpdate(activeFile, value);
    }, 400);
  }, [activeFile, sendFileUpdate]);

  // ---- Explicit save (Ctrl+S or button) -----------------------------------
  const saveCurrentFile = useCallback(async () => {
    if (!activeFile || !user) return;
    const content = fileContents[activeFile];
    if (content == null) return;
    setSaveStatus('saving');
    try {
      await updateFile(spaceId, activeFile, content, user.user_id);
      setDirtyFiles((prev) => { const n = new Set(prev); n.delete(activeFile); return n; });
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus(''), 2000);
    } catch {
      setSaveStatus('');
    }
  }, [activeFile, fileContents, user]);

  // ---- Ctrl+S keyboard shortcut -------------------------------------------
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveCurrentFile();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [saveCurrentFile]);

  // ---- Cursor position broadcast ------------------------------------------
  const handleEditorMount = useCallback((editor) => {
    editorRef.current = editor;
    editor.onDidChangeCursorPosition((e) => {
      if (activeFile) sendCursor(activeFile, e.position.lineNumber, e.position.column);
    });
  }, [activeFile, sendCursor]);

  // ---- Chat ---------------------------------------------------------------
  const handleSendChat = () => {
    if (!chatInput.trim()) return;
    sendChat(chatInput.trim());
    setChatInput('');
  };

  // ---- Agent prompt -------------------------------------------------------
  const handleAgentPrompt = async () => {
    if (!agentInput.trim() || agentLoading) return;
    const prompt = agentInput.trim();
    setAgentHistory((prev) => [...prev, { role: 'user', content: prompt }]);
    setAgentInput('');
    setAgentLoading(true);
    try {
      const res = await sendAgentPrompt(spaceId, prompt, user.user_id);
      setAgentHistory((prev) => [...prev, { role: 'agent', content: res.response, files_changed: res.files_changed }]);

      // Refresh the full file list from backend (picks up new files)
      const updatedFiles = await fetchFiles(spaceId);
      setFiles(updatedFiles);

      // Fetch content for every changed file so editor + preview have it
      const changedPaths = res.files_changed || [];
      for (const fp of changedPaths) {
        try {
          const f = await fetchFile(spaceId, fp);
          if (f && f.content != null) {
            setFileContents((prev) => ({ ...prev, [fp]: f.content }));
          }
        } catch (_) { /* file may not be in cache yet */ }
      }

      // If an HTML file was created/changed, select it and switch to preview
      const htmlFile = changedPaths.find((p) => p.endsWith('.html'));
      if (htmlFile) {
        setActiveFile(htmlFile);
        setPreviewFile(htmlFile);
        setActivePanel('preview');
      } else if (changedPaths.length > 0) {
        setActiveFile(changedPaths[0]);
        setActivePanel('editor');
      }
    } catch (e) {
      setAgentHistory((prev) => [...prev, { role: 'agent', content: `Error: ${e.message}` }]);
    }
    setAgentLoading(false);
  };

  // ---- Preview refresh ----------------------------------------------------
  const refreshPreview = useCallback(() => {
    const iframe = previewRef.current;
    if (!iframe) return;

    // Use the selected preview file, fall back to index.html
    let html = fileContents[previewFile] || fileContents['index.html'] || '';

    // Inline all CSS files referenced via <link> tags
    html = html.replace(
      /<link\s+[^>]*href=["']([^"']+\.css)["'][^>]*\/?>/gi,
      (match, cssPath) => {
        const cssContent = fileContents[cssPath];
        return cssContent != null ? `<style>${cssContent}</style>` : match;
      }
    );

    // Inline all JS files referenced via <script src="...">
    html = html.replace(
      /<script\s+[^>]*src=["']([^"']+\.js)["'][^>]*>\s*<\/script>/gi,
      (match, jsPath) => {
        const jsContent = fileContents[jsPath];
        return jsContent != null ? `<script>${jsContent}<\/script>` : match;
      }
    );

    iframe.srcdoc = html;
  }, [fileContents, previewFile]);

  useEffect(() => {
    if (activePanel === 'preview') refreshPreview();
  }, [activePanel, fileContents, refreshPreview, previewFile]);

  // ---- Login screen -------------------------------------------------------
  if (!user) {
    return (
      <div className="h-screen flex items-center justify-center bg-slate-950">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 w-full max-w-md shadow-2xl">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center">
              <Code2 size={22} className="text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">CodeSpace</h1>
              <p className="text-sm text-slate-400">Collaborative coding for teams</p>
            </div>
          </div>
          <label className="block text-sm text-slate-400 mb-1">Your Name</label>
          <input
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white mb-4 focus:outline-none focus:border-indigo-500"
            placeholder="e.g. Alice"
            value={setupName}
            onChange={(e) => setSetupName(e.target.value)}
          />
          <label className="block text-sm text-slate-400 mb-1">Role</label>
          <div className="flex gap-2 mb-6">
            {Object.entries(ROLE_LABELS).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setSetupRole(key)}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
                  setupRole === key
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                }`}
              >
                {ROLES[key]} {label}
              </button>
            ))}
          </div>
          <button
            disabled={!setupName.trim()}
            onClick={() => {
              const stableId = setupName.trim().toLowerCase().replace(/\s+/g, '-');
              setUser({
                user_id: stableId,
                username: setupName.trim(),
                role: setupRole,
                avatar_color: ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6'][
                  Math.abs(stableId.split('').reduce((a, c) => a + c.charCodeAt(0), 0)) % 5
                ],
              });
            }}
            className="w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold disabled:opacity-40 transition-all"
          >
            Join Space
          </button>
        </div>
      </div>
    );
  }

  // ---- Main workspace UI --------------------------------------------------
  return (
    <div className="h-screen flex flex-col bg-slate-950 text-slate-200">
      {/* Top bar */}
      <header className="h-12 flex items-center justify-between px-4 bg-slate-900 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
            <Code2 size={16} className="text-white" />
          </div>
          <span className="font-semibold text-sm">CodeSpace</span>
          <span className="text-xs text-slate-500 ml-2">Demo Project</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Collaborator avatars */}
          <div className="flex -space-x-2 mr-3">
            {collaborators.map((c) => (
              <div
                key={c.user_id}
                title={`${c.username} (${ROLE_LABELS[c.role] || c.role})`}
                className="w-7 h-7 rounded-full border-2 border-slate-900 flex items-center justify-center text-xs font-bold text-white"
                style={{ backgroundColor: c.avatar_color }}
              >
                {c.username[0]?.toUpperCase()}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-400 bg-slate-800 px-2 py-1 rounded-md">
            <Users size={12} /> {collaborators.length + 1} online
          </div>
          <div className="flex items-center gap-1 text-xs bg-slate-800 px-2 py-1 rounded-md" style={{ color: user.avatar_color }}>
            {ROLES[user.role]} {user.username}
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar — file tree */}
        {sidebarOpen && (
          <aside className="w-56 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0">
            <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Files</span>
              <button onClick={() => setSidebarOpen(false)} className="text-slate-500 hover:text-slate-300">
                <PanelLeftClose size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto py-1">
              {files.map((f) => (
                <button
                  key={f.path}
                  onClick={() => selectFile(f.path)}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-slate-800 transition-colors ${
                    activeFile === f.path ? 'bg-slate-800 text-white' : 'text-slate-400'
                  }`}
                >
                  {fileIcon(f.name)}
                  {f.name}
                  {dirtyFiles.has(f.path) && (
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 ml-1" title="Unsaved" />
                  )}
                  {/* Show who else is editing this file */}
                  {Object.values(cursors).filter((c) => c.file_path === f.path).map((c) => (
                    <span
                      key={c.user_id}
                      className="w-2 h-2 rounded-full ml-auto"
                      style={{ backgroundColor: c.avatar_color }}
                      title={`${c.username} is editing`}
                    />
                  ))}
                </button>
              ))}
            </div>
          </aside>
        )}

        {/* Main content area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Tab bar */}
          <div className="h-9 flex items-center bg-slate-900 border-b border-slate-800 px-2 gap-1 shrink-0">
            {!sidebarOpen && (
              <button onClick={() => setSidebarOpen(true)} className="text-slate-500 hover:text-slate-300 mr-1">
                <PanelLeft size={14} />
              </button>
            )}
            <button
              onClick={() => setActivePanel('editor')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors ${
                activePanel === 'editor' ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Code2 size={13} /> Editor
              {dirtyFiles.size > 0 && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" title="Unsaved changes" />}
            </button>
            <button
              onClick={() => setActivePanel('preview')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors ${
                activePanel === 'preview' ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Eye size={13} /> Preview
            </button>
            <button
              onClick={() => setActivePanel('chat')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors ${
                activePanel === 'chat' ? 'bg-slate-800 text-white' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <MessageSquare size={13} /> Chat
              {messages.length > 0 && (
                <span className="bg-indigo-600 text-white text-[10px] px-1.5 rounded-full">{messages.length}</span>
              )}
            </button>
            {activePanel === 'preview' && (
              <div className="ml-auto flex items-center gap-2">
                <select
                  value={previewFile}
                  onChange={(e) => setPreviewFile(e.target.value)}
                  className="bg-slate-800 text-slate-300 text-xs border border-slate-700 rounded px-1.5 py-0.5 focus:outline-none"
                >
                  {files.filter((f) => f.name.endsWith('.html')).map((f) => (
                    <option key={f.path} value={f.path}>{f.name}</option>
                  ))}
                </select>
                <button onClick={refreshPreview} className="text-slate-500 hover:text-slate-300">
                  <RefreshCw size={13} />
                </button>
              </div>
            )}
            {activePanel === 'editor' && (
              <div className="ml-auto flex items-center gap-2">
                {saveStatus === 'saved' && (
                  <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                    <Check size={11} /> Saved
                  </span>
                )}
                {saveStatus === 'saving' && (
                  <span className="text-[10px] text-slate-500">Saving...</span>
                )}
                <button
                  onClick={saveCurrentFile}
                  disabled={!activeFile || !dirtyFiles.has(activeFile)}
                  className="flex items-center gap-1 text-xs text-slate-400 hover:text-white disabled:opacity-30 transition-colors px-2 py-0.5 rounded hover:bg-slate-800"
                  title="Save (Ctrl+S)"
                >
                  <Save size={12} /> Save
                </button>
              </div>
            )}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-hidden">
            {activePanel === 'editor' && (
              <Editor
                height="100%"
                language={activeFile ? langFromPath(activeFile) : 'html'}
                value={activeFile ? fileContents[activeFile] || '' : ''}
                theme="vs-dark"
                onChange={handleEditorChange}
                onMount={handleEditorMount}
                options={{
                  fontSize: 13,
                  minimap: { enabled: false },
                  padding: { top: 12 },
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  lineNumbers: 'on',
                  renderWhitespace: 'selection',
                  bracketPairColorization: { enabled: true },
                }}
              />
            )}

            {activePanel === 'preview' && (
              <div className="h-full bg-white">
                <iframe ref={previewRef} title="Preview" className="w-full h-full border-0" sandbox="allow-scripts" />
              </div>
            )}

            {activePanel === 'chat' && (
              <div className="h-full flex flex-col">
                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {messages.map((m, i) => (
                    <div key={i} className={`flex gap-2 ${m.is_agent ? '' : ''}`}>
                      <div
                        className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                        style={{ backgroundColor: m.is_agent ? '#6366f1' : m.avatar_color || '#475569' }}
                      >
                        {m.is_agent ? <Bot size={14} /> : (m.username?.[0]?.toUpperCase() || '?')}
                      </div>
                      <div>
                        <div className="text-xs text-slate-500 mb-0.5">
                          {m.is_agent ? 'CodeSpace AI' : m.username} · {new Date(m.timestamp).toLocaleTimeString()}
                        </div>
                        <div className="text-sm text-slate-300 bg-slate-900 rounded-lg px-3 py-2 max-w-lg">
                          {m.content}
                        </div>
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>
                <div className="p-3 border-t border-slate-800">
                  <div className="flex gap-2">
                    <input
                      className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
                      placeholder="Message your team..."
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSendChat()}
                    />
                    <button onClick={handleSendChat} className="bg-indigo-600 hover:bg-indigo-500 px-3 rounded-lg transition-colors">
                      <Send size={16} />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right panel — AI Agent */}
        <aside className="w-80 bg-slate-900 border-l border-slate-800 flex flex-col shrink-0">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800">
            <Sparkles size={14} className="text-indigo-400" />
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">AI Agent</span>
            <span className="text-[10px] bg-indigo-600/20 text-indigo-400 px-1.5 py-0.5 rounded ml-auto">AgentCore</span>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {agentHistory.length === 0 && (
              <div className="text-center py-8">
                <Bot size={32} className="mx-auto text-slate-600 mb-3" />
                <p className="text-sm text-slate-500">Ask the AI to generate or modify code.</p>
                <p className="text-xs text-slate-600 mt-1">Powered by AgentCore Runtime</p>
              </div>
            )}
            {agentHistory.map((m, i) => (
              <div key={i} className={`flex gap-2 ${m.role === 'user' ? 'justify-end' : ''}`}>
                {m.role === 'agent' && (
                  <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
                    <Bot size={12} className="text-white" />
                  </div>
                )}
                <div
                  className={`text-sm rounded-lg px-3 py-2 max-w-[240px] ${
                    m.role === 'user'
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-800 text-slate-300'
                  }`}
                >
                  {m.content}
                  {m.files_changed?.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-slate-700">
                      <p className="text-[10px] text-slate-500 mb-1">Files changed:</p>
                      {m.files_changed.map((fp) => (
                        <div key={fp} className="flex items-center gap-1 mb-0.5">
                          {fileIcon(fp)}
                          <button
                            onClick={() => { selectFile(fp); setActivePanel('editor'); }}
                            className="text-xs text-indigo-400 hover:underline truncate"
                            title={`Edit ${fp}`}
                          >
                            {fp}
                          </button>
                          {fp.endsWith('.html') && (
                            <button
                              onClick={() => { setPreviewFile(fp); setActivePanel('preview'); }}
                              className="text-xs text-emerald-400 hover:text-emerald-300 ml-auto shrink-0"
                              title={`Preview ${fp}`}
                            >
                              <Eye size={11} />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {agentLoading && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <div className="animate-spin w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full" />
                <span>Generating code... this may take up to 2 minutes</span>
              </div>
            )}
            <div ref={agentEndRef} />
          </div>
          <div className="p-3 border-t border-slate-800">
            <div className="flex gap-2">
              <input
                className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
                placeholder="Ask AI to generate code..."
                value={agentInput}
                onChange={(e) => setAgentInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAgentPrompt()}
              />
              <button
                onClick={handleAgentPrompt}
                disabled={agentLoading}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 px-3 rounded-lg transition-colors"
              >
                <Play size={16} />
              </button>
            </div>
            <p className="text-[10px] text-slate-600 mt-1.5 text-center">
              Conversations stored in AgentCore Memory · Files persist in Runtime Sessions
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
