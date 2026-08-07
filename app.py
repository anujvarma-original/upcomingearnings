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

DEFAULT_DAYS_AHEAD = 90


# =========================================================
# STREAMLIT CONFIG
# =========================================================

st.set_page_config(
    page_title="Earnings Alert Monitor",
    layout="wide"
)

st.title("Earnings Alert Monitor")


# =========================================================
# EMAIL CONFIGURATION
#
# Values come from .streamlit/secrets.toml
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
# SEND GMAIL
# =========================================================

def send_email(subject, body):

    if not EMAIL_CONFIGURED:

        return False, "Email configuration missing."

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
# SEND EARNINGS ALERT
# =========================================================

def send_earnings_alert(
    ticker,
    earnings_date,
    days_until
):

    formatted_date = earnings_date.strftime(
        "%A, %B %d, %Y"
    )

    subject = (
        f"Earnings Alert: {ticker} - "
        f"{formatted_date}"
    )

    body = f"""
Upcoming Earnings Announcement

Ticker: {ticker}

Earnings Date:
{formatted_date}

Days Away:
{days_until}

Detected:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

This alert was generated automatically by the
Earnings Alert Monitor.
"""

    return send_email(
        subject,
        body
    )


# =========================================================
# GET UPCOMING EARNINGS
# =========================================================

def get_upcoming_earnings(
    tickers,
    days_ahead,
    send_alerts=True
):

    today = pd.Timestamp.now().normalize()

    end_date = (
        today +
        pd.Timedelta(days=days_ahead)
    )

    results = []

    state = load_alert_state()

    progress_bar = st.progress(0)
    status = st.empty()

    total = len(tickers)

    new_alerts = []

    for i, ticker in enumerate(tickers):

        status.text(
            f"Checking {ticker} "
            f"({i + 1} of {total})..."
        )

        try:

            stock = yf.Ticker(ticker)

            earnings = stock.get_earnings_dates(
                limit=12
            )

            if (
                earnings is not None
                and not earnings.empty
            ):

                for earnings_date in earnings.index:

                    earnings_date = pd.Timestamp(
                        earnings_date
                    )

                    # Remove timezone
                    if earnings_date.tzinfo is not None:

                        earnings_date = (
                            earnings_date
                            .tz_localize(None)
                        )

                    earnings_day = (
                        earnings_date.normalize()
                    )

                    if (
                        today
                        <= earnings_day
                        <= end_date
                    ):

                        days_until = (
                            earnings_day - today
                        ).days

                        # ---------------------------------
                        # Pull additional earnings info
                        # ---------------------------------

                        row = earnings.loc[
                            earnings.index[
                                earnings.index.get_loc(
                                    earnings_date,
                                    method="nearest"
                                )
                            ]
                        ] if False else None

                        results.append({
                            "Ticker": ticker,
                            "Earnings Date": earnings_date,
                            "Days Away": days_until
                        })


                        # =================================
                        # ALERT KEY
                        #
                        # Each ticker/date pair is unique.
                        # =================================

                        date_string = (
                            earnings_day
                            .strftime("%Y-%m-%d")
                        )

                        alert_key = (
                            f"{ticker}_{date_string}"
                        )


                        # =================================
                        # NEW EARNINGS ALERT
                        # =================================

                        if (
                            send_alerts
                            and alert_key not in state
                        ):

                            success, error = (
                                send_earnings_alert(
                                    ticker,
                                    earnings_date,
                                    days_until
                                )
                            )

                            if success:

                                state[alert_key] = {
                                    "ticker": ticker,
                                    "earnings_date":
                                        date_string,
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
                                    f"Email alert failed "
                                    f"for {ticker}: "
                                    f"{error}"
                                )

                        # Only use next earnings date
                        break

        except Exception as e:

            # Don't crash entire scanner
            print(
                f"Error retrieving "
                f"{ticker}: {e}"
            )


        # =============================================
        # UPDATE PROGRESS
        # =============================================

        progress_bar.progress(
            (i + 1) / total
        )


        # Small pause helps avoid Yahoo throttling
        time.sleep(0.1)


    progress_bar.empty()
    status.empty()

    return (
        pd.DataFrame(results),
        new_alerts
    )


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.header(
    "Scanner Settings"
)


days_ahead = st.sidebar.selectbox(
    "Upcoming earnings period",
    options=[
        7,
        14,
        30,
        60,
        90,
        120
    ],
    index=4
)


send_alerts = st.sidebar.checkbox(
    "Send email alerts",
    value=True
)


# =========================================================
# EMAIL STATUS
# =========================================================

if EMAIL_CONFIGURED:

    st.sidebar.success(
        "Gmail alerts configured"
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
# RUN SCANNER
# =========================================================

if st.button(
    "Scan Earnings",
    type="primary"
):

    df, new_alerts = (
        get_upcoming_earnings(
            tickers,
            days_ahead,
            send_alerts
        )
    )


    # =====================================================
    # EMAIL ALERT SUMMARY
    # =====================================================

    if new_alerts:

        st.success(
            f"Sent {len(new_alerts)} "
            f"new earnings alerts."
        )

        st.write(
            "Alerts sent for:",
            ", ".join(new_alerts)
        )


    # =====================================================
    # RESULTS
    # =====================================================

    if df.empty:

        st.warning(
            f"No earnings found "
            f"in the next "
            f"{days_ahead} days."
        )

    else:

        df = df.sort_values(
            by=[
                "Earnings Date",
                "Ticker"
            ]
        ).reset_index(
            drop=True
        )


        # ---------------------------------------------
        # Display date
        # ---------------------------------------------

        display_df = df.copy()

        display_df["Earnings Date"] = (
            pd.to_datetime(
                display_df[
                    "Earnings Date"
                ]
            )
            .dt.strftime(
                "%a %b %d, %Y"
            )
        )


        # ---------------------------------------------
        # Summary
        # ---------------------------------------------

        st.subheader(
            "Upcoming Earnings"
        )

        st.metric(
            "Upcoming Earnings",
            len(display_df)
        )


        # ---------------------------------------------
        # Table
        # ---------------------------------------------

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )


        # ---------------------------------------------
        # CSV Download
        # ---------------------------------------------

        csv = (
            display_df
            .to_csv(index=False)
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
# ALERT HISTORY
# =========================================================

st.divider()

with st.expander(
    "Email Alert History"
):

    alert_state = (
        load_alert_state()
    )

    if not alert_state:

        st.write(
            "No earnings alerts "
            "have been sent yet."
        )

    else:

        history = []

        for key, value in (
            alert_state.items()
        ):

            history.append({
                "Ticker":
                    value.get(
                        "ticker"
                    ),

                "Earnings Date":
                    value.get(
                        "earnings_date"
                    ),

                "Alert Sent":
                    value.get(
                        "alert_sent"
                    )
            })

        history_df = pd.DataFrame(
            history
        )

        history_df = (
            history_df
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
