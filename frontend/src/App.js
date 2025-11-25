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
  const [editingIndex, setEditingIndex] = useState(null);
  const [editValue, setEditValue] = useState('');
  const messagesEndRef = useRef(null);
  const editInputRef = useRef(null);
  const sessionId = useRef(`session_${Date.now()}`);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentStreamingMessage]);

  useEffect(() => {
    let mounted = true;
    const bootstrapChats = async () => {
      const list = await fetchChatList();
      if (mounted) {
        if (!list.length) {
          const id = await createNewChat();
          if (mounted && id) {
            setActiveChatId(id);
          }
        } else {
          setActiveChatId((prev) => prev || list[0].id);
        }
      }
    };
    bootstrapChats();
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeChatId) return;
    const loadChat = async () => {
      try {
        await loadChatHistory(activeChatId);
      } catch (error) {
        console.error('Failed to load chat:', error);
        // If chat doesn't exist, refresh the list
        await fetchChatList();
      }
    };
    loadChat();
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
      setChats((prev) => {
        // Avoid duplicates - check if chat already exists
        if (prev.some(chat => chat.id === newChat.id)) {
          return prev;
        }
        return [newChat, ...prev];
      });
      setMessages([]);
      setCurrentDocument(null);
      return newChat.id;
    } catch (error) {
      console.error(error);
      return null;
    }
  };

  const loadChatHistory = async (chatId) => {
    if (!chatId) return;
    try {
      const res = await fetch(`${API_BASE}/api/chats/${sessionId.current}/${chatId}`);
      if (!res.ok) {
        if (res.status === 404) {
          // Chat doesn't exist, refresh chat list
          await fetchChatList();
          return;
        }
        throw new Error('Unable to load chat');
      }
      const data = await res.json();
      setMessages(normalizeMessages(data.chat?.messages || []));
      setCurrentStreamingMessage('');
      setCurrentDocument(null);
    } catch (error) {
      console.error('Error loading chat:', error);
    }
  };

  const ensureActiveChat = async () => {
    if (activeChatId) return activeChatId;
    // Only create if we really don't have an active chat
    const list = await fetchChatList();
    if (list.length > 0) {
      setActiveChatId(list[0].id);
      return list[0].id;
    }
    const id = await createNewChat();
    if (id) {
      setActiveChatId(id);
    }
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

  const handleStartEdit = (index, currentContent) => {
    setEditingIndex(index);
    setEditValue(currentContent);
  };

  const handleCancelEdit = () => {
    setEditingIndex(null);
    setEditValue('');
  };

  const handleSaveEdit = async (index) => {
    if (!activeChatId) {
      handleCancelEdit();
      return;
    }
    const trimmed = editValue.trim();
    if (!trimmed) {
      handleCancelEdit();
      return;
    }

    const originalMessage = messages[index];
    if (trimmed === originalMessage.content?.trim()) {
      handleCancelEdit();
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/chats/${sessionId.current}/${activeChatId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_index: index, new_content: trimmed }),
      });
      if (!res.ok) {
        if (res.status === 404) {
          // Chat doesn't exist, refresh chat list and create new chat
          await fetchChatList();
          const newId = await createNewChat();
          if (newId) {
            setActiveChatId(newId);
            setMessages([{ role: 'user', content: trimmed }]);
            setEditingIndex(null);
            setEditValue('');
            startStreaming({ message: trimmed, regenerate: false });
          }
          return;
        }
        throw new Error('Unable to edit message');
      }
      const data = await res.json();
      setMessages(normalizeMessages(data.messages || []));
      setCurrentDocument(null);
      setCurrentStreamingMessage('');
      setEditingIndex(null);
      setEditValue('');
      // Update chat title if it changed
      if (data.title) {
        setChats((prev) =>
          prev.map((chat) =>
            chat.id === activeChatId ? { ...chat, title: data.title } : chat
          )
        );
      }
      startStreaming({ regenerate: true });
    } catch (error) {
      console.error('Error editing message:', error);
      handleCancelEdit();
    }
  };

  useEffect(() => {
    if (editingIndex !== null && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingIndex]);

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

  const handleDeleteChat = async (chatId, e) => {
    e.stopPropagation(); // Prevent selecting the chat when clicking delete
    if (!window.confirm('Are you sure you want to delete this chat?')) {
      return;
    }
    
    try {
      const res = await fetch(`${API_BASE}/api/chats/${sessionId.current}/${chatId}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Unable to delete chat');
      
      // If we deleted the active chat, create a new empty chat
      if (chatId === activeChatId) {
        const newId = await createNewChat();
        if (newId) {
          setActiveChatId(newId);
        } else {
          setActiveChatId(null);
          setMessages([]);
        }
      }
      
      await fetchChatList();
    } catch (error) {
      console.error('Error deleting chat:', error);
      alert('Failed to delete chat. Please try again.');
    }
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
            <div
              key={chat.id}
              className={`chat-list-item ${chat.id === activeChatId ? 'active' : ''}`}
            >
              <button
                className="chat-list-item-button"
                onClick={() => handleSelectChat(chat.id)}
              >
                <span className="chat-title">{chat.title}</span>
              </button>
              <button
                className="delete-chat-btn"
                onClick={(e) => handleDeleteChat(chat.id, e)}
                aria-label="Delete chat"
              >
                ×
              </button>
            </div>
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
                  {msg.role === 'user' && editingIndex !== idx && (
                    <button className="edit-message-btn" onClick={() => handleStartEdit(idx, msg.content || '')}>
                      ✏️
                    </button>
                  )}
                  {editingIndex === idx && msg.role === 'user' ? (
                    <div className="edit-message-container">
                      <textarea
                        ref={editInputRef}
                        className="edit-message-input"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                            e.preventDefault();
                            handleSaveEdit(idx);
                          } else if (e.key === 'Escape') {
                            e.preventDefault();
                            handleCancelEdit();
                          }
                        }}
                        rows={Math.min(editValue.split('\n').length, 10)}
                      />
                      <div className="edit-message-actions">
                        <button className="save-edit-btn" onClick={() => handleSaveEdit(idx)}>
                          Save
                        </button>
                        <button className="cancel-edit-btn" onClick={handleCancelEdit}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {msg.isFunctionCall && <div className="function-call-indicator"> {msg.content}</div>}
                      {msg.isError && <div className="error-message"> {msg.content}</div>}
                      {!msg.isFunctionCall && !msg.isError && renderMessageContent(msg) && (
                        <div className="message-text">{renderMessageContent(msg)}</div>
                      )}
                    </>
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

