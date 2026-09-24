"""Local paper broker with deterministic fills, positions, and exits."""
from __future__ import annotations
from typing import Any, Dict, Optional
from storage import get_store

class RiskError(Exception):
    """Raised when a simulated order violates a portfolio limit."""

class PaperBroker:
    def __init__(self, fee_pct=0.0, slippage_pct=0.0, max_open_positions=5):
        self.fee_pct=max(0.0,float(fee_pct)); self.slippage_pct=max(0.0,float(slippage_pct)); self.max_open_positions=max(0,int(max_open_positions)); self.store=get_store()
    def _fill_price(self, side, price):
        if not price or float(price)<=0: raise RiskError('INVALID_PRICE')
        direction=1 if str(side).upper() in ('BUY','LONG') else -1
        return float(price)*(1+direction*self.slippage_pct/100.0)
    def open_position(self, signal: Dict[str, Any], quantity: float, reason='SIGNAL') -> Dict[str, Any]:
        if self.store.open_positions_count() >= self.max_open_positions: raise RiskError('MAX_OPEN_POSITIONS')
        side='BUY' if str(signal.get('signal','')).upper()=='BUY' else 'SELL'; quantity=float(quantity); entry=float(signal['entry']); sl=signal.get('sl'); tp=signal.get('tp')
        if side not in ('BUY','SELL') or quantity<=0: raise RiskError('INVALID_ORDER')
        if sl is None or tp is None or (side=='BUY' and not sl<entry<tp) or (side=='SELL' and not tp<entry<sl): raise RiskError('INVALID_SL_TP')
        fill=self._fill_price(side,entry); fee=abs(fill*quantity)*self.fee_pct/100
        return self.store.open_position(signal,side,fill,quantity,sl,tp,fee,reason)
    def mark_and_close(self, position_id:int, current_price:float, reason='MANUAL')->Optional[Dict[str,Any]]:
        p=self.store.get_position(position_id)
        if not p or p['status']!='OPEN': return None
        exit_price=self._fill_price(p['side'],current_price); direction=1 if p['side']=='BUY' else -1
        gross=(exit_price-p['entry_price'])*p['quantity']*direction; exit_fee=abs(exit_price*p['quantity'])*self.fee_pct/100
        return self.store.close_position(position_id,exit_price,gross-float(p['entry_fee'] or 0)-exit_fee,reason)
    def check_exit(self, current_prices:Dict[str,float])->list:
        closed=[]
        for p in self.store.open_positions():
            price=current_prices.get(p['symbol']); sl,tp=p['sl'],p['tp']
            if price is None: continue
            hit_sl=sl is not None and ((p['side']=='BUY' and price<=sl) or (p['side']=='SELL' and price>=sl)); hit_tp=tp is not None and ((p['side']=='BUY' and price>=tp) or (p['side']=='SELL' and price<=tp))
            if hit_sl or hit_tp:
                result=self.mark_and_close(p['id'],sl if hit_sl else tp,'STOP_LOSS' if hit_sl else 'TAKE_PROFIT')
                if result: closed.append(result)
        return closed
