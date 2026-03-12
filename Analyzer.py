#!/Projects/Picker/bin/python3

import io
import base64
import sys
import os
sys.path.append('/Projects/Picker/code/python_modules')

import sqlite3
import json

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from flask import Flask, request, render_template

app = Flask(__name__)

DB_PATH  = '/Projects/Picker/code/historical.db'
INFO_DIR = '/Projects/Picker/code/data'


def format_large_number(n):
    if n is None:
        return 'N/A'
    try:
        n = float(n)
        if n >= 1_000_000_000_000:
            return f'${n / 1_000_000_000_000:.2f}T'
        elif n >= 1_000_000_000:
            return f'${n / 1_000_000_000:.2f}B'
        elif n >= 1_000_000:
            return f'${n / 1_000_000:.2f}M'
        else:
            return f'${n:,.0f}'
    except (TypeError, ValueError):
        return 'N/A'


def format_volume(n):
    if n is None:
        return 'N/A'
    try:
        n = float(n)
        if n >= 1_000_000_000:
            return f'{n / 1_000_000_000:.2f}B'
        elif n >= 1_000_000:
            return f'{n / 1_000_000:.2f}M'
        elif n >= 1_000:
            return f'{n / 1_000:.2f}K'
        else:
            return f'{n:,.0f}'
    except (TypeError, ValueError):
        return 'N/A'


def safe_val(val, fmt='{:.2f}'):
    try:
        if val is None:
            return 'N/A'
        return fmt.format(float(val))
    except (TypeError, ValueError):
        return 'N/A'


@app.route('/', methods=['GET', 'POST'])
def index():
    ticker = request.form.get('ticker', '').strip().upper()
    if not ticker:
        ticker = request.args.get('ticker', default=None, type=str)
    chart_b64 = None
    fundamentals = None
    error = None

    if ticker:
        try:
            # --- Load historical price data from SQLite ---
            conn = sqlite3.connect(DB_PATH)
            hist = pd.read_sql_query(
                    "select date,close from (SELECT date, close FROM historical WHERE ticker = ? ORDER BY date DESC limit 275) order by date ASC",
                conn,
                params=(ticker,),
            )
            conn.close()

            # --- Load fundamentals from local JSON ---
            info_path = os.path.join(INFO_DIR, f'{ticker}_info.json')
            if os.path.exists(info_path):
                with open(info_path) as f:
                    info = json.load(f)
            else:
                info = {}

            longName = info.get('longName', ticker)

            if hist.empty:
                error = f'No data found for ticker "{ticker}". Please check the symbol and try again.'
            else:
                hist['date']  = pd.to_datetime(hist['date'])
                hist['close'] = hist['close'].astype(float)
                hist = hist.set_index('date')

                # --- Moving averages ---
                hist['SMA150'] = hist['close'].rolling(window=150).mean()
                hist['SMA50']  = hist['close'].rolling(window=50).mean()
                hist['EMA21']  = hist['close'].ewm(span=21, adjust=False).mean()
                hist['SMA15']  = hist['close'].rolling(window=15).mean()

                # --- Chart ---
                fig, ax = plt.subplots(figsize=(12, 5))
                fig.patch.set_facecolor('#1a1a2e')
                ax.set_facecolor('#16213e')

                ax.plot(hist.index, hist['close'],  label='Price',    color='#e0e0e0', linewidth=1.5, zorder=5)
                ax.plot(hist.index, hist['SMA150'], label='SMA 150',  color='#e74c3c', linewidth=1.2, linestyle='--')
                ax.plot(hist.index, hist['SMA50'],  label='SMA 50',   color='#f39c12', linewidth=1.2, linestyle='--')
                ax.plot(hist.index, hist['EMA21'],  label='EMA 21',   color='#2ecc71', linewidth=1.2, linestyle='-.')
                ax.plot(hist.index, hist['SMA15'],  label='SMA 15',   color='#3498db', linewidth=1.2, linestyle='-.')

                ax.set_title(f'{longName} ({ticker}) — Price Chart', color='#e0e0e0', fontsize=14, pad=12)
                ax.set_xlabel('Date', color='#aaaaaa')
                ax.set_ylabel('Price (USD)', color='#aaaaaa')
                ax.tick_params(colors='#aaaaaa')
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
                ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
                plt.xticks(rotation=30, ha='right')
                for spine in ax.spines.values():
                    spine.set_edgecolor('#444466')
                ax.grid(color='#2a2a4a', linestyle='--', linewidth=0.5)
                ax.legend(facecolor='#1a1a2e', edgecolor='#444466', labelcolor='#e0e0e0', fontsize=9)

                plt.tight_layout()

                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=120, facecolor=fig.get_facecolor())
                plt.close(fig)
                buf.seek(0)
                chart_b64 = base64.b64encode(buf.read()).decode('utf-8')

                # --- Fundamentals ---
                current_price = info.get('currentPrice') or info.get('regularMarketPrice') or hist['close'].iloc[-1]
                fundamentals = {
                    'Name':                info.get('longName'),
                    'Ticker':              info.get('symbol'),
                    'Beta':                safe_val(info.get('beta')),
                    'Current Price':       f'${safe_val(current_price)}',
                    'Trailing P/E':        safe_val(info.get('trailingPE')),
                    'Forward P/E':         safe_val(info.get('forwardPE')),
                    'Trailing P/S':        safe_val(info.get('priceToSalesTrailing12Months')),
                    '52w Range':           info.get('fiftyTwoWeekRange'),
                    '52w Chg PCT':         safe_val(info.get('fiftyTwoWeekHighChangePercent')),
                    'Avg Target Price':    safe_val(info.get('targetMeanPrice')),
                    'Recommendation':      info.get('recommendationKey'),
                    'EPS (TTM)':           f'${safe_val(info.get("trailingEps"))}',
                    'Market Cap':          format_large_number(info.get('marketCap')),
                    '90-Day Avg Volume':   format_volume(info.get('averageVolume90Day') or info.get('averageVolume')),
                }

        except Exception as e:
            error = f'Error fetching data for "{ticker}": {str(e)}'

    return render_template(
        'index.html',
        ticker=ticker,
        chart_b64=chart_b64,
        fundamentals=fundamentals,
        error=error,
    )
