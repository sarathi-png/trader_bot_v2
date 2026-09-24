"""Minimal, disabled-by-default OpenAlgo REST client for later Analyzer Mode."""
from __future__ import annotations
import os, requests
from typing import Any, Dict
class OpenAlgoClient:
    def __init__(self, base_url=None, api_key=None, enabled=None, timeout=10):
        self.base_url=(base_url or os.getenv('OPENALGO_URL','')).rstrip('/'); self.api_key=api_key or os.getenv('OPENALGO_API_KEY',''); self.enabled=enabled if enabled is not None else os.getenv('OPENALGO_ENABLED','false').lower()=='true'; self.timeout=timeout
    def health(self):
        if not self.enabled: return {'enabled':False,'status':'DISABLED'}
        if not self.base_url or not self.api_key: raise RuntimeError('OpenAlgo enabled but URL/API key missing')
        r=requests.get(self.base_url+'/api/v1/health',headers=self._headers(),timeout=self.timeout); r.raise_for_status(); return r.json()
    def place_order(self, payload: Dict[str, Any]):
        if not self.enabled: raise RuntimeError('OpenAlgo is disabled; use EXECUTION_MODE=PAPER')
        if not self.base_url or not self.api_key: raise RuntimeError('OPENALGO_URL and OPENALGO_API_KEY are required')
        r=requests.post(self.base_url+'/api/v1/placeorder',json=payload,headers=self._headers(),timeout=self.timeout); r.raise_for_status(); return r.json()
    def _headers(self): return {'X-API-KEY':self.api_key,'Content-Type':'application/json'}
