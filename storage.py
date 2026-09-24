"""SQLite persistence for analysis runs, signals, and paper orders."""
from __future__ import annotations
import json, sqlite3, threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

class Store:
    def __init__(self, path):
        self.path=str(path); self._lock=threading.RLock(); Path(self.path).parent.mkdir(parents=True,exist_ok=True); self._init_db()
    def _connect(self):
        c=sqlite3.connect(self.path,timeout=30,check_same_thread=False); c.row_factory=sqlite3.Row; return c
    def _init_db(self):
        with self._connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS analysis_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,finished_at TEXT,symbols_total INTEGER,symbols_ok INTEGER,signals_found INTEGER,errors INTEGER,details_json TEXT); CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT,signal_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,symbol TEXT NOT NULL,timeframe TEXT NOT NULL,direction TEXT NOT NULL,entry REAL,sl REAL,tp REAL,rrr REAL,htf_trend TEXT,source_candle TEXT,status TEXT DEFAULT 'NEW',chart_path TEXT,telegram_status TEXT,order_id TEXT,pnl REAL,details_json TEXT); CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,signal_key TEXT,created_at TEXT NOT NULL,broker TEXT,symbol TEXT,side TEXT,quantity REAL,status TEXT,order_json TEXT); CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY AUTOINCREMENT,signal_key TEXT,created_at TEXT NOT NULL,symbol TEXT,side TEXT,entry_price REAL,quantity REAL,sl REAL,tp REAL,entry_fee REAL,status TEXT,exit_price REAL,exit_reason TEXT,pnl REAL,closed_at TEXT); CREATE TABLE IF NOT EXISTS daily_risk(day TEXT PRIMARY KEY,realized_pnl REAL NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS app_state(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);''')
    def _now(self): return datetime.now(timezone.utc).isoformat()
    @contextmanager
    def _tx(self):
        with self._lock:
            c=self._connect()
            try:
                with c:
                    yield c
            finally:
                c.close()
    def start_run(self,total):
        with self._tx() as c: return int(c.execute('INSERT INTO analysis_runs(started_at,symbols_total) VALUES (?,?)',(self._now(),total)).lastrowid)
    def finish_run(self,run_id,ok,found,errors,details=None):
        with self._tx() as c: c.execute('UPDATE analysis_runs SET finished_at=?,symbols_ok=?,signals_found=?,errors=?,details_json=? WHERE id=?',(self._now(),ok,found,errors,json.dumps(details or {}),run_id))
    @staticmethod
    def make_signal_key(symbol,timeframe,direction,candle): return f'{symbol}|{timeframe}|{direction}|{candle}'
    def insert_signal(self,s):
        v=(s['signal_key'],s.get('created_at',self._now()),s['symbol'],s.get('timeframe',''),s['signal'],s.get('entry'),s.get('sl'),s.get('tp'),s.get('rrr'),s.get('htf_trend'),s.get('source_candle'),s.get('chart_path'),json.dumps(s,default=str))
        with self._tx() as c: return c.execute('INSERT OR IGNORE INTO signals(signal_key,created_at,symbol,timeframe,direction,entry,sl,tp,rrr,htf_trend,source_candle,chart_path,details_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',v).rowcount==1
    def update_signal(self,key,**vals):
        vals={k:v for k,v in vals.items() if k in {'status','chart_path','telegram_status','order_id','pnl'}}
        if vals:
            with self._tx() as c: c.execute('UPDATE signals SET '+','.join(f'{k}=?' for k in vals)+' WHERE signal_key=?',(*vals.values(),key))
    def insert_order(self,order,signal_key=None):
        with self._tx() as c: c.execute('INSERT INTO orders(signal_key,created_at,broker,symbol,side,quantity,status,order_json) VALUES (?,?,?,?,?,?,?,?)',(signal_key,self._now(),order.get('mode','PAPER'),order.get('symbol'),order.get('side'),order.get('qty'),order.get('status'),json.dumps(order,default=str)))
    def recent_signals(self,limit=50):
        with self._tx() as c: return [dict(r) for r in c.execute('SELECT * FROM signals ORDER BY created_at DESC LIMIT ?',(limit,))]
    def recent_runs(self,limit=20):
        with self._tx() as c: return [dict(r) for r in c.execute('SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT ?',(limit,)).fetchall()]
    def open_position(self, signal, side, entry_price, quantity, sl, tp, entry_fee, reason):
        with self._tx() as c:
            cur=c.execute("INSERT INTO positions(signal_key,created_at,symbol,side,entry_price,quantity,sl,tp,entry_fee,status) VALUES (?,?,?,?,?,?,?,?,?,'OPEN')",(signal.get('signal_key'),self._now(),signal['symbol'],side,entry_price,quantity,sl,tp,entry_fee)); return {'id':int(cur.lastrowid),'signal_key':signal.get('signal_key'),'symbol':signal['symbol'],'side':side,'entry_price':entry_price,'quantity':quantity,'sl':sl,'tp':tp,'status':'OPEN'}
    def get_position(self, position_id):
        with self._tx() as c:
            r=c.execute('SELECT * FROM positions WHERE id=?',(position_id,)).fetchone(); return dict(r) if r else None
    def open_positions(self):
        with self._tx() as c: return [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='OPEN' ORDER BY id")]
    def open_positions_count(self):
        with self._tx() as c: return c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
    def close_position(self, position_id, exit_price, pnl, reason):
        with self._tx() as c:
            position=c.execute("SELECT signal_key FROM positions WHERE id=? AND status='OPEN'",(position_id,)).fetchone()
            if not position: return None
            c.execute("UPDATE positions SET status='CLOSED',exit_price=?,exit_reason=?,pnl=?,closed_at=? WHERE id=?",(exit_price,reason,pnl,self._now(),position_id))
            c.execute("INSERT INTO daily_risk(day,realized_pnl) VALUES(date('now'),?) ON CONFLICT(day) DO UPDATE SET realized_pnl=realized_pnl+excluded.realized_pnl",(pnl,))
            if position['signal_key']:
                c.execute("UPDATE signals SET status='PAPER_CLOSED',pnl=? WHERE signal_key=?",(pnl,position['signal_key']))
            r=c.execute('SELECT * FROM positions WHERE id=?',(position_id,)).fetchone()
            return dict(r) if r else None
    def daily_realized_pnl(self):
        with self._tx() as c:
            r=c.execute("SELECT realized_pnl FROM daily_risk WHERE day=date('now')").fetchone(); return float(r[0]) if r else 0.0
    def set_state(self,key,value):
        with self._tx() as c:
            c.execute('INSERT INTO app_state(key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',(key,str(value),self._now()))
    def get_state(self,key,default=None):
        with self._tx() as c:
            r=c.execute('SELECT value FROM app_state WHERE key=?',(key,)).fetchone(); return r[0] if r else default
    def recent_positions(self,limit=50):
        with self._tx() as c: return [dict(r) for r in c.execute('SELECT * FROM positions ORDER BY id DESC LIMIT ?',(limit,)).fetchall()]
    def recent_closed_positions(self,limit=50):
        with self._tx() as c: return [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT ?",(limit,)).fetchall()]
    def signals_since(self,since_iso):
        with self._tx() as c: return [dict(r) for r in c.execute('SELECT * FROM signals WHERE created_at>=? ORDER BY created_at DESC',(since_iso,)).fetchall()]
    def runs_since(self,since_iso):
        with self._tx() as c: return [dict(r) for r in c.execute('SELECT * FROM analysis_runs WHERE started_at>=? ORDER BY started_at DESC',(since_iso,)).fetchall()]
    def health(self):
        with self._tx() as c:
            last=c.execute('SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT 1').fetchone()
            day=datetime.now(timezone.utc).date().isoformat()
            daily=c.execute('SELECT realized_pnl FROM daily_risk WHERE day=?',(day,)).fetchone()
            states={r['key']:r['value'] for r in c.execute('SELECT key,value FROM app_state').fetchall()}
            return {'last_run':dict(last) if last else None,'signal_count':c.execute('SELECT COUNT(*) FROM signals').fetchone()[0],'open_positions':c.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0],'daily_pnl':float(daily[0]) if daily else 0.0,'db':self.path,'state':states}
_GLOBAL_STORE=None
def get_store(path=None):
    global _GLOBAL_STORE
    if _GLOBAL_STORE is None:
        from config.settings import DB_PATH
        _GLOBAL_STORE=Store(path or DB_PATH)
    return _GLOBAL_STORE
