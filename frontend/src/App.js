import React, { useState, useRef, useEffect } from 'react';
import './App.css';

const API_BASE = 'http://localhost:5001';

const normalizeMessages = (history = []) =>
  history
    .filter((msg) => msg.role !== 'tool') // Filter out tool messages
    .map((msg, index) => ({
      role: msg.role,
      content: msg.content,
      tool_calls: msg.tool_calls,
      isTool: msg.role === 'tool',
      key: `${msg.role}-${index}-${Date.now()}`,
    }));

function App() {
  const [messages, setMessages] = useState([]);
  const [chats, setChats] = useState([]);
  const [activeChatId, setActiveChatId] = useState(null);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentStreamingMessage, setCurrentStreamingMessage] = useState('');
  const [currentDocument, setCurrentDocument] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const messagesEndRef = useRef(null);
  const sessionId = useRef(`session_${Date.now()}`);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentStreamingMessage]);

  useEffect(() => {
    const bootstrapChats = async () => {
      const list = await fetchChatList();
      if (!list.length) {
        const id = await createNewChat();
        setActiveChatId(id);
        return;
      }
      setActiveChatId((prev) => prev || list[0].id);
    };
    bootstrapChats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeChatId) return;
    loadChatHistory(activeChatId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChatId]);

  const fetchChatList = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/chats/${sessionId.current}`);
      if (!res.ok) throw new Error('Unable to fetch chats');
      const data = await res.json();
      setChats(data.chats || []);
      return data.chats || [];
    } catch (error) {
      console.error(error);
      return [];
    }
  };

  const createNewChat = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/chats`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId.current }),
      });
      if (!res.ok) throw new Error('Unable to create chat');
      const data = await res.json();
      const newChat = {
        id: data.chat_id,
        title: data.title,
        created_at: data.created_at,
      };
      setChats((prev) => [newChat, ...prev]);
      setMessages([]);
      setCurrentDocument(null);
      return newChat.id;
    } catch (error) {
      console.error(error);
      return null;
    }
  };

  const loadChatHistory = async (chatId) => {
    try {
      const res = await fetch(`${API_BASE}/api/chats/${sessionId.current}/${chatId}`);
      if (!res.ok) throw new Error('Unable to load chat');
      const data = await res.json();
      setMessages(normalizeMessages(data.chat?.messages || []));
      setCurrentStreamingMessage('');
      setCurrentDocument(null);
    } catch (error) {
      console.error(error);
    }
  };

  const ensureActiveChat = async () => {
    if (activeChatId) return activeChatId;
    const id = await createNewChat();
    setActiveChatId(id);
    return id;
  };

  const startStreaming = async ({ message, regenerate = false }) => {
    const chatId = await ensureActiveChat();
    if (!chatId) return;

    setIsLoading(true);
    setCurrentStreamingMessage('');
    setCurrentDocument(null);

    try {
      const payload = {
        session_id: sessionId.current,
        chat_id: chatId,
        regenerate,
      };
      if (!regenerate) {
        payload.message = message;
      }

      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error('Failed to get response');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6);
          if (payload === '[DONE]') {
            if (assistantMessage) {
              setMessages((prev) => [...prev, { role: 'assistant', content: assistantMessage }]);
              setCurrentStreamingMessage('');
            }
            setIsLoading(false);
            await fetchChatList();
            return;
          }

          try {
            const parsed = JSON.parse(payload);

            if (parsed.type === 'content') {
              assistantMessage += parsed.content;
              setCurrentStreamingMessage(assistantMessage);
            } else if (parsed.type === 'function_call') {

            } else if (parsed.type === 'function_result') {
              if (
                (parsed.function_name === 'generate_document' ||
                  parsed.function_name === 'apply_edits') &&
                parsed.result?.document
              ) {
                setCurrentDocument(parsed.result.document);
              }
            } else if (parsed.type === 'document') {
              setCurrentDocument(parsed.content);
            } else if (parsed.type === 'error') {
              setMessages((prev) => [
                ...prev,
                { role: 'assistant', content: `Error: ${parsed.message}`, isError: true },
              ]);
              setIsLoading(false);
              return;
            }
          } catch (error) {
            console.error('Parse error', error);
          }
        }
      }

      // finish message iff the streaming completed
      if (assistantMessage) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: assistantMessage,
          },
        ]);
        setCurrentStreamingMessage('');
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${error.message}`, isError: true },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const chatId = await ensureActiveChat();
    if (!chatId) return;

    const userMessage = input.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: userMessage }]);

    startStreaming({ message: userMessage, regenerate: false });
  };

  const handleEditMessage = async (index, currentContent) => {
    if (!activeChatId) return;
    const updated = window.prompt('Edit your message', currentContent);
    if (updated === null) return;
    const trimmed = updated.trim();
    if (!trimmed || trimmed === currentContent.trim()) return;

    try {
      const res = await fetch(`${API_BASE}/api/chats/${sessionId.current}/${activeChatId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_index: index, new_content: trimmed }),
      });
      if (!res.ok) throw new Error('Unable to edit message');
      const data = await res.json();
      setMessages(normalizeMessages(data.messages || []));
      setCurrentDocument(null);
      setCurrentStreamingMessage('');
      startStreaming({ regenerate: true });
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error editing message: ${error.message}`, isError: true },
      ]);
    }
  };

  const handleNewChat = async () => {
    const id = await createNewChat();
    if (id) {
      setActiveChatId(id);
      await fetchChatList();
    }
  };

  const handleSelectChat = (chatId) => {
    if (chatId === activeChatId) return;
    setActiveChatId(chatId);
  };

  const renderMessageContent = (msg) => {
    if (msg.role === 'tool' || (!msg.content && !msg.isFunctionCall)) {
      return null;
    }
    if (!msg.content) return '';
    const segments = msg.content.split('\n');
    return segments.map((line, i) => (
      <React.Fragment key={`${msg.role}-${i}`}>
        {line}
        {i < segments.length - 1 && <br />}
      </React.Fragment>
    ));
  };

  return (
    <div className="app">
      <div className={`sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
        <div className="sidebar-header">
          <div>
            <h2>Chats</h2>
            <p>Legal assistant</p>
          </div>
          <button className="new-chat-btn" onClick={handleNewChat}>
            + New Chat
          </button>
        </div>
        <div className="chat-list">
          {chats.map((chat) => (
            <button
              key={chat.id}
              className={`chat-list-item ${chat.id === activeChatId ? 'active' : ''}`}
              onClick={() => handleSelectChat(chat.id)}
            >
              <span>{chat.title}</span>
            </button>
          ))}
          {!chats.length && (
            <div className="empty-chat-list">
              <p>No chats yet. Start a conversation!</p>
            </div>
          )}
        </div>
      </div>

      <div className="chat-pane">
        <div className="chat-header">
          <div>
            <h1>Legal Document Assistant</h1>
            <p>Specialized ChatGPT experience for legal workflows</p>
          </div>
          <div className="header-actions">
            <button className="toggle-sidebar" onClick={() => setSidebarOpen((prev) => !prev)}>
              {sidebarOpen ? 'Hide Chats' : 'Show Chats'}
            </button>
            <button className="new-chat-inline" onClick={handleNewChat}>
              New Chat
            </button>
          </div>
        </div>

        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="welcome-message">
              <h2>Start drafting</h2>
              <p>Request NDAs, employment agreements, resolutions, and more.</p>
            </div>
          )}

          {messages
            .filter((msg) => msg.role !== 'tool' && (msg.content || msg.isFunctionCall || msg.isError))
            .map((msg, idx) => (
              <div key={`${msg.role}-${idx}`} className={`message ${msg.role}`}>
                <div className="message-content">
                  {msg.role === 'user' && (
                    <button className="edit-message-btn" onClick={() => handleEditMessage(idx, msg.content || '')}>
                      ✏️
                    </button>
                  )}
                  {msg.isFunctionCall && <div className="function-call-indicator"> {msg.content}</div>}
                  {msg.isError && <div className="error-message"> {msg.content}</div>}
                  {!msg.isFunctionCall && !msg.isError && renderMessageContent(msg) && (
                    <div className="message-text">{renderMessageContent(msg)}</div>
                  )}
                </div>
              </div>
            ))}

          {currentStreamingMessage && (
            <div className="message assistant">
              <div className="message-content">
                <div className="message-text">
                  {currentStreamingMessage}
                  <span className="cursor">▊</span>
                </div>
              </div>
            </div>
          )}

          {currentDocument && (
            <div className="document-preview">
              <div className="document-header">
                <h3>📄 Generated Document</h3>
              </div>
              <pre className="document-content">{currentDocument}</pre>
            </div>
          )}

          {isLoading && !currentStreamingMessage && (
            <div className="message assistant">
              <div className="message-content">
                <div className="loading-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <form className="chat-input-form" onSubmit={handleSend}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Describe the legal document you need..."
            disabled={isLoading}
            className="chat-input"
          />
          <button type="submit" disabled={isLoading || !input.trim()} className="send-button">
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

export default App;

