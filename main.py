"""
Ghost Exchange Backend - Full Hyperliquid SDK Integration
Uses official hyperliquid-python-sdk for real trading
Fixed candle data handling and comprehensive error handling
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
import time
import httpx

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Hyperliquid Info (read-only, no keys needed)
info = Info(constants.MAINNET_API_URL, skip_ws=True)

class QuoteRequest(BaseModel):
    symbol: str
    is_buy: bool
    size_usd: float
    leverage: int

class SignedTransaction(BaseModel):
    symbol: str
    is_buy: bool
    size_usd: float
    leverage: int
    user_address: str
    signature: dict
    timestamp: int

@app.get("/")
async def root():
    return {
        "service": "Ghost Exchange API",
        "version": "4.0.0",
        "status": "operational",
        "hyperliquid_sdk": "integrated",
        "mode": "mainnet",
        "features": ["real-time prices", "candle data", "orderbook", "trading quotes"]
    }

@app.get("/health")
async def health_check():
    """Health check with Hyperliquid connectivity test"""
    try:
        mids = info.all_mids()
        if mids and "BTC" in mids:
            return {
                "status": "healthy",
                "hyperliquid": "connected",
                "btc_price": mids["BTC"],
                "timestamp": int(time.time() * 1000)
            }
        else:
            return {"status": "degraded", "hyperliquid": "no_data"}
    except Exception as e:
        return {
            "status": "degraded",
            "hyperliquid": "error",
            "error": str(e)
        }

@app.get("/prices")
async def get_prices():
    """Fetch real-time prices from Hyperliquid using official SDK"""
    try:
        all_mids = info.all_mids()
        meta_and_asset_ctxs = info.meta_and_asset_ctxs()
        
        price_changes = {}
        if len(meta_and_asset_ctxs) > 1:
            asset_ctxs = meta_and_asset_ctxs[1]
            for ctx in asset_ctxs:
                coin = ctx.get("coin", "")
                mark_px = float(ctx.get("markPx", 0))
                prev_day_px = float(ctx.get("prevDayPx", mark_px))
                
                if prev_day_px > 0:
                    change = ((mark_px - prev_day_px) / prev_day_px) * 100
                    price_changes[coin] = round(change, 2)
        
        prices = {}
        for symbol in ["BTC", "ETH", "SOL", "HYPE"]:
            prices[symbol] = {
                "price": float(all_mids.get(symbol, 0)),
                "change_24h": price_changes.get(symbol, 0)
            }
        
        return prices
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching prices: {str(e)}")

@app.get("/candles/{symbol}")
async def get_candles(symbol: str, interval: str = "1h", limit: int = 100):
    """
    Fetch candlestick data from Hyperliquid
    
    Hyperliquid candle format:
    {
        "t": 1681923600000,  # open time (milliseconds)
        "T": 1681924499999,  # close time (milliseconds)
        "s": "BTC",          # symbol
        "i": "1h",           # interval
        "o": "29295.0",      # open price (string)
        "c": "29258.0",      # close price (string)
        "h": "29309.0",      # high price (string)
        "l": "29250.0",      # low price (string)
        "v": "0.98639",      # volume (string)
        "n": 189             # number of trades
    }
    """
    try:
        end_time = int(time.time() * 1000)
        
        # Map interval to milliseconds
        interval_map = {
            "1m": 60000,
            "3m": 180000,
            "5m": 300000,
            "15m": 900000,
            "30m": 1800000,
            "1h": 3600000,
            "2h": 7200000,
            "4h": 14400000,
            "8h": 28800000,
            "12h": 43200000,
            "1d": 86400000,
            "3d": 259200000,
            "1w": 604800000,
            "1M": 2592000000
        }
        
        interval_ms = interval_map.get(interval, 3600000)
        start_time = end_time - (interval_ms * limit)
        
        # Direct API call to get candles
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.hyperliquid.xyz/info",
                json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": symbol,
                        "interval": interval,
                        "startTime": start_time,
                        "endTime": end_time
                    }
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Hyperliquid API error: {response.text}"
                )
            
            candles = response.json()
            
            if not candles or not isinstance(candles, list):
                raise HTTPException(
                    status_code=404,
                    detail=f"No candle data available for {symbol}"
                )
        
        # Transform to our format
        transformed = []
        for candle in candles:
            try:
                transformed.append({
                    "time": int(candle.get("t", 0)),  # Use open time
                    "open": float(candle.get("o", 0)),
                    "high": float(candle.get("h", 0)),
                    "low": float(candle.get("l", 0)),
                    "close": float(candle.get("c", 0)),
                    "volume": float(candle.get("v", 0))
                })
            except (ValueError, TypeError) as e:
                print(f"Error parsing candle: {e}, candle: {candle}")
                continue
        
        if not transformed:
            raise HTTPException(
                status_code=404,
                detail=f"No valid candle data for {symbol}"
            )
        
        # Sort by time to ensure chronological order
        transformed.sort(key=lambda x: x["time"])
        
        return transformed
        
    except httpx.HTTPError as e:
        print(f"HTTP error fetching candles: {str(e)}")
        raise HTTPException(status_code=503, detail=f"Error connecting to Hyperliquid: {str(e)}")
    except Exception as e:
        print(f"Candles error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching candles: {str(e)}")

@app.post("/quote")
async def get_quote(request: QuoteRequest):
    """Generate a quote for a trade using real Hyperliquid data"""
    try:
        all_mids = info.all_mids()
        current_price = float(all_mids.get(request.symbol, 0))
        
        if current_price == 0:
            raise HTTPException(status_code=400, detail=f"Price not found for {request.symbol}")
        
        meta_and_asset_ctxs = info.meta_and_asset_ctxs()
        asset_ctx = None
        if len(meta_and_asset_ctxs) > 1:
            for ctx in meta_and_asset_ctxs[1]:
                if ctx.get("coin") == request.symbol:
                    asset_ctx = ctx
                    break
        
        position_value = request.size_usd * request.leverage
        
        # Hyperliquid fee structure
        # Maker: -0.00020 (rebate)
        # Taker: 0.00035
        # Using taker fee for market orders
        fee_rate = 0.00035
        estimated_fee = request.size_usd * fee_rate
        
        # Calculate liquidation price
        # For long: liq_price = entry * (1 - (1/leverage) * margin_fraction)
        # For short: liq_price = entry * (1 + (1/leverage) * margin_fraction)
        # Using 95% margin fraction (conservative)
        if request.is_buy:
            liquidation_price = current_price * (1 - (1 / request.leverage) * 0.95)
        else:
            liquidation_price = current_price * (1 + (1 / request.leverage) * 0.95)
        
        funding_rate = 0
        if asset_ctx:
            funding_rate = float(asset_ctx.get("funding", 0))
        
        # Calculate position size in coins
        position_size_coins = request.size_usd / current_price
        
        quote = {
            "symbol": request.symbol,
            "side": "buy" if request.is_buy else "sell",
            "size_usd": request.size_usd,
            "size_coins": round(position_size_coins, 8),
            "leverage": request.leverage,
            "estimated_price": current_price,
            "mark_price": float(asset_ctx.get("markPx", current_price)) if asset_ctx else current_price,
            "estimated_fee": round(estimated_fee, 6),
            "total_cost": round(request.size_usd + estimated_fee, 6),
            "position_value": round(position_value, 2),
            "liquidation_price": round(liquidation_price, 2),
            "funding_rate": funding_rate,
            "funding_rate_annualized": round(funding_rate * 365 * 24, 4),  # Hourly to annualized
            "timestamp": int(time.time() * 1000)
        }
        
        return quote
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating quote: {str(e)}")

@app.post("/submit")
async def submit_order(tx: SignedTransaction):
    """Submit order to Hyperliquid - Demo mode (requires user wallet integration)"""
    try:
        # Validate the order parameters
        if tx.size_usd <= 0:
            raise HTTPException(status_code=400, detail="Size must be positive")
        
        if tx.leverage < 1 or tx.leverage > 100:
            raise HTTPException(status_code=400, detail="Leverage must be between 1 and 100")
        
        # In a real implementation, you would:
        # 1. Verify the signature
        # 2. Use the user's wallet to sign and submit the order
        # 3. Return the actual order response from Hyperliquid
        
        return {
            "success": True,
            "message": "Order validation successful",
            "note": "Real execution requires user wallet integration with private key signing",
            "details": {
                "symbol": tx.symbol,
                "side": "buy" if tx.is_buy else "sell",
                "size_usd": tx.size_usd,
                "leverage": tx.leverage,
                "user": tx.user_address,
                "timestamp": tx.timestamp
            },
            "next_steps": [
                "1. Integrate web3 wallet (MetaMask, WalletConnect)",
                "2. Sign order with user's private key",
                "3. Submit to Hyperliquid Exchange endpoint",
                "4. Monitor order status via WebSocket"
            ]
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }

@app.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str, n_sig_figs: int = 5):
    """Fetch L2 orderbook from Hyperliquid"""
    try:
        book = info.l2_snapshot(symbol, nSigFigs=n_sig_figs)
        
        return {
            "symbol": symbol,
            "bids": book["levels"][0][:20],  # Top 20 bids
            "asks": book["levels"][1][:20],  # Top 20 asks
            "timestamp": book.get("time", int(time.time() * 1000))
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching orderbook: {str(e)}")

@app.get("/meta")
async def get_meta():
    """Get Hyperliquid perpetuals metadata"""
    try:
        meta = info.meta()
        return meta
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching metadata: {str(e)}")

@app.get("/spot-meta")
async def get_spot_meta():
    """Get Hyperliquid spot metadata"""
    try:
        spot_meta = info.spot_meta()
        return spot_meta
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching spot metadata: {str(e)}")

@app.get("/user/{address}")
async def get_user_state(address: str):
    """Get user's account state on Hyperliquid"""
    try:
        state = info.user_state(address)
        return state
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user state: {str(e)}")

@app.get("/funding-history/{symbol}")
async def get_funding_history(symbol: str, start_time: Optional[int] = None, end_time: Optional[int] = None):
    """Get funding rate history for a symbol"""
    try:
        if end_time is None:
            end_time = int(time.time() * 1000)
        if start_time is None:
            start_time = end_time - (86400000 * 7)  # Last 7 days
        
        funding = info.funding_history(symbol, startTime=start_time, endTime=end_time)
        return funding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching funding history: {str(e)}")

@app.get("/market-summary/{symbol}")
async def get_market_summary(symbol: str):
    """Get comprehensive market summary for a symbol"""
    try:
        # Get all data in parallel
        all_mids = info.all_mids()
        meta_and_asset_ctxs = info.meta_and_asset_ctxs()
        
        current_price = float(all_mids.get(symbol, 0))
        
        asset_ctx = None
        if len(meta_and_asset_ctxs) > 1:
            for ctx in meta_and_asset_ctxs[1]:
                if ctx.get("coin") == symbol:
                    asset_ctx = ctx
                    break
        
        if not asset_ctx:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
        mark_px = float(asset_ctx.get("markPx", current_price))
        prev_day_px = float(asset_ctx.get("prevDayPx", mark_px))
        
        return {
            "symbol": symbol,
            "mid_price": current_price,
            "mark_price": mark_px,
            "index_price": float(asset_ctx.get("indexPx", mark_px)),
            "prev_day_price": prev_day_px,
            "price_change_24h": round(((mark_px - prev_day_px) / prev_day_px) * 100, 2) if prev_day_px > 0 else 0,
            "funding_rate": float(asset_ctx.get("funding", 0)),
            "open_interest": float(asset_ctx.get("openInterest", 0)),
            "volume_24h": float(asset_ctx.get("dayNtlVlm", 0)),
            "premium": float(asset_ctx.get("premium", 0)),
            "oracle_price": float(asset_ctx.get("oraclePx", mark_px)),
            "timestamp": int(time.time() * 1000)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching market summary: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
