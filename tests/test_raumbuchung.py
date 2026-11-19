from datetime import datetime

import pytest
from conftest import make_token

from app import views


def at(hour: int, minute: int = 0):
    return lambda: datetime(2026, 11, 19, hour, minute)


@pytest.fixture(autouse=True)
def morning(monkeypatch):
    monkeypatch.setattr(views, "now", at(9))


def book(client, headers, room="A101", slot="vormittag"):
    return client.post("/buchen", data={"raum": room, "zeit": slot}, headers=headers, follow_redirects=False)


def test_uebersicht_zeigt_alle_raeume_frei(client, as_student):
    html = client.get("/", headers=as_student).text
    for room in ("A101", "A102", "B201", "B202"):
        assert f'<th scope="row">{room}</th>' in html
    assert html.count('type="submit" class="btn btn--primary">Buchen') == 8
    assert "Heute sind noch 8 Zeitfenster frei." in html
    assert "Donnerstag, 19.11.2026" in html
    assert "<caption" in html


def test_buchen_mit_einem_klick(client, as_student):
    response = book(client, as_student)
    assert response.status_code == 303
    assert response.headers["location"] == "/?meldung=gebucht&raum=A101&zeit=vormittag"
    html = client.get(response.headers["location"], headers=as_student).text
    assert "Sie haben Raum A101 für Vormittag gebucht." in html
    assert "Von Ihnen gebucht" in html
    assert "Heute sind noch 7 Zeitfenster frei." in html


def test_beschaeftigte_sehen_belegt_und_koennen_nicht_doppelt_buchen(client, as_student, as_employee):
    book(client, as_student)
    html = client.get("/", headers=as_employee).text
    assert "Belegt" in html
    assert "Von Ihnen gebucht" not in html
    response = book(client, as_employee)
    assert response.headers["location"] == "/?meldung=belegt&raum=A101&zeit=vormittag"
    assert "schon gebucht" in client.get(response.headers["location"], headers=as_employee).text


def test_vorbei_am_nachmittag(client, as_student, monkeypatch):
    monkeypatch.setattr(views, "now", at(14))
    html = client.get("/", headers=as_student).text
    assert html.count("Vorbei") == 4
    assert "Heute sind noch 4 Zeitfenster frei." in html
    response = book(client, as_student)
    assert response.headers["location"] == "/?meldung=vorbei&raum=A101&zeit=vormittag"


def test_stornieren_nur_eigene(client, as_student, as_employee):
    book(client, as_student, "B202", "nachmittag")
    other = client.post(
        "/stornieren", data={"raum": "B202", "zeit": "nachmittag"}, headers=as_employee, follow_redirects=False
    )
    assert "meldung=unbekannt" in other.headers["location"]
    own = client.post(
        "/stornieren", data={"raum": "B202", "zeit": "nachmittag"}, headers=as_student, follow_redirects=False
    )
    assert "meldung=storniert" in own.headers["location"]
    assert "Heute sind noch 8 Zeitfenster frei." in client.get("/", headers=as_student).text


def test_stornieren_mit_dialog(client, as_student):
    book(client, as_student)
    html = client.get("/", headers=as_student).text
    assert 'data-dialog-open="confirm-A101-vormittag"' in html
    assert 'data-submit-form="cancel-A101-vormittag"' in html
    assert ">Abbrechen</button>" in html


def test_falsche_eingaben_deutsch(client, as_student):
    response = book(client, as_student, room="Z999")
    assert response.status_code == 400
    assert "Diesen Raum oder dieses Zeitfenster gibt es nicht." in response.text
    response = client.post("/buchen", headers=as_student)
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Field required" not in response.text


def test_fremde_seite_kann_nicht_buchen(client, as_student):
    headers = {**as_student, "Sec-Fetch-Site": "cross-site"}
    assert book(client, headers).status_code == 400
    assert "Heute sind noch 8 Zeitfenster frei." in client.get("/", headers=as_student).text


def test_rolle_ohne_freigabe(client):
    headers = {"X-Portal-Assertion": make_token(roles=["guest"]), "Accept": "text/html"}
    assert client.get("/", headers=headers).status_code == 403


def test_post_ohne_anmeldung_401(client):
    assert client.post("/buchen", data={"raum": "A101", "zeit": "vormittag"}).status_code == 401
    assert client.post("/stornieren", data={"raum": "A101", "zeit": "vormittag"}).status_code == 401
