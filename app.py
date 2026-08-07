import streamlit as st
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime
import smtplib
from email.message import EmailMessage
import json
import time



# =========================================================
# CONFIGURATION
# =========================================================

TICKER_FILE = "tickers.txt"
STATE_FILE = "earnings_alert_state.json"

# Only alert on earnings within this many calendar days
DAYS_AHEAD = 10


# =========================================================
# STREAMLIT CONFIG
# =========================================================

st.set_page_config(
    page_title="Earnings Alert Monitor",
    layout="wide"
)

st.title("Earnings Alert Monitor")

st.caption(
    f"Automatically checks for earnings occurring "
    f"within the next {DAYS_AHEAD} days."
)


# =========================================================
# EMAIL CONFIGURATION
#
# Streamlit Secrets:
#
# [gmail]
# address = "yourgmail@gmail.com"
# app_password = "xxxx xxxx xxxx xxxx"
# alert_email = "destination@email.com"
# =========================================================

try:
    GMAIL_ADDRESS = st.secrets["gmail"]["address"]
    GMAIL_APP_PASSWORD = st.secrets["gmail"]["app_password"]
    ALERT_EMAIL = st.secrets["gmail"]["alert_email"]

    EMAIL_CONFIGURED = True

except Exception:
    GMAIL_ADDRESS = ""
    GMAIL_APP_PASSWORD = ""
    ALERT_EMAIL = ""

    EMAIL_CONFIGURED = False


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
# LOAD ALERT STATE
# =========================================================

def load_alert_state():

    path = Path(STATE_FILE)

    if not path.exists():
        return {}

    try:
        with open(path, "r") as f:
            return json.load(f)

    except Exception:
        return {}


# =========================================================
# SAVE ALERT STATE
# =========================================================

def save_alert_state(state):

    try:
        with open(STATE_FILE, "w") as f:

            json.dump(
                state,
                f,
                indent=4
            )

    except Exception as e:
        st.warning(
            f"Could not save alert state: {e}"
        )


# =========================================================
# SEND EMAIL
# =========================================================

def send_email(subject, body):

    if not EMAIL_CONFIGURED:
        return False, "Gmail configuration missing."

    try:

        msg = EmailMessage()

        msg["From"] = GMAIL_ADDRESS
        msg["To"] = ALERT_EMAIL
        msg["Subject"] = subject

        msg.set_content(body)

        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465
        ) as smtp:

            smtp.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            smtp.send_message(msg)

        return True, None

    except Exception as e:
        return False, str(e)


# =========================================================
# CLEAN / NORMALIZE DATE
# =========================================================

def clean_date(value):

    if value is None:
        return None

    try:

        if isinstance(
            value,
            (list, tuple)
        ):

            if not value:
                return None

            value = value[0]

        date = pd.Timestamp(value)

        if date.tzinfo is not None:
            date = date.tz_localize(None)

        return date

    except Exception:
        return None


# =========================================================
# METHOD 1:
# GET EARNINGS DATE FROM YAHOO CALENDAR
# =========================================================

def get_date_from_calendar(stock):

    try:

        calendar = stock.calendar

        if calendar is None:
            return None

        # -------------------------------------------------
        # Newer yfinance versions may return dict
        # -------------------------------------------------

        if isinstance(calendar, dict):

            for key in [
                "Earnings Date",
                "EarningsDate",
                "earningsDate"
            ]:

                if key in calendar:

                    date = clean_date(
                        calendar[key]
                    )

                    if date is not None:
                        return date

        # -------------------------------------------------
        # Other versions may return DataFrame
        # -------------------------------------------------

        if isinstance(
            calendar,
            pd.DataFrame
        ):

            for key in [
                "Earnings Date",
                "EarningsDate"
            ]:

                if key in calendar.index:

                    value = (
                        calendar
                        .loc[key]
                        .iloc[0]
                    )

                    date = clean_date(
                        value
                    )

                    if date is not None:
                        return date

            for key in [
                "Earnings Date",
                "EarningsDate"
            ]:

                if key in calendar.columns:

                    value = (
                        calendar[key]
                        .iloc[0]
                    )

                    date = clean_date(
                        value
                    )

                    if date is not None:
                        return date

    except Exception:
        pass

    return None


# =========================================================
# METHOD 2:
# GET EARNINGS DATE FROM EARNINGS HISTORY
# =========================================================

def get_date_from_earnings_history(stock):

    try:

        earnings = stock.get_earnings_dates(
            limit=12
        )

        if (
            earnings is None
            or earnings.empty
        ):
            return None

        today = pd.Timestamp.now().normalize()

        future_dates = []

        for value in earnings.index:

            date = clean_date(
                value
            )

            if date is None:
                continue

            if date.normalize() >= today:

                future_dates.append(
                    date
                )

        if future_dates:
            return min(future_dates)

    except Exception:
        pass

    return None


# =========================================================
# METHOD 3:
# GET DATE FROM YAHOO QUOTE METADATA
# =========================================================

def get_date_from_info(stock):

    try:

        info = stock.info

        timestamp = (
            info.get(
                "earningsTimestamp"
            )
            or info.get(
                "earningsTimestampStart"
            )
        )

        if timestamp:

            date = pd.to_datetime(
                timestamp,
                unit="s"
            )

            return clean_date(
                date
            )

    except Exception:
        pass

    return None


# =========================================================
# MAIN EARNINGS LOOKUP
# =========================================================

def get_next_earnings_date(ticker):

    stock = yf.Ticker(ticker)

    # Method 1
    date = get_date_from_calendar(
        stock
    )

    if date is not None:

        return (
            date,
            "Yahoo Calendar"
        )

    # Method 2
    date = get_date_from_earnings_history(
        stock
    )

    if date is not None:

        return (
            date,
            "Yahoo Earnings Dates"
        )

    # Method 3
    date = get_date_from_info(
        stock
    )

    if date is not None:

        return (
            date,
            "Yahoo Quote Metadata"
        )

    return None, "Not Found"


# =========================================================
# SEND EARNINGS ALERT
# =========================================================

def send_earnings_alert(
    ticker,
    earnings_date,
    days_until,
    source
):

    formatted_date = (
        earnings_date.strftime(
            "%A, %B %d, %Y"
        )
    )

    subject = (
        f"{ticker} Earnings in "
        f"{days_until} Days - "
        f"{formatted_date}"
    )

    body = f"""
UPCOMING EARNINGS ALERT

Ticker:
{ticker}

Earnings Date:
{formatted_date}

Days Until Earnings:
{days_until}

Data Source:
{source}

Checked:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

This alert was generated automatically by the
Earnings Alert Monitor.
"""

    return send_email(
        subject,
        body
    )


# =========================================================
# SCAN EARNINGS
# =========================================================

def scan_earnings(
    tickers,
    days_ahead,
    send_alerts=True
):

    today = pd.Timestamp.now().normalize()

    end_date = (
        today
        + pd.Timedelta(
            days=days_ahead
        )
    )

    results = []
    failures = []
    new_alerts = []

    state = load_alert_state()

    progress_bar = st.progress(0)
    status = st.empty()

    total = len(tickers)

    for i, ticker in enumerate(tickers):

        status.text(
            f"Checking {ticker} "
            f"({i + 1} of {total})..."
        )

        try:

            earnings_date, source = (
                get_next_earnings_date(
                    ticker
                )
            )

            # ---------------------------------------------
            # No earnings date found
            # ---------------------------------------------

            if earnings_date is None:

                failures.append(
                    {
                        "Ticker": ticker,
                        "Reason":
                            "No earnings date returned"
                    }
                )

            else:

                earnings_day = (
                    earnings_date.normalize()
                )

                days_until = (
                    earnings_day - today
                ).days

                # -----------------------------------------
                # Only care about earnings occurring
                # within the next DAYS_AHEAD days
                # -----------------------------------------

                if (
                    today
                    <= earnings_day
                    <= end_date
                ):

                    results.append(
                        {
                            "Ticker":
                                ticker,

                            "Earnings Date":
                                earnings_date,

                            "Days Away":
                                days_until,

                            "Source":
                                source
                        }
                    )

                    # -------------------------------------
                    # Unique alert key
                    # -------------------------------------

                    date_string = (
                        earnings_day.strftime(
                            "%Y-%m-%d"
                        )
                    )

                    alert_key = (
                        f"{ticker}_{date_string}"
                    )

                    # -------------------------------------
                    # Send only once for this ticker/date
                    # -------------------------------------

                    if (
                        send_alerts
                        and alert_key
                        not in state
                    ):

                        success, error = (
                            send_earnings_alert(
                                ticker,
                                earnings_date,
                                days_until,
                                source
                            )
                        )

                        if success:

                            state[alert_key] = {
                                "ticker":
                                    ticker,

                                "earnings_date":
                                    date_string,

                                "source":
                                    source,

                                "days_until":
                                    days_until,

                                "alert_sent":
                                    datetime.now()
                                    .isoformat()
                            }

                            save_alert_state(
                                state
                            )

                            new_alerts.append(
                                ticker
                            )

                        else:

                            st.warning(
                                f"Email failed "
                                f"for {ticker}: "
                                f"{error}"
                            )

        except Exception as e:

            failures.append(
                {
                    "Ticker": ticker,
                    "Reason": str(e)
                }
            )

        progress_bar.progress(
            (i + 1) / total
        )

        # Helps reduce Yahoo throttling
        time.sleep(0.15)

    progress_bar.empty()
    status.empty()

    return (
        pd.DataFrame(results),
        pd.DataFrame(failures),
        new_alerts
    )


# =========================================================
# SIDEBAR STATUS
# =========================================================

st.sidebar.header(
    "Monitor Status"
)

st.sidebar.metric(
    "Alert Window",
    f"{DAYS_AHEAD} Days"
)


# =========================================================
# EMAIL STATUS
# =========================================================

if EMAIL_CONFIGURED:

    st.sidebar.success(
        "Gmail configured"
    )

    st.sidebar.caption(
        f"Alerts → {ALERT_EMAIL}"
    )

else:

    st.sidebar.error(
        "Gmail not configured"
    )


# =========================================================
# LOAD TICKERS
# =========================================================

tickers = load_tickers(
    TICKER_FILE
)

if not tickers:

    st.error(
        f"No tickers found in "
        f"{TICKER_FILE}."
    )

    st.stop()


st.sidebar.metric(
    "Tickers Loaded",
    len(tickers)
)


with st.sidebar.expander(
    "View Tickers"
):

    st.write(
        ", ".join(tickers)
    )


# =========================================================
# TEST SINGLE TICKER
# =========================================================

st.sidebar.divider()

st.sidebar.subheader(
    "Test Earnings Lookup"
)

test_ticker = (
    st.sidebar.text_input(
        "Ticker",
        value="NVDA"
    )
    .strip()
    .upper()
)


if st.sidebar.button(
    "Test Ticker"
):

    date, source = (
        get_next_earnings_date(
            test_ticker
        )
    )

    if date:

        st.sidebar.success(
            f"{test_ticker}: "
            f"{date.strftime('%b %d, %Y')}"
        )

        st.sidebar.caption(
            f"Source: {source}"
        )

    else:

        st.sidebar.error(
            f"No earnings date "
            f"found for {test_ticker}"
        )


# =========================================================
# AUTOMATIC DAILY SCAN
#
# This runs whenever the Streamlit app is loaded/woken.
# A scheduler such as GitHub Actions should wake the
# application once each day.
# =========================================================

st.subheader(
    "Today's Earnings Scan"
)

st.info(
    f"Checking {len(tickers)} tickers for "
    f"earnings occurring within the next "
    f"{DAYS_AHEAD} days."
)

scan_started = datetime.now()

df, failures, new_alerts = (
    scan_earnings(
        tickers,
        DAYS_AHEAD,
        send_alerts=True
    )
)

scan_finished = datetime.now()


# =========================================================
# SCAN STATUS
# =========================================================

st.caption(
    "Last scan: "
    + scan_finished.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
)


# =========================================================
# ALERT SUMMARY
# =========================================================

if new_alerts:

    st.success(
        f"Sent {len(new_alerts)} "
        f"new earnings alert(s): "
        + ", ".join(new_alerts)
    )

else:

    st.info(
        "No new email alerts were required."
    )


# =========================================================
# UPCOMING EARNINGS RESULTS
# =========================================================

if df.empty:

    st.warning(
        f"No earnings found within "
        f"the next {DAYS_AHEAD} days."
    )

else:

    df = (
        df.sort_values(
            by=[
                "Earnings Date",
                "Ticker"
            ]
        )
        .reset_index(
            drop=True
        )
    )

    display_df = df.copy()

    display_df[
        "Earnings Date"
    ] = (
        pd.to_datetime(
            display_df[
                "Earnings Date"
            ]
        )
        .dt.strftime(
            "%a %b %d, %Y"
        )
    )

    st.subheader(
        "Upcoming Earnings"
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Upcoming Earnings",
        len(display_df)
    )

    c2.metric(
        "Alert Window",
        f"{DAYS_AHEAD} Days"
    )

    c3.metric(
        "New Alerts Sent",
        len(new_alerts)
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    csv = (
        display_df
        .to_csv(
            index=False
        )
        .encode("utf-8")
    )

    st.download_button(
        label="Download CSV",
        data=csv,
        file_name=
            "upcoming_earnings.csv",
        mime="text/csv"
    )


# =========================================================
# FAILED / UNKNOWN TICKERS
# =========================================================

if not failures.empty:

    with st.expander(
        f"No Earnings Date Found "
        f"({len(failures)})"
    ):

        st.dataframe(
            failures,
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# EMAIL ALERT HISTORY
# =========================================================

st.divider()

with st.expander(
    "Email Alert History"
):

    state = load_alert_state()

    if not state:

        st.write(
            "No earnings alerts "
            "have been sent yet."
        )

    else:

        history = []

        for value in state.values():

            history.append(
                {
                    "Ticker":
                        value.get(
                            "ticker"
                        ),

                    "Earnings Date":
                        value.get(
                            "earnings_date"
                        ),

                    "Days Away When Sent":
                        value.get(
                            "days_until"
                        ),

                    "Source":
                        value.get(
                            "source"
                        ),

                    "Alert Sent":
                        value.get(
                            "alert_sent"
                        )
                }
            )

        history_df = (
            pd.DataFrame(
                history
            )
            .sort_values(
                "Alert Sent",
                ascending=False
            )
        )

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True
        )
```
