from flask import Flask, request, render_template, redirect, url_for, flash
from forex_python.converter import CurrencyRates
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
import os

from db import get_connection, init_db

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev'

# Ensure database exists
if not Path(__file__).with_name('portfolio.db').exists():
    init_db()


@app.route('/')
def portfolio_summary():
    conn = get_connection()
    trades = conn.execute('SELECT * FROM trades ORDER BY date').fetchall()
    conn.close()

    tickers = {}
    for tr in trades:
        ticker = tr['ticker']
        tickers.setdefault(ticker, []).append(tr)

    c = CurrencyRates()
    fx = c.get_rate('USD', 'AUD')

    positions = []
    for symbol, ts in tickers.items():
        shares = 0
        cash = 0.0
        for t in ts:
            qty = int(t['quantity'])
            price = float(t['price'])
            if t['trade_type'] in ('SELL_PUT', 'SELL_CALL'):
                cash += price * qty * (100 if t['trade_type'] in ('SELL_PUT','SELL_CALL','BUY_PUT','BUY_CALL') else 1)
            elif t['trade_type'] in ('BUY_PUT', 'BUY_CALL'):
                cash -= price * qty * 100
            elif t['trade_type'] == 'BUY_STOCK':
                shares += qty
                cash -= price * qty
            elif t['trade_type'] == 'SELL_STOCK':
                shares -= qty
                cash += price * qty
        cost_basis = (-cash / shares) if shares else 0
        latest = 0
        if shares:
            data = yf.Ticker(symbol).history(period='1d')
            if not data.empty:
                latest = float(data['Close'][-1])
        unrealized = (latest - cost_basis) * shares if shares else 0
        positions.append({
            'ticker': symbol,
            'shares': shares,
            'cost_basis_usd': round(cost_basis, 2) if shares else None,
            'cost_basis_aud': round(cost_basis * fx, 2) if shares else None,
            'unrealized_usd': round(unrealized, 2) if shares else None,
            'unrealized_aud': round(unrealized * fx, 2) if shares else None,
            'realized_usd': round(cash, 2) if not shares else None,
            'realized_aud': round(cash * fx, 2) if not shares else None
        })

    # Generate performance chart
    generate_performance_chart(trades)

    return render_template('portfolio.html', positions=positions, fx=fx)


@app.route('/add_trade', methods=['GET', 'POST'])
def add_trade():
    if request.method == 'POST':
        data = {
            'date': request.form['date'],
            'ticker': request.form['ticker'].upper(),
            'trade_type': request.form['trade_type'],
            'quantity': int(request.form['quantity']),
            'price': float(request.form['price']),
            'option_type': request.form.get('option_type'),
            'strike': request.form.get('strike'),
            'expiration': request.form.get('expiration'),
        }
        c = CurrencyRates()
        fx = c.get_rate('USD', 'AUD', datetime.strptime(data['date'], '%Y-%m-%d'))
        conn = get_connection()
        conn.execute(
            'INSERT INTO trades (date, ticker, trade_type, quantity, price, option_type, strike, expiration, fx_rate) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                data['date'], data['ticker'], data['trade_type'], data['quantity'],
                data['price'], data['option_type'], data['strike'], data['expiration'], fx
            )
        )
        conn.commit()
        conn.close()
        flash('Trade added')
        return redirect(url_for('portfolio_summary'))
    return render_template('add_trade.html')


def generate_performance_chart(trades):
    if not trades:
        return
    start = datetime.strptime(trades[0]['date'], '%Y-%m-%d')
    tickers = sorted(set(t['ticker'] for t in trades))
    end = datetime.today()
    dates = []
    portfolio_values = []
    cash = 0.0
    shares = {t:0 for t in tickers}

    all_days = yf.download(tickers, start=start, end=end)['Close']
    sp500 = yf.download('^GSPC', start=start, end=end)['Close']
    sp_start = sp500.iloc[0]

    for day in all_days.index:
        # apply trades for the day
        day_str = day.strftime('%Y-%m-%d')
        for tr in [t for t in trades if t['date'] == day_str]:
            qty = int(tr['quantity'])
            price = float(tr['price'])
            if tr['trade_type'] in ('SELL_PUT', 'SELL_CALL'):
                cash += price * qty * 100
            elif tr['trade_type'] in ('BUY_PUT', 'BUY_CALL'):
                cash -= price * qty * 100
            elif tr['trade_type'] == 'BUY_STOCK':
                shares[tr['ticker']] += qty
                cash -= price * qty
            elif tr['trade_type'] == 'SELL_STOCK':
                shares[tr['ticker']] -= qty
                cash += price * qty
        # compute portfolio value
        value = cash
        for sym, num in shares.items():
            if num and sym in all_days.columns:
                value += all_days.loc[day, sym] * num
        dates.append(day)
        portfolio_values.append(value)
    sp_values = sp500 / sp_start * portfolio_values[0] if portfolio_values else []
    plt.figure(figsize=(6,4))
    plt.plot(dates, portfolio_values, label='Portfolio')
    if len(sp_values) == len(dates):
        plt.plot(dates, sp_values, label='S&P 500')
    plt.legend()
    plt.tight_layout()
    static_dir = Path(__file__).resolve().parent / 'static'
    os.makedirs(static_dir, exist_ok=True)
    plt.savefig(static_dir / 'performance.png')
    plt.close()


if __name__ == '__main__':
    app.run(debug=True)
