#!/usr/bin/env python3
"""
Desktop Butler - Main Backend Service
Handles data collection, processing, and scheduling
"""

import sqlite3
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import arxiv
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pytz

# Set up working directory
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(WORK_DIR)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE
# ============================================================================

class Database:
    """SQLite database manager"""

    def __init__(self, db_path: str = "papers.db"):
        self.db_path = db_path
        self.init_schema()

    def init_schema(self):
        """Create database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT NOT NULL,
                abstract TEXT,
                published_date TEXT,
                retrieved_date TEXT,
                pdf_url TEXT,
                source_url TEXT,
                categories TEXT,
                source_type TEXT DEFAULT 'arxiv',
                relevance_score REAL DEFAULT 0.5
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Database schema initialized")

    def insert_paper(self, paper: Dict) -> bool:
        """Insert or update a paper"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO papers
                (id, title, authors, abstract, published_date, retrieved_date,
                 pdf_url, source_url, categories, source_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                paper['id'],
                paper['title'],
                json.dumps(paper.get('authors', [])),
                paper.get('abstract', '')[:500],
                paper.get('published_date', ''),
                paper.get('retrieved_date', datetime.utcnow().isoformat()),
                paper.get('pdf_url', ''),
                paper.get('source_url', ''),
                json.dumps(paper.get('categories', [])),
                'arxiv'
            ))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error inserting paper: {e}")
            return False

    def get_recent_papers(self, limit: int = 20) -> List[Dict]:
        """Get most recent papers"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, title, authors, published_date, pdf_url, relevance_score
            FROM papers
            ORDER BY published_date DESC
            LIMIT ?
        ''', (limit,))

        papers = []
        for row in cursor.fetchall():
            papers.append({
                'id': row[0],
                'title': row[1],
                'authors': json.loads(row[2]),
                'published_date': row[3],
                'pdf_url': row[4],
                'relevance_score': row[5] if row[5] else 0.5
            })

        conn.close()
        return papers

# ============================================================================
# ARXIV COLLECTOR
# ============================================================================

class ArxivCollector:
    """Collect papers from arXiv"""

    RESEARCH_CATEGORIES = {
        "portfolio_management": {
            "query": "cat:q-fin.PR",
            "name": "Portfolio & Risk Management",
        },
        "ml_statistics": {
            "query": "cat:stat.ML",
            "name": "Machine Learning",
        },
        "deep_learning": {
            "query": "cat:cs.LG",
            "name": "Deep Learning",
        },
    }

    def __init__(self, db: Database):
        self.db = db
        self.client = arxiv.Client(page_size=10, delay_seconds=1)

    def collect_briefing(self) -> Dict:
        """Collect papers for a briefing"""
        logger.info("Starting briefing collection")

        briefing = {
            "collected_at": datetime.utcnow().isoformat(),
            "categories": {},
            "total_papers": 0
        }

        for category_key, category_info in self.RESEARCH_CATEGORIES.items():
            logger.info(f"Collecting {category_info['name']}...")
            
            try:
                search = arxiv.Search(
                    query=category_info['query'],
                    max_results=5,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending
                )

                papers = []
                for result in self.client.results(search):
                    paper = {
                        'id': result.entry_id.split('/abs/')[-1],
                        'title': result.title,
                        'authors': [author.name for author in result.authors][:3],
                        'abstract': result.summary[:200],
                        'published_date': result.published.isoformat(),
                        'pdf_url': result.pdf_url,
                        'source_url': result.entry_id,
                        'categories': result.categories,
                        'retrieved_date': datetime.utcnow().isoformat()
                    }

                    if self.db.insert_paper(paper):
                        papers.append(paper)

                briefing['categories'][category_key] = {
                    'name': category_info['name'],
                    'papers': len(papers),
                }
                briefing['total_papers'] += len(papers)
                
            except Exception as e:
                logger.error(f"Error collecting {category_key}: {e}")

        logger.info(f"Briefing complete: {briefing['total_papers']} papers collected")
        return briefing

# ============================================================================
# API
# ============================================================================

app = FastAPI(title="Desktop Butler API", version="0.1.0")

# Initialize services
db = Database("papers.db")
collector = ArxivCollector(db)

class PaperResponse(BaseModel):
    id: str
    title: str
    authors: List[str]
    published_date: str
    pdf_url: str
    relevance_score: float

@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "operational"
    }

@app.get("/papers/recent")
async def get_recent_papers(limit: int = 20):
    """Get most recent papers"""
    papers = db.get_recent_papers(limit)
    return papers

@app.post("/briefing/run")
async def run_briefing():
    """Manually trigger a briefing"""
    try:
        result = collector.collect_briefing()
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Briefing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 Starting Desktop Butler Backend...")
    logger.info("🌐 Starting API server on http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
