const API = '/api';

export async function fetchSpaces() {
  const res = await fetch(`${API}/spaces`);
  return res.json();
}

export async function fetchFiles(spaceId) {
  const res = await fetch(`${API}/spaces/${spaceId}/files`);
  return res.json();
}

export async function fetchFile(spaceId, filePath) {
  const res = await fetch(`${API}/spaces/${spaceId}/files/${filePath}`);
  return res.json();
}

export async function updateFile(spaceId, filePath, content, userId) {
  const res = await fetch(`${API}/spaces/${spaceId}/files/${filePath}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ space_id: spaceId, file_path: filePath, content, user_id: userId }),
  });
  return res.json();
}

export async function sendAgentPrompt(spaceId, prompt, userId) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 min timeout
  try {
    const res = await fetch(`${API}/agent/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ space_id: spaceId, prompt, user_id: userId }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error ${res.status}`);
    }
    return res.json();
  } catch (e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') throw new Error('Request timed out — the agent may still be working. Try again in a moment.');
    throw e;
  }
}

export async function fetchPreview(spaceId) {
  const res = await fetch(`${API}/preview/${spaceId}`);
  return res.json();
}

export async function fetchConversationHistory(spaceId, userId) {
  const res = await fetch(`${API}/agent/history/${spaceId}/${userId}`);
  return res.json();
}
