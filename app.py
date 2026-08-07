```python
import streamlit as st
import yfinance as yf
import pandas as pd
from pathlib import Path

# =========================================================
# CONFIG
# =========================================================

TICKER_FILE = "tickers.txt"

st.set_page_config(
    page_title="Upcoming Earnings Scanner",
    layout="wide"
)

st.title("Upcoming Earnings Scanner")

# =========================================================
# LOAD TICKERS
# =========================================================

@st.cache_data
def load_tickers(filename):
    path = Path(filename)

    if not path.exists():
        return []

    with open(path, "r") as f:
        tickers = [
            line.strip().upper()
            for line in f
            if line.strip()
        ]

    # Remove duplicates while preserving order
    return list(dict.fromkeys(tickers))


# =========================================================
# GET EARNINGS
# =========================================================

def get_upcoming_earnings(tickers, days_ahead):

    today = pd.Timestamp.now().normalize()
    end_date = today + pd.Timedelta(days=days_ahead)

    results = []

    progress_bar = st.progress(0)
    status = st.empty()

    total = len(tickers)

    for i, ticker in enumerate(tickers):

        status.text(
            f"Checking {ticker} "
            f"({i + 1} of {total})..."
        )

        try:
            stock = yf.Ticker(ticker)

            earnings = stock.get_earnings_dates(limit=12)

            if earnings is not None and not earnings.empty:

                for earnings_date in earnings.index:

                    earnings_date = pd.Timestamp(
                        earnings_date
                    )

                    # Remove timezone
                    if earnings_date.tzinfo is not None:
                        earnings_date = (
                            earnings_date.tz_localize(None)
                        )

                    earnings_day = (
                        earnings_date.normalize()
                    )

                    if today <= earnings_day <= end_date:

                        days_until = (
                            earnings_day - today
                        ).days

                        results.append({
                            "Ticker": ticker,
                            "Earnings Date": earnings_date,
                            "Days Away": days_until
                        })

                        break

        except Exception as e:
            # Skip bad tickers instead of crashing app
            pass

        progress_bar.progress(
            (i + 1) / total
        )

    progress_bar.empty()
    status.empty()

    return pd.DataFrame(results)


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.header("Scanner Settings")

days_ahead = st.sidebar.selectbox(
    "Upcoming earnings period",
    options=[
        3,
        7,
        14,
        30,
        60,
        90
    ],
    index=1
)


# =========================================================
# LOAD TICKERS
# =========================================================

tickers = load_tickers(TICKER_FILE)

if not tickers:

    st.error(
        f"No tickers found in {TICKER_FILE}. "
        "Make sure the file exists in the same "
        "directory as app.py."
    )

    st.stop()


st.sidebar.metric(
    "Tickers Loaded",
    len(tickers)
)


# Optional ticker preview

with st.sidebar.expander("View Tickers"):

    st.write(
        ", ".join(tickers)
    )


# =========================================================
# RUN SCANNER
# =========================================================

if st.button(
    "Scan Upcoming Earnings",
    type="primary"
):

    with st.spinner(
        "Retrieving earnings dates..."
    ):

        df = get_upcoming_earnings(
            tickers,
            days_ahead
        )


    # =====================================================
    # RESULTS
    # =====================================================

    if df.empty:

        st.warning(
            f"No earnings found in the next "
            f"{days_ahead} days."
        )

    else:

        df = df.sort_values(
            by=[
                "Earnings Date",
                "Ticker"
            ]
        ).reset_index(drop=True)

        # Keep actual datetime internally
        df["Date"] = (
            pd.to_datetime(
                df["Earnings Date"]
            )
            .dt.strftime(
                "%a %b %d, %Y"
            )
        )

        display_df = df[
            [
                "Ticker",
                "Date",
                "Days Away"
            ]
        ].rename(
            columns={
                "Date": "Earnings Date"
            }
        )

        st.success(
            f"Found {len(display_df)} companies "
            f"with earnings in the next "
            f"{days_ahead} days."
        )

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )


        # =============================================
        # DOWNLOAD CSV
        # =============================================

        csv = display_df.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            label="Download Results as CSV",
            data=csv,
            file_name="upcoming_earnings.csv",
            mime="text/csv"
        )
```
