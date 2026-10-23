"""The filer's contact details live on their own account and come back on /me."""


def test_save_and_read_my_contact(client, auth_headers):
    r = client.put("/api/auth/me/contact", headers=auth_headers, json={
        "name": "  Test Filer ", "phone": "555-0100", "email": "filer@example.test",
        "address": "", "city": "Bend",
    })
    assert r.status_code == 200
    # Trimmed, blanks dropped.
    assert r.json()["contact"] == {"name": "Test Filer", "phone": "555-0100",
                                   "email": "filer@example.test", "city": "Bend"}
    me = client.get("/api/auth/me", headers=auth_headers).json()["user"]
    assert me["contact"]["email"] == "filer@example.test"


def test_contact_requires_login(client):
    assert client.put("/api/auth/me/contact", json={"name": "x"}).status_code in (401, 403)


def test_contact_values_are_capped():
    from core.auth_store import clean_contact
    out = clean_contact({"name": "a" * 500, "evil": "x", "phone": 5})
    assert out == {"name": "a" * 200}
