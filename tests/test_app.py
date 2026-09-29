from datetime import date, timedelta

import pytest

from app import app, calculate_task_status, init_db


@pytest.fixture()
def client(tmp_path):
    app.config.update(TESTING=True, DATABASE=tmp_path / "test.db")
    app.config["SECRET_KEY"] = "test"
    with app.app_context():
        init_db()
    with app.test_client() as client:
        client.post(
            "/register",
            data={
                "name": "Test Student",
                "email": "student@example.com",
                "password": "secret123",
            },
        )
        yield client


def test_overdue_difficult_task_is_critical():
    task = {
        "due_date": (date.today() - timedelta(days=1)).isoformat(),
        "estimated_hours": 8,
        "study_hours": 2,
        "difficulty": 5,
    }
    status = calculate_task_status(task)
    assert status["risk_label"] == "Overdue"
    assert status["risk_tone"] == "critical"
    assert status["priority"] == "Do next"


def test_add_and_complete_task(client):
    response = client.post(
        "/tasks",
        data={
            "title": "Read chapter four",
            "course": "History",
            "task_type": "Reading",
            "due_date": (date.today() + timedelta(days=5)).isoformat(),
            "estimated_hours": "2",
            "difficulty": "2",
            "study_hours": "4",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Read chapter four" in response.data
    response = client.post("/tasks/1/complete", follow_redirects=True)
    assert b"Completed" in response.data
    response = client.post(
        "/api/tasks/1/subtasks", json={"title": "Review key formulas"}
    )
    assert response.status_code == 201
    subtask_id = response.get_json()["id"]
    response = client.post(f"/api/subtasks/{subtask_id}/complete")
    assert response.get_json()["completed"] is True


def test_anonymous_users_are_sent_to_login(client):
    client.get("/logout")
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
