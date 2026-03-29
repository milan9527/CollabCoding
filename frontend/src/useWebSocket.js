import { useEffect, useRef, useCallback, useState } from 'react';

export default function useWebSocket(spaceId, user) {
  const wsRef = useRef(null);
  const [collaborators, setCollaborators] = useState([]);
  const [messages, setMessages] = useState([]);
  const [fileUpdates, setFileUpdates] = useState(null);
  const [cursors, setCursors] = useState({});

  useEffect(() => {
    if (!spaceId || !user) return;

    const params = new URLSearchParams({
      username: user.username,
      role: user.role,
      color: user.avatar_color,
    });
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}://${host}/ws/${spaceId}/${user.user_id}?${params}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      switch (data.type) {
        case 'collaborators_list':
          setCollaborators(data.collaborators);
          break;
        case 'user_joined':
          setCollaborators((prev) => {
            if (prev.find((c) => c.user_id === data.user_id)) return prev;
            return [...prev, { user_id: data.user_id, username: data.username, role: data.role, avatar_color: data.avatar_color }];
          });
          break;
        case 'user_left':
          setCollaborators((prev) => prev.filter((c) => c.user_id !== data.user_id));
          setCursors((prev) => { const n = { ...prev }; delete n[data.user_id]; return n; });
          break;
        case 'file_update':
          setFileUpdates(data);
          break;
        case 'cursor_update':
          setCursors((prev) => ({ ...prev, [data.user_id]: data }));
          break;
        case 'chat_message':
          setMessages((prev) => [...prev, data]);
          break;
        case 'agent_response':
          setMessages((prev) => [
            ...prev,
            { type: 'agent_response', content: data.response, files_changed: data.files_changed, timestamp: data.timestamp, is_agent: true },
          ]);
          break;
        default:
          break;
      }
    };

    return () => {
      ws.close();
    };
  }, [spaceId, user]);

  const sendFileUpdate = useCallback((filePath, content) => {
    wsRef.current?.send(JSON.stringify({ type: 'file_update', file_path: filePath, content }));
  }, []);

  const sendCursor = useCallback((filePath, line, column) => {
    wsRef.current?.send(JSON.stringify({ type: 'cursor_update', file_path: filePath, line, column }));
  }, []);

  const sendChat = useCallback((content) => {
    wsRef.current?.send(JSON.stringify({ type: 'chat_message', content }));
  }, []);

  return { collaborators, messages, fileUpdates, cursors, sendFileUpdate, sendCursor, sendChat };
}
