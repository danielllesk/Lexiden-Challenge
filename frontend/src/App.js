import React, { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentStreamingMessage, setCurrentStreamingMessage] = useState('');
  const [currentDocument, setCurrentDocument] = useState(null);
  const messagesEndRef = useRef(null);
  const sessionId = useRef(`session_${Date.now()}`);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentStreamingMessage]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setIsLoading(true);
    setCurrentStreamingMessage('');
    setCurrentDocument(null);

    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);

    try {
      const response = await fetch('http://localhost:5000/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: userMessage,
          session_id: sessionId.current,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to get response');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMessage = '';
      let functionCallName = null;
      let isDocument = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') {
              // finish the message
              if (assistantMessage) {
                setMessages(prev => [...prev, { role: 'assistant', content: assistantMessage }]);
                setCurrentStreamingMessage('');
              }
              setIsLoading(false);
              return;
            }

            try {
              const parsed = JSON.parse(data);
              
              if (parsed.type === 'content') {
                assistantMessage += parsed.content;
                setCurrentStreamingMessage(assistantMessage);
              } else if (parsed.type === 'function_call') {
                functionCallName = parsed.function_name;
                setMessages(prev => [...prev, { 
                  role: 'assistant', 
                  content: `Calling function: ${parsed.function_name}...`,
                  isFunctionCall: true
                }]);
              } else if (parsed.type === 'function_result') {
                if (parsed.function_name === 'generate_document' || parsed.function_name === 'apply_edits') {
                  if (parsed.result && parsed.result.document) {
                    setCurrentDocument(parsed.result.document);
                    isDocument = true;
                  }
                }
              } else if (parsed.type === 'document') {
                setCurrentDocument(parsed.content);
                isDocument = true;
              } else if (parsed.type === 'error') {
                setMessages(prev => [...prev, { 
                  role: 'assistant', 
                  content: `Error: ${parsed.message}`,
                  isError: true
                }]);
                setIsLoading(false);
                return;
              }
            } catch (e) {
            }
          }
        }
      }

      // finish message iff the streaming completed
      if (assistantMessage) {
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: assistantMessage,
          isDocument: isDocument
        }]);
        setCurrentStreamingMessage('');
      }
    } catch (error) {
      console.error('Error:', error);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `Error: ${error.message}`,
        isError: true
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClear = async () => {
    setMessages([]);
    setCurrentDocument(null);
    setCurrentStreamingMessage('');
    // Optionally clear backend conversation
    try {
      await fetch(`http://localhost:5000/api/conversations/${sessionId.current}`, {
        method: 'DELETE',
      });
    } catch (error) {
      console.error('Error clearing conversation:', error);
    }
  };

  return (
    <div className="app">
      <div className="chat-container">
        <div className="chat-header">
          <h1>Legal Document Assistant</h1>
          <p>Generate legal documents through conversation</p>
          <button className="clear-button" onClick={handleClear}>
            Clear Conversation
          </button>
        </div>

        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="welcome-message">
              <h2>Welcome!</h2>
              <p>I can help you create legal documents like:</p>
              <ul>
                <li>Non-Disclosure Agreements (NDA)</li>
                <li>Employment Agreements</li>
                <li>Director Appointment Resolutions</li>
                <li>And more...</li>
              </ul>
              <p>Just tell me what you need, and I'll guide you through the process!</p>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
              <div className="message-content">
                {msg.isFunctionCall && (
                  <div className="function-call-indicator">
                    ⚙️ {msg.content}
                  </div>
                )}
                {msg.isError && (
                  <div className="error-message">
                    ❌ {msg.content}
                  </div>
                )}
                {!msg.isFunctionCall && !msg.isError && (
                  <div className="message-text">
                    {msg.content.split('\n').map((line, i) => (
                      <React.Fragment key={i}>
                        {line}
                        {i < msg.content.split('\n').length - 1 && <br />}
                      </React.Fragment>
                    ))}
                  </div>
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
              <h3>📄 Generated Document</h3>
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
            placeholder="Type your message..."
            disabled={isLoading}
            className="chat-input"
          />
          <button 
            type="submit" 
            disabled={isLoading || !input.trim()}
            className="send-button"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

export default App;

