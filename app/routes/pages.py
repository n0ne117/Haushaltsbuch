from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.templating import assets_version, render, static_assets, templates

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/help")
def help_page(request: Request):
    return render(request, "help.html")



@router.get("/sw.js")
def service_worker():
    js = templates.get_template("sw.js").render(version=assets_version(), assets=static_assets())
    return Response(js, media_type="text/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})
