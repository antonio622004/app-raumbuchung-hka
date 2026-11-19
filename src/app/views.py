from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from platform_sdk import Portal, User

from .bookings import ROOMS, SLOTS, SLOTS_BY_KEY, AlreadyBooked, BookingStore, now

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")  # autoescape ist an

TITLE = "Raumbuchung"
ROLES = ("student", "employee", "professor")

# Meldungen nach einer Aktion. Die Adresse trägt nur den Schlüssel, nie freien Text.
MESSAGES = {
    "gebucht": ("success", "Sie haben Raum {room} für {slot} gebucht."),
    "storniert": ("success", "Sie haben Ihre Buchung für Raum {room}, {slot}, storniert."),
    "belegt": ("warn", "Raum {room} ist für {slot} leider schon gebucht. Bitte wählen Sie einen anderen Raum."),
    "vorbei": ("warn", "Das Zeitfenster {slot} ist heute schon vorbei. Bitte wählen Sie ein anderes."),
    "unbekannt": ("warn", "Diese Buchung gibt es nicht mehr. Die Übersicht zeigt den aktuellen Stand."),
}
WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def build_router(portal: Portal, store: BookingStore | None = None) -> APIRouter:
    router = portal.router(dependencies=[Depends(portal.requires(*ROLES))])
    store = store or BookingStore.from_env()

    async def render(user: User, *, message: tuple[str, str] | None = None, status_code: int = 200) -> HTMLResponse:
        current = now()
        today = current.date()
        booked = store.for_day(today)
        rows = []
        for room in ROOMS:
            cells = []
            for slot in SLOTS:
                person = booked.get((room, slot.key))
                if person == user.sub:
                    state = "mine"
                elif person:
                    state = "taken"
                elif current.time() >= slot.end:
                    state = "past"
                else:
                    state = "free"
                cells.append({"slot": slot, "state": state, "id": f"{room}-{slot.key}"})
            rows.append({"room": room, "cells": cells})
        free_count = sum(c["state"] == "free" for r in rows for c in r["cells"])
        body = templates.get_template("page.html").render(
            today=f"{WEEKDAYS[today.weekday()]}, {today:%d.%m.%Y}",
            slots=SLOTS,
            rows=rows,
            free_count=free_count,
            message=message,
            book_url=portal.url("/buchen"),
            cancel_url=portal.url("/stornieren"),
        )
        html = await portal.layout(title=TITLE, body=body, current=portal.url("/"), user=user)
        return HTMLResponse(html, status_code=status_code)

    def back(key: str, room: str, slot: str) -> RedirectResponse:
        return RedirectResponse(portal.url(f"/?meldung={key}&raum={room}&zeit={slot}"), status_code=303)

    def invalid(request: Request, room: str, slot: str) -> tuple[str, str] | None:
        """Prüft Herkunft und Eingaben. Gibt eine Meldung zurück, wenn etwas nicht stimmt."""
        if request.headers.get("sec-fetch-site") == "cross-site":
            return ("warn", "Buchungen sind nur direkt auf dieser Seite möglich. Bitte klicken Sie hier auf „Buchen“.")
        if room not in ROOMS or slot not in SLOTS_BY_KEY:
            return ("warn", "Diesen Raum oder dieses Zeitfenster gibt es nicht. Bitte wählen Sie aus der Übersicht.")
        return None

    @router.get("/", response_class=HTMLResponse)
    async def home(user: User = Depends(portal.user), meldung: str = "", raum: str = "", zeit: str = ""):
        message = None
        if meldung in MESSAGES and raum in ROOMS and zeit in SLOTS_BY_KEY:
            kind, text = MESSAGES[meldung]
            message = (kind, text.format(room=raum, slot=SLOTS_BY_KEY[zeit].label))
        return await render(user, message=message)

    @router.post("/buchen", response_class=HTMLResponse)
    async def book(request: Request, user: User = Depends(portal.user), raum: str = Form(""), zeit: str = Form("")):
        if error := invalid(request, raum, zeit):
            return await render(user, message=error, status_code=400)
        current = now()
        if current.time() >= SLOTS_BY_KEY[zeit].end:
            return back("vorbei", raum, zeit)
        try:
            store.book(current.date(), raum, zeit, user.sub)
        except AlreadyBooked:
            return back("belegt", raum, zeit)
        return back("gebucht", raum, zeit)

    @router.post("/stornieren", response_class=HTMLResponse)
    async def cancel(request: Request, user: User = Depends(portal.user), raum: str = Form(""), zeit: str = Form("")):
        if error := invalid(request, raum, zeit):
            return await render(user, message=error, status_code=400)
        if store.cancel(now().date(), raum, zeit, user.sub):
            return back("storniert", raum, zeit)
        return back("unbekannt", raum, zeit)

    return router
