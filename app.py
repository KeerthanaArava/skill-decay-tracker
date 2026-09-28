import os
import sys
import json
import secrets
import urllib.parse
import urllib.request
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)

import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

# ---------------------------------------------------------
# UTF-8 Console Safety (Prevents Windows charmap crash)
# ---------------------------------------------------------
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment variables
load_dotenv()


# =========================================================
# FLASK APP & CONFIGURATION
# =========================================================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "skill-decay-tracker-secret-key")

# Database configuration
DB_HOST = os.getenv("MYSQLHOST", "localhost")
DB_PORT = int(os.getenv("MYSQLPORT", "3306"))
DB_USER = os.getenv("MYSQLUSER", "root")
DB_PASSWORD = os.getenv("MYSQLPASSWORD", "Keerthana@123")
DB_NAME = os.getenv("MYSQLDATABASE", "skill_decay_tracker")

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/auth/google/callback").strip()


# =========================================================
# DATABASE SCHEMA INITIALIZATION & MIGRATION
# =========================================================

def init_database_schema(connection):
    """
    Ensures all necessary tables and columns exist in skill_decay_tracker.
    Creates tables if they don't exist and migrates schema for Google Auth.
    """
    cursor = None
    try:
        cursor = connection.cursor()

        # 1. users table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(150) NOT NULL UNIQUE,
                password VARCHAR(255) NULL,
                google_id VARCHAR(255) NULL,
                auth_provider VARCHAR(50) DEFAULT 'local',
                avatar_url VARCHAR(500) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # 2. skills table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                skill_name VARCHAR(100) NOT NULL,
                category VARCHAR(100) NOT NULL,
                initial_level ENUM('Beginner', 'Intermediate', 'Advanced') NOT NULL DEFAULT 'Beginner',
                target_frequency INT NOT NULL DEFAULT 7,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_skills_user
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )

        # 3. practice_sessions table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS practice_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                skill_id INT NOT NULL,
                practice_date DATE NOT NULL,
                duration INT NOT NULL,
                difficulty ENUM('Easy', 'Medium', 'Hard') NOT NULL DEFAULT 'Medium',
                performance INT NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_practice_skill
                    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
            );
            """
        )

        # 4. skill_history table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                skill_id INT NOT NULL,
                health_score DECIMAL(5,2) NOT NULL,
                status VARCHAR(50) NOT NULL,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_history_skill
                    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
            );
            """
        )

        connection.commit()

        # Migrate existing users table if columns are missing
        cursor.execute("DESCRIBE users")
        cols = [row[0] for row in cursor.fetchall()]

        if "google_id" not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN google_id VARCHAR(255) NULL AFTER password")
        if "auth_provider" not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN auth_provider VARCHAR(50) DEFAULT 'local' AFTER google_id")
        if "avatar_url" not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NULL AFTER auth_provider")

        cursor.execute("ALTER TABLE users MODIFY COLUMN password VARCHAR(255) NULL")
        connection.commit()

    except Exception as e:
        print("[DB SCHEMA WARNING]", e)
    finally:
        if cursor is not None:
            cursor.close()


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db_connection(database_name=DB_NAME):
    """
    Establishes and returns a connection to MySQL.
    If the database does not exist, it automatically creates it and sets up all tables.
    """
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=database_name,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci"
        )
        return connection

    except mysql.connector.Error as error:
        # Error 1049: Unknown database -> auto-create!
        if error.errno == 1049 and database_name:
            print(f"[DB] Database '{database_name}' not found. Initializing database and tables...")
            try:
                server_conn = mysql.connector.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    charset="utf8mb4"
                )
                cursor = server_conn.cursor()
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                )
                server_conn.commit()
                cursor.close()
                server_conn.close()

                connection = mysql.connector.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    user=DB_USER,
                    password=DB_PASSWORD,
                    database=database_name,
                    charset="utf8mb4",
                    collation="utf8mb4_unicode_ci"
                )
                init_database_schema(connection)
                print(f"[DB] Database '{database_name}' created and initialized successfully.")
                return connection
            except Exception as init_err:
                print(f"[DB ERROR] Failed to auto-create database '{database_name}':", init_err)
                raise

        print(f"[DB ERROR] MySQL connection error to {DB_HOST}:{DB_PORT}:", error)
        raise


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if "user_id" in session:

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "index.html"
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not name:

            flash(
                "Please enter your name.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if not email:

            flash(
                "Please enter your email.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if not password:

            flash(
                "Please enter a password.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if not confirm_password:

            flash(
                "Please confirm your password.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        connection = None
        cursor = None

        try:

            connection = get_db_connection()

            cursor = connection.cursor(
                dictionary=True
            )

            # -------------------------------------------------
            # CHECK EXISTING EMAIL
            # -------------------------------------------------

            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            existing_user = cursor.fetchone()

            if existing_user:

                flash(
                    "An account with this email already exists.",
                    "warning"
                )

                return render_template(
                    "register.html"
                )

            # -------------------------------------------------
            # HASH PASSWORD
            # -------------------------------------------------

            hashed_password = generate_password_hash(
                password
            )

            # -------------------------------------------------
            # INSERT USER
            # -------------------------------------------------

            cursor.execute(
                """
                INSERT INTO users
                (
                    name,
                    email,
                    password,
                    auth_provider
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    'local'
                )
                """,
                (
                    name,
                    email,
                    hashed_password
                )
            )

            connection.commit()

            flash(
                "Account created successfully. Please login.",
                "success"
            )

            return redirect(
                url_for("login")
            )

        except mysql.connector.Error as error:

            print(
                "REGISTER DATABASE ERROR:",
                error
            )

            flash(
                "Unable to create account.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        except Exception as error:

            print(
                "REGISTER ERROR:",
                error
            )

            flash(
                "Something went wrong while creating your account.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        finally:

            if cursor is not None:
                cursor.close()

            if connection is not None:
                connection.close()

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if "user_id" in session:

        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:

            flash(
                "Please enter your email and password.",
                "warning"
            )

            return render_template(
                "login.html"
            )

        connection = None
        cursor = None

        try:

            connection = get_db_connection()

            cursor = connection.cursor(
                dictionary=True
            )

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    email,
                    password,
                    google_id,
                    auth_provider,
                    avatar_url
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            if user is None:

                flash(
                    "Invalid email or password.",
                    "danger"
                )

                return render_template(
                    "login.html"
                )

            # -------------------------------------------------
            # CHECK GOOGLE ONLY ACCOUNT
            # -------------------------------------------------

            if not user["password"]:

                flash(
                    "This account was created with Google. Please click 'Sign in with Google' above.",
                    "info"
                )

                return render_template(
                    "login.html"
                )

            # -------------------------------------------------
            # CHECK HASHED PASSWORD
            # -------------------------------------------------

            if not check_password_hash(
                user["password"],
                password
            ):

                flash(
                    "Invalid email or password.",
                    "danger"
                )

                return render_template(
                    "login.html"
                )

            # -------------------------------------------------
            # SESSION
            # -------------------------------------------------

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]

            session["user_avatar"] = user.get("avatar_url") or ""

            session["auth_provider"] = user.get("auth_provider") or "local"

            flash(
                f"Welcome back, {user['name']}!",
                "success"
            )

            return redirect(
                url_for("dashboard")
            )

        except mysql.connector.Error as error:

            print(
                "LOGIN DATABASE ERROR:",
                error
            )

            flash(
                "Unable to connect to the database.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        except Exception as error:

            print(
                "LOGIN ERROR:",
                error
            )

            flash(
                "Something went wrong during login.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        finally:

            if cursor is not None:
                cursor.close()

            if connection is not None:
                connection.close()

    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("login")
    )


# =========================================================
# GOOGLE AUTHENTICATION HELPERS & ROUTES
# =========================================================

def login_or_register_google_user(email, name, google_id=None, avatar_url=None):
    """
    Finds or creates a user account linked to Google.
    Logs the user into the Flask session.
    """
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, name, email, avatar_url, auth_provider
            FROM users
            WHERE email = %s
            """,
            (email,)
        )

        existing_user = cursor.fetchone()

        if existing_user:
            user_id = existing_user["id"]
            user_name = existing_user["name"] or name
            saved_avatar = avatar_url or existing_user.get("avatar_url") or ""

            # Update Google ID and Avatar if provided
            cursor.execute(
                """
                UPDATE users
                SET google_id = COALESCE(%s, google_id),
                    avatar_url = COALESCE(%s, avatar_url),
                    auth_provider = CASE WHEN auth_provider = 'local' THEN 'google' ELSE auth_provider END
                WHERE id = %s
                """,
                (google_id, avatar_url, user_id)
            )
            connection.commit()

            session["user_id"] = user_id
            session["user_name"] = user_name
            session["user_email"] = existing_user["email"]
            session["user_avatar"] = saved_avatar
            session["auth_provider"] = "google"

            flash(
                f"Welcome back, {user_name}! Successfully signed in with Google.",
                "success"
            )
            return True, None

        else:
            # Create a brand new Google user
            cursor.execute(
                """
                INSERT INTO users
                (
                    name,
                    email,
                    password,
                    google_id,
                    auth_provider,
                    avatar_url
                )
                VALUES
                (
                    %s,
                    %s,
                    NULL,
                    %s,
                    'google',
                    %s
                )
                """,
                (
                    name,
                    email,
                    google_id,
                    avatar_url
                )
            )
            connection.commit()
            new_id = cursor.lastrowid

            session["user_id"] = new_id
            session["user_name"] = name
            session["user_email"] = email
            session["user_avatar"] = avatar_url or ""
            session["auth_provider"] = "google"

            flash(
                f"Welcome to Skill Decay Tracker, {name}! Your account was created with Google.",
                "success"
            )
            return True, None

    except Exception as error:
        print("[GOOGLE AUTH ERROR]:", error)
        return False, str(error)

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/auth/google")
def auth_google():
    """
    Entrypoint for Google Authentication (used by both Register and Login).
    If live Google Cloud credentials are configured in .env, redirects to accounts.google.com.
    Otherwise renders a Google account selector / demo test page.
    """
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    mode = request.args.get("mode", "login")
    session["oauth_mode"] = mode

    # Check if live Google credentials are set
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        state = secrets.token_urlsafe(32)
        session["oauth_state"] = state

        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
            "access_type": "offline"
        }
        google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
        return redirect(google_auth_url)

    # Fallback to Google Auth selector / simulator for instant testability
    return render_template(
        "google_auth.html",
        mode=mode,
        redirect_uri=GOOGLE_REDIRECT_URI
    )


@app.route("/auth/google/callback")
def auth_google_callback():
    """
    OAuth 2.0 callback endpoint from Google Accounts.
    """
    error = request.args.get("error")
    if error:
        flash(f"Google sign-in was cancelled or encountered an error: {error}", "warning")
        return redirect(url_for("login"))

    code = request.args.get("code")
    state = request.args.get("state")
    expected_state = session.pop("oauth_state", None)

    if not code or (expected_state and state != expected_state):
        flash("Invalid Google authentication session. Please try again.", "danger")
        return redirect(url_for("login"))

    try:
        # 1. Exchange code for access token
        token_endpoint = "https://oauth2.googleapis.com/token"
        token_payload = urllib.parse.urlencode({
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code"
        }).encode("utf-8")

        token_req = urllib.request.Request(
            token_endpoint,
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(token_req, timeout=10) as token_resp:
            tokens = json.loads(token_resp.read().decode("utf-8"))

        if "access_token" not in tokens:
            error_desc = tokens.get("error_description", "Failed to retrieve access token from Google.")
            flash(f"Google authorization failed: {error_desc}", "danger")
            return redirect(url_for("login"))

        access_token = tokens["access_token"]

        # 2. Fetch Google profile info
        userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
        userinfo_req = urllib.request.Request(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(userinfo_req, timeout=10) as userinfo_resp:
            user_info = json.loads(userinfo_resp.read().decode("utf-8"))

        google_id = user_info.get("sub")
        email = (user_info.get("email") or "").strip().lower()
        name = user_info.get("name") or user_info.get("given_name") or (email.split("@")[0].capitalize() if email else "User")
        avatar_url = user_info.get("picture")

        if not email:
            flash("Could not retrieve email address from your Google profile.", "danger")
            return redirect(url_for("login"))

        success, err = login_or_register_google_user(
            email=email,
            name=name,
            google_id=google_id,
            avatar_url=avatar_url
        )

        if success:
            return redirect(url_for("dashboard"))
        else:
            flash(f"Database error during Google sign-in: {err}", "danger")
            return redirect(url_for("login"))

    except urllib.error.URLError as e:
        print("[GOOGLE CALLBACK NETWORK ERROR]:", e)
        flash("Network error communicating with Google servers.", "danger")
        return redirect(url_for("login"))

    except Exception as e:
        print("[GOOGLE CALLBACK ERROR]:", e)
        flash("An error occurred during Google sign-in.", "danger")
        return redirect(url_for("login"))


@app.route("/auth/google/demo", methods=["GET", "POST"])
def auth_google_demo():
    """
    Instant demo/test Google Sign-in handler when running locally without Google Cloud keys.
    """
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
    else:
        email = request.args.get("email", "").strip().lower()
        name = request.args.get("name", "").strip()

    if not email:
        email = "demo.student@gmail.com"
    if not name:
        name = email.split("@")[0].replace(".", " ").title()

    google_id = f"demo_google_{abs(hash(email))}"
    avatar_url = f"https://api.dicebear.com/7.x/initials/svg?seed={urllib.parse.quote(name)}"

    success, err = login_or_register_google_user(
        email=email,
        name=name,
        google_id=google_id,
        avatar_url=avatar_url
    )

    if success:
        return redirect(url_for("dashboard"))
    else:
        flash(f"Database error: {err}", "danger")
        return redirect(url_for("login"))


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        flash(
            "Please login first.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        user_id = session["user_id"]

        # -------------------------------------------------
        # TOTAL SKILLS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total_skills
            FROM skills
            WHERE user_id = %s
            """,
            (user_id,)
        )

        total_skills_result = cursor.fetchone()

        total_skills = (
            total_skills_result["total_skills"]
            if total_skills_result
            else 0
        )

        # -------------------------------------------------
        # TOTAL PRACTICE SESSIONS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*) AS total_sessions
            FROM practice_sessions ps

            INNER JOIN skills s
                ON ps.skill_id = s.id

            WHERE s.user_id = %s
            """,
            (user_id,)
        )

        total_sessions_result = cursor.fetchone()

        total_sessions = (
            total_sessions_result["total_sessions"]
            if total_sessions_result
            else 0
        )

        # -------------------------------------------------
        # TOTAL PRACTICE MINUTES
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                COALESCE(
                    SUM(ps.duration),
                    0
                ) AS total_minutes

            FROM practice_sessions ps

            INNER JOIN skills s
                ON ps.skill_id = s.id

            WHERE s.user_id = %s
            """,
            (user_id,)
        )

        total_minutes_result = cursor.fetchone()

        total_minutes = (
            total_minutes_result["total_minutes"]
            if total_minutes_result
            else 0
        )

        # -------------------------------------------------
        # AVERAGE PERFORMANCE
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                COALESCE(
                    ROUND(
                        AVG(ps.performance)
                    ),
                    0
                ) AS average_performance

            FROM practice_sessions ps

            INNER JOIN skills s
                ON ps.skill_id = s.id

            WHERE s.user_id = %s
            """,
            (user_id,)
        )

        average_result = cursor.fetchone()

        average_performance = (
            average_result["average_performance"]
            if average_result
            else 0
        )

        # -------------------------------------------------
        # RECENT SKILLS
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                s.id,
                s.skill_name,
                s.category,
                s.initial_level,
                s.target_frequency,
                s.created_at,

                MAX(ps.practice_date)
                AS last_practice_date

            FROM skills s

            LEFT JOIN practice_sessions ps
                ON s.id = ps.skill_id

            WHERE s.user_id = %s

            GROUP BY
                s.id,
                s.skill_name,
                s.category,
                s.initial_level,
                s.target_frequency,
                s.created_at

            ORDER BY
                s.created_at DESC

            LIMIT 6
            """,
            (user_id,)
        )

        recent_skills = cursor.fetchall()

        return render_template(

            "dashboard.html",

            total_skills=total_skills,

            total_sessions=total_sessions,

            total_minutes=total_minutes,

            average_performance=average_performance,

            recent_skills=recent_skills

        )

    except mysql.connector.Error as error:

        print(
            "DASHBOARD DATABASE ERROR:",
            error
        )

        flash(
            "Unable to load dashboard.",
            "danger"
        )

        return redirect(
            url_for("login")
        )

    except Exception as error:

        print(
            "DASHBOARD ERROR:",
            error
        )

        flash(
            "Something went wrong while loading dashboard.",
            "danger"
        )

        return redirect(
            url_for("login")
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# =========================================================
# DATABASE TEST
#
# IMPORTANT:
# Template filename:
# database_test.html
#
# URL:
# /database-test
# =========================================================

@app.route("/database-test")
def database_test():

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SHOW TABLES"
        )

        raw_tables = cursor.fetchall()

        tables_data = []

        for row in raw_tables:
            table_name = list(row.values())[0]
            try:
                c2 = connection.cursor()
                c2.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                row_count = c2.fetchone()[0]
                c2.close()
            except Exception:
                row_count = 0
            tables_data.append({
                "name": table_name,
                "count": row_count
            })

        return render_template(
            "database_test.html",
            tables=tables_data,
            connected=True,
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            database=DB_NAME,
            error=None
        )

    except Exception as error:

        print(
            "DATABASE TEST ERROR:",
            error
        )

        return render_template(
            "database_test.html",
            tables=[],
            connected=False,
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            database=DB_NAME,
            error=str(error)
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# =========================================================
# ADD SKILL
# =========================================================

@app.route(
    "/add-skill",
    methods=["GET", "POST"]
)
def add_skill():

    if "user_id" not in session:

        flash(
            "Please login first.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        skill_name = request.form.get(
            "skill_name",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        target_frequency = request.form.get(
            "target_frequency",
            ""
        ).strip()

        initial_level = request.form.get(
            "initial_level",
            "Beginner"
        ).strip()

        notes = request.form.get(
            "notes",
            ""
        ).strip()

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not skill_name:

            flash(
                "Please enter a skill name.",
                "danger"
            )

            return render_template(
                "add_skill.html"
            )

        if not category:

            flash(
                "Please select a category.",
                "danger"
            )

            return render_template(
                "add_skill.html"
            )

        try:

            target_frequency = int(
                target_frequency
            )

        except ValueError:

            flash(
                "Invalid practice frequency.",
                "danger"
            )

            return render_template(
                "add_skill.html"
            )

        allowed_frequencies = [
            1,
            3,
            7,
            14,
            30
        ]

        if target_frequency not in allowed_frequencies:

            flash(
                "Invalid practice frequency.",
                "danger"
            )

            return render_template(
                "add_skill.html"
            )

        allowed_levels = [
            "Beginner",
            "Intermediate",
            "Advanced"
        ]

        if initial_level not in allowed_levels:

            initial_level = "Beginner"

        connection = None
        cursor = None

        try:

            connection = get_db_connection()

            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO skills
                (
                    user_id,
                    skill_name,
                    category,
                    initial_level,
                    target_frequency,
                    notes
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    session["user_id"],
                    skill_name,
                    category,
                    initial_level,
                    target_frequency,
                    notes
                )
            )

            connection.commit()

            flash(
                "Skill added successfully!",
                "success"
            )

            return redirect(
                url_for("skills")
            )

        except mysql.connector.Error as error:

            print(
                "ADD SKILL DATABASE ERROR:",
                error
            )

            flash(
                "Unable to add skill.",
                "danger"
            )

        except Exception as error:

            print(
                "ADD SKILL ERROR:",
                error
            )

            flash(
                "Something went wrong while adding the skill.",
                "danger"
            )

        finally:

            if cursor is not None:
                cursor.close()

            if connection is not None:
                connection.close()

    return render_template(
        "add_skill.html"
    )


# =========================================================
# MY SKILLS
# =========================================================

@app.route("/skills")
def skills():

    if "user_id" not in session:

        flash(
            "Please login first.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                s.id,
                s.skill_name,
                s.category,
                s.initial_level,
                s.target_frequency,
                s.notes,
                s.created_at,

                MAX(ps.practice_date)
                AS last_practice_date,

                COUNT(ps.id)
                AS practice_count

            FROM skills s

            LEFT JOIN practice_sessions ps
                ON s.id = ps.skill_id

            WHERE s.user_id = %s

            GROUP BY
                s.id,
                s.skill_name,
                s.category,
                s.initial_level,
                s.target_frequency,
                s.notes,
                s.created_at

            ORDER BY
                s.created_at DESC
            """,
            (session["user_id"],)
        )

        user_skills = cursor.fetchall()

        return render_template(
            "skills.html",
            skills=user_skills
        )

    except mysql.connector.Error as error:

        print(
            "SKILLS DATABASE ERROR:",
            error
        )

        flash(
            "Unable to load your skills.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    except Exception as error:

        print(
            "SKILLS ERROR:",
            error
        )

        flash(
            "Something went wrong while loading skills.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# =========================================================
# PRACTICE SKILL
# =========================================================

@app.route(
    "/practice/<int:skill_id>",
    methods=["GET", "POST"]
)
def practice(skill_id):

    if "user_id" not in session:

        flash(
            "Please login first.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        # -------------------------------------------------
        # CHECK SKILL BELONGS TO USER
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                skill_name,
                category
            FROM skills
            WHERE
                id = %s
                AND user_id = %s
            """,
            (
                skill_id,
                session["user_id"]
            )
        )

        skill = cursor.fetchone()

        if skill is None:

            flash(
                "Skill not found.",
                "danger"
            )

            return redirect(
                url_for("skills")
            )

        # -------------------------------------------------
        # SAVE PRACTICE SESSION
        # -------------------------------------------------

        if request.method == "POST":

            practice_date = request.form.get(
                "practice_date",
                ""
            )

            duration = request.form.get(
                "duration",
                ""
            )

            difficulty = request.form.get(
                "difficulty",
                "Medium"
            )

            performance = request.form.get(
                "performance",
                ""
            )

            notes = request.form.get(
                "notes",
                ""
            ).strip()

            # -------------------------------------------------
            # DURATION
            # -------------------------------------------------

            try:

                duration = int(
                    duration
                )

            except ValueError:

                flash(
                    "Please enter a valid duration.",
                    "danger"
                )

                return render_template(
                    "practice.html",
                    skill=skill
                )

            if duration <= 0:

                flash(
                    "Duration must be greater than 0.",
                    "danger"
                )

                return render_template(
                    "practice.html",
                    skill=skill
                )

            # -------------------------------------------------
            # PERFORMANCE
            # -------------------------------------------------

            try:

                performance = int(
                    performance
                )

            except ValueError:

                flash(
                    "Please enter a valid performance score.",
                    "danger"
                )

                return render_template(
                    "practice.html",
                    skill=skill
                )

            if performance < 0 or performance > 100:

                flash(
                    "Performance must be between 0 and 100.",
                    "danger"
                )

                return render_template(
                    "practice.html",
                    skill=skill
                )

            # -------------------------------------------------
            # DIFFICULTY
            # -------------------------------------------------

            allowed_difficulties = [
                "Easy",
                "Medium",
                "Hard"
            ]

            if difficulty not in allowed_difficulties:

                difficulty = "Medium"

            # -------------------------------------------------
            # DATE
            # -------------------------------------------------

            if not practice_date:

                flash(
                    "Please select a practice date.",
                    "danger"
                )

                return render_template(
                    "practice.html",
                    skill=skill
                )

            # -------------------------------------------------
            # INSERT PRACTICE SESSION
            # -------------------------------------------------

            cursor.execute(
                """
                INSERT INTO practice_sessions
                (
                    skill_id,
                    practice_date,
                    duration,
                    difficulty,
                    performance,
                    notes
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    skill_id,
                    practice_date,
                    duration,
                    difficulty,
                    performance,
                    notes
                )
            )

            connection.commit()

            flash(
                "Practice session recorded successfully!",
                "success"
            )

            return redirect(
                url_for("history")
            )

        return render_template(
            "practice.html",
            skill=skill
        )

    except mysql.connector.Error as error:

        print(
            "PRACTICE DATABASE ERROR:",
            error
        )

        flash(
            "Unable to save practice session.",
            "danger"
        )

        return redirect(
            url_for("skills")
        )

    except Exception as error:

        print(
            "PRACTICE ERROR:",
            error
        )

        flash(
            "Something went wrong while recording practice.",
            "danger"
        )

        return redirect(
            url_for("skills")
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# =========================================================
# HISTORY
# =========================================================

@app.route("/history")
def history():

    if "user_id" not in session:

        flash(
            "Please login first.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                ps.id,
                ps.skill_id,
                ps.practice_date,
                ps.duration,
                ps.difficulty,
                ps.performance,
                ps.notes,
                ps.created_at,

                s.skill_name,
                s.category

            FROM practice_sessions ps

            INNER JOIN skills s
                ON ps.skill_id = s.id

            WHERE s.user_id = %s

            ORDER BY
                ps.practice_date DESC,
                ps.created_at DESC
            """,
            (session["user_id"],)
        )

        practice_history = cursor.fetchall()

        # -------------------------------------------------
        # TOTAL SESSIONS
        # -------------------------------------------------

        total_sessions = len(
            practice_history
        )

        # -------------------------------------------------
        # TOTAL MINUTES
        # -------------------------------------------------

        total_minutes = sum(

            int(
                item["duration"] or 0
            )

            for item in practice_history

        )

        # -------------------------------------------------
        # AVERAGE PERFORMANCE
        # -------------------------------------------------

        if total_sessions > 0:

            average_performance = round(

                sum(

                    int(
                        item["performance"] or 0
                    )

                    for item in practice_history

                )
                / total_sessions

            )

        else:

            average_performance = 0

        return render_template(

            "history.html",

            practice_history=practice_history,

            total_sessions=total_sessions,

            total_minutes=total_minutes,

            average_performance=average_performance

        )

    except mysql.connector.Error as error:

        print(
            "HISTORY DATABASE ERROR:",
            error
        )

        flash(
            "Unable to load practice history.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    except Exception as error:

        print(
            "HISTORY ERROR:",
            error
        )

        flash(
            "Something went wrong while loading history.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# =========================================================
# RECOMMENDATIONS
#
# THIS WAS THE MISSING ROUTE
# =========================================================

@app.route("/recommendations")
def recommendations():

    if "user_id" not in session:

        flash(
            "Please login first.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                s.id,
                s.skill_name,
                s.category,
                s.initial_level,
                s.target_frequency,
                COUNT(ps.id) AS total_sessions,
                COALESCE(ROUND(AVG(ps.performance)), 0) AS average_performance,
                MAX(ps.practice_date) AS last_practice_date,
                DATEDIFF(
                    CURDATE(),
                    MAX(ps.practice_date)
                ) AS days_since_practice
            FROM skills s
            LEFT JOIN practice_sessions ps
                ON s.id = ps.skill_id
            WHERE s.user_id = %s
            GROUP BY
                s.id,
                s.skill_name,
                s.category,
                s.initial_level,
                s.target_frequency
            ORDER BY
                CASE
                    WHEN MAX(ps.practice_date) IS NULL
                    THEN 999999
                    ELSE DATEDIFF(
                        CURDATE(),
                        MAX(ps.practice_date)
                    )
                END DESC
            """,
            (session["user_id"],)
        )

        skills_data = cursor.fetchall()

        recommendations_list = []

        for skill in skills_data:

            days_since_practice = skill.get("days_since_practice")
            target_frequency = skill.get("target_frequency") or 7
            total_sessions = skill.get("total_sessions", 0) or 0
            average_performance = int(skill.get("average_performance", 0) or 0)

            # Determine recommendation type, title, text, and tips
            if days_since_practice is None:
                rec_type = "start"
                rec_title = "Start Your Practice"
                rec_text = "You haven't logged any practice sessions for this skill yet. A short session will establish your baseline."
                tip = "Start with basic fundamentals and write concise notes to document your initial understanding."
                status = "Critical"
            elif days_since_practice <= target_frequency:
                rec_type = "on-track"
                rec_title = "Great Consistency!"
                rec_text = f"You practiced {days_since_practice} day(s) ago, comfortably within your {target_frequency}-day target. Keep up the excellent work!"
                tip = "Try increasing the challenge or duration slightly in your next session to accelerate mastery."
                status = "Excellent"
            elif days_since_practice <= (target_frequency * 1.5):
                rec_type = "soon"
                rec_title = "Practice Session Due Soon"
                rec_text = f"Your last practice was {days_since_practice} days ago (target interval: every {target_frequency} days). Plan a quick refresher session."
                tip = "Review previous session notes and solve 1 or 2 targeted practice exercises."
                status = "Good"
            else:
                rec_type = "attention"
                rec_title = "Skill Decay Warning"
                rec_text = f"It has been {days_since_practice} days since you last practiced. Skill retention drops significantly without regular reinforcement."
                tip = "Schedule a dedicated 45-minute practice session today to prevent forgetting core concepts."
                status = "At Risk"

            recommendations_list.append({
                "id": skill["id"],
                "skill_id": skill["id"],
                "skill_name": skill["skill_name"],
                "category": skill["category"],
                "initial_level": skill["initial_level"],
                "target_frequency": target_frequency,
                "total_sessions": total_sessions,
                "average_performance": average_performance,
                "last_practice_date": skill["last_practice_date"],
                "days_since_practice": days_since_practice,
                "recommendation_type": rec_type,
                "recommendation_title": rec_title,
                "recommendation_text": rec_text,
                "performance_tip": tip,
                "status": status,
                "message": rec_text
            })

        return render_template(
            "recommendations.html",
            recommendations=recommendations_list
        )

    except mysql.connector.Error as error:

        print(
            "RECOMMENDATIONS DATABASE ERROR:",
            error
        )

        flash(
            "Unable to load recommendations.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    except Exception as error:

        print(
            "RECOMMENDATIONS ERROR:",
            error
        )

        flash(
            "Something went wrong while loading recommendations.",
            "danger"
        )

        return redirect(
            url_for("dashboard")
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# =========================================================
# DELETE SKILL
# =========================================================

@app.route(
    "/delete-skill/<int:skill_id>",
    methods=["POST"]
)
def delete_skill(skill_id):

    if "user_id" not in session:

        flash(
            "Please login first.",
            "warning"
        )

        return redirect(
            url_for("login")
        )

    connection = None
    cursor = None

    try:

        connection = get_db_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM skills

            WHERE
                id = %s
                AND user_id = %s
            """,
            (
                skill_id,
                session["user_id"]
            )
        )

        connection.commit()

        if cursor.rowcount == 0:

            flash(
                "Skill not found.",
                "warning"
            )

        else:

            flash(
                "Skill deleted successfully.",
                "success"
            )

        return redirect(
            url_for("skills")
        )

    except mysql.connector.Error as error:

        print(
            "DELETE SKILL DATABASE ERROR:",
            error
        )

        flash(
            "Unable to delete skill.",
            "danger"
        )

        return redirect(
            url_for("skills")
        )

    except Exception as error:

        print(
            "DELETE SKILL ERROR:",
            error
        )

        flash(
            "Something went wrong while deleting the skill.",
            "danger"
        )

        return redirect(
            url_for("skills")
        )

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )