from __future__ import annotations

import os
import secrets
import smtplib
import sqlite3
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from functools import wraps
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("DEADLINESOS_DB", BASE_DIR / "deadlinesos.db"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "deadlinesos-local-key"
)


def send_otp_email(recipient: str, otp: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM", username or "")
    if not all((host, username, password, sender)):
        return False
    message = EmailMessage()
    message["Subject"] = "Your DeadlineSOS verification code"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Your DeadlineSOS verification code is "
        f"{otp}. It expires in 10 minutes."
    )
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        return False
    return True


def ask_ai_model(
    question: str, tasks: list[dict]
) -> tuple[str | None, str | None]:
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        return None, (
            "AI_API_KEY is not configured. Add it before using ChatGPT mode."
        )
    api_url = os.environ.get(
        "AI_API_URL", "https://api.openai.com/v1/chat/completions"
    )
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    context = [
        {
            "title": task["title"],
            "course": task["course"],
            "due_date": task["due_date"],
            "risk": task["risk_label"],
            "risk_score": task["risk_score"],
            "hours": task["estimated_hours"],
            "completed": bool(task["completed"]),
        }
        for task in tasks
    ]
    payload = {
        "model": model,
        "temperature": 0.7,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are DeadlineSOS AI Study Coach. Give practical, "
                    "kind, concise academic planning advice. Use the task "
                    "context when relevant. Break solutions into clear steps. "
                    "Never invent task details."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Student task context:\n"
                    f"{json.dumps(context)}\n\nQuestion: {question}"
                ),
            },
        ],
    }
    request = Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        answer = result["choices"][0]["message"]["content"].strip()
        return answer, None
    except (
        HTTPError,
        URLError,
        TimeoutError,
        KeyError,
        IndexError,
        json.JSONDecodeError,
    ) as error:
        return None, f"AI service error: {error}"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(app.config.get("DATABASE", DATABASE))
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error: object | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            course TEXT DEFAULT '',
            semester TEXT DEFAULT '',
            daily_available_hours REAL DEFAULT 3,
            is_verified INTEGER NOT NULL DEFAULT 0,
            daily_goal INTEGER NOT NULL DEFAULT 3,
            points INTEGER NOT NULL DEFAULT 0,
            streak INTEGER NOT NULL DEFAULT 0,
            last_active TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            course TEXT NOT NULL,
            task_type TEXT NOT NULL,
            due_date TEXT NOT NULL,
            estimated_hours REAL NOT NULL,
            difficulty INTEGER NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
            study_hours REAL NOT NULL,
            notes TEXT DEFAULT '',
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    task_columns = {
        row[1] for row in db.execute("PRAGMA table_info(tasks)").fetchall()
    }
    if "user_id" not in task_columns:
        db.execute(
            "ALTER TABLE tasks ADD COLUMN user_id INTEGER REFERENCES users(id)"
        )
    if "recurrence" not in task_columns:
        db.execute(
            "ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT 'None'"
        )
    if "category" not in task_columns:
        db.execute(
            "ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT 'Assignment'"
        )
    if "dependency_id" not in task_columns:
        db.execute(
            "ALTER TABLE tasks ADD COLUMN dependency_id "
            "INTEGER REFERENCES tasks(id)"
        )
    for column, definition in {
        "description": "TEXT DEFAULT ''",
        "progress": "INTEGER NOT NULL DEFAULT 0",
        "status": "TEXT NOT NULL DEFAULT 'Not started'",
        "submission_status": "TEXT NOT NULL DEFAULT 'Not submitted'",
        "submitted_at": "TEXT DEFAULT ''",
        "submission_link": "TEXT DEFAULT ''",
        "teacher": "TEXT DEFAULT ''",
    }.items():
        if column not in task_columns:
            db.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")
    user_columns = {
        row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "is_verified" not in user_columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN is_verified "
            "INTEGER NOT NULL DEFAULT 0"
        )
    for column, definition in {
        "daily_goal": "INTEGER NOT NULL DEFAULT 3",
        "points": "INTEGER NOT NULL DEFAULT 0",
        "streak": "INTEGER NOT NULL DEFAULT 0",
        "last_active": "TEXT DEFAULT ''",
    }.items():
        if column not in user_columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    if "completed_at" not in task_columns:
        db.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT DEFAULT ''")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    db.commit()


@app.before_request
def load_logged_in_user() -> None:
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def calculate_task_status(task: sqlite3.Row | dict) -> dict:
    due = date.fromisoformat(task["due_date"])
    days_left = (due - date.today()).days
    available_hours = max(float(task["study_hours"]), 0.5)
    estimated_hours = max(float(task["estimated_hours"]), 0.5)
    difficulty = int(task["difficulty"])
    urgency = max(0, 14 - days_left) / 14
    workload_pressure = min(1.0, estimated_hours / available_hours)
    difficulty_pressure = (difficulty - 1) / 4
    dependency_pressure = (
        15 if not task.get("dependency_completed", True) else 0
    )
    progress_pressure = max(0, 100 - int(task.get("progress", 0))) / 100 * 15
    risk_score = round(
        min(
            100,
            (urgency * 38)
            + (workload_pressure * 42)
            + (difficulty_pressure * 20)
            + dependency_pressure
            + progress_pressure,
        )
    )

    if days_left < 0:
        risk_label, risk_tone = "Overdue", "critical"
    elif risk_score >= 70:
        risk_label, risk_tone = "High risk", "critical"
    elif risk_score >= 40:
        risk_label, risk_tone = "Watch", "warning"
    else:
        risk_label, risk_tone = "On track", "healthy"

    if risk_score >= 70 or days_left <= 1:
        priority = "Do next"
    elif risk_score >= 45:
        priority = "Plan soon"
    else:
        priority = "Scheduled"

    risk_reasons = []
    if days_left <= 2:
        risk_reasons.append(f"Only {max(days_left, 0)} days remaining")
    if estimated_hours > available_hours:
        risk_reasons.append(
            f"{estimated_hours:g}h work vs {available_hours:g}h available"
        )
    if difficulty >= 4:
        risk_reasons.append("Difficulty is hard")
    if int(task.get("progress", 0)) < 30:
        risk_reasons.append(f"Current progress is {task.get('progress', 0)}%")
    if not task.get("dependency_completed", True):
        risk_reasons.append("Waiting for a prerequisite task")
    if not risk_reasons:
        risk_reasons.append("Enough time and capacity are available")
    return {
        "days_left": days_left,
        "risk_score": risk_score,
        "risk_label": risk_label,
        "risk_tone": risk_tone,
        "priority": priority,
        "load_ratio": round(min(1, workload_pressure) * 100),
        "blocked": not task.get("dependency_completed", True),
        "risk_reasons": risk_reasons,
        "recommendation": (
            "Start today for at least "
            f"{min(estimated_hours, available_hours):g} hours."
            if risk_score >= 70
            else "Schedule a focused session before the deadline."
        ),
    }


def task_with_status(row: sqlite3.Row) -> dict:
    task = dict(row)
    dependency_id = task.get("dependency_id")
    task["dependency_title"] = ""
    task["dependency_completed"] = True
    if dependency_id:
        dependency = get_db().execute(
            "SELECT title, completed FROM tasks WHERE id = ? AND user_id = ?",
            (dependency_id, g.user["id"]),
        ).fetchone()
        if dependency:
            task["dependency_title"] = dependency["title"]
            task["dependency_completed"] = bool(dependency["completed"])
    task.update(calculate_task_status(task))
    task["subtasks"] = [
        dict(item)
        for item in get_db().execute(
            "SELECT * FROM subtasks WHERE task_id = ? "
            "ORDER BY id",
            (task["id"],),
        ).fetchall()
    ]
    return task


def load_tasks() -> list[dict]:
    rows = get_db().execute(
        "SELECT * FROM tasks WHERE user_id = ? "
        "ORDER BY completed ASC, due_date ASC",
        (g.user["id"],),
    ).fetchall()
    return [task_with_status(row) for row in rows]


def update_user_progress() -> None:
    today = date.today().isoformat()
    user = g.user
    if user["last_active"] == today:
        return
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    streak = user["streak"] + 1 if user["last_active"] == yesterday else 1
    get_db().execute(
        "UPDATE users SET points = points + 10, streak = ?, "
        "last_active = ? WHERE id = ?",
        (streak, today, user["id"]),
    )
    get_db().commit()


@app.template_filter("date_label")
def date_label(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    if os.name != "nt":
        return parsed.strftime("%b %-d")
    return parsed.strftime("%b %#d")


@app.context_processor
def inject_today() -> dict:
    return {"today": date.today().isoformat(), "current_user": g.user}


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST" and request.form.get("otp"):
        pending = session.get("pending_registration")
        if not pending or datetime.now().timestamp() > pending["expires_at"]:
            flash(
                "This verification code expired. Please register again.",
                "error",
            )
            return redirect(url_for("register"))
        if request.form.get("otp", "").strip() != pending["otp"]:
            flash("That OTP is not correct. Please try again.", "error")
            return render_template("register.html", otp_pending=True)
        cursor = get_db().execute(
            """INSERT INTO users
            (name, email, password, course, semester, daily_available_hours,
             is_verified, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pending["name"], pending["email"], pending["password"],
             pending["course"], pending["semester"], 3, 1,
             datetime.now().isoformat()),
        )
        get_db().commit()
        session.clear()
        session["user_id"] = cursor.lastrowid
        flash("Email verified. Welcome to DeadlineSOS!", "success")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 6:
            flash(
                "Add your name, a valid email, and a password of 6+ chars.",
                "error",
            )
        else:
            try:
                if not app.config.get("TESTING"):
                    otp = f"{secrets.randbelow(1000000):06d}"
                    if not send_otp_email(email, otp):
                        flash(
                            "Email service is not configured. Add SMTP "
                            "settings "
                            "before creating an account.",
                            "error",
                        )
                        return render_template("register.html")
                    session["pending_registration"] = {
                        "name": name,
                        "email": email,
                        "password": generate_password_hash(password),
                        "course": request.form.get("course", "").strip(),
                        "semester": request.form.get("semester", "").strip(),
                        "otp": otp,
                        "expires_at": (
                            datetime.now() + timedelta(minutes=10)
                        ).timestamp(),
                    }
                    flash(
                        "Verification code sent to your email.",
                        "success",
                    )
                    return render_template("register.html", otp_pending=True)
                cursor = get_db().execute(
                    """INSERT INTO users
                    (
                        name,
                        email,
                        password,
                        course,
                        semester,
                        daily_available_hours,
                        is_verified,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        name,
                        email,
                        generate_password_hash(password),
                        request.form.get("course", "").strip(),
                        request.form.get("semester", "").strip(),
                        3,
                        1,
                        datetime.now().isoformat(),
                    ),
                )
                get_db().commit()
                session.clear()
                session["user_id"] = cursor.lastrowid
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash(
                    "That email is already registered. Try logging in.",
                    "error",
                )
    return render_template(
        "register.html",
        otp_pending=bool(session.get("pending_registration")),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        if user is None or not check_password_hash(
            user["password"], request.form.get("password", "")
        ):
            flash("Email or password not recognized.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    tasks = load_tasks()
    pending = [task for task in tasks if not task["completed"]]
    completed = [task for task in tasks if task["completed"]]
    high_risk = [task for task in pending if task["risk_tone"] == "critical"]
    total_hours = sum(task["estimated_hours"] for task in pending)
    completed_hours = sum(task["estimated_hours"] for task in completed)
    total_count = len(tasks)
    progress = (
        round((len(completed) / total_count) * 100) if total_count else 0
    )
    recommended = max(
        pending, key=lambda task: task["risk_score"], default=None
    )
    today = date.today().isoformat()
    completed_today = sum(
        1 for task in tasks if task.get("completed_at", "").startswith(today)
    )
    daily_goal = max(1, int(g.user["daily_goal"] or 3))
    workload_ratio = total_hours / max(
        float(g.user["daily_available_hours"]), 0.5
    )
    if workload_ratio >= 2:
        workload_level = "Overloaded"
    elif workload_ratio >= 1:
        workload_level = "Busy"
    else:
        workload_level = "Balanced"
    week_load = []
    for offset in range(7):
        day = date.today() + timedelta(days=offset)
        week_load.append({
            "label": day.strftime("%a"),
            "date": day.isoformat(),
            "hours": round(
                sum(
                    task["estimated_hours"]
                    for task in pending
                    if task["due_date"] == day.isoformat()
                ),
                1,
            ),
        })
    return render_template(
        "dashboard.html",
        tasks=tasks,
        pending=pending,
        completed=completed,
        high_risk=high_risk,
        total_hours=round(total_hours, 1),
        completed_hours=round(completed_hours, 1),
        progress=progress,
        recommended=recommended,
        completed_today=completed_today,
        daily_goal=daily_goal,
        workload_ratio=round(min(workload_ratio, 3) / 3 * 100),
        workload_level=workload_level,
        week_load=week_load,
    )


@app.route("/planner")
@login_required
def planner():
    tasks = load_tasks()
    return render_template(
        "planner.html",
        tasks=tasks,
        today=date.today().isoformat(),
    )


@app.route("/sos-mode", methods=["GET", "POST"])
@login_required
def sos_mode():
    pending = [task for task in load_tasks() if not task["completed"]]
    available_hours = 3.0
    if request.method == "POST":
        try:
            available_hours = max(0.25, float(request.form.get("hours", 3)))
        except ValueError:
            available_hours = 3.0
    pending.sort(key=lambda task: (-task["risk_score"], task["due_date"]))
    minutes_left = round(available_hours * 60)
    sos_plan = []
    for task in pending:
        if minutes_left <= 0:
            break
        minutes = min(round(float(task["estimated_hours"]) * 60), minutes_left)
        sos_plan.append({
            "title": task["title"],
            "course": task["course"],
            "risk_score": task["risk_score"],
            "risk_label": task["risk_label"],
            "risk_tone": task["risk_tone"],
            "minutes": minutes,
        })
        minutes_left -= minutes
    return render_template(
        "sos_mode.html",
        sos_plan=sos_plan,
        available_hours=available_hours,
        pending=pending,
    )


@app.route("/deadline-simulator/<int:task_id>", methods=["GET", "POST"])
@login_required
def deadline_simulator(task_id: int):
    task = owned_task(task_id)
    if task is None:
        return redirect(url_for("dashboard"))
    current = task_with_status(task)
    simulated_date = request.form.get("simulated_date", task["due_date"])
    try:
        date.fromisoformat(simulated_date)
    except ValueError:
        simulated_date = task["due_date"]
    simulated = dict(current)
    simulated["due_date"] = simulated_date
    simulated_status = calculate_task_status(simulated)
    days = max((date.fromisoformat(simulated_date) - date.today()).days, 1)
    remaining_hours = max(
        float(task["estimated_hours"])
        * (1 - int(task.get("progress", 0)) / 100),
        0,
    )
    required_daily_hours = round(remaining_hours / days, 1)
    return render_template(
        "deadline_simulator.html",
        task=current,
        simulated=simulated_status,
        simulated_date=simulated_date,
        required_daily_hours=required_daily_hours,
    )


@app.route("/insights")
@login_required
def insights():
    tasks = load_tasks()
    pending = [task for task in tasks if not task["completed"]]
    completed = [task for task in tasks if task["completed"]]
    total_hours = sum(task["estimated_hours"] for task in pending)
    available_hours = max(float(g.user["daily_available_hours"]), 0.5) * 7
    shortage_hours = round(max(total_hours - available_hours, 0), 1)
    today = date.today().isoformat()
    daily_goal = max(1, int(g.user["daily_goal"] or 3))
    completed_today = sum(
        1 for task in tasks if task.get("completed_at", "").startswith(today)
    )
    late_submissions = sum(
        1
        for task in completed
        if task.get("completed_at", "")
        and task["completed_at"][:10] > task["due_date"]
    )
    subject_workload = {}
    for task in tasks:
        subject_workload[task["course"]] = round(
            subject_workload.get(task["course"], 0) + task["estimated_hours"],
            1,
        )
    risk_counts = {
        "Low": sum(task["risk_tone"] == "healthy" for task in tasks),
        "Medium": sum(task["risk_tone"] == "warning" for task in tasks),
        "High / Critical": sum(
            task["risk_tone"] == "critical" for task in tasks
        ),
    }
    overdue_count = sum(task["days_left"] < 0 for task in pending)
    average_progress = (
        round(sum(int(task.get("progress", 0)) for task in tasks) / len(tasks))
        if tasks else 0
    )
    badges = []
    if int(g.user["streak"] or 0) >= 7:
        badges.append("7-Day Streak")
    if len(completed) >= 10:
        badges.append("10 Tasks Completed")
    if overdue_count == 0 and tasks:
        badges.append("Zero Overdue")
    if completed and not overdue_count:
        badges.append("Deadline Master")
    week_load = []
    for offset in range(7):
        day = date.today() + timedelta(days=offset)
        week_load.append({
            "label": day.strftime("%a"),
            "date": day.isoformat(),
            "hours": round(
                sum(
                    task["estimated_hours"]
                    for task in pending
                    if task["due_date"] == day.isoformat()
                ),
                1,
            ),
        })
    return render_template(
        "insights.html",
        tasks=tasks,
        pending=pending,
        completed=completed,
        total_hours=round(total_hours, 1),
        completed_today=completed_today,
        daily_goal=daily_goal,
        week_load=week_load,
        late_submissions=late_submissions,
        subject_workload=subject_workload,
        risk_counts=risk_counts,
        overdue_count=overdue_count,
        average_progress=average_progress,
        badges=badges,
        available_hours=round(available_hours, 1),
        shortage_hours=shortage_hours,
    )


@app.route("/study-plan")
@login_required
def study_plan():
    pending = [task for task in load_tasks() if not task["completed"]]
    pending.sort(key=lambda task: (-task["risk_score"], task["due_date"]))
    available_hours = max(float(g.user["daily_available_hours"]), 0.5)
    plan = []
    remaining = pending[:]
    for offset in range(7):
        day = date.today() + timedelta(days=offset)
        hours_left = available_hours
        sessions = []
        for task in remaining[:]:
            session_hours = min(float(task["estimated_hours"]), hours_left)
            if session_hours <= 0:
                break
            sessions.append({
                "title": task["title"],
                "course": task["course"],
                "hours": round(session_hours, 1),
                "risk_label": task["risk_label"],
            })
            hours_left -= session_hours
            task["estimated_hours"] = round(
                float(task["estimated_hours"]) - session_hours, 1
            )
            if task["estimated_hours"] <= 0:
                remaining.remove(task)
            if hours_left <= 0:
                break
        plan.append({
            "date": day.isoformat(),
            "label": day.strftime("%A"),
            "sessions": sessions,
        })
        if not remaining:
            break
    return render_template(
        "study_plan.html",
        plan=plan,
        pending=pending,
        available_hours=available_hours,
    )


def study_coach_reply(question: str, tasks: list[dict]) -> str:
    question = question.lower().strip()
    pending = [task for task in tasks if not task["completed"]]
    pending.sort(key=lambda task: (-task["risk_score"], task["due_date"]))
    if not pending:
        return (
            "You are clear right now. Add a task and I will help you "
            "choose the best next step."
        )
    if any(
        word in question for word in ("first", "priority", "next", "start")
    ):
        task = pending[0]
        return (
            f"Start with {task['title']} ({task['course']}). It is marked "
            f"{task['risk_label'].lower()} with a risk score of "
            f"{task['risk_score']}%. "
            f"Give it a focused "
            f"{min(float(task['estimated_hours']), 1.5):g}-hour session first."
        )
    if any(
        word in question for word in ("today", "plan", "schedule", "study")
    ):
        total = sum(float(task["estimated_hours"]) for task in pending[:3])
        names = ", ".join(task["title"] for task in pending[:3])
        return (
            f"For today, work in this order: {names}. "
            "Start with 25 minutes of "
            f"focused work, take a 5-minute break, and repeat. Your top three "
            f"tasks need about {total:g} hours in total."
        )
    if any(
        word in question
        for word in ("stress", "overload", "too much", "manage")
    ):
        hours = sum(float(task["estimated_hours"]) for task in pending)
        available = max(float(g.user["daily_available_hours"]), 0.5)
        return (
            f"You have about {hours:g} hours pending and {available:g} hours "
            "available per day. Do not attempt everything at once: finish the "
            "highest-risk task first, split the next task into smaller "
            "subtasks, "
            "and protect one short recovery break."
        )
    task = pending[0]
    return (
        "I can help you plan, prioritize, or reduce workload. A good starting "
        f"point is {task['title']}, due {task['due_date']}. "
        "Try asking: 'What should I do first?'"
    )


@app.route("/ai-coach", methods=["GET", "POST"])
@login_required
def ai_coach():
    question = (
        request.form.get("question", "").strip()
        if request.method == "POST"
        else ""
    )
    answer = ""
    error = ""
    if question:
        answer, error = ask_ai_model(question, load_tasks())
        if answer is None:
            answer = study_coach_reply(question, load_tasks())
    return render_template(
        "ai_coach.html",
        question=question,
        answer=answer,
        error=error,
        tasks=load_tasks(),
    )


@app.route("/category/<category>")
@login_required
def category_page(category: str):
    allowed = {
        "Assignment",
        "Homework",
        "Exam",
        "Project",
        "Practical",
        "Daily Task",
        "Academic Event",
        "Quiz",
        "Submission",
    }
    category = category.title()
    if category not in allowed:
        return redirect(url_for("dashboard"))
    tasks = [
        task for task in load_tasks()
        if task.get("category", task["task_type"]) == category
    ]
    return render_template("category.html", category=category, tasks=tasks)


@app.route("/tasks", methods=["POST"])
@login_required
def add_task():
    form = request.form
    title = form.get("title", "").strip()
    course = form.get("course", "").strip()
    due_date = form.get("due_date", "")
    dependency_id = form.get("dependency_id", "").strip() or None
    description = form.get("description", "").strip()
    status = form.get("status", "Not started")
    submission_status = form.get("submission_status", "Not submitted")
    teacher = form.get("teacher", "").strip()
    submission_link = form.get("submission_link", "").strip()
    if not title or not course or not due_date:
        flash("Add a title, course, and deadline to create a task.", "error")
        return redirect(url_for("dashboard"))
    try:
        estimated_hours = float(form.get("estimated_hours", 1))
        difficulty = int(form.get("difficulty", 3))
        study_hours = float(form.get("study_hours", 1))
        if (
            estimated_hours <= 0
            or study_hours <= 0
            or difficulty not in range(1, 6)
        ):
            raise ValueError
        date.fromisoformat(due_date)
        progress = int(form.get("progress", 0))
        if progress not in range(0, 101):
            raise ValueError
        if dependency_id:
            dependency = get_db().execute(
                "SELECT id FROM tasks WHERE id = ? AND user_id = ?",
                (int(dependency_id), g.user["id"]),
            ).fetchone()
            if dependency is None:
                raise ValueError
    except ValueError:
        flash(
            "Use valid positive hours and a difficulty from 1 to 5.", "error"
        )
        return redirect(url_for("dashboard"))

    get_db().execute(
        """INSERT INTO tasks
        (
            title,
            course,
            task_type,
            due_date,
            estimated_hours,
            difficulty,
            study_hours,
            notes,
            created_at,
            user_id,
            recurrence,
            category,
            dependency_id,
            description,
            progress,
            status,
            submission_status,
            teacher,
            submission_link
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            title,
            course,
            form.get("task_type", "Assignment"),
            due_date,
            estimated_hours,
            difficulty,
            study_hours,
            form.get("notes", "").strip(),
            datetime.now().isoformat(),
            g.user["id"],
            form.get("recurrence", "None"),
            form.get("category", form.get("task_type", "Assignment")),
            dependency_id,
            description,
            progress,
            status,
            submission_status,
            teacher,
            submission_link,
        ),
    )
    get_db().commit()
    flash("Task added to your plan.", "success")
    return redirect(url_for("dashboard"))


@app.route("/tasks/<int:task_id>/complete", methods=["POST"])
@login_required
def complete_task(task_id: int):
    task = owned_task(task_id)
    if task is None:
        return redirect(url_for("dashboard"))
    completed = 0 if task["completed"] else 1
    completed_at = datetime.now().isoformat() if completed else ""
    get_db().execute(
        "UPDATE tasks SET completed = ?, completed_at = ? "
        "WHERE id = ? AND user_id = ?",
        (completed, completed_at, task_id, g.user["id"]),
    )
    if completed:
        update_user_progress()
        if task["recurrence"] and task["recurrence"] != "None":
            days = {
                "Daily": 1,
                "Weekly": 7,
                "Monthly": 30,
            }.get(task["recurrence"], 0)
            if days:
                next_due = date.fromisoformat(task["due_date"]) + timedelta(
                    days=days
                )
                get_db().execute(
                    """INSERT INTO tasks
                    (title, course, task_type, due_date, estimated_hours,
                     difficulty, study_hours, notes, created_at, user_id,
                     recurrence, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                     ?, ?, ?, ?)""",
                    (
                        task["title"],
                        task["course"],
                        task["task_type"],
                        next_due.isoformat(),
                        task["estimated_hours"],
                        task["difficulty"],
                        task["study_hours"],
                        task["notes"],
                        datetime.now().isoformat(),
                        g.user["id"],
                        task["recurrence"],
                        task["category"],
                    ),
                )
    get_db().commit()
    return redirect(url_for("dashboard"))


@app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id: int):
    task = get_db().execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, g.user["id"]),
    ).fetchone()
    if task is None:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        form = request.form
        try:
            values = (
                form.get("title", "").strip(),
                form.get("course", "").strip(),
                form.get("task_type", "Assignment"),
                form.get("due_date", ""),
                float(form.get("estimated_hours", 1)),
                int(form.get("difficulty", 3)),
                float(form.get("study_hours", 1)),
                form.get("notes", "").strip(),
            )
            if not values[0] or not values[1] or values[3] == "":
                raise ValueError
            date.fromisoformat(values[3])
            if (
                values[4] <= 0
                or values[5] not in range(1, 6)
                or values[6] <= 0
            ):
                raise ValueError
        except ValueError:
            flash("Check the task details and try again.", "error")
            return render_template("edit_task.html", task=task)
        get_db().execute(
            """UPDATE tasks SET title = ?, course = ?, task_type = ?,
            due_date = ?, estimated_hours = ?, difficulty = ?,
            study_hours = ?, notes = ? WHERE id = ? AND user_id = ?""",
            (*values, task_id, g.user["id"]),
        )
        get_db().commit()
        flash("Task updated.", "success")
        return redirect(url_for("dashboard"))
    return render_template("edit_task.html", task=task)


@app.route("/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id: int):
    get_db().execute(
        "DELETE FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, g.user["id"]),
    )
    get_db().commit()
    flash("Task removed.", "success")
    return redirect(url_for("dashboard"))


def owned_task(task_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, g.user["id"]),
    ).fetchone()


@app.post("/api/tasks/<int:task_id>/complete")
@login_required
def api_complete_task(task_id: int):
    task = owned_task(task_id)
    if task is None:
        return {"error": "Task not found"}, 404
    completed = 0 if task["completed"] else 1
    get_db().execute(
        "UPDATE tasks SET completed = ?, completed_at = ? WHERE id = ?",
        (completed, datetime.now().isoformat() if completed else "", task_id),
    )
    if completed:
        update_user_progress()
    get_db().commit()
    return {"id": task_id, "completed": bool(completed)}


@app.post("/api/tasks/<int:task_id>/subtasks")
@login_required
def api_add_subtask(task_id: int):
    if owned_task(task_id) is None:
        return {"error": "Task not found"}, 404
    title = request.json.get("title", "").strip() if request.is_json else ""
    if not title:
        return {"error": "Subtask title is required"}, 400
    cursor = get_db().execute(
        "INSERT INTO subtasks (task_id, title) VALUES (?, ?)",
        (task_id, title),
    )
    get_db().commit()
    return {"id": cursor.lastrowid, "title": title, "completed": False}, 201


@app.post("/api/tasks/<int:task_id>/breakdown")
@login_required
def api_breakdown_task(task_id: int):
    task = owned_task(task_id)
    if task is None:
        return {"error": "Task not found"}, 404
    task_type = (task["task_type"] or "").lower()
    title = task["title"].lower()
    if "project" in task_type or "project" in title:
        steps = [
            "Understand requirements",
            "Make a small plan",
            "Build the main work",
            "Test and fix issues",
            "Prepare report or presentation",
            "Submit final work",
        ]
    elif "exam" in task_type or "revision" in task_type:
        steps = [
            "Collect syllabus and notes",
            "Review key concepts",
            "Practice important questions",
            "Take a timed self-test",
        ]
    elif "practical" in task_type or "lab" in task_type:
        steps = [
            "Read the practical brief",
            "Prepare algorithm or experiment",
            "Write code or procedure",
            "Test output and record results",
        ]
    else:
        steps = [
            "Read the instructions",
            "Collect notes or resources",
            "Complete the main work",
            "Review and submit",
        ]
    existing = {
        row["title"]
        for row in get_db().execute(
            "SELECT title FROM subtasks WHERE task_id = ?", (task_id,)
        ).fetchall()
    }
    created = []
    for step in steps:
        if step not in existing:
            cursor = get_db().execute(
                "INSERT INTO subtasks (task_id, title) VALUES (?, ?)",
                (task_id, step),
            )
            created.append({"id": cursor.lastrowid, "title": step})
    get_db().commit()
    return {"subtasks": created}, 201


@app.post("/api/subtasks/<int:subtask_id>/complete")
@login_required
def api_complete_subtask(subtask_id: int):
    subtask = get_db().execute(
        """SELECT subtasks.* FROM subtasks
        JOIN tasks ON tasks.id = subtasks.task_id
        WHERE subtasks.id = ? AND tasks.user_id = ?""",
        (subtask_id, g.user["id"]),
    ).fetchone()
    if subtask is None:
        return {"error": "Subtask not found"}, 404
    completed = 0 if subtask["completed"] else 1
    get_db().execute(
        "UPDATE subtasks SET completed = ? WHERE id = ?",
        (completed, subtask_id),
    )
    get_db().commit()
    return {"id": subtask_id, "completed": bool(completed)}


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        get_db().execute(
            """UPDATE users SET name = ?, course = ?, semester = ?,
            daily_available_hours = ?, daily_goal = ? WHERE id = ?""",
            (
                request.form.get("name", "").strip(),
                request.form.get("course", "").strip(),
                request.form.get("semester", "").strip(),
                float(request.form.get("daily_available_hours", 3)),
                max(1, int(request.form.get("daily_goal", 3))),
                g.user["id"],
            ),
        )
        get_db().commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html")


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
