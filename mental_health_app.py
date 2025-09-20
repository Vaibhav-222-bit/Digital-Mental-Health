# mental_health_app.py
import streamlit as st
import sqlite3
import pandas as pd
import altair as alt
import os
import datetime
import json
import random
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken

# Optional OpenAI usage (only if OPENAI_API_KEY set)
USE_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
if USE_OPENAI:
    import openai

# ---------- CONFIG ----------
DB_PATH = "mental_platform.db"
FERNET_KEY = os.getenv("FERNET_KEY")  # optional — base64 key from Fernet.generate_key()
MOD_PASSWORD = os.getenv("MOD_PASSWORD", "modpass123")  # Change in deployment
EMERGENCY_HELPLINE = """Please reach out for immediate help. You are not alone.\n\n
                📞 National Suicide Prevention Lifeline (India): 9152987821\n\n
                📞 KIRAN Mental Health Helpline: 1800-599-0019\n\n
                If you are in immediate danger, please call your local emergency services."""

# Screening thresholds (PHQ-9)
PHQ9_THRESHOLDS = {
    "none_mild": range(0, 10),
    "moderate": range(10, 15),
    "moderately_severe": range(15, 20),
    "severe": range(20, 100)
}
# GAD-7 thresholds
GAD7_THRESHOLDS = {
    "none_mild": range(0, 10),
    "moderate": range(10, 15),
    "severe": range(15, 22)
}

# ---------- DATABASE SETUP ----------
def get_db_connection():
    """Establishes connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema."""
    conn = get_db_connection()
    c = conn.cursor()
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')
    # Journal entries
    c.execute('''
        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            entry_text TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Mood tracker
    c.execute('''
        CREATE TABLE IF NOT EXISTS mood_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            mood_score INTEGER, -- e.g., 1-5
            mood_notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Screening results
    c.execute('''
        CREATE TABLE IF NOT EXISTS screening_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            test_type TEXT, -- 'PHQ-9' or 'GAD-7'
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            score INTEGER,
            category TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    # Connect Page Posts
    c.execute('''
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
    conn.commit()
    conn.close()

# Ensure DB is initialized on first run
if not os.path.exists(DB_PATH):
    init_db()

# ---------- AUTHENTICATION HELPERS ----------
def hash_password(password):
    """Hashes a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def signup(username, password):
    """Signs up a new user."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hash_password(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False # Username already exists
    finally:
        conn.close()

def login(username, password):
    """Logs in an existing user."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

# ------------------------
# FEATURE PAGES
# ------------------------

def journal_page():
    st.header("My Private Journal ✍️")
    st.write("Reflect on your thoughts and feelings. This is a safe space for you.")

    entry = st.text_area("New entry:", height=200, key="journal_entry")
    if st.button("Save Entry"):
        if entry:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO journal_entries (user_id, entry_text) VALUES (?, ?)",
                      (st.session_state.user_id, entry))
            conn.commit()
            conn.close()
            st.success("Journal entry saved!")
            st.rerun()
        else:
            st.warning("Please write something before saving.")

    st.subheader("Past Entries")
    conn = get_db_connection()
    entries = pd.read_sql_query("SELECT timestamp, entry_text FROM journal_entries WHERE user_id = ? ORDER BY timestamp DESC", conn, params=[st.session_state.user_id])
    conn.close()

    if entries.empty:
        st.info("You haven't written any journal entries yet.")
    else:
        for index, row in entries.iterrows():
            with st.expander(f"Entry from {row['timestamp']}"):
                st.write(row['entry_text'])

def mood_tracker_page():
    st.header("Mood Tracker 😊😐😟")
    st.write("How are you feeling today?")

    mood_score = st.slider("Rate your mood (1=Very Bad, 5=Very Good):", 1, 5, 3)
    mood_notes = st.text_input("Any specific thoughts? (optional)")

    if st.button("Log Mood"):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO mood_entries (user_id, mood_score, mood_notes) VALUES (?, ?, ?)",
                  (st.session_state.user_id, mood_score, mood_notes))
        conn.commit()
        conn.close()
        st.success("Mood logged successfully!")

    st.subheader("Your Mood History")
    conn = get_db_connection()
    mood_data = pd.read_sql_query("SELECT timestamp, mood_score FROM mood_entries WHERE user_id = ? ORDER BY timestamp ASC", conn, params=[st.session_state.user_id], parse_dates=['timestamp'])
    conn.close()

    if mood_data.empty:
        st.info("No mood data logged yet. Track your mood to see trends here.")
    else:
        chart = alt.Chart(mood_data).mark_line(point=True).encode(
            x=alt.X('timestamp:T', title='Date'),
            y=alt.Y('mood_score:Q', title='Mood Score', scale=alt.Scale(domain=[1, 5])),
            tooltip=['timestamp:T', 'mood_score:Q']
        ).properties(
            title="Your Mood Over Time"
        ).interactive()
        st.altair_chart(chart, use_container_width=True)

def screening_page():
    st.header("Self-Screening Tools 📝")
    st.info("These are not diagnostic tools. They are meant to help you understand your feelings. Please consult a professional for a diagnosis.")

    test = st.selectbox("Choose a screening test:", ["PHQ-9 (Depression)", "GAD-7 (Anxiety)"])

    if test == "PHQ-9 (Depression)":
        questions = [
            "Little interest or pleasure in doing things",
            "Feeling down, depressed, or hopeless",
            "Trouble falling or staying asleep, or sleeping too much",
            "Feeling tired or having little energy",
            "Poor appetite or overeating",
            "Feeling bad about yourself — or that you are a failure or have let yourself or your family down",
            "Trouble concentrating on things, such as reading the newspaper or watching television",
            "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual",
            "Thoughts that you would be better off dead or of hurting yourself in some way"
        ]
        options = ["Not at all", "Several days", "More than half the days", "Nearly every day"]
        scores = {option: i for i, option in enumerate(options)}

        results = []
        for i, q in enumerate(questions):
            answer = st.radio(f"{i+1}. {q}", options, key=f"phq9_{i}")
            results.append(scores[answer])

        if st.button("Calculate My PHQ-9 Score"):
            total_score = sum(results)
            category = "Unknown"
            if total_score in PHQ9_THRESHOLDS["none_mild"]: category = "None to Mild Depression"
            elif total_score in PHQ9_THRESHOLDS["moderate"]: category = "Moderate Depression"
            elif total_score in PHQ9_THRESHOLDS["moderately_severe"]: category = "Moderately Severe Depression"
            elif total_score in PHQ9_THRESHOLDS["severe"]: category = "Severe Depression"

            st.subheader(f"Your score is: {total_score}")
            st.write(f"This suggests: **{category}**")

            # Save result
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO screening_results (user_id, test_type, score, category) VALUES (?, ?, ?, ?)",
                      (st.session_state.user_id, "PHQ-9", total_score, category))
            conn.commit()
            conn.close()

            if total_score >= 10:
                st.warning("Your score indicates you may benefit from talking to a mental health professional.")
                st.info(EMERGENCY_HELPLINE)

    elif test == "GAD-7 (Anxiety)":
        questions = [
            "Feeling nervous, anxious, or on edge",
            "Not being able to stop or control worrying",
            "Worrying too much about different things",
            "Trouble relaxing",
            "Being so restless that it is hard to sit still",
            "Becoming easily annoyed or irritable",
            "Feeling afraid as if something awful might happen"
        ]
        options = ["Not at all", "Several days", "More than half the days", "Nearly every day"]
        scores = {option: i for i, option in enumerate(options)}

        results = []
        for i, q in enumerate(questions):
            answer = st.radio(f"{i+1}. {q}", options, key=f"gad7_{i}")
            results.append(scores[answer])

        if st.button("Calculate My GAD-7 Score"):
            total_score = sum(results)
            category = "Unknown"
            if total_score in GAD7_THRESHOLDS["none_mild"]: category = "None to Mild Anxiety"
            elif total_score in GAD7_THRESHOLDS["moderate"]: category = "Moderate Anxiety"
            elif total_score in GAD7_THRESHOLDS["severe"]: category = "Severe Anxiety"

            st.subheader(f"Your score is: {total_score}")
            st.write(f"This suggests: **{category}**")

            # Save result
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO screening_results (user_id, test_type, score, category) VALUES (?, ?, ?, ?)",
                      (st.session_state.user_id, "GAD-7", total_score, category))
            conn.commit()
            conn.close()

            if total_score >= 10:
                st.warning("Your score indicates you may benefit from talking to a mental health professional.")
                st.info(EMERGENCY_HELPLINE)

def resources_page():
    st.header("Helpful Resources 📚")
    st.write("You are not alone. Here are some resources that can help.")

    st.subheader("Emergency Helplines")
    st.info(EMERGENCY_HELPLINE)

    st.subheader("Articles and Information")
    resources = {
        "Understanding Anxiety": "https://www.nimh.nih.gov/health/topics/anxiety-disorders",
        "Coping with Depression": "https://www.helpguide.org/articles/depression/coping-with-depression.htm",
        "Mindfulness for Beginners": "https://www.mindful.org/meditation/mindfulness-getting-started/",
        "iCALL Psychosocial Helpline": "https://icallhelpline.org/"
    }
    for title, url in resources.items():
        st.markdown(f"- [{title}]({url})")

def chatbot_page():
    st.header("AI Companion Chatbot 🤖")
    st.write("Talk about anything on your mind. I'm here to listen without judgment.")
    st.warning("I am an AI and not a substitute for professional help. Please use the resources page if you are in crisis.", icon="⚠️")

    if not USE_OPENAI:
        st.error("The AI chatbot is currently unavailable. The app owner needs to set an `OPENAI_API_KEY` environment variable.")
        return

    openai.api_key = os.getenv("OPENAI_API_KEY")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": "You are a kind, empathetic, and supportive mental health companion. Your goal is to listen, validate feelings, and provide a safe space. Do not give medical advice. If the user expresses thoughts of self-harm or is in a crisis, gently guide them to the emergency resources provided in the app."}]

    for message in st.session_state.messages:
        if message["role"] != "system":
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    if prompt := st.chat_input("What is on your mind?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            try:
                for response in openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": m["role"], "content": m["content"]} for m in st.session_state.messages],
                    stream=True,
                ):
                    full_response += response.choices[0].delta.get("content", "")
                    message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response)
            except Exception as e:
                full_response = f"Sorry, I encountered an error. Please try again. Error: {e}"
                message_placeholder.markdown(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})

def connect_page():
    st.header("Connect with Others 💬")
    st.write("Share your thoughts and connect with others in a supportive community.")

    # New post form
    with st.form("new_post"):
        content = st.text_area("Share something with the community:", height=100)
        if st.form_submit_button("Post"):
            if content.strip():
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("INSERT INTO posts (user_id, username, content) VALUES (?, ?, ?)",
                          (st.session_state.user_id, st.session_state.username, content.strip()))
                conn.commit()
                conn.close()
                st.success("Your post has been shared!")
                st.rerun()
            else:
                st.warning("Please write something before posting.")

    # Display posts
    st.subheader("Community Posts")
    conn = get_db_connection()
    posts = pd.read_sql_query("SELECT username, content, timestamp FROM posts ORDER BY timestamp DESC LIMIT 20", conn)
    conn.close()

    if posts.empty:
        st.info("No posts yet. Be the first to share!")
    else:
        for index, row in posts.iterrows():
            with st.expander(f"Post by {row['username']} - {row['timestamp']}"):
                st.write(row['content'])

# ------------------------
# MAIN APP LOGIC
# ------------------------
def main():
    st.set_page_config(page_title="Mental Well-being Platform", layout="wide")

    # Initialize session state variables
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'is_moderator' not in st.session_state:
        st.session_state.is_moderator = False
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "Home"

    # --- LOGIN/SIGNUP/LOGOUT Sidebar ---
    with st.sidebar:
        st.title("Navigation")
        if st.session_state.logged_in:
            st.success(f"Logged in as **{st.session_state.username}**")
            if st.button("Logout"):
                st.session_state.logged_in = False
                st.session_state.is_moderator = False
                st.session_state.current_page = "Home"
                del st.session_state.username
                del st.session_state.user_id
                st.rerun()
        else:
            login_form = st.form("login_form")
            login_form.subheader("Login")
            username = login_form.text_input("Username", key="login_user")
            password = login_form.text_input("Password", type="password", key="login_pass")
            if login_form.form_submit_button("Login"):
                if username == "moderator" and password == MOD_PASSWORD:
                    st.session_state.logged_in = True
                    st.session_state.is_moderator = True
                    st.session_state.username = "moderator"
                    st.session_state.user_id = 0 # special ID for mod
                    st.rerun()
                else:
                    user = login(username, password)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.username = user['username']
                        st.session_state.user_id = user['id']
                        st.rerun()
                    else:
                        st.error("Invalid username or password")

            signup_form = st.form("signup_form")
            signup_form.subheader("Sign Up")
            new_username = signup_form.text_input("New Username", key="signup_user")
            new_password = signup_form.text_input("New Password", type="password", key="signup_pass")
            if signup_form.form_submit_button("Sign Up"):
                if signup(new_username, new_password):
                    st.success("Account created! Please log in.")
                else:
                    st.error("Username already exists.")

    # --- PAGE ROUTING ---
    if not st.session_state.logged_in:
        st.title("Welcome to the Mental Well-being Platform")
        st.write("Please log in or sign up using the sidebar to access the platform's features.")
        return

    # Dictionary mapping page names to functions
    pages = {
        "Home": None, # Special case for home
        "My Journal": journal_page,
        "Mood Tracker": mood_tracker_page,
        "Self-Screening": screening_page,
        "Connect": connect_page,
        "AI Companion": chatbot_page,
        "Resources": resources_page,
    }

    # --- HOME PAGE ---
    if st.session_state.current_page == "Home":
        st.title(f"Welcome back, {st.session_state.username}!")
        st.write("How can we support you today? Choose a feature to get started.")

        card_styles = {
            "My Journal": "#1E40AF",
            "Mood Tracker": "#065F46",
            "Self-Screening": "#7C2D12",
            "Connect": "#86198F",
            "AI Companion": "#4A044E",
            "Resources": "#854D0E"
        }

        # Create cards in columns
        features = list(pages.keys())[1:]  # exclude Home
        
        # Create a grid layout
        col1, col2, col3 = st.columns(3)
        cols = [col1, col2, col3]

        for i, feature in enumerate(features):
            with cols[i % 3]:
                if st.button(f"Go to {feature}", key=f"btn_{feature}", use_container_width=True):
                    st.session_state.current_page = feature
                    st.rerun()

    # --- RUN SELECTED PAGE ---
    else:
        # Back to Home button at the top
        if st.button("⬅ Back to Home"):
            st.session_state.current_page = "Home"
            st.rerun() # Rerun to immediately go home
        
        # Render the selected page
        page_function = pages.get(st.session_state.current_page)
        if page_function:
            page_function()


if __name__ == "__main__":
    main()
