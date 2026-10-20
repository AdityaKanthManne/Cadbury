import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './ButlerApp.css';

// Types
interface Paper {
  id: string;
  title: string;
  authors: string[];
  published_date: string;
  pdf_url: string;
  relevance_score: number;
}

interface BriefingData {
  total_papers: number;
  categories: Record<string, any>;
  collected_at: string;
}

interface ButlerState {
  isIdle: boolean;
  isReading: boolean;
  isAlert: boolean;
  expression: 'neutral' | 'happy' | 'focused' | 'thinking';
}

// Main App Component
const ButlerApp: React.FC = () => {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [butlerState, setButlerState] = useState<ButlerState>({
    isIdle: true,
    isReading: false,
    isAlert: false,
    expression: 'neutral'
  });
  const [loading, setLoading] = useState(false);
  const [schedulerRunning, setSchedulerRunning] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');

  const API_URL = 'http://localhost:8000';

  // Fetch recent papers
  const fetchPapers = async (category?: string) => {
    setLoading(true);
    setButlerState(prev => ({ ...prev, isReading: true, expression: 'focused' }));

    try {
      const endpoint = category && category !== 'all' 
        ? `${API_URL}/papers/category/${category}`
        : `${API_URL}/papers/recent`;
      
      const response = await axios.get<Paper[]>(endpoint, { params: { limit: 20 } });
      setPapers(response.data);
      setButlerState(prev => ({ ...prev, expression: 'happy' }));
    } catch (error) {
      console.error('Error fetching papers:', error);
      setButlerState(prev => ({ ...prev, expression: 'neutral' }));
    } finally {
      setLoading(false);
      setTimeout(() => {
        setButlerState(prev => ({ ...prev, isReading: false }));
      }, 2000);
    }
  };

  // Run briefing manually
  const runBriefingNow = async () => {
    setLoading(true);
    setButlerState(prev => ({ ...prev, isAlert: true, expression: 'thinking' }));
    
    try {
      await axios.post(`${API_URL}/briefing/run`);
      // Refetch papers after briefing
      await fetchPapers();
      setButlerState(prev => ({ ...prev, isAlert: false }));
    } catch (error) {
      console.error('Error running briefing:', error);
    } finally {
      setLoading(false);
    }
  };

  // Start/Stop scheduler
  const toggleScheduler = async () => {
    try {
      const endpoint = schedulerRunning ? '/schedule/stop' : '/schedule/start';
      await axios.post(`${API_URL}${endpoint}`);
      setSchedulerRunning(!schedulerRunning);
      setButlerState(prev => ({ 
        ...prev, 
        expression: schedulerRunning ? 'neutral' : 'happy' 
      }));
    } catch (error) {
      console.error('Error toggling scheduler:', error);
    }
  };

  // Load papers on mount
  useEffect(() => {
    fetchPapers();
    // Check scheduler status
    const checkScheduler = async () => {
      try {
        const response = await axios.get(`${API_URL}/health`);
        setSchedulerRunning(response.status === 200);
      } catch {
        setSchedulerRunning(false);
      }
    };
    checkScheduler();
  }, []);

  const categories = [
    { key: 'all', name: 'All Papers', emoji: '📚' },
    { key: 'portfolio_management', name: 'Portfolio Management', emoji: '💼' },
    { key: 'computational_finance', name: 'Computational Finance', emoji: '💻' },
    { key: 'ml_statistics', name: 'Machine Learning', emoji: '🤖' },
    { key: 'deep_learning', name: 'Deep Learning', emoji: '🧠' },
    { key: 'trading', name: 'Trading', emoji: '📈' }
  ];

  return (
    <div className="butler-app">
      {/* Animated Butler */}
      <div className="butler-container">
        <Butler state={butlerState} />
        <div className="butler-status">
          <p className="status-text">
            {butlerState.isReading && "📖 Reading papers..."}
            {butlerState.isAlert && "🔔 Briefing in progress..."}
            {butlerState.isIdle && !loading && "✨ Ready"}
            {loading && "⏳ Processing..."}
          </p>
        </div>
      </div>

      {/* Dashboard */}
      <div className="dashboard">
        {/* Controls */}
        <div className="controls">
          <button 
            onClick={runBriefingNow}
            disabled={loading}
            className="btn btn-primary"
          >
            🎯 Run Briefing Now
          </button>
          
          <button 
            onClick={toggleScheduler}
            className={`btn ${schedulerRunning ? 'btn-danger' : 'btn-success'}`}
          >
            {schedulerRunning ? '⏹️ Stop Scheduler' : '▶️ Start Scheduler'}
          </button>

          <div className="scheduler-info">
            {schedulerRunning ? (
              <span className="badge badge-success">Scheduler Active (8 AM & 8 PM)</span>
            ) : (
              <span className="badge badge-danger">Scheduler Inactive</span>
            )}
          </div>
        </div>

        {/* Category Tabs */}
        <div className="category-tabs">
          {categories.map(cat => (
            <button
              key={cat.key}
              onClick={() => {
                setSelectedCategory(cat.key);
                fetchPapers(cat.key === 'all' ? undefined : cat.key);
              }}
              className={`tab ${selectedCategory === cat.key ? 'active' : ''}`}
            >
              {cat.emoji} {cat.name}
            </button>
          ))}
        </div>

        {/* Papers List */}
        <div className="papers-container">
          {loading && <div className="loading">Loading papers...</div>}
          
          {!loading && papers.length === 0 && (
            <div className="empty-state">
              <p>📭 No papers found. Run a briefing to get started!</p>
            </div>
          )}

          {!loading && papers.length > 0 && (
            <div className="papers-list">
              <h3>📄 {papers.length} Papers Found</h3>
              {papers.map(paper => (
                <div
                  key={paper.id}
                  className={`paper-card ${selectedPaper?.id === paper.id ? 'selected' : ''}`}
                  onClick={() => setSelectedPaper(paper)}
                >
                  <div className="paper-header">
                    <h4>{paper.title}</h4>
                    <span className="relevance-badge">
                      ⭐ {(paper.relevance_score * 100).toFixed(0)}%
                    </span>
                  </div>
                  
                  <div className="paper-meta">
                    <p className="authors">
                      👤 {paper.authors.slice(0, 2).join(', ')}
                      {paper.authors.length > 2 && ` +${paper.authors.length - 2}`}
                    </p>
                    <p className="date">📅 {new Date(paper.published_date).toLocaleDateString()}</p>
                  </div>

                  <div className="paper-actions">
                    <a href={paper.pdf_url} target="_blank" rel="noopener noreferrer" className="link">
                      📖 Read PDF
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Paper Detail View */}
        {selectedPaper && (
          <div className="paper-detail">
            <div className="detail-header">
              <h2>{selectedPaper.title}</h2>
              <button 
                onClick={() => setSelectedPaper(null)}
                className="btn-close"
              >
                ✕
              </button>
            </div>
            
            <div className="detail-content">
              <h4>Authors</h4>
              <p>{selectedPaper.authors.join(', ')}</p>
              
              <h4>Published</h4>
              <p>{new Date(selectedPaper.published_date).toLocaleDateString()}</p>
              
              <h4>Relevance Score</h4>
              <div className="score-bar">
                <div 
                  className="score-fill"
                  style={{ width: `${selectedPaper.relevance_score * 100}%` }}
                />
              </div>
              
              <h4>PDF</h4>
              <a href={selectedPaper.pdf_url} target="_blank" rel="noopener noreferrer" className="link">
                🔗 {selectedPaper.pdf_url}
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Animated Butler Component
interface ButlerProps {
  state: ButlerState;
}

const Butler: React.FC<ButlerProps> = ({ state }) => {
  const getExpression = () => {
    switch (state.expression) {
      case 'happy':
        return '😊';
      case 'focused':
        return '🎯';
      case 'thinking':
        return '🤔';
      default:
        return '😐';
    }
  };

  const getAnimation = () => {
    if (state.isReading) return 'reading';
    if (state.isAlert) return 'alert';
    return 'idle';
  };

  return (
    <div className={`butler-character ${getAnimation()}`}>
      <div className="butler-head">
        <div className="expression">{getExpression()}</div>
      </div>
      <div className="butler-body">
        <div className="butler-torso" />
        <div className="butler-arms">
          <div className="arm arm-left" />
          <div className="arm arm-right" />
        </div>
        <div className="butler-legs">
          <div className="leg leg-left" />
          <div className="leg leg-right" />
        </div>
      </div>
    </div>
  );
};

export default ButlerApp;
