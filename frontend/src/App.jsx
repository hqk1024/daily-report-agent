import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';

const DEFAULT_QUERY = '生成一份关于 Pilbara 锂矿的研报';

export default function App() {
  const [query, setQuery] = useState('');
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const generateReport = async (q) => {
    setLoading(true);
    setError('');
    setReport(null);
    try {
      const res = await fetch('/api/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      });
      const data = await res.json();
      if (data.success) {
        setReport(data.report);
      } else {
        setError(data.error || 'Failed to generate report');
      }
    } catch (e) {
      setError(e.message || 'Network error');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const q = query.trim() || DEFAULT_QUERY;
    generateReport(q);
  };

  return (
    <div className="app">
      <header className="header">
        <h1>Daily Research Report Agent</h1>
        <p className="subtitle">基于 MCP 协议的智能研报生成系统</p>
      </header>

      <form className="query-form" onSubmit={handleSubmit}>
        <input
          className="query-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={DEFAULT_QUERY}
        />
        <button className="submit-btn" type="submit" disabled={loading}>
          {loading ? 'Generating...' : 'Generate Report'}
        </button>
      </form>

      <div className="status-bar">
        <span className="status-dot" />
        <span>Agent Status: Running &mdash; 3 MCP Servers Connected</span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading && (
        <div className="loading">
          <div className="spinner" />
          <p>Gathering intelligence from MCP servers...</p>
        </div>
      )}

      {report && (
        <div className="report-container">
          <div className="report-toolbar">
            <span className="report-meta">
              Generated{' '}
              {new Date(report.generated_at).toLocaleString('zh-CN')}
            </span>
            <button
              className="download-btn"
              onClick={() => {
                const blob = new Blob([report.markdown], {
                  type: 'text/markdown',
                });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `report-${report.company}-${report.generated_at.slice(0, 10)}.md`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              Download .md
            </button>
          </div>
          <div className="report-content">
            <ReactMarkdown
              components={{
                h1: ({ children }) => <h1 className="report-h1">{children}</h1>,
                h2: ({ children }) => <h2 className="report-h2">{children}</h2>,
                h3: ({ children }) => <h3 className="report-h3">{children}</h3>,
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                ),
                table: ({ children }) => (
                  <div className="table-wrap">
                    <table>{children}</table>
                  </div>
                ),
              }}
            >
              {report.markdown}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
